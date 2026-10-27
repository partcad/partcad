#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Windows named-pipe rendezvous: its name, and probing what answers on it.

The counterpart of the AF_UNIX half of :mod:`partcad_utils.workspace`, and here
for the same reason: the daemon serves the pipe these functions name, and clients
look for it under the same name, so the name is computed in one place. Serving
the pipe is `partcad_service_json_rpc.win_pipe`; stopping and enumerating is
`partcad_client.daemon`.

NOTE: Windows-only. It is not exercised in the Linux dev container / CI;
Windows-specific APIs are reached only inside functions so the module still
byte-compiles (and imports) on POSIX.
"""

import asyncio
import hashlib

from . import framing
from .workspace import LIVENESS_METHOD

_HEADER_SEP = b"\r\n\r\n"
STOP_METHOD = "daemon.stop"

PIPE_PREFIX = r"\\.\pipe"
PIPE_BASENAME_PREFIX = "partcad-"


def pipe_hash(root_path: str) -> str:
    return hashlib.sha256(root_path.encode("utf-8")).hexdigest()[:16]


def pipe_name(root_path: str) -> str:
    return "%s\\%s%s" % (PIPE_PREFIX, PIPE_BASENAME_PREFIX, pipe_hash(root_path))


def is_pipe_alive(name: str, timeout: float = 1.0) -> bool:
    """True if a daemon answers rpc.discover on the named pipe."""
    reply = pipe_request(name, LIVENESS_METHOD, timeout)
    return isinstance(reply, dict) and reply.get("id") == 0 and "result" in reply


def pipe_request(name: str, method: str, timeout: float, params=None):
    """Send one request over the named pipe and return the reply (None on error)."""
    try:
        return asyncio.run(_pipe_roundtrip(name, method, timeout, params))
    except Exception:  # pylint: disable=broad-except
        return None


async def _pipe_roundtrip(name: str, method: str, timeout: float, params=None):  # pragma: no cover - Windows only
    loop = asyncio.get_event_loop()
    transport = None
    try:
        # ProactorEventLoop.create_pipe_connection connects to a named pipe.
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await asyncio.wait_for(loop.create_pipe_connection(lambda: protocol, name), timeout=timeout)
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        write_frame(writer, {"jsonrpc": "2.0", "id": 0, "method": method, "params": params or {}})
        await writer.drain()
        return await asyncio.wait_for(read_frame(reader), timeout=timeout)
    finally:
        if transport is not None:
            transport.close()


def write_frame(writer, message, attachments: bool = False) -> None:
    """One message on an asyncio stream, framed as ``partcad_utils.framing`` frames it.

    ``attachments`` as there: only for a peer that said it reads them.
    """
    for chunk in framing.encode_message(message, attachments):
        writer.write(chunk)


async def read_frame(reader, peer=None):
    """One message from an asyncio stream, or None at its end.

    ``peer`` is told what the sender said it reads (``framing.Peer``).
    """
    try:
        raw = await reader.readuntil(_HEADER_SEP)
    except asyncio.IncompleteReadError:
        return None
    headers = framing.parse_headers(raw)
    framing.observe(headers, peer)
    length = int(headers.get("content-length", 0))
    try:
        body = await reader.readexactly(length)
        segments = [await reader.readexactly(size) for size in framing.attachment_lengths(headers)]
    except asyncio.IncompleteReadError:
        return None
    return framing.decode_body(body, segments)
