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
`partcad_client_utils.daemon`.

NOTE: Windows-only. It is not exercised in the Linux dev container / CI;
Windows-specific APIs are reached only inside functions so the module still
byte-compiles (and imports) on POSIX.
"""

import asyncio
import hashlib
import json

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
    reply = pipe_request(name, "rpc.discover", timeout)
    return isinstance(reply, dict) and reply.get("id") == 0 and "result" in reply


def pipe_request(name: str, method: str, timeout: float):
    """Send one request over the named pipe and return the reply (None on error)."""
    try:
        return asyncio.run(_pipe_roundtrip(name, method, timeout))
    except Exception:  # pylint: disable=broad-except
        return None


async def _pipe_roundtrip(name: str, method: str, timeout: float):  # pragma: no cover - Windows only
    loop = asyncio.get_event_loop()
    transport = None
    try:
        # ProactorEventLoop.create_pipe_connection connects to a named pipe.
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await asyncio.wait_for(loop.create_pipe_connection(lambda: protocol, name), timeout=timeout)
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        write_frame(writer, {"jsonrpc": "2.0", "id": 0, "method": method, "params": {}})
        await writer.drain()
        return await asyncio.wait_for(read_frame(reader), timeout=timeout)
    finally:
        if transport is not None:
            transport.close()


def write_frame(writer, message) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    writer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)


async def read_frame(reader):
    raw = b""
    while _HEADER_SEP not in raw:
        chunk = await reader.read(1)
        if not chunk:
            return None
        raw += chunk
    headers = {}
    for line in raw.split(b"\r\n"):
        if b":" in line:
            k, _, v = line.partition(b":")
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get(b"content-length", b"0"))
    body = await reader.readexactly(length)
    return json.loads(body.decode("utf-8"))
