import pytest

from rtsp_video_streaming.rtsp import (
    Headers,
    ParseError,
    Response,
    interleaved_frame,
    parse_request_head,
    parse_transport,
)


def test_headers_are_case_insensitive():
    headers = Headers({"CSeq": "4"})
    assert headers["cseq"] == "4"
    assert "CSEQ" in headers
    headers["cseq"] = "5"
    assert headers["CSeq"] == "5"
    assert len(headers) == 1


def test_parse_request_head_extracts_line_and_headers():
    request = parse_request_head(
        b"DESCRIBE rtsp://host:8554/live RTSP/1.0\r\n"
        b"CSeq: 2\r\nAccept: application/sdp\r\n\r\n"
    )
    assert request.method == "DESCRIBE"
    assert request.path == "/live"
    assert request.cseq == "2"
    assert request.headers["accept"] == "application/sdp"


def test_session_header_ignores_timeout_parameter():
    request = parse_request_head(
        b"PLAY rtsp://h/live RTSP/1.0\r\nCSeq: 3\r\nSession: 12345;timeout=60\r\n\r\n"
    )
    assert request.session == "12345"


@pytest.mark.parametrize("head", [b"", b"GARBAGE\r\n\r\n", b"PLAY url RTSP/1.0\r\nbad\r\n\r\n"])
def test_malformed_requests_raise(head):
    with pytest.raises(ParseError):
        parse_request_head(head)


def test_parse_transport_tcp_interleaved():
    transport = parse_transport("RTP/AVP/TCP;unicast;interleaved=2-3")
    assert transport.is_tcp and transport.interleaved == (2, 3)


def test_parse_transport_udp_client_ports():
    transport = parse_transport("RTP/AVP;unicast;client_port=6000-6001")
    assert not transport.is_tcp and transport.client_ports == (6000, 6001)


def test_parse_transport_prefers_a_supported_spec_over_multicast():
    transport = parse_transport(
        "RTP/AVP;multicast;port=7000-7001,RTP/AVP/TCP;unicast;interleaved=0-1"
    )
    assert transport.is_tcp


def test_parse_transport_rejects_unusable_headers():
    with pytest.raises(ParseError):
        parse_transport("RTP/SAVP;unicast;client_port=6000-6001")
    with pytest.raises(ParseError):
        parse_transport("RTP/AVP;multicast;port=7000-7001")


def test_transport_encode_round_trips_server_ports():
    transport = parse_transport("RTP/AVP;unicast;client_port=6000-6001")
    transport.server_ports = (9000, 9001)
    transport.ssrc = 0xDEADBEEF
    encoded = transport.encode()
    assert "client_port=6000-6001" in encoded
    assert "server_port=9000-9001" in encoded
    assert "ssrc=DEADBEEF" in encoded


def test_response_sets_content_length():
    encoded = Response(200, Headers({"CSeq": "1"}), b"body").encode()
    assert encoded.endswith(b"\r\n\r\nbody")
    assert b"Content-Length: 4" in encoded


def test_interleaved_frame_layout():
    frame = interleaved_frame(1, b"abc")
    assert frame == b"$\x01\x00\x03abc"


def test_headers_stay_case_insensitive_when_entries_are_removed():
    """Both mappings have to agree, or lookups and membership disagree."""
    headers = Headers({"CSeq": "4", "Session": "abc"})

    del headers["cseq"]
    assert "CSeq" not in headers and "cseq" not in headers
    assert headers.get("CSeq") is None
    with pytest.raises(KeyError):
        headers["CSeq"]

    assert headers.pop("SESSION") == "abc"
    assert "Session" not in headers
    assert headers.pop("Session", "fallback") == "fallback"
    with pytest.raises(KeyError):
        headers.pop("Session")

    headers["Content-Length"] = "3"
    headers.clear()
    assert "content-length" not in headers and len(headers) == 0


def test_headers_update_keeps_the_case_insensitive_index():
    headers = Headers()
    headers.update({"CSeq": "1"})
    headers.update([("Session", "abc")])
    headers.update(Public="OPTIONS")
    assert headers["cseq"] == "1"
    assert headers["session"] == "abc"
    assert headers["public"] == "OPTIONS"


def test_a_rewritten_header_keeps_only_the_newest_casing():
    headers = Headers({"cseq": "1"})
    headers["CSeq"] = "2"
    assert list(headers) == ["CSeq"]
    assert headers["cseq"] == "2"
