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
"""

import json
from typing import Any, BinaryIO, Optional

_HEADER_SEPARATOR = b"\r\n\r\n"


def write_message(stream: BinaryIO, message: Any) -> None:
    """Encode ``message`` as JSON and write it with a ``Content-Length`` header."""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(b"Content-Length: %d\r\n\r\n" % len(body))
    stream.write(body)
    stream.flush()


def _read_headers(stream: BinaryIO) -> Optional[dict]:
    """Read header lines up to the blank separator. Returns None at EOF."""
    raw = b""
    while _HEADER_SEPARATOR not in raw:
        chunk = stream.read(1)
        if not chunk:
            # Clean EOF only counts if we have not started a header.
            return None if not raw else {}
        raw += chunk

    headers = {}
    for line in raw.split(b"\r\n"):
        if not line:
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
    return json.loads(body.decode("utf-8"))
