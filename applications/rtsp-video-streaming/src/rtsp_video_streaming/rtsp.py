"""RTSP 1.0 message parsing and formatting (RFC 2326, the subset we serve)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

RTSP_VERSION = "RTSP/1.0"
CRLF = "\r\n"

STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    454: "Session Not Found",
    455: "Method Not Valid In This State",
    459: "Aggregate Operation Not Allowed",
    461: "Unsupported Transport",
    500: "Internal Server Error",
    501: "Not Implemented",
}


class ParseError(ValueError):
    pass


_MISSING = object()


class Headers(Dict[str, str]):
    """Case-insensitive header mapping that remembers the original casing.

    Every entry point that names a key has to go through ``_keys``, deletion
    included: an override that reaches only half of them leaves the two
    mappings disagreeing, and ``"CSeq" in headers`` then answers True for a
    header that ``headers["cseq"]`` raises ``KeyError`` for.
    """

    def __init__(self, items=()):
        super().__init__()
        self._keys: Dict[str, str] = {}
        self.update(items)

    def __setitem__(self, key: str, value: str) -> None:
        lower = key.lower()
        existing = self._keys.get(lower)
        if existing is not None and existing != key:
            super().__delitem__(existing)
        self._keys[lower] = key
        super().__setitem__(key, value)

    def __getitem__(self, key: str) -> str:
        return super().__getitem__(self._keys[key.lower()])

    def __delitem__(self, key: str) -> None:
        stored = self._keys.pop(key.lower())
        super().__delitem__(stored)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._keys

    def setdefault(self, key: str, default: str = "") -> str:
        if key in self:
            return self[key]
        self[key] = default
        return default

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key: str, default=_MISSING):
        try:
            stored = self._keys.pop(key.lower())
        except KeyError:
            if default is _MISSING:
                raise
            return default
        return super().pop(stored)

    def update(self, items=(), **extra) -> None:  # type: ignore[override]
        pairs = items.items() if hasattr(items, "items") else items
        for key, value in pairs:
            self[key] = value
        for key, value in extra.items():
            self[key] = value

    def clear(self) -> None:
        self._keys.clear()
        super().clear()


@dataclass
class Request:
    method: str
    uri: str
    version: str
    headers: Headers
    body: bytes = b""

    @property
    def cseq(self) -> Optional[str]:
        return self.headers.get("CSeq")

    @property
    def session(self) -> Optional[str]:
        value = self.headers.get("Session")
        if not value:
            return None
        return value.split(";", 1)[0].strip()

    @property
    def path(self) -> str:
        parsed = urlparse(self.uri)
        return parsed.path or "/"


@dataclass
class Response:
    status: int = 200
    headers: Headers = field(default_factory=Headers)
    body: bytes = b""

    def encode(self) -> bytes:
        reason = STATUS_TEXT.get(self.status, "Error")
        lines = [f"{RTSP_VERSION} {self.status} {reason}"]
        headers = Headers(self.headers)
        if self.body:
            headers["Content-Length"] = str(len(self.body))
        lines += [f"{key}: {value}" for key, value in headers.items()]
        head = CRLF.join(lines) + CRLF + CRLF
        return head.encode("utf-8") + self.body


def parse_request_head(head: bytes) -> Request:
    """Parse a complete request head (everything before the blank line)."""
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("request is not valid UTF-8") from exc

    lines = text.split(CRLF) if CRLF in text else text.split("\n")
    lines = [line for line in lines if line != ""]
    if not lines:
        raise ParseError("empty request")

    parts = lines[0].split()
    if len(parts) != 3:
        raise ParseError(f"malformed request line: {lines[0]!r}")
    method, uri, version = parts

    headers = Headers()
    for line in lines[1:]:
        if ":" not in line:
            raise ParseError(f"malformed header: {line!r}")
        key, value = line.split(":", 1)
        headers[key.strip()] = value.strip()
    return Request(method=method.upper(), uri=uri, version=version, headers=headers)


@dataclass
class Transport:
    """A parsed (and answerable) Transport header."""

    lower: str = "UDP"  # "UDP" or "TCP"
    interleaved: Optional[Tuple[int, int]] = None
    client_ports: Optional[Tuple[int, int]] = None
    server_ports: Optional[Tuple[int, int]] = None
    ssrc: Optional[int] = None

    @property
    def is_tcp(self) -> bool:
        return self.lower == "TCP"

    def encode(self) -> str:
        parts = ["RTP/AVP/TCP" if self.is_tcp else "RTP/AVP", "unicast"]
        if self.is_tcp and self.interleaved is not None:
            parts.append(f"interleaved={self.interleaved[0]}-{self.interleaved[1]}")
        if not self.is_tcp:
            if self.client_ports:
                parts.append(f"client_port={self.client_ports[0]}-{self.client_ports[1]}")
            if self.server_ports:
                parts.append(f"server_port={self.server_ports[0]}-{self.server_ports[1]}")
        if self.ssrc is not None:
            parts.append(f"ssrc={self.ssrc:08X}")
        return ";".join(parts)


def _parse_port_pair(value: str) -> Optional[Tuple[int, int]]:
    try:
        first, _, second = value.partition("-")
        low = int(first)
        high = int(second) if second else low + 1
    except ValueError:
        return None
    return low, high


def parse_transport(header: str) -> Transport:
    """Pick the first transport specification we can actually serve."""
    for spec in header.split(","):
        fields = [part.strip() for part in spec.split(";") if part.strip()]
        if not fields:
            continue
        protocol = fields[0].upper()
        if not protocol.startswith("RTP/AVP"):
            continue
        transport = Transport(lower="TCP" if protocol.endswith("/TCP") else "UDP")
        if "multicast" in (part.lower() for part in fields[1:]):
            continue  # unicast only
        for item in fields[1:]:
            key, _, value = item.partition("=")
            key = key.strip().lower()
            if key == "interleaved":
                transport.interleaved = _parse_port_pair(value)
            elif key == "client_port":
                transport.client_ports = _parse_port_pair(value)
        if transport.is_tcp and transport.interleaved is None:
            transport.interleaved = (0, 1)
        if not transport.is_tcp and transport.client_ports is None:
            continue  # a UDP setup without client ports is unusable
        return transport
    raise ParseError(f"no supported transport in {header!r}")


def public_methods() -> str:
    return ", ".join(
        ["OPTIONS", "DESCRIBE", "SETUP", "PLAY", "PAUSE", "TEARDOWN",
         "GET_PARAMETER", "SET_PARAMETER"]
    )


def interleaved_frame(channel: int, payload: bytes) -> bytes:
    return b"$" + bytes([channel & 0xFF]) + len(payload).to_bytes(2, "big") + payload
