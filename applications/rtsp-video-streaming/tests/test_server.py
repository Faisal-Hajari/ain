"""End-to-end RTSP handshake tests against a real server (no ffmpeg involved)."""

import asyncio
import socket
import struct

import pytest

from rtsp_video_streaming.ffmpeg import EncodingConfig
from rtsp_video_streaming.playlist import Playlist
from rtsp_video_streaming.rtsp import parse_request_head
from rtsp_video_streaming.sdp import AUDIO, VIDEO
from rtsp_video_streaming.server import RtspServer
from rtsp_video_streaming.source import MediaSource


def rtp_packet(seq=1, timestamp=1000, payload=b"frame"):
    return struct.pack("!BBHII", 0x80, 96, seq, timestamp, 0x1234) + payload


class Client:
    """A minimal RTSP client that can also read interleaved media frames."""

    def __init__(self, reader, writer, url):
        self.reader = reader
        self.writer = writer
        self.url = url
        self.session = None
        self._cseq = 0

    @classmethod
    async def connect(cls, server):
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        return cls(reader, writer, f"rtsp://127.0.0.1:{server.port}{server.path}")

    async def request(self, method, url=None, **headers):
        self._cseq += 1
        lines = [f"{method} {url or self.url} RTSP/1.0", f"CSeq: {self._cseq}"]
        if self.session:
            lines.append(f"Session: {self.session}")
        lines += [f"{key.replace('_', '-')}: {value}" for key, value in headers.items()]
        self.writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
        await self.writer.drain()
        return await self.read_response()

    async def read_response(self):
        head = await self.reader.readuntil(b"\r\n\r\n")
        status_line, _, header_block = head.decode().partition("\r\n")
        response = parse_request_head(b"X X RTSP/1.0\r\n" + header_block.encode())
        status = int(status_line.split()[1])
        length = int(response.headers.get("Content-Length", "0") or 0)
        body = await self.reader.readexactly(length) if length else b""
        if "Session" in response.headers:
            self.session = response.headers["Session"].split(";")[0]
        return status, response.headers, body

    async def read_interleaved(self):
        assert await self.reader.readexactly(1) == b"$"
        channel = (await self.reader.readexactly(1))[0]
        length = struct.unpack("!H", await self.reader.readexactly(2))[0]
        return channel, await self.reader.readexactly(length)

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, OSError):
            pass


@pytest.fixture
async def server(tmp_path):
    source = MediaSource(Playlist(tmp_path), EncodingConfig())
    server = RtspServer(source, path="live", host="127.0.0.1", port=0)
    await server.start()
    serve = asyncio.create_task(server.serve_forever())
    yield server
    serve.cancel()
    await asyncio.gather(serve, return_exceptions=True)
    await server.stop()


async def setup_tcp(client, kind_suffix, channels):
    return await client.request(
        "SETUP",
        url=f"{client.url}/{kind_suffix}",
        Transport=f"RTP/AVP/TCP;unicast;interleaved={channels[0]}-{channels[1]}",
    )


async def play_over_tcp(server):
    client = await Client.connect(server)
    await setup_tcp(client, "streamid=0", (0, 1))
    await setup_tcp(client, "streamid=1", (2, 3))
    status, headers, _ = await client.request("PLAY")
    assert status == 200
    return client, headers


async def test_options_advertises_the_methods(server):
    client = await Client.connect(server)
    status, headers, _ = await client.request("OPTIONS")
    assert status == 200
    assert "DESCRIBE" in headers["Public"] and "TEARDOWN" in headers["Public"]
    await client.close()


async def test_describe_returns_the_sdp_for_the_configured_path(server):
    client = await Client.connect(server)
    status, headers, body = await client.request("DESCRIBE", Accept="application/sdp")
    assert status == 200
    assert headers["Content-Type"] == "application/sdp"
    assert headers["Content-Base"].endswith("/live/")
    assert b"m=video 0 RTP/AVP 96" in body
    await client.close()


async def test_describe_of_an_unknown_path_is_404(server):
    client = await Client.connect(server)
    status, _, _ = await client.request(
        "DESCRIBE", url=f"rtsp://127.0.0.1:{server.port}/nope"
    )
    assert status == 404
    await client.close()


async def test_setup_echoes_the_interleaved_channels_and_opens_a_session(server):
    client = await Client.connect(server)
    status, headers, _ = await setup_tcp(client, "streamid=0", (0, 1))
    assert status == 200
    assert "interleaved=0-1" in headers["Transport"]
    assert client.session and client.session in server.sessions
    await client.close()


async def test_setup_rejects_a_transport_we_cannot_serve(server):
    client = await Client.connect(server)
    status, _, _ = await setup_tcp(client, "streamid=0", (0, 1))
    assert status == 200
    status, _, _ = await client.request(
        "SETUP", url=f"{client.url}/streamid=1", Transport="RTP/AVP;multicast;port=9000-9001"
    )
    assert status == 461
    await client.close()


async def test_play_returns_rtp_info_for_each_setup_stream(server):
    client, headers = await play_over_tcp(server)
    rtp_info = headers["RTP-Info"]
    assert "streamid=0" in rtp_info and "streamid=1" in rtp_info
    assert "seq=" in rtp_info and "rtptime=" in rtp_info
    await client.close()


async def test_media_flows_to_a_playing_client_on_its_own_channels(server):
    client, _ = await play_over_tcp(server)

    server.source.publish_rtp(VIDEO, rtp_packet(seq=1, payload=b"video-nal"))
    channel, packet = await asyncio.wait_for(client.read_interleaved(), 2)
    assert channel == 0
    assert packet[12:] == b"video-nal"

    server.source.publish_rtp(AUDIO, rtp_packet(seq=1, payload=b"alaw"))
    channel, packet = await asyncio.wait_for(client.read_interleaved(), 2)
    assert channel == 2
    assert packet[12:] == b"alaw"

    server.source.publish_rtcp(VIDEO, server.source.rewriters[VIDEO].sender_report())
    channel, report = await asyncio.wait_for(client.read_interleaved(), 2)
    assert channel == 1 and report[1] == 200
    await client.close()


async def test_one_encoder_feeds_several_clients(server):
    first, _ = await play_over_tcp(server)
    second, _ = await play_over_tcp(server)
    assert server.source.subscriber_count == 2

    server.source.publish_rtp(VIDEO, rtp_packet(payload=b"shared"))
    for client in (first, second):
        channel, packet = await asyncio.wait_for(client.read_interleaved(), 2)
        assert channel == 0 and packet[12:] == b"shared"
    await first.close()
    await second.close()


async def test_nothing_is_sent_before_play_or_after_pause(server):
    client = await Client.connect(server)
    await setup_tcp(client, "streamid=0", (0, 1))
    server.source.publish_rtp(VIDEO, rtp_packet(payload=b"too-early"))
    assert server.source.subscriber_count == 0

    status, _, _ = await client.request("PLAY")
    assert status == 200
    status, _, _ = await client.request("PAUSE")
    assert status == 200
    assert server.source.subscriber_count == 0

    server.source.publish_rtp(VIDEO, rtp_packet(payload=b"after-pause"))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client.read_interleaved(), 0.2)
    await client.close()


async def test_teardown_and_disconnect_release_the_session(server):
    client, _ = await play_over_tcp(server)
    session_id = client.session
    status, _, _ = await client.request("TEARDOWN")
    assert status == 200
    assert session_id not in server.sessions
    assert server.source.subscriber_count == 0

    other, _ = await play_over_tcp(server)
    await other.close()
    for _ in range(50):
        if not server.sessions:
            break
        await asyncio.sleep(0.02)
    assert server.sessions == {}
    assert server.source.subscriber_count == 0
    await client.close()


async def test_requests_for_an_unknown_session_are_rejected(server):
    client = await Client.connect(server)
    client.session = "99999999999999"
    assert (await client.request("PLAY"))[0] == 454
    assert (await client.request("TEARDOWN"))[0] == 454
    await client.close()


async def test_unsupported_method_is_501(server):
    client = await Client.connect(server)
    assert (await client.request("RECORD"))[0] == 501
    await client.close()


async def test_get_parameter_keeps_the_session_alive(server):
    client, _ = await play_over_tcp(server)
    status, headers, _ = await client.request("GET_PARAMETER")
    assert status == 200
    assert headers["Session"].startswith(client.session)
    assert client.session in server.sessions
    await client.close()


async def test_udp_transport_delivers_rtp_to_the_client_port(server):
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(2)
    rtcp_receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rtcp_receiver.bind(("127.0.0.1", 0))
    rtp_port = receiver.getsockname()[1]
    rtcp_port = rtcp_receiver.getsockname()[1]

    client = await Client.connect(server)
    status, headers, _ = await client.request(
        "SETUP",
        url=f"{client.url}/streamid=0",
        Transport=f"RTP/AVP;unicast;client_port={rtp_port}-{rtcp_port}",
    )
    assert status == 200
    assert f"client_port={rtp_port}-{rtcp_port}" in headers["Transport"]
    assert "server_port=" in headers["Transport"]
    assert (await client.request("PLAY"))[0] == 200

    await asyncio.sleep(0.05)  # let the send sockets attach to the loop
    for _ in range(5):
        server.source.publish_rtp(VIDEO, rtp_packet(payload=b"udp-video"))
        await asyncio.sleep(0.02)
    data = await asyncio.to_thread(receiver.recv, 2048)
    assert data[12:] == b"udp-video"

    receiver.close()
    rtcp_receiver.close()
    await client.close()


async def test_interleaved_data_from_the_client_is_skipped(server):
    """Clients send RTCP receiver reports back on the control connection."""
    client, _ = await play_over_tcp(server)
    client.writer.write(b"$\x01\x00\x04\xde\xad\xbe\xef")
    await client.writer.drain()
    status, _, _ = await client.request("GET_PARAMETER")
    assert status == 200
    await client.close()


# -- malformed requests ----------------------------------------------------
async def test_malformed_content_length_is_400_not_a_traceback(server):
    """A body length we cannot parse is the client's mistake, not ours."""
    client = await Client.connect(server)
    client.writer.write(
        b"SET_PARAMETER " + client.url.encode() + b" RTSP/1.0\r\n"
        b"CSeq: 1\r\nContent-Length: abc\r\n\r\n"
    )
    await client.writer.drain()
    status, _, _ = await asyncio.wait_for(client.read_response(), 2)
    assert status == 400
    await client.close()


async def test_negative_content_length_is_400(server):
    client = await Client.connect(server)
    client.writer.write(
        b"SET_PARAMETER " + client.url.encode() + b" RTSP/1.0\r\n"
        b"CSeq: 1\r\nContent-Length: -1\r\n\r\n"
    )
    await client.writer.drain()
    status, _, _ = await asyncio.wait_for(client.read_response(), 2)
    assert status == 400
    await client.close()


async def test_an_absurd_content_length_is_refused_before_reading_it(server):
    """Otherwise a client can make the server wait on a gigabyte it never sends."""
    client = await Client.connect(server)
    client.writer.write(
        b"SET_PARAMETER " + client.url.encode() + b" RTSP/1.0\r\n"
        b"CSeq: 1\r\nContent-Length: 1000000000\r\n\r\n"
    )
    await client.writer.drain()
    status, _, _ = await asyncio.wait_for(client.read_response(), 2)
    assert status == 400
    await client.close()


async def test_a_body_within_the_limit_is_still_read(server):
    client = await Client.connect(server)
    body = b"x" * 512
    client.writer.write(
        b"SET_PARAMETER " + client.url.encode() + b" RTSP/1.0\r\n"
        b"CSeq: 1\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    await client.writer.drain()
    status, _, _ = await asyncio.wait_for(client.read_response(), 2)
    assert status == 200
    await client.close()


async def test_an_oversized_request_head_is_400_not_a_traceback(server):
    """The reader refuses to buffer it; that has to surface as a status."""
    client = await Client.connect(server)
    client.writer.write(b"OPTIONS " + client.url.encode() + b" RTSP/1.0\r\nCSeq: 1\r\n")
    client.writer.write(b"X-Padding: " + b"p" * (128 * 1024) + b"\r\n\r\n")
    try:
        await client.writer.drain()
    except (ConnectionError, OSError):  # the server may close mid-write
        pass
    status, _, _ = await asyncio.wait_for(client.read_response(), 2)
    assert status == 400
    await client.close()


# -- SETUP and session state -----------------------------------------------
async def test_aggregate_setup_without_a_stream_id_sets_up_video(server):
    client = await Client.connect(server)
    status, headers, _ = await client.request(
        "SETUP", Transport="RTP/AVP/TCP;unicast;interleaved=0-1"
    )
    assert status == 200
    session = server.sessions[client.session]
    assert list(session.streams) == [VIDEO]
    await client.close()


async def test_a_failed_udp_setup_answers_461_and_leaks_no_sockets(server, monkeypatch):
    """The second socket failing must not strand the first one."""
    import rtsp_video_streaming.server as server_module

    real_socket = socket.socket
    created = []

    def flaky_socket(family=socket.AF_INET, type=socket.SOCK_STREAM, *args, **kwargs):
        # Only the UDP pair this test is about; the loop builds stream sockets
        # of its own to accept connections with.
        if type != socket.SOCK_DGRAM:
            return real_socket(family, type, *args, **kwargs)
        sock = real_socket(family, type, *args, **kwargs)
        created.append(sock)
        if len(created) == 2:  # the RTCP socket of the pair
            sock.close()
            raise OSError("no more sockets")
        return sock

    monkeypatch.setattr(server_module.socket, "socket", flaky_socket)

    client = await Client.connect(server)
    status, _, _ = await client.request(
        "SETUP",
        url=f"{client.url}/streamid=0",
        Transport="RTP/AVP;unicast;client_port=45678-45679",
    )
    assert status == 461
    assert all(sock.fileno() == -1 for sock in created)
    await client.close()


async def test_play_resumes_after_pause(server):
    client, _ = await play_over_tcp(server)
    status, _, _ = await client.request("PAUSE")
    assert status == 200
    assert server.source.subscriber_count == 0

    status, _, _ = await client.request("PLAY")
    assert status == 200
    assert server.source.subscriber_count == 1

    server.source.publish_rtp(VIDEO, rtp_packet(payload=b"after-resume"))
    channel, packet = await asyncio.wait_for(client.read_interleaved(), 2)
    assert channel == 0 and packet[12:] == b"after-resume"
    await client.close()


# -- backlog ---------------------------------------------------------------
def test_a_lagging_client_is_cut_at_a_frame_boundary():
    """Dropping mid-frame hands the decoder a broken picture, not a clean gap."""
    from rtsp_video_streaming.server import RtspConnection

    class FakeTransport:
        def __init__(self):
            self.backlog = 0

        def is_closing(self):
            return False

        def get_write_buffer_size(self):
            return self.backlog

    class FakeWriter:
        def __init__(self):
            self.transport = FakeTransport()
            self.written = []

        def get_extra_info(self, _name):
            return ("127.0.0.1", 1)

        def write(self, data):
            self.written.append(data)

    writer = FakeWriter()
    connection = RtspConnection(None, None, writer)

    def send(marker):
        connection.write_video(0, struct.pack("!BBHII", 0x80, 96 | (0x80 if marker else 0),
                                              1, 0, 1) + b"nal")

    # A frame arrives as three packets, the last one marked. The backlog fills
    # partway through, so the rest of that frame goes too...
    send(False)
    writer.transport.backlog = 99_000_000
    send(False)
    writer.transport.backlog = 0
    send(True)
    assert len(writer.written) == 1

    # ...and the next frame, which starts clean, is sent again.
    send(False)
    send(True)
    assert len(writer.written) == 3
