#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""LSP-style ``Content-Length`` framing for JSON-RPC messages over a byte stream.

The same codec as ``partcad_utils.framing``, duplicated here
on purpose: the addon talks to the *standalone* service, so it cannot import the
service's Python package -- FreeCAD's interpreter has neither it nor ``partcad``
installed, which is the whole point of using the frozen bundle.

Less of it, though: no attachments. The service sends a file as raw bytes after
a message only to a client that says it reads them, and this one never says so
-- the addon is handed no file over the wire at all (an export is written to a
path the addon names), so the service writes to it exactly what it always has.
"""

import json
from typing import Any, BinaryIO, Optional


def write_message(stream: BinaryIO, message: Any) -> None:
    """Encode ``message`` as JSON and write it with a ``Content-Length`` header."""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(b"Content-Length: %d\r\n\r\n" % len(body))
    stream.write(body)
    stream.flush()


def _read_headers(stream: BinaryIO) -> Optional[dict]:
    """Read header lines up to the blank separator. Returns None at EOF.

    A line at a time, as ``partcad_utils.framing`` reads them: on a buffered
    stream a byte at a time was a call per byte of every header.
    """
    raw = b""
    while True:
        line = stream.readline()
        if not line:
            # End of stream, before a header or part way through one.
            return None
        if not line.strip():
            if raw:
                break
            continue  # a blank line before any header
        raw += line

    headers = {}
    for line in raw.split(b"\r\n"):
        if not line.strip():
            continue
        name, _, value = line.partition(b":")
        headers[name.strip().lower().decode("ascii")] = value.strip().decode("ascii")
    return headers


def read_message(stream: BinaryIO) -> Optional[Any]:
    """Read one framed JSON-RPC message. Returns None at end of stream."""
    headers = _read_headers(stream)
    if headers is None:
        return None
    length = int(headers.get("content-length", 0))
    body = stream.read(length)
    if len(body) < length:
        # Truncated stream: treat as end of input rather than raising.
        return None
    return json.loads(body)
