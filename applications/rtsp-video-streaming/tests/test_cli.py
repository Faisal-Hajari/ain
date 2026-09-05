"""The command line surface: parsing, defaults and the early exits."""

import argparse
import asyncio
import socket

import pytest

from rtsp_video_streaming import cli


def test_parse_size_accepts_dimensions_and_the_source_keywords():
    assert cli.parse_size("1920x1080") == (1920, 1080)
    assert cli.parse_size("640X480") == (640, 480)
    for keyword in ("source", "native", "none", "SOURCE"):
        assert cli.parse_size(keyword) == (None, None)


@pytest.mark.parametrize("value", ["1920", "1920x", "axb", "1920x1080x30", ""])
def test_parse_size_rejects_anything_else(value):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_size(value)


def test_parser_defaults_match_the_documented_ones():
    args = cli.build_parser().parse_args(["/videos"])
    assert (args.host, args.port, args.path) == ("0.0.0.0", 8554, "live")
    assert args.size == (1280, 720)
    assert (args.fps, args.bitrate, args.preset) == (25, "2M", "veryfast")
    assert args.gop is None  # resolved to one keyframe per second in run()
    assert not args.no_audio and not args.recursive and not args.shuffle


def test_the_port_can_come_from_the_environment(monkeypatch):
    """The container healthcheck reads the same variable, so they cannot drift."""
    monkeypatch.setenv("RTSP_PORT", "9554")
    assert cli.build_parser().parse_args(["/videos"]).port == 9554


@pytest.mark.parametrize("value", ["not-a-number", "0", "70000", "-1"])
def test_an_unusable_rtsp_port_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("RTSP_PORT", value)
    assert cli.build_parser().parse_args(["/videos"]).port == cli.DEFAULT_PORT


def test_an_explicit_port_still_beats_the_environment(monkeypatch):
    monkeypatch.setenv("RTSP_PORT", "9554")
    assert cli.build_parser().parse_args(["/videos", "--port", "1234"]).port == 1234


def test_advertised_host_passes_through_a_specific_bind_address():
    assert cli.advertised_host("192.168.1.10") == "192.168.1.10"


@pytest.mark.parametrize("wildcard", ["0.0.0.0", "::", ""])
def test_advertised_host_resolves_a_wildcard_to_something_reachable(wildcard):
    host = cli.advertised_host(wildcard)
    assert host not in ("0.0.0.0", "::", "")
    socket.inet_pton(socket.AF_INET, host)  # a usable IPv4 literal


def test_advertised_host_falls_back_to_loopback_with_no_route(monkeypatch):
    def no_route(*_args, **_kwargs):
        raise OSError("network unreachable")

    monkeypatch.setattr(cli.socket, "socket", no_route)
    assert cli.advertised_host("0.0.0.0") == "127.0.0.1"


def test_run_reports_a_missing_folder_instead_of_starting(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "require_ffmpeg", lambda config: None)
    args = cli.build_parser().parse_args([str(tmp_path / "nope")])
    assert asyncio.run(cli.run(args)) == 2


def test_run_reports_a_missing_ffmpeg_instead_of_starting(tmp_path, monkeypatch):
    def missing(config):
        raise cli.FFmpegNotFound("no ffmpeg on PATH")

    monkeypatch.setattr(cli, "require_ffmpeg", missing)
    args = cli.build_parser().parse_args([str(tmp_path)])
    assert asyncio.run(cli.run(args)) == 2
