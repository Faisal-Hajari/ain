"""Building and probing with ffmpeg.

Every file in the playlist is normalised to the *same* codecs, resolution,
frame rate and payload types.  Clients negotiate the stream once (via DESCRIBE)
and that description has to stay true for every file in the loop, so the
encoder settings are deliberately fixed rather than copied from the source.
"""

from __future__ import annotations

import base64
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

VIDEO_PAYLOAD_TYPE = 96
VIDEO_CLOCK_RATE = 90000
# G.711 A-law: a static payload type, so the SDP needs no codec-specific fmtp
# line that would have to change per file.
AUDIO_PAYLOAD_TYPE = 8
AUDIO_CLOCK_RATE = 8000
RTP_PKT_SIZE = 1200


class FFmpegNotFound(RuntimeError):
    pass


@dataclass
class EncodingConfig:
    width: Optional[int] = 1280
    height: Optional[int] = 720
    fps: int = 25
    video_bitrate: str = "2M"
    gop: int = 25
    preset: str = "veryfast"
    audio: bool = True
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    loglevel: str = "error"

    @property
    def scaled(self) -> bool:
        return bool(self.width and self.height)


def require_ffmpeg(config: EncodingConfig) -> None:
    """Fail early, with an actionable message, if ffmpeg is missing.

    ffprobe is only needed to tell whether a file has an audio track, so it is
    not required when audio is switched off.
    """
    needed = [config.ffmpeg] + ([config.ffprobe] if config.audio else [])
    missing = [
        name for name in needed
        if shutil.which(name) is None and not Path(name).is_file()
    ]
    if missing:
        raise FFmpegNotFound(
            f"could not find {' and '.join(missing)} on PATH. "
            "Install ffmpeg (e.g. 'apt install ffmpeg' or 'brew install ffmpeg') "
            "or pass --ffmpeg/--ffprobe with explicit paths."
        )


@dataclass(frozen=True)
class MediaInfo:
    has_audio: bool = False
    duration: Optional[float] = None


def probe_media(path: Path, config: EncodingConfig) -> MediaInfo:
    """Ask ffprobe for the audio track and duration of ``path``.

    Both answers are optional: an unprobeable file is simply treated as silent
    and of unknown length, and the stall watchdog covers the rest.
    """
    try:
        out = subprocess.run(
            [
                config.ffprobe, "-v", "error",
                "-show_entries", "format=duration:stream=index,codec_type",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if out.returncode != 0:
            log.debug("ffprobe failed for %s: %s", path, out.stderr.strip())
            return MediaInfo()
        payload = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log.debug("ffprobe failed for %s: %s", path, exc)
        return MediaInfo()

    streams = payload.get("streams") or []
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    if duration is not None and duration <= 0:
        duration = None
    return MediaInfo(has_audio=has_audio, duration=duration)


def video_encoder_args(config: EncodingConfig) -> List[str]:
    """The x264 settings shared by the real encode and the SDP probe.

    They must match exactly: the parameter sets advertised in the SDP are the
    ones the probe produces, and clients will decode with them.
    """
    return [
        "-c:v", "libx264", "-preset", config.preset, "-tune", "zerolatency",
        "-profile:v", "baseline", "-pix_fmt", "yuv420p",
        "-b:v", config.video_bitrate, "-maxrate", config.video_bitrate,
        "-bufsize", config.video_bitrate,
        "-g", str(config.gop), "-keyint_min", str(config.gop), "-bf", "0",
        # Repeat SPS/PPS in-band on every keyframe: clients join mid-stream and
        # never see the out-of-band parameter sets from the SDP of an older file.
        "-bsf:v", "dump_extra=freq=keyframe",
    ]


def split_annexb(data: bytes) -> List[bytes]:
    """Split an Annex-B byte stream into NAL units (without start codes)."""
    units = []
    index = data.find(b"\x00\x00\x01")
    while index != -1:
        start = index + 3
        nxt = data.find(b"\x00\x00\x01", start)
        unit = data[start:] if nxt == -1 else data[start:nxt]
        # A 4-byte start code leaves a trailing zero on the previous unit.
        units.append(unit[:-1] if unit.endswith(b"\x00") and nxt != -1 else unit)
        index = nxt
    return [unit for unit in units if unit]


def parameter_sets(annexb: bytes) -> Optional[Tuple[bytes, bytes]]:
    """Pick the (SPS, PPS) pair out of an Annex-B stream."""
    sps = pps = None
    for unit in split_annexb(annexb):
        nal_type = unit[0] & 0x1F
        if nal_type == 7 and sps is None:
            sps = unit
        elif nal_type == 8 and pps is None:
            pps = unit
    if sps is None or pps is None:
        return None
    return sps, pps


def probe_parameter_sets(config: EncodingConfig) -> Optional[Tuple[bytes, bytes]]:
    """Encode one throwaway frame to learn the SPS/PPS the loop will produce.

    Every file is encoded with identical settings, so a single probe describes
    them all.  Putting the result in the SDP means a client can decode from the
    first keyframe instead of waiting to discover the parameter sets in-band.
    """
    if not config.scaled:
        return None  # resolution varies per file, so no stable parameter sets
    command = [
        config.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"color=c=black:s={config.width}x{config.height}:r={config.fps}",
        "-frames:v", "1", *video_encoder_args(config), "-f", "h264", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("parameter set probe failed: %s", exc)
        return None
    if result.returncode != 0:
        log.debug(
            "parameter set probe failed: %s", result.stderr.decode(errors="replace")
        )
        return None
    return parameter_sets(result.stdout)


def sprop_parameter_sets(sets: Tuple[bytes, bytes]) -> str:
    return ",".join(base64.b64encode(unit).decode("ascii") for unit in sets)


def profile_level_id(sps: bytes) -> Optional[str]:
    """profile_idc / constraint flags / level_idc, as the SDP hex triplet."""
    if len(sps) < 4:
        return None
    return sps[1:4].hex()


def _rtp_url(port: int, rtcp_port: int) -> str:
    return f"rtp://127.0.0.1:{port}?rtcpport={rtcp_port}&pkt_size={RTP_PKT_SIZE}"


def build_command(
    path: Path,
    config: EncodingConfig,
    video_port: int,
    video_rtcp_port: int,
    audio_port: Optional[int] = None,
    audio_rtcp_port: Optional[int] = None,
    source_has_audio: bool = True,
    duration: Optional[float] = None,
) -> List[str]:
    """Build the ffmpeg command that pushes one file to the local RTP sockets."""
    want_audio = config.audio and audio_port is not None
    # A file with no audio track still has to produce an audio stream, otherwise
    # the loop would go silent-but-broken for clients that already negotiated it.
    silence = want_audio and not source_has_audio

    cmd = [
        config.ffmpeg, "-hide_banner", "-nostdin",
        "-loglevel", config.loglevel,
        "-re", "-i", str(path),
    ]
    if silence:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono"]

    filters = [f"fps={config.fps}"]
    if config.scaled:
        filters.insert(
            0,
            f"scale={config.width}:{config.height}:force_original_aspect_ratio=decrease,"
            f"pad={config.width}:{config.height}:(ow-iw)/2:(oh-ih)/2",
        )
    cmd += [
        "-map", "0:v:0",
        "-vf", ",".join(filters),
        *video_encoder_args(config),
        "-payload_type", str(VIDEO_PAYLOAD_TYPE),
        "-f", "rtp", _rtp_url(video_port, video_rtcp_port),
    ]
    if want_audio:
        cmd += [
            "-map", "1:a:0" if silence else "0:a:0",
            "-c:a", "pcm_alaw", "-ar", str(AUDIO_CLOCK_RATE), "-ac", "1",
            "-payload_type", str(AUDIO_PAYLOAD_TYPE),
        ]
        if silence:
            # This output holds only the generated silence, so "-shortest" has
            # nothing to be short of: bound it by the file's own duration and
            # let the stall watchdog handle files whose duration is unknown.
            cmd += ["-t", f"{duration:.3f}"] if duration else ["-shortest"]
        cmd += ["-f", "rtp", _rtp_url(audio_port, audio_rtcp_port or audio_port + 1)]
    return cmd
