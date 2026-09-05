"""SDP generation for the DESCRIBE response."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from rtsp_video_streaming.ffmpeg import (
    AUDIO_CLOCK_RATE,
    AUDIO_PAYLOAD_TYPE,
    VIDEO_CLOCK_RATE,
    VIDEO_PAYLOAD_TYPE,
    profile_level_id,
    sprop_parameter_sets,
)

VIDEO = "video"
AUDIO = "audio"


def stream_kinds(with_audio: bool) -> Sequence[str]:
    return (VIDEO, AUDIO) if with_audio else (VIDEO,)


def control_id(kind: str) -> str:
    """The per-stream control suffix used in SETUP URLs."""
    return "streamid=0" if kind == VIDEO else "streamid=1"


def video_fmtp(parameter_sets: Optional[Tuple[bytes, bytes]]) -> str:
    """The a=fmtp line for the video stream.

    With the SPS/PPS in hand a client can decode the very first keyframe it
    receives; without them it has to wait to pick them up in-band.
    """
    parts = ["packetization-mode=1"]
    if parameter_sets is not None:
        level = profile_level_id(parameter_sets[0])
        if level:
            parts.append(f"profile-level-id={level}")
        parts.append(f"sprop-parameter-sets={sprop_parameter_sets(parameter_sets)}")
    return f"a=fmtp:{VIDEO_PAYLOAD_TYPE} " + ";".join(parts)


def build_sdp(
    session_name: str,
    with_audio: bool,
    parameter_sets: Optional[Tuple[bytes, bytes]] = None,
    origin_ip: str = "127.0.0.1",
) -> str:
    """Describe the fixed encoding the loop always produces."""
    lines = [
        "v=0",
        f"o=- 0 0 IN IP4 {origin_ip}",
        f"s={session_name}",
        "c=IN IP4 0.0.0.0",
        "t=0 0",
        "a=tool:rtsp-video-streaming",
        "a=type:broadcast",
        "a=range:npt=now-",
        "a=control:*",
        f"m=video 0 RTP/AVP {VIDEO_PAYLOAD_TYPE}",
        f"a=rtpmap:{VIDEO_PAYLOAD_TYPE} H264/{VIDEO_CLOCK_RATE}",
        video_fmtp(parameter_sets),
        f"a=control:{control_id(VIDEO)}",
    ]
    if with_audio:
        lines += [
            f"m=audio 0 RTP/AVP {AUDIO_PAYLOAD_TYPE}",
            f"a=rtpmap:{AUDIO_PAYLOAD_TYPE} PCMA/{AUDIO_CLOCK_RATE}",
            f"a=control:{control_id(AUDIO)}",
        ]
    return "\r\n".join(lines) + "\r\n"
