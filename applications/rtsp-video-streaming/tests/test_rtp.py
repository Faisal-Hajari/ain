import struct

import pytest

from rtsp_video_streaming.rtp import InvalidPacket, RtpRewriter, parse_header

MAX_U16 = 0xFFFF
MAX_U32 = 0xFFFFFFFF


def packet(seq, timestamp, ssrc=0xAABBCCDD, payload=b"payload", marker=False):
    header = struct.pack(
        "!BBHII", 0x80, (0x80 if marker else 0) | 96, seq, timestamp, ssrc
    )
    return header + payload


def test_parse_header_rejects_short_and_wrong_version():
    with pytest.raises(InvalidPacket):
        parse_header(b"\x80\x60\x00")
    with pytest.raises(InvalidPacket):
        parse_header(b"\x40" + b"\x00" * 11)


def test_rewrite_uses_one_ssrc_and_contiguous_sequence_numbers():
    rewriter = RtpRewriter(90000, 96, ssrc=0x11223344)
    rewriter.start_segment()
    headers = [parse_header(rewriter.rewrite(packet(9000 + i, 1000 + i * 3600)))
               for i in range(5)]
    assert {h.ssrc for h in headers} == {0x11223344}
    assert {h.payload_type for h in headers} == {96}
    sequences = [h.sequence for h in headers]
    assert sequences == [(sequences[0] + i) & MAX_U16 for i in range(5)]


def test_marker_bit_and_payload_survive_the_rewrite():
    rewriter = RtpRewriter(90000, 96)
    rewriter.start_segment()
    out = rewriter.rewrite(packet(1, 100, payload=b"nal-unit", marker=True))
    assert parse_header(out).marker is True
    assert out[12:] == b"nal-unit"


def test_timestamps_stay_continuous_when_the_next_file_starts():
    """A client mid-playback must not see the encoder restart between files."""
    rewriter = RtpRewriter(90000, 96, gap_ms=20)

    rewriter.start_segment()
    first = [parse_header(rewriter.rewrite(packet(i, 1000 + i * 3600))) for i in range(3)]

    # Next file: the encoder restarts with unrelated sequence/timestamp bases.
    rewriter.start_segment()
    second = [parse_header(rewriter.rewrite(packet(60000 + i, 7_000_000 + i * 3600)))
              for i in range(3)]

    assert second[0].sequence == (first[-1].sequence + 1) & MAX_U16
    gap = (second[0].timestamp - first[-1].timestamp) & MAX_U32
    assert gap == (20 * 90000) // 1000
    assert (second[1].timestamp - second[0].timestamp) & MAX_U32 == 3600


def test_input_timestamp_wraparound_does_not_jump_the_output():
    rewriter = RtpRewriter(90000, 96)
    rewriter.start_segment()
    before = parse_header(rewriter.rewrite(packet(1, 2**32 - 1000)))
    after = parse_header(rewriter.rewrite(packet(2, 2600)))  # wrapped past 2**32
    assert (after.timestamp - before.timestamp) & MAX_U32 == 3600


def test_sender_report_counts_packets_and_payload_octets():
    rewriter = RtpRewriter(8000, 8, ssrc=0x0A0B0C0D)
    rewriter.start_segment()
    for i in range(4):
        rewriter.rewrite(packet(i, i * 160, payload=b"a" * 160))

    report = rewriter.sender_report()
    version_pt, packet_type, length, ssrc = struct.unpack("!BBHI", report[:8])
    assert version_pt == 0x80 and packet_type == 200
    assert length == 6 and len(report) == 28
    assert ssrc == 0x0A0B0C0D
    _, _, _, _, _, _, _, packets, octets = struct.unpack("!BBHIIIIII", report)
    assert packets == 4
    assert octets == 4 * 160


def test_segments_are_anchored_to_a_clock_shared_by_all_streams():
    """Audio and video must stay locked together across a file switch."""
    video = RtpRewriter(90000, 96)
    audio = RtpRewriter(8000, 8)
    for rewriter in (video, audio):
        rewriter.start_segment(0.0)
    video.rewrite(packet(1, 0))
    audio.rewrite(packet(1, 0))
    video_start, audio_start = video.timestamp, audio.timestamp

    # The next file starts 4.5s into the stream; both streams advance by 4.5s
    # of their own clock, so they stay in sync no matter where each one stopped.
    for rewriter in (video, audio):
        rewriter.start_segment(4.5)
    video.rewrite(packet(1, 500))
    audio.rewrite(packet(1, 700))
    assert (video.timestamp - video_start) & MAX_U32 == int(4.5 * 90000)
    assert (audio.timestamp - audio_start) & MAX_U32 == int(4.5 * 8000)


def test_a_segment_never_steps_the_clock_backwards():
    rewriter = RtpRewriter(90000, 96, gap_ms=40)
    rewriter.start_segment(0.0)
    for i in range(3):
        rewriter.rewrite(packet(i, i * 3600))
    last = rewriter.timestamp

    rewriter.start_segment(0.01)  # anchor lands before the packets we just sent
    after = parse_header(rewriter.rewrite(packet(0, 0)))
    assert (after.timestamp - last) & MAX_U32 == (40 * 90000) // 1000


def _report_mapping(report):
    """The (NTP seconds, RTP timestamp) pair a client builds its clock from."""
    _, _, _, _, seconds, fraction, rtp_ts, _, _ = struct.unpack("!BBHIIIIII", report)
    return seconds + fraction / (1 << 32), rtp_ts


def test_sender_reports_describe_one_line_across_files(monkeypatch):
    """Every report must place RTP on the same NTP line, file after file.

    A client rebuilds its mapping from the newest report, so two reports that
    disagree move the whole timeline and playback jumps at the file switch.
    Packets arrive at wall-clock times unrelated to the media clock -- the
    encoder takes a moment to start and then bursts -- and the report must not
    inherit that.
    """
    clock = [1000.0]
    monkeypatch.setattr("rtsp_video_streaming.rtp.time.time", lambda: clock[0])

    rewriter = RtpRewriter(8000, 8, gap_ms=20)
    mappings = []
    for segment in range(3):
        # Each file is anchored to the shared epoch, one second apart...
        rewriter.start_segment(float(segment))
        # ...but its packets are forwarded late and in a burst, by a different
        # amount every time, the way a restarted encoder really behaves.
        clock[0] = 1000.0 + segment + 0.6 * (segment + 1)
        for i in range(4):
            rewriter.rewrite(packet(i, i * 160))
        mappings.append(_report_mapping(rewriter.sender_report()))

    reference_ntp, reference_rtp = mappings[0]
    for ntp, rtp_ts in mappings[1:]:
        rtp_advance = ((rtp_ts - reference_rtp) & MAX_U32) / 8000
        assert ntp - reference_ntp == pytest.approx(rtp_advance, abs=1e-3)


def test_sender_report_clock_survives_the_32_bit_wraparound(monkeypatch):
    """A feed runs for days; the 90 kHz field on the wire wraps every 13 hours.

    The NTP time in the report has to keep climbing across that wrap, so it
    cannot be recovered by subtracting two wrapped 32-bit timestamps.
    """
    clock = [1000.0]
    monkeypatch.setattr("rtsp_video_streaming.rtp.time.time", lambda: clock[0])

    rewriter = RtpRewriter(90000, 96, ssrc=1, gap_ms=40)
    rewriter.epoch_timestamp = MAX_U32 - 90000  # one second short of wrapping
    rewriter.timestamp = rewriter.epoch_timestamp

    ntp_times = []
    for hour in range(4):  # 4 * 7 hours, so the 13.25 hour wrap is crossed twice
        rewriter.start_segment(hour * 7 * 3600.0)
        rewriter.rewrite(packet(hour, 0))
        ntp_times.append(_report_mapping(rewriter.sender_report())[0])

    steps = [b - a for a, b in zip(ntp_times, ntp_times[1:])]
    assert steps == pytest.approx([7 * 3600.0] * 3, abs=1e-3)
