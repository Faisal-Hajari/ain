"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys
from pathlib import Path

from rtsp_video_streaming import __version__
from rtsp_video_streaming.ffmpeg import (
    EncodingConfig,
    FFmpegNotFound,
    probe_parameter_sets,
    require_ffmpeg,
)
from rtsp_video_streaming.playlist import DEFAULT_EXTENSIONS, Playlist, normalize_extensions
from rtsp_video_streaming.server import RtspServer
from rtsp_video_streaming.source import MediaSource

log = logging.getLogger("rtsp_video_streaming")


def parse_size(value: str):
    """Parse ``1280x720`` or ``source`` (keep each file's own resolution)."""
    if value.lower() in ("source", "native", "none"):
        return None, None
    try:
        width, height = value.lower().split("x")
        return int(width), int(height)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid size {value!r}: expected WIDTHxHEIGHT or 'source'"
        )


DEFAULT_PORT = 8554


def _env_port() -> int:
    """The port from $RTSP_PORT, ignoring a value that is not a port."""
    raw = os.environ.get("RTSP_PORT")
    if raw is None:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        log.warning("ignoring RTSP_PORT=%r: not a number", raw)
        return DEFAULT_PORT
    if not 1 <= port <= 65535:
        log.warning("ignoring RTSP_PORT=%r: out of range", raw)
        return DEFAULT_PORT
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtsp-video-streaming",
        description="Stream a folder of video files over RTSP, looping forever.",
    )
    parser.add_argument("folder", type=Path, help="folder containing the video files")
    parser.add_argument(
        "--host", default=os.environ.get("RTSP_HOST", "0.0.0.0"),
        help="bind address, or $RTSP_HOST (default: %(default)s)",
    )
    # The container's healthcheck has to probe the port the server actually
    # binds, and it cannot read the command line; both read $RTSP_PORT instead.
    parser.add_argument(
        "--port", type=int, default=_env_port(),
        help="RTSP port, or $RTSP_PORT (default: %(default)s)",
    )
    parser.add_argument(
        "--path", default=os.environ.get("RTSP_PATH", "live"),
        help="stream path, or $RTSP_PATH (default: %(default)s)",
    )
    parser.add_argument(
        "--size", type=parse_size, default=(1280, 720),
        help="output resolution WxH, or 'source' to keep each file's own "
             "(clients may need to reconnect between files) (default: 1280x720)",
    )
    parser.add_argument("--fps", type=int, default=25, help="output frame rate (default: %(default)s)")
    parser.add_argument("--bitrate", default="2M", help="video bitrate (default: %(default)s)")
    parser.add_argument(
        "--gop", type=int, default=None,
        help="keyframe interval in frames; smaller means clients that join "
             "mid-file start showing video sooner (default: one per second)",
    )
    parser.add_argument(
        "--preset", default="veryfast", help="x264 preset (default: %(default)s)"
    )
    parser.add_argument("--no-audio", action="store_true", help="stream video only")
    parser.add_argument(
        "--extensions", default=",".join(DEFAULT_EXTENSIONS),
        help="comma separated file extensions to play (default: %(default)s)",
    )
    parser.add_argument("--recursive", action="store_true", help="also scan subfolders")
    parser.add_argument("--shuffle", action="store_true", help="shuffle each loop pass")
    parser.add_argument("--seed", type=int, default=None, help="shuffle seed")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="path to the ffmpeg binary")
    parser.add_argument("--ffprobe", default="ffprobe", help="path to the ffprobe binary")
    parser.add_argument(
        "--log-level", default="info",
        choices=["debug", "info", "warning", "error"], help="default: %(default)s",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def advertised_host(host: str) -> str:
    if host not in ("0.0.0.0", "::", ""):
        return host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # Connecting a UDP socket sends nothing; it only asks the kernel
            # which local address it would route from. TEST-NET-1 (RFC 5737) is
            # reserved for documentation, so no real host is named here.
            probe.connect(("192.0.2.1", 80))
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


async def run(args: argparse.Namespace) -> int:
    width, height = args.size
    config = EncodingConfig(
        width=width,
        height=height,
        fps=args.fps,
        video_bitrate=args.bitrate,
        gop=args.gop if args.gop is not None else args.fps,
        preset=args.preset,
        audio=not args.no_audio,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        loglevel="warning" if args.log_level == "debug" else "error",
    )
    try:
        require_ffmpeg(config)
    except FFmpegNotFound as exc:
        log.error("%s", exc)
        return 2

    if not args.folder.is_dir():
        log.error("not a folder: %s", args.folder)
        return 2

    playlist = Playlist(
        folder=args.folder,
        extensions=normalize_extensions(args.extensions.split(",")),
        recursive=args.recursive,
        shuffle=args.shuffle,
        seed=args.seed,
    )
    files = playlist.scan()
    if not files:
        log.warning(
            "no matching video files in %s yet; the server will start anyway and "
            "pick them up as soon as they appear",
            args.folder,
        )
    else:
        log.info("found %d file(s) in %s", len(files), args.folder)

    parameter_sets = await asyncio.to_thread(probe_parameter_sets, config)
    if parameter_sets is None and config.scaled:
        log.warning(
            "could not determine the H.264 parameter sets up front; clients may "
            "need a moment to start decoding"
        )

    source = MediaSource(playlist, config)
    server = RtspServer(
        source,
        path=args.path,
        host=args.host,
        port=args.port,
        with_audio=config.audio,
        parameter_sets=parameter_sets,
    )
    port = await server.start()
    await source.start()

    url = f"rtsp://{advertised_host(args.host)}:{port}{server.path}"
    log.info("streaming on %s", url)
    log.info("try it with: ffplay -rtsp_transport tcp %s", url)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    serve_task = asyncio.create_task(server.serve_forever())
    try:
        await stop.wait()
    finally:
        log.info("shutting down")
        serve_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await serve_task
        await source.stop()
        await server.stop()
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
