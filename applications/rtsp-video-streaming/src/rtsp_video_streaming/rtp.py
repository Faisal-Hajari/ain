"""RTP/RTCP packet handling.

The encoder is restarted for every file in the playlist, so each file arrives
with its own sequence numbers, timestamps and SSRC.  Clients must not see that:
:class:`RtpRewriter` renumbers every packet onto a single continuous stream so a
player that connected during file 1 keeps playing across files 2, 3, ... without
ever noticing a discontinuity.
"""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass

RTP_HEADER_LEN = 12
MAX_U32 = 0xFFFFFFFF
MAX_U16 = 0xFFFF
# Seconds between 1900-01-01 (NTP epoch) and 1970-01-01 (Unix epoch).
NTP_EPOCH_OFFSET = 2208988800


class InvalidPacket(ValueError):
    """Raised when a datagram is too short or is not RTP version 2."""


@dataclass(frozen=True)
class RtpHeader:
    marker: bool
    payload_type: int
    sequence: int
    timestamp: int
    ssrc: int


def parse_header(packet: bytes) -> RtpHeader:
    if len(packet) < RTP_HEADER_LEN:
        raise InvalidPacket(f"packet too short: {len(packet)} bytes")
    b0, b1, seq, timestamp, ssrc = struct.unpack("!BBHII", packet[:RTP_HEADER_LEN])
    if (b0 >> 6) != 2:
        raise InvalidPacket(f"unsupported RTP version {b0 >> 6}")
    return RtpHeader(
        marker=bool(b1 & 0x80),
        payload_type=b1 & 0x7F,
        sequence=seq,
        timestamp=timestamp,
        ssrc=ssrc,
    )


def _random_u32() -> int:
    return struct.unpack("!I", os.urandom(4))[0]


def _is_before(first: int, second: int) -> bool:
    """Compare two RTP timestamps, accounting for 32-bit wraparound."""
    return ((first - second) & MAX_U32) >= 0x80000000


class RtpRewriter:
    """Renumber packets from a sequence of encoder runs into one RTP stream."""

    def __init__(
        self,
        clock_rate: int,
        payload_type: int,
        ssrc: int | None = None,
        gap_ms: int = 20,
    ) -> None:
        self.clock_rate = clock_rate
        self.payload_type = payload_type
        self.ssrc = _random_u32() if ssrc is None else ssrc
        self.gap_ticks = max(1, (gap_ms * clock_rate) // 1000)

        self.sequence = _random_u32() & MAX_U16
        self.epoch_timestamp = _random_u32()
        self.timestamp = self.epoch_timestamp
        self._segment_out_base = self.timestamp
        self._segment_in_base: int | None = None

        self.packet_count = 0
        self.octet_count = 0
        # Wall-clock time paired with ``self.timestamp``, for RTCP sender reports.
        self.last_send_time = time.time()

    def start_segment(self, elapsed: float = 0.0) -> None:
        """Begin a new encoder run (i.e. the next file in the playlist).

        ``elapsed`` is the time in seconds since a single epoch shared by every
        stream of the source.  Anchoring each segment to that one clock, rather
        than to each stream's own last packet, keeps audio and video locked
        together across file boundaries instead of drifting apart a little at
        every switch.
        """
        self._segment_in_base = None
        anchored = (self.epoch_timestamp + int(elapsed * self.clock_rate)) & MAX_U32
        earliest = (self.timestamp + self.gap_ticks) & MAX_U32
        if self.packet_count and _is_before(anchored, earliest):
            anchored = earliest  # never step the outgoing clock backwards
        self._segment_out_base = anchored

    def rewrite(self, packet: bytes) -> bytes:
        """Return ``packet`` renumbered onto the continuous outgoing stream."""
        header = parse_header(packet)
        if self._segment_in_base is None:
            self._segment_in_base = header.timestamp
        elapsed = (header.timestamp - self._segment_in_base) & MAX_U32

        self.sequence = (self.sequence + 1) & MAX_U16
        self.timestamp = (self._segment_out_base + elapsed) & MAX_U32
        self.last_send_time = time.time()
        self.packet_count += 1
        self.octet_count += len(packet) - RTP_HEADER_LEN

        b1 = (0x80 if header.marker else 0) | (self.payload_type & 0x7F)
        new_header = struct.pack(
            "!BBHII", 0x80, b1, self.sequence, self.timestamp, self.ssrc
        )
        return new_header + packet[RTP_HEADER_LEN:]

    def sender_report(self) -> bytes:
        """Build an RTCP sender report so clients can sync audio to video.

        The report pairs the wall-clock time of the last packet we sent with
        that packet's RTP timestamp.  Extrapolating to "now" instead would put
        a real-time guess into the mapping clients use to schedule playback,
        and the guess is wrong by however much the encoder is ahead or behind.
        """
        ntp = self.last_send_time + NTP_EPOCH_OFFSET
        ntp_seconds = int(ntp)
        ntp_fraction = int((ntp - ntp_seconds) * (1 << 32)) & MAX_U32
        rtp_ts = self.timestamp
        return struct.pack(
            "!BBHIIIIII",
            0x80,  # version 2, no report blocks
            200,  # SR
            6,  # length in 32-bit words minus one
            self.ssrc,
            ntp_seconds,
            ntp_fraction,
            rtp_ts,
            self.packet_count & MAX_U32,
            self.octet_count & MAX_U32,
        )
