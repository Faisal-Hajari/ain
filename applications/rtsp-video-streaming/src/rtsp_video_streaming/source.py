"""The looping media source: one ffmpeg run per file, fanned out to all clients.

A single encoder feeds every connected client, so N viewers cost one ffmpeg
process, not N.  Packets arrive on loopback UDP sockets, get renumbered onto a
continuous stream (see :mod:`rtsp_video_streaming.rtp`) and are handed to each
subscriber, which decides how to put them on the wire (TCP interleaved or UDP).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Set

from rtsp_video_streaming.ffmpeg import (
    AUDIO_CLOCK_RATE,
    AUDIO_PAYLOAD_TYPE,
    EncodingConfig,
    MediaInfo,
    VIDEO_CLOCK_RATE,
    VIDEO_PAYLOAD_TYPE,
    build_command,
    probe_media,
)
from rtsp_video_streaming.playlist import Playlist
from rtsp_video_streaming.rtp import InvalidPacket, RtpRewriter
from rtsp_video_streaming.sdp import AUDIO, VIDEO

log = logging.getLogger(__name__)

EMPTY_FOLDER_RETRY_SECONDS = 5.0
FAILED_FILE_BACKOFF_SECONDS = 1.0
RTCP_INTERVAL_SECONDS = 5.0
# How long the encoder may run without producing video before we give up on the
# current file and move to the next one.
STALL_TIMEOUT_SECONDS = 15.0
WATCHDOG_POLL_SECONDS = 1.0
# How long an encoder gets to honour SIGTERM before it is killed outright.
TERMINATE_TIMEOUT_SECONDS = 5.0


class Subscriber(Protocol):
    """What the source needs from a playing RTSP session.

    Structural, not inherited: ``Session`` lives in the server and knows how to
    put a packet on its own wire, which is the whole of the relationship.
    """

    def deliver_rtp(self, kind: str, packet: bytes) -> None: ...

    def deliver_rtcp(self, kind: str, packet: bytes) -> None: ...


class _RtpReceiver(asyncio.DatagramProtocol):
    def __init__(self, on_packet: Callable[[bytes], None]) -> None:
        self._on_packet = on_packet

    def datagram_received(self, data: bytes, addr) -> None:
        self._on_packet(data)

    def error_received(self, exc: Exception) -> None:  # pragma: no cover
        log.debug("RTP socket error: %s", exc)


class _Discard(asyncio.DatagramProtocol):
    """Holds ffmpeg's RTCP port open so it does not get ICMP port-unreachable."""


@dataclass
class _Endpoints:
    """The loopback sockets one encoder run pushes RTP and RTCP into."""

    video_rtp: asyncio.DatagramTransport
    video_rtcp: asyncio.DatagramTransport
    audio_rtp: Optional[asyncio.DatagramTransport] = None
    audio_rtcp: Optional[asyncio.DatagramTransport] = None

    @staticmethod
    def _port(transport: Optional[asyncio.DatagramTransport]) -> Optional[int]:
        if transport is None:
            return None
        return transport.get_extra_info("sockname")[1]

    @property
    def ports(self) -> Dict[str, Optional[int]]:
        return {
            "video_port": self._port(self.video_rtp),
            "video_rtcp_port": self._port(self.video_rtcp),
            "audio_port": self._port(self.audio_rtp),
            "audio_rtcp_port": self._port(self.audio_rtcp),
        }

    def close(self) -> None:
        for transport in (self.video_rtp, self.video_rtcp, self.audio_rtp, self.audio_rtcp):
            if transport is not None:
                transport.close()


class MediaSource:
    def __init__(
        self,
        playlist: Playlist,
        config: EncodingConfig,
        stall_timeout: float = STALL_TIMEOUT_SECONDS,
    ) -> None:
        self.playlist = playlist
        self.config = config
        self.stall_timeout = stall_timeout
        # Leave exactly one frame of space between files so the first frame of
        # the next file does not land on the same timestamp as the last one.
        frame_ms = max(1, round(1000 / max(1, config.fps)))
        self.rewriters: Dict[str, RtpRewriter] = {
            VIDEO: RtpRewriter(VIDEO_CLOCK_RATE, VIDEO_PAYLOAD_TYPE, gap_ms=frame_ms)
        }
        if config.audio:
            self.rewriters[AUDIO] = RtpRewriter(
                AUDIO_CLOCK_RATE, AUDIO_PAYLOAD_TYPE, gap_ms=20
            )

        self.current_file: Optional[Path] = None
        self.invalid_packets = 0
        self._last_video_at = 0.0
        self._epoch: Optional[float] = None
        self._subscribers: Set[Subscriber] = set()
        self._stopping = asyncio.Event()
        self._tasks: List[asyncio.Task] = []
        self._process: Optional[asyncio.subprocess.Process] = None

    # -- subscriptions ----------------------------------------------------
    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.add(subscriber)

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.discard(subscriber)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish_rtp(self, kind: str, packet: bytes) -> None:
        """Renumber one encoder packet and fan it out to every playing client."""
        if kind == VIDEO:
            self._last_video_at = asyncio.get_running_loop().time()
        try:
            rewritten = self.rewriters[kind].rewrite(packet)
        except InvalidPacket as exc:
            # The socket is bound to loopback, so this takes a local sender, but
            # one stray datagram must not raise out of the receive callback once
            # per packet for as long as it keeps arriving.
            self.invalid_packets += 1
            log.debug("discarding non-RTP datagram on the %s socket: %s", kind, exc)
            return
        self._fan_out(lambda subscriber: subscriber.deliver_rtp(kind, rewritten))

    def publish_rtcp(self, kind: str, packet: bytes) -> None:
        self._fan_out(lambda subscriber: subscriber.deliver_rtcp(kind, packet))

    def _fan_out(self, deliver: Callable[[Subscriber], None]) -> None:
        for subscriber in list(self._subscribers):
            try:
                deliver(subscriber)
            except Exception:  # a broken client must not stall the loop
                log.debug("dropping subscriber after delivery error", exc_info=True)
                self._subscribers.discard(subscriber)

    # -- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._run_loop(), name="media-loop"),
            asyncio.create_task(self._run_rtcp(), name="media-rtcp"),
        ]

    async def stop(self) -> None:
        self._stopping.set()
        self._terminate_process()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []

    def _terminate_process(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:  # pragma: no cover - already gone
                pass

    async def _stop_process(self, process) -> None:
        """Ask the encoder to stop, then insist.

        An ffmpeg that ignores SIGTERM would otherwise hold the playlist open
        forever on an unbounded wait, which is the exact failure the stall
        watchdog exists to prevent.
        """
        self._terminate_process()
        try:
            await asyncio.wait_for(asyncio.shield(process.wait()), TERMINATE_TIMEOUT_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        log.warning("ffmpeg ignored SIGTERM for %.0fs - killing it", TERMINATE_TIMEOUT_SECONDS)
        try:
            process.kill()
        except ProcessLookupError:  # pragma: no cover - exited in the meantime
            pass
        await process.wait()

    # -- the loop ---------------------------------------------------------
    async def _run_loop(self) -> None:
        warned_empty = False
        while not self._stopping.is_set():
            files = self.playlist.scan()
            if not files:
                if not warned_empty:
                    log.warning(
                        "no playable files in %s - waiting for some to appear",
                        self.playlist.folder,
                    )
                    warned_empty = True
                await self._sleep(EMPTY_FOLDER_RETRY_SECONDS)
                continue
            warned_empty = False
            log.info("starting pass over %d file(s)", len(files))
            for path in files:
                if self._stopping.is_set():
                    return
                await self._play_file(path)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _open_endpoints(self) -> _Endpoints:
        """Bind the loopback sockets the next encoder run will push into."""
        loop = asyncio.get_running_loop()

        async def receiver(kind: str) -> asyncio.DatagramTransport:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _RtpReceiver(lambda pkt: self.publish_rtp(kind, pkt)),
                local_addr=("127.0.0.1", 0),
            )
            return transport

        async def discard() -> asyncio.DatagramTransport:
            transport, _ = await loop.create_datagram_endpoint(
                _Discard, local_addr=("127.0.0.1", 0)
            )
            return transport

        endpoints = _Endpoints(video_rtp=await receiver(VIDEO), video_rtcp=await discard())
        try:
            if self.config.audio:
                endpoints.audio_rtp = await receiver(AUDIO)
                endpoints.audio_rtcp = await discard()
        except OSError:
            endpoints.close()
            raise
        return endpoints

    async def _play_file(self, path: Path) -> None:
        endpoints = await self._open_endpoints()
        try:
            info = MediaInfo(has_audio=True)
            if self.config.audio:
                info = await asyncio.to_thread(probe_media, path, self.config)

            command = build_command(
                path,
                self.config,
                source_has_audio=info.has_audio,
                duration=info.duration,
                **endpoints.ports,
            )
            now = asyncio.get_running_loop().time()
            if self._epoch is None:
                self._epoch = now
            for rewriter in self.rewriters.values():
                rewriter.start_segment(now - self._epoch)

            self.current_file = path
            log.info("now playing %s", path.name)
            await self._run_ffmpeg(command, path)
        finally:
            self.current_file = None
            endpoints.close()

    async def _run_ffmpeg(self, command: List[str], path: Path) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self._process = process
        self._last_video_at = loop.time()
        stderr_task = asyncio.create_task(self._drain_stderr(process, path))
        waiter = asyncio.ensure_future(process.wait())
        try:
            await self._wait_with_watchdog(waiter, process, path)
        except asyncio.CancelledError:
            await self._stop_process(process)
            raise
        finally:
            self._process = None
            # A stray grandchild could hold the pipe open; never block on it.
            try:
                await asyncio.wait_for(asyncio.shield(stderr_task), timeout=5)
            except asyncio.TimeoutError:
                stderr_task.cancel()

        if process.returncode not in (0, -15) and not self._stopping.is_set():
            log.error("ffmpeg exited with code %s for %s", process.returncode, path.name)
        if loop.time() - started < FAILED_FILE_BACKOFF_SECONDS:
            # Guard against spinning at full speed over a folder of broken files.
            await self._sleep(FAILED_FILE_BACKOFF_SECONDS)

    async def _wait_with_watchdog(self, waiter: "asyncio.Future", process, path: Path) -> None:
        """Wait for the encoder, but do not let one bad file freeze the loop.

        A file whose video ends while another output keeps running (silence
        generated for a video-only file of unknown length, for instance) would
        otherwise hold the playlist forever.
        """
        loop = asyncio.get_running_loop()
        while not waiter.done():
            await asyncio.wait({waiter}, timeout=WATCHDOG_POLL_SECONDS)
            if waiter.done() or self._stopping.is_set():
                break
            if loop.time() - self._last_video_at > self.stall_timeout:
                log.warning(
                    "no video from %s for %.0fs - skipping to the next file",
                    path.name,
                    self.stall_timeout,
                )
                await self._stop_process(process)
                break
        await waiter

    async def _drain_stderr(self, process, path: Path) -> None:
        assert process.stderr is not None
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            log.warning("ffmpeg[%s]: %s", path.name, line.decode(errors="replace").rstrip())

    # -- RTCP -------------------------------------------------------------
    async def _run_rtcp(self) -> None:
        while not self._stopping.is_set():
            await self._sleep(RTCP_INTERVAL_SECONDS)
            if self._stopping.is_set():
                return
            for kind, rewriter in self.rewriters.items():
                if rewriter.packet_count == 0:
                    continue
                self.publish_rtcp(kind, rewriter.sender_report())
