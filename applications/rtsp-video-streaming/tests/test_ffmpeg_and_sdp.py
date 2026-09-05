from pathlib import Path

import pytest

from rtsp_video_streaming.ffmpeg import (
    AUDIO_PAYLOAD_TYPE,
    EncodingConfig,
    FFmpegNotFound,
    MediaInfo,
    VIDEO_PAYLOAD_TYPE,
    build_command,
    extract_parameter_sets,
    probe_media,
    require_ffmpeg,
    split_annexb,
    video_encoder_args,
)
from rtsp_video_streaming.sdp import build_sdp, video_fmtp


def args_after(command, flag):
    return command[command.index(flag) + 1]


def test_command_targets_the_given_rtp_ports_with_fixed_payload_types():
    command = build_command(
        Path("/videos/a.mp4"), EncodingConfig(), 5000, 5001, 5002, 5003
    )
    assert command[0] == "ffmpeg"
    assert "-re" in command and args_after(command, "-i") == "/videos/a.mp4"
    assert command.count("-f") == 2  # one rtp output per stream
    assert "rtp://127.0.0.1:5000?rtcpport=5001&pkt_size=1200" in command
    assert "rtp://127.0.0.1:5002?rtcpport=5003&pkt_size=1200" in command
    payload_types = [command[i + 1] for i, a in enumerate(command) if a == "-payload_type"]
    assert payload_types == [str(VIDEO_PAYLOAD_TYPE), str(AUDIO_PAYLOAD_TYPE)]


def test_every_file_is_normalized_to_the_same_size_and_rate():
    command = build_command(
        Path("a.mp4"), EncodingConfig(width=640, height=360, fps=30), 5000, 5001, 5002, 5003
    )
    video_filter = args_after(command, "-vf")
    assert "scale=640:360:force_original_aspect_ratio=decrease" in video_filter
    assert "pad=640:360" in video_filter
    assert video_filter.endswith("fps=30")


def test_source_resolution_mode_skips_the_scaler():
    command = build_command(
        Path("a.mp4"), EncodingConfig(width=None, height=None), 5000, 5001, 5002, 5003
    )
    assert args_after(command, "-vf") == "fps=25"


def test_parameter_sets_are_repeated_in_band_for_mid_stream_joiners():
    command = build_command(Path("a.mp4"), EncodingConfig(), 5000, 5001, 5002, 5003)
    assert args_after(command, "-bsf:v") == "dump_extra=freq=keyframe"
    assert args_after(command, "-g") == "25"


def test_a_silent_file_still_produces_an_audio_stream():
    command = build_command(
        Path("a.mp4"), EncodingConfig(), 5000, 5001, 5002, 5003, source_has_audio=False
    )
    assert "anullsrc=r=8000:cl=mono" in command
    assert args_after(command, "-map") == "0:v:0"
    assert command[command.index("-c:a") - 1] == "1:a:0"
    assert "-shortest" in command


def test_audio_can_be_disabled_entirely():
    command = build_command(
        Path("a.mp4"), EncodingConfig(audio=False), 5000, 5001, 5002, 5003
    )
    assert "-c:a" not in command
    assert command.count("-f") == 1


def test_require_ffmpeg_reports_missing_binaries():
    config = EncodingConfig(ffmpeg="ffmpeg-does-not-exist", ffprobe="ffprobe-nope")
    with pytest.raises(FFmpegNotFound) as excinfo:
        require_ffmpeg(config)
    assert "ffmpeg-does-not-exist" in str(excinfo.value)


def test_ffprobe_is_only_required_when_audio_is_enabled(tmp_path):
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_text("#!/bin/sh\n")
    config = EncodingConfig(
        ffmpeg=str(fake_ffmpeg), ffprobe="ffprobe-nope", audio=False
    )
    require_ffmpeg(config)  # does not raise


def test_sdp_describes_both_streams_with_control_ids():
    sdp = build_sdp("live", with_audio=True)
    assert "m=video 0 RTP/AVP 96" in sdp
    assert "a=rtpmap:96 H264/90000" in sdp
    assert "a=control:streamid=0" in sdp
    assert "m=audio 0 RTP/AVP 8" in sdp
    assert "a=rtpmap:8 PCMA/8000" in sdp
    assert "a=control:streamid=1" in sdp
    assert sdp.endswith("\r\n")


def test_sdp_omits_audio_when_disabled():
    assert "m=audio" not in build_sdp("live", with_audio=False)


def test_a_silent_file_of_known_duration_is_bounded_by_it():
    """Otherwise the generated silence would outlive the video and stall the loop."""
    command = build_command(
        Path("a.mp4"), EncodingConfig(), 5000, 5001, 5002, 5003,
        source_has_audio=False, duration=12.5,
    )
    assert "-shortest" not in command
    assert args_after(command, "-t") == "12.500"


def test_a_silent_file_of_unknown_duration_falls_back_to_shortest():
    command = build_command(
        Path("a.mp4"), EncodingConfig(), 5000, 5001, 5002, 5003,
        source_has_audio=False, duration=None,
    )
    assert "-shortest" in command and "-t" not in command


def test_probe_media_reads_audio_and_duration(tmp_path):
    probe = tmp_path / "ffprobe"
    probe.write_text(
        "#!/bin/sh\n"
        'echo \'{"streams":[{"codec_type":"video"},{"codec_type":"audio"}],'
        '"format":{"duration":"7.25"}}\'\n'
    )
    probe.chmod(0o755)
    info = probe_media(Path("clip.mp4"), EncodingConfig(ffprobe=str(probe)))
    assert info.has_audio is True
    assert info.duration == 7.25


def test_probe_media_reports_a_file_without_audio(tmp_path):
    probe = tmp_path / "ffprobe"
    probe.write_text(
        "#!/bin/sh\n"
        'echo \'{"streams":[{"codec_type":"video"}],"format":{"duration":"N/A"}}\'\n'
    )
    probe.chmod(0o755)
    info = probe_media(Path("clip.mp4"), EncodingConfig(ffprobe=str(probe)))
    assert info.has_audio is False
    assert info.duration is None


def test_probe_media_survives_a_broken_probe(tmp_path):
    probe = tmp_path / "ffprobe"
    probe.write_text("#!/bin/sh\nexit 1\n")
    probe.chmod(0o755)
    info = probe_media(Path("clip.mp4"), EncodingConfig(ffprobe=str(probe)))
    assert info == MediaInfo(has_audio=False, duration=None)


def test_the_sdp_probe_and_the_real_encode_use_the_same_settings():
    config = EncodingConfig(width=640, height=360, fps=20, gop=40)
    encoder_args = video_encoder_args(config)
    command = build_command(Path("a.mp4"), config, 5000, 5001, 5002, 5003)
    assert [arg for arg in encoder_args if arg in command] == encoder_args


def test_split_annexb_handles_three_and_four_byte_start_codes():
    stream = b"\x00\x00\x00\x01\x67\xAA\x00\x00\x01\x68\xBB\x00\x00\x00\x01\x65\xCC"
    assert split_annexb(stream) == [b"\x67\xAA", b"\x68\xBB", b"\x65\xCC"]


def test_parameter_sets_picks_the_sps_and_pps():
    stream = b"\x00\x00\x01\x09\x10\x00\x00\x01\x67SPS\x00\x00\x01\x68PPS\x00\x00\x01\x65IDR"
    assert extract_parameter_sets(stream) == (b"\x67SPS", b"\x68PPS")


def test_parameter_sets_missing_from_the_stream():
    assert extract_parameter_sets(b"\x00\x00\x01\x65IDR") is None


def test_video_fmtp_advertises_the_parameter_sets():
    sps = bytes([0x67, 0x42, 0xC0, 0x14, 0xAA])
    line = video_fmtp((sps, b"\x68\xCE\x3C\x80"))
    assert "packetization-mode=1" in line
    assert "profile-level-id=42c014" in line
    assert "sprop-parameter-sets=Z0LAFKo=,aM48gA==" in line


def test_video_fmtp_without_parameter_sets_is_still_valid():
    assert video_fmtp(None) == "a=fmtp:96 packetization-mode=1"


def test_sdp_includes_the_parameter_sets_when_known():
    sdp = build_sdp("live", with_audio=False, parameter_sets=(b"\x67\x42\xC0\x14", b"\x68\xCE"))
    assert "sprop-parameter-sets=" in sdp
