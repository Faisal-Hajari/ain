"""Loop behaviour of the media source, driven by a stub encoder."""

import asyncio
from pathlib import Path

import pytest

from rtsp_video_streaming.ffmpeg import EncodingConfig
from rtsp_video_streaming.playlist import Playlist
from rtsp_video_streaming.source import MediaSource


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
