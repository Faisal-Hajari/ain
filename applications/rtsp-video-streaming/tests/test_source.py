"""Loop behaviour of the media source, driven by a stub encoder."""

import asyncio
import struct
from pathlib import Path

import pytest

from rtsp_video_streaming.ffmpeg import EncodingConfig
from rtsp_video_streaming.playlist import Playlist
from rtsp_video_streaming.sdp import VIDEO
from rtsp_video_streaming.source import MediaSource


def rtp_packet(seq=1, timestamp=0, payload=b"frame"):
    return struct.pack("!BBHII", 0x80, 96, seq, timestamp, 0x1234) + payload


class _Recorder:
    """A subscriber that just keeps what it was handed."""

    def __init__(self, delivered):
        self.delivered = delivered

    def deliver_rtp(self, kind, packet):
        self.delivered.append((kind, packet))

    def deliver_rtcp(self, kind, packet):
        self.delivered.append((kind, packet))


def stub_encoder(tmp_path: Path, body: str) -> Path:
    """A stand-in for ffmpeg that records the file it was asked to play."""
    script = tmp_path / "fake-ffmpeg"
    script.write_text(
        "#!/bin/sh\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in *.mp4) echo \"$arg\" >> " + str(tmp_path / "played.log") + ";; esac\n"
        "done\n" + body
    )
    script.chmod(0o755)
    return script


def played(tmp_path: Path):
    log = tmp_path / "played.log"
    if not log.exists():
        return []
    return [Path(line).name for line in log.read_text().split() if line]


async def wait_for(predicate, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.fixture
def videos(tmp_path):
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "one.mp4").write_bytes(b"x")
    (folder / "two.mp4").write_bytes(b"x")
    return folder


async def test_the_playlist_loops_back_to_the_first_file(tmp_path, videos):
    config = EncodingConfig(
        audio=False, ffmpeg=str(stub_encoder(tmp_path, "exit 0\n"))
    )
    source = MediaSource(Playlist(videos), config)
    await source.start()
    try:
        assert await wait_for(lambda: len(played(tmp_path)) >= 4)
    finally:
        await source.stop()
    assert played(tmp_path)[:4] == ["one.mp4", "two.mp4", "one.mp4", "two.mp4"]


async def test_a_stalled_encoder_does_not_block_the_playlist(tmp_path, videos):
    """A file that produces no video must not hold the loop forever."""
    config = EncodingConfig(
        audio=False, ffmpeg=str(stub_encoder(tmp_path, "exec sleep 60\n"))
    )
    source = MediaSource(Playlist(videos), config, stall_timeout=0.5)
    await source.start()
    try:
        assert await wait_for(lambda: len(played(tmp_path)) >= 2, timeout=10)
    finally:
        await source.stop()
    assert played(tmp_path)[:2] == ["one.mp4", "two.mp4"]


async def test_files_added_after_startup_are_picked_up(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    config = EncodingConfig(
        audio=False, ffmpeg=str(stub_encoder(tmp_path, "exit 0\n"))
    )
    source = MediaSource(Playlist(folder), config)
    await source.start()
    try:
        await asyncio.sleep(0.2)
        assert played(tmp_path) == []
        (folder / "late.mp4").write_bytes(b"x")
        assert await wait_for(lambda: played(tmp_path) != [], timeout=10)
    finally:
        await source.stop()
    assert played(tmp_path)[0] == "late.mp4"


async def test_stop_terminates_the_running_encoder(tmp_path, videos):
    config = EncodingConfig(
        audio=False, ffmpeg=str(stub_encoder(tmp_path, "exec sleep 60\n"))
    )
    source = MediaSource(Playlist(videos), config, stall_timeout=30)
    await source.start()
    assert await wait_for(lambda: source.current_file is not None)
    await asyncio.wait_for(source.stop(), timeout=5)
    assert source.current_file is None


async def test_a_stray_datagram_does_not_escape_the_receive_callback(tmp_path):
    """Anything that is not RTPv2 is counted and dropped, not propagated."""
    source = MediaSource(Playlist(tmp_path), EncodingConfig())
    source.publish_rtp(VIDEO, b"not an rtp packet at all")
    source.publish_rtp(VIDEO, b"\x40" + b"\x00" * 20)  # RTP version 1
    assert source.invalid_packets == 2

    delivered = []
    source.subscribe(_Recorder(delivered))
    source.rewriters[VIDEO].start_segment()
    source.publish_rtp(VIDEO, rtp_packet())
    assert len(delivered) == 1  # still working afterwards


async def test_an_encoder_that_ignores_sigterm_is_killed(tmp_path, monkeypatch):
    """Otherwise the playlist waits forever on a process it asked to stop."""
    (tmp_path / "clip.mp4").write_bytes(b"x")
    # Ignore SIGTERM, then sit still. Only SIGKILL ends this.
    encoder = stub_encoder(tmp_path, "trap '' TERM\nwhile :; do sleep 0.05; done\n")

    monkeypatch.setattr("rtsp_video_streaming.source.TERMINATE_TIMEOUT_SECONDS", 0.5)
    source = MediaSource(
        Playlist(tmp_path, extensions=(".mp4",)),
        EncodingConfig(ffmpeg=str(encoder), audio=False),
        stall_timeout=0.5,
    )
    await source.start()
    try:
        assert await wait_for(lambda: source.current_file is not None)
        # The stall watchdog fires, SIGTERM is ignored, and the kill has to land.
        assert await wait_for(lambda: played(tmp_path).count("clip.mp4") >= 2, timeout=15)
    finally:
        await source.stop()
