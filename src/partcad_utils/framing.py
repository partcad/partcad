#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""LSP-style ``Content-Length`` framing for JSON-RPC messages over a byte stream.

This is the same framing the Language Server Protocol uses, so a client that
speaks nothing else -- ``vscode-jsonrpc``, an older editor extension, the
FreeCAD addon -- reads and writes it unchanged. The functions operate on any
binary file object, which keeps them trivially unit-testable with
``io.BytesIO``.

**Attachments.** A file the daemon hands back -- a render, a CAE model, the
thumbnails of a Build vs Buy table, an instruction book -- used to cross as
base64 inside the JSON. That made it a third bigger and, worse, made both ends
spend a large file's worth of time encoding and decoding it: the daemon while
holding the GIL, which every other thread of it then waited for, and the editor
on its extension host's event loop. So a message may carry raw segments after
its body::

    Content-Length: <body bytes>\\r\\n
    Attachment-Lengths: <bytes>,<bytes>,...\\r\\n
    \\r\\n
    <body><segment 0><segment 1>...

and the body names each one where it belongs, as ``{"$attachment": <index>}``.
Writing them is asked for with ``attachments=True``, which turns every ``bytes``
value in the message into a segment; without it the same value is written as
base64 text, which is exactly what such a field held before attachments existed.

That is what keeps a skewed pair working -- the editor extension and the FreeCAD
addon are released apart from the daemon. A daemon writes attachments only to a
peer that said it reads them, by sending ``Accept-Attachments: 1`` in the header
of a message (see :class:`Peer`); an older peer never says so, and gets the
base64 it has always had, under the same key. So a reader of such a field takes
both forms, and :func:`as_bytes` is how. No request carries a file today, so a
client writes none, and need not know whether its daemon could read them.

The same object appearing twice in one message is one segment, named twice: an
instruction book shows the same illustration on several pages.

There is no other way for a file to reach a client -- a path on a local
daemon's disk, say -- on purpose: two ways of delivering one file are two ways
of getting it wrong, and this one serves a remote daemon as well as a local one.
"""

import base64
import json
from typing import Any, BinaryIO, Optional

# The lengths of the raw segments that follow a message's body, in order.
ATTACHMENT_LENGTHS = "Attachment-Lengths"
# "You may send me attachments", from a peer that reads them. The value is the
# form of them it reads, and there is one.
ACCEPT_ATTACHMENTS = "Accept-Attachments"
# How a body names a segment.
ATTACHMENT_KEY = "$attachment"

_BINARY = (bytes, bytearray, memoryview)


class Peer:
    """What the other end of one connection has said it reads.

    One per connection, filled in by :func:`read_message` from the headers of
    what that end sends, and consulted by whoever writes back to it. The
    connection is the unit because the capability is the *client's*, and one
    daemon serves clients of several versions at once.
    """

    __slots__ = ("attachments",)

    def __init__(self, attachments: bool = False):
        self.attachments = attachments


def as_bytes(value) -> Optional[bytes]:
    """A file a message carried, whichever way it was carried.

    ``bytes`` when it came as an attachment, base64 text when the peer wrote
    none -- an older daemon, or a transport without them -- and ``None`` for no
    file at all.
    """
    if value is None:
        return None
    if isinstance(value, _BINARY):
        return bytes(value)
    return base64.b64decode(value)


def _unserializable(value):
    return TypeError("Object of type %s is not JSON serializable" % type(value).__name__)


def _base64(value):
    """``json.dumps``'s fallback for a peer that reads no attachments."""
    if isinstance(value, _BINARY):
        return base64.b64encode(value).decode("ascii")
    raise _unserializable(value)


def encode_message(message: Any, attachments: bool = False, accept_attachments: bool = False) -> list:
    """The frame of one message: its header, its body and its segments, in order.

    A list rather than one ``bytes``, so that a segment of forty megabytes is
    written as it is rather than copied in behind the header first.
    """
    segments: list = []
    if attachments:
        # By identity: one object, one segment, however often it appears. The
        # message keeps every value alive while this runs, so no id is reused.
        indices: dict = {}

        def default(value):
            if isinstance(value, _BINARY):
                index = indices.get(id(value))
                if index is None:
                    index = indices[id(value)] = len(segments)
                    segments.append(value)
                return {ATTACHMENT_KEY: index}
            raise _unserializable(value)

    else:
        default = _base64
    body = json.dumps(message, ensure_ascii=False, default=default).encode("utf-8")
    header = b"Content-Length: %d\r\n" % len(body)
    if segments:
        lengths = b",".join(b"%d" % memoryview(segment).nbytes for segment in segments)
        header += b"%s: %s\r\n" % (ATTACHMENT_LENGTHS.encode("ascii"), lengths)
    if accept_attachments:
        header += b"%s: 1\r\n" % ACCEPT_ATTACHMENTS.encode("ascii")
    return [header + b"\r\n", body, *segments]


def to_json(message: Any) -> str:
    """``message`` as JSON text, for a transport with no attachments at all (HTTP).

    Its files are base64 text there, and the rest is what ``json.dumps`` always
    wrote for it.
    """
    return json.dumps(message, default=_base64)


def write_message(stream: BinaryIO, message: Any, attachments: bool = False, accept_attachments: bool = False) -> None:
    """Encode ``message`` as JSON and write it with a ``Content-Length`` header.

    ``attachments`` writes its ``bytes`` values as raw segments after the body
    rather than as base64 inside it, which is only for a peer that said it reads
    them (:class:`Peer`). ``accept_attachments`` tells the peer that this end does.
    """
    for chunk in encode_message(message, attachments, accept_attachments):
        stream.write(chunk)
    stream.flush()


def parse_headers(raw: bytes) -> dict:
    """The header lines of one frame, by lower-case name."""
    headers: dict[str, str] = {}
    for line in raw.split(b"\r\n"):
        if not line.strip():
            continue
        name, _, value = line.partition(b":")
        headers[name.strip().lower().decode("ascii")] = value.strip().decode("ascii")
    return headers


def attachment_lengths(headers: dict) -> list:
    """The segment lengths a frame's headers announce, in order; none for most frames."""
    value = headers.get(ATTACHMENT_LENGTHS.lower())
    if not value:
        return []
    return [int(length) for length in value.split(",")]


def observe(headers: dict, peer: Optional[Peer]) -> None:
    """Record on ``peer`` what the headers of a frame it sent say it reads."""
    if peer is not None and ACCEPT_ATTACHMENTS.lower() in headers:
        peer.attachments = True


def decode_body(body: bytes, segments: list) -> Any:
    """A frame's body as data, with each ``{"$attachment": i}`` its segment.

    ``json.loads`` is handed the bytes as they came: it recognises UTF-8 itself,
    and decoding them to a ``str`` first is one more copy of the whole body.
    """
    if not segments:
        return json.loads(body)

    def hook(obj):
        if len(obj) == 1 and ATTACHMENT_KEY in obj:
            return segments[obj[ATTACHMENT_KEY]]
        return obj

    return json.loads(body, object_hook=hook)


def _read_headers(stream: BinaryIO) -> Optional[dict]:
    """Read header lines up to the blank separator. Returns None at EOF.

    A line at a time: ``readline`` on a buffered stream -- a socket's file, a
    pipe, ``io.BytesIO`` -- finds the newline in what it has already read,
    where reading the header a byte at a time cost a small message a call per
    byte, more than half of its whole time. An unbuffered stream reads a byte at
    a time inside ``readline`` all the same, as correctly as before.
    """
    raw = b""
    while True:
        line = stream.readline()
        if not line:
            # End of stream -- and a header cut off part way is no message
            # either, any more than a body cut off is.
            return None
        if not line.strip():
            if raw:
                return parse_headers(raw)
            continue  # a blank line before any header
        raw += line


def _read_exactly(stream: BinaryIO, length: int) -> Optional[bytes]:
    """``length`` bytes, or None if the stream ends first.

    In a loop, because an unbuffered stream -- a raw pipe -- returns what one
    read of the operating system had, which for a segment of megabytes is less
    than was asked for without being the end of anything.
    """
    data = stream.read(length) or b""
    if len(data) == length:
        return data
    parts = [data]
    received = len(data)
    while received < length:
        chunk = stream.read(length - received)
        if not chunk:
            return None
        parts.append(chunk)
        received += len(chunk)
    return b"".join(parts)


def read_message(stream: BinaryIO, peer: Optional[Peer] = None) -> Optional[Any]:
    """Read one framed JSON-RPC message. Returns None at end of stream.

    Its attachments, if it has any, are in it as ``bytes``. ``peer``, when
    given, is told what the sender said it reads (see :class:`Peer`).
    """
    headers = _read_headers(stream)
    if headers is None:
        return None
    observe(headers, peer)
    length = int(headers.get("content-length", 0))
    body = _read_exactly(stream, length)
    if body is None:
        # Truncated stream: treat as end of input rather than raising.
        return None
    segments = []
    for size in attachment_lengths(headers):
        segment = _read_exactly(stream, size)
        if segment is None:
            return None
        segments.append(segment)
    return decode_body(body, segments)
