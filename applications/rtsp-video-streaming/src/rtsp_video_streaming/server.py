"""The RTSP server: one connection handler per client, one shared media source."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import struct
from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Tuple

from rtsp_video_streaming.rtsp import (
    Headers,
    ParseError,
    Request,
    Response,
    Transport,
    interleaved_frame,
    parse_request_head,
    parse_transport,
    public_methods,
)
from rtsp_video_streaming.rtp import ends_frame
from rtsp_video_streaming.sdp import VIDEO, build_sdp, control_id, stream_kinds
from rtsp_video_streaming.source import MediaSource

log = logging.getLogger(__name__)

SERVER_NAME = "rtsp-video-streaming"
SESSION_TIMEOUT_SECONDS = 60
MAX_REQUEST_BYTES = 64 * 1024
# SET_PARAMETER is the only method here that carries a body, and those are a
# line or two; anything larger is a client claiming a length it will not send.
MAX_BODY_BYTES = 8 * 1024
# Past this much queued data a client is not keeping up; drop rather than buffer.
MAX_TCP_BACKLOG_BYTES = 2 * 1024 * 1024


def _session_id() -> str:
    return str(int.from_bytes(os.urandom(6), "big")).zfill(14)


@dataclass
class StreamSetup:
    kind: str
    transport: Transport
    udp_rtp: Optional[asyncio.DatagramTransport] = None
    udp_rtcp: Optional[asyncio.DatagramTransport] = None

    def close(self) -> None:
        for transport in (self.udp_rtp, self.udp_rtcp):
            if transport is not None:
                transport.close()


@dataclass(eq=False)  # identity based: sessions live in a set of subscribers
class Session:
    """One client's RTSP session: its stream setups and playing state."""

    id: str
    connection: "RtspConnection"
    streams: Dict[str, StreamSetup] = field(default_factory=dict)
    playing: bool = False

    # -- Subscriber protocol ---------------------------------------------
    def deliver_rtp(self, kind: str, packet: bytes) -> None:
        setup = self.streams.get(kind)
        if setup is None or not self.playing:
            return
        if setup.transport.is_tcp:
            channel = setup.transport.interleaved[0]
            if kind == VIDEO:
                self.connection.write_video(channel, packet)
            else:
                self.connection.write_packet(channel, packet)
        elif setup.udp_rtp is not None:
            setup.udp_rtp.sendto(packet)

    def deliver_rtcp(self, kind: str, packet: bytes) -> None:
        setup = self.streams.get(kind)
        if setup is None or not self.playing:
            return
        if setup.transport.is_tcp:
            self.connection.write_packet(setup.transport.interleaved[1], packet)
        elif setup.udp_rtcp is not None:
            setup.udp_rtcp.sendto(packet)

    def close(self) -> None:
        self.playing = False
        for setup in self.streams.values():
            setup.close()
        self.streams.clear()


class _UdpSender(asyncio.DatagramProtocol):
    """Send-only endpoint; inbound RTCP receiver reports are ignored."""


class RtspServer:
    def __init__(
        self,
        source: MediaSource,
        path: str = "/live",
        host: str = "0.0.0.0",
        port: int = 8554,
        with_audio: bool = True,
        parameter_sets: Optional[Tuple[bytes, bytes]] = None,
    ) -> None:
        self.source = source
        self.path = "/" + path.strip("/")
        self.host = host
        self.port = port
        self.with_audio = with_audio
        self.parameter_sets = parameter_sets
        self.sessions: Dict[str, Session] = {}
        self._server: Optional[asyncio.AbstractServer] = None

    @property
    def kinds(self) -> Sequence[str]:
        return stream_kinds(self.with_audio)

    async def start(self) -> int:
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.host,
            port=self.port,
            # The reader refuses to buffer a longer head than this, so the limit
            # is the request-size guard: a bigger one raises LimitOverrunError.
            limit=MAX_REQUEST_BYTES,
        )
        sockets = self._server.sockets or ()
        bound_port = sockets[0].getsockname()[1] if sockets else self.port
        self.port = bound_port
        return bound_port

    async def serve_forever(self) -> None:
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        for session in list(self.sessions.values()):
            self.source.unsubscribe(session)
            session.close()
        self.sessions.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        connection = RtspConnection(self, reader, writer)
        await connection.run()

    # -- session bookkeeping ---------------------------------------------
    def register(self, session: Session) -> None:
        self.sessions[session.id] = session

    def drop(self, session: Session) -> None:
        self.sessions.pop(session.id, None)
        self.source.unsubscribe(session)
        session.close()

    def matches_path(self, request_path: str) -> bool:
        """Accept the aggregate URL and any per-stream control URL under it."""
        candidate = "/" + request_path.strip("/")
        return candidate == self.path or self.kind_for_path(request_path) is not None

    def kind_for_path(self, request_path: str) -> Optional[str]:
        candidate = "/" + request_path.strip("/")
        for kind in self.kinds:
            if candidate == f"{self.path}/{control_id(kind)}":
                return kind
        return None


class RtspConnection:
    def __init__(
        self,
        server: RtspServer,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.server = server
        self.reader = reader
        self.writer = writer
        self.peer = writer.get_extra_info("peername")
        self.sessions: Dict[str, Session] = {}
        self._closed = False
        self._dropping_frame = False

    # -- wire I/O ---------------------------------------------------------
    def _backlogged(self) -> bool:
        """Whether the client is too far behind to be sent anything more."""
        if self._closed:
            return True
        transport = self.writer.transport
        if transport is None or transport.is_closing():
            self._closed = True
            return True
        return transport.get_write_buffer_size() > MAX_TCP_BACKLOG_BYTES

    def _write(self, channel: int, payload: bytes) -> None:
        try:
            self.writer.write(interleaved_frame(channel, payload))
        except (ConnectionError, RuntimeError):  # pragma: no cover - racy teardown
            self._closed = True

    def write_packet(self, channel: int, payload: bytes) -> None:
        """Interleave one self-contained packet, dropping it if the client lags.

        Audio packets and RTCP reports each stand alone, so losing one costs
        exactly itself.
        """
        if self._backlogged():
            return
        self._write(channel, payload)

    def write_video(self, channel: int, packet: bytes) -> None:
        """Interleave one video packet, dropping whole frames when the client lags.

        A dropped packet is usually the middle of a fragmented NAL unit, and the
        decoder renders the resulting half-picture rather than skipping it.
        Dropping on to the end of the access unit costs no more bandwidth and
        leaves a clean gap, so playback resumes at the next frame.
        """
        if self._backlogged():
            self._dropping_frame = not ends_frame(packet)
            return
        if self._dropping_frame:
            self._dropping_frame = not ends_frame(packet)
            return
        self._write(channel, packet)

    def _send(self, response: Response) -> None:
        if self._closed:
            return
        headers = response.headers
        headers.setdefault("Server", SERVER_NAME)
        self.writer.write(response.encode())

    async def run(self) -> None:
        log.info("client connected: %s", self.peer)
        try:
            while not self._closed:
                message = await self._read_message()
                if message is None:
                    break
                request, body = message
                response = await self._dispatch(request, body)
                if response is not None:
                    self._send(response)
                    await self.writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:  # pragma: no cover - defensive
            log.exception("error handling client %s", self.peer)
        finally:
            await self.close()

    async def _read_message(self) -> Optional[Tuple[Request, bytes]]:
        """Read one RTSP request, skipping any interleaved data from the client."""
        while True:
            first = await self.reader.read(1)
            if not first:
                return None
            if first == b"$":
                header = await self.reader.readexactly(3)
                length = struct.unpack("!H", header[1:3])[0]
                await self.reader.readexactly(length)
                continue
            if first in b"\r\n":
                continue  # tolerate stray CRLF between requests
            try:
                head = first + await self.reader.readuntil(b"\r\n\r\n")
            except (asyncio.LimitOverrunError, ValueError) as exc:
                return self._reject(f"request head over {MAX_REQUEST_BYTES} bytes: {exc}")
            try:
                request = parse_request_head(head)
            except ParseError as exc:
                return self._reject(f"bad request: {exc}")
            try:
                length = self._body_length(request)
            except ValueError as exc:
                return self._reject(str(exc))
            body = await self.reader.readexactly(length) if length else b""
            return request, body

    @staticmethod
    def _body_length(request: Request) -> int:
        """The Content-Length to read, or ``ValueError`` if it is not usable."""
        raw = request.headers.get("Content-Length", "0") or "0"
        try:
            length = int(raw)
        except ValueError:
            raise ValueError(f"malformed Content-Length {raw!r}") from None
        if length < 0:
            raise ValueError(f"negative Content-Length {raw!r}")
        if length > MAX_BODY_BYTES:
            raise ValueError(f"Content-Length {length} over the {MAX_BODY_BYTES} byte limit")
        return length

    def _reject(self, reason: str) -> None:
        """Answer 400 and stop reading: the stream is no longer trustworthy."""
        log.warning("rejecting request from %s: %s", self.peer, reason)
        self._send(Response(status=400))
        return None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for session in list(self.sessions.values()):
            self.server.drop(session)
        self.sessions.clear()
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except (ConnectionError, OSError):  # pragma: no cover
            pass
        log.info("client disconnected: %s", self.peer)

    # -- request handling -------------------------------------------------
    _HANDLERS = {
        "OPTIONS": "_options",
        "DESCRIBE": "_describe",
        "SETUP": "_setup",
        "PLAY": "_play",
        "PAUSE": "_pause",
        "TEARDOWN": "_teardown",
        "GET_PARAMETER": "_keepalive",
        "SET_PARAMETER": "_keepalive",
    }

    async def _dispatch(self, request: Request, body: bytes) -> Optional[Response]:
        log.debug("%s %s from %s", request.method, request.uri, self.peer)
        name = self._HANDLERS.get(request.method)
        if name is None:
            return self._respond(request, 501)
        return await getattr(self, name)(request)

    def _respond(
        self,
        request: Request,
        status: int = 200,
        body: bytes = b"",
        headers: Optional[Dict[str, str]] = None,
        session: Optional[Session] = None,
    ) -> Response:
        response_headers = Headers()
        if request.cseq is not None:
            response_headers["CSeq"] = request.cseq
        if session is not None:
            response_headers["Session"] = f"{session.id};timeout={SESSION_TIMEOUT_SECONDS}"
        for key, value in (headers or {}).items():
            response_headers[key] = value
        return Response(status=status, headers=response_headers, body=body)

    def _session_for(self, request: Request) -> Optional[Session]:
        session_id = request.session
        if session_id is None:
            return None
        return self.sessions.get(session_id)

    async def _options(self, request: Request) -> Response:
        return self._respond(request, 200, headers={"Public": public_methods()})

    async def _describe(self, request: Request) -> Response:
        if not self.server.matches_path(request.path):
            return self._respond(request, 404)
        sdp = build_sdp(
            self.server.path.lstrip("/"),
            self.server.with_audio,
            self.server.parameter_sets,
        )
        base = request.uri.split("?")[0].rstrip("/") + "/"
        return self._respond(
            request,
            200,
            body=sdp.encode("utf-8"),
            headers={"Content-Type": "application/sdp", "Content-Base": base},
        )

    async def _setup(self, request: Request) -> Response:
        kind = self.server.kind_for_path(request.path)
        if kind is None:
            if not self.server.matches_path(request.path):
                return self._respond(request, 404)
            kind = VIDEO  # aggregate SETUP: assume the first stream
        header = request.headers.get("Transport")
        if not header:
            return self._respond(request, 400)
        try:
            transport = parse_transport(header)
        except ParseError:
            return self._respond(request, 461)

        session = self._session_for(request)
        if session is None:
            if request.session is not None:
                return self._respond(request, 454)
            session = Session(id=_session_id(), connection=self)
            self.sessions[session.id] = session
            self.server.register(session)
        if session.playing:
            return self._respond(request, 455, session=session)

        existing = session.streams.pop(kind, None)
        if existing is not None:
            existing.close()

        setup = StreamSetup(kind=kind, transport=transport)
        if not transport.is_tcp:
            try:
                await self._open_udp(setup)
            except OSError as exc:
                log.warning("cannot open UDP transport for %s: %s", self.peer, exc)
                return self._respond(request, 461, session=session)
        transport.ssrc = self.server.source.rewriters[kind].ssrc
        session.streams[kind] = setup
        return self._respond(
            request, 200, headers={"Transport": transport.encode()}, session=session
        )

    async def _open_udp(self, setup: StreamSetup) -> None:
        """Bind this stream's two sending sockets and wire them into the loop.

        Done before SETUP is answered, so the ``server_port`` the client reads is
        already sending by the time it can look. The address family follows the
        client's own, because the connection may well be IPv6.

        The stack unwinds every socket and transport opened so far if a later
        one fails, leaving SETUP free to answer 461 without leaking a descriptor.
        """
        host = self.peer[0] if self.peer else "127.0.0.1"
        loop = asyncio.get_running_loop()
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        wildcard = "::" if family == socket.AF_INET6 else "0.0.0.0"

        with contextlib.ExitStack() as opened:
            sockets = []
            for client_port in setup.transport.client_ports:
                sock = socket.socket(family, socket.SOCK_DGRAM)
                opened.callback(sock.close)
                sock.setblocking(False)
                sock.bind((wildcard, 0))
                sock.connect((host, client_port))
                sockets.append(sock)

            setup.transport.server_ports = (
                sockets[0].getsockname()[1],
                sockets[1].getsockname()[1],
            )
            setup.udp_rtp, _ = await loop.create_datagram_endpoint(
                _UdpSender, sock=sockets[0]
            )
            opened.callback(setup.udp_rtp.close)
            setup.udp_rtcp, _ = await loop.create_datagram_endpoint(
                _UdpSender, sock=sockets[1]
            )
            opened.pop_all()  # all of it opened: the setup owns it now

    async def _play(self, request: Request) -> Response:
        session = self._session_for(request)
        if session is None:
            return self._respond(request, 454)
        if not session.streams:
            return self._respond(request, 455, session=session)

        rtp_info = []
        base = self.server.path
        for kind in self.server.kinds:
            if kind not in session.streams:
                continue
            rewriter = self.server.source.rewriters[kind]
            url = f"{request.uri.split('?')[0].rstrip('/')}"
            if self.server.kind_for_path(request.path) is None:
                url = f"{url}/{control_id(kind)}"
            # Approximate by construction: the encoder is free-running and
            # shared, so more packets go out between here and the client
            # reading this. Clients treat RTP-Info as a hint, not a promise.
            rtp_info.append(
                f"url={url};seq={(rewriter.sequence + 1) & 0xFFFF};"
                f"rtptime={rewriter.timestamp}"
            )
        session.playing = True
        self.server.source.subscribe(session)
        log.info("session %s playing (%s)", session.id, base)
        return self._respond(
            request,
            200,
            headers={"Range": "npt=now-", "RTP-Info": ",".join(rtp_info)},
            session=session,
        )

    async def _pause(self, request: Request) -> Response:
        session = self._session_for(request)
        if session is None:
            return self._respond(request, 454)
        session.playing = False
        self.server.source.unsubscribe(session)
        return self._respond(request, 200, session=session)

    async def _teardown(self, request: Request) -> Response:
        session = self._session_for(request)
        if session is None:
            return self._respond(request, 454)
        self.sessions.pop(session.id, None)
        self.server.drop(session)
        return self._respond(request, 200)

    async def _keepalive(self, request: Request) -> Response:
        session = self._session_for(request)
        return self._respond(request, 200, session=session)
