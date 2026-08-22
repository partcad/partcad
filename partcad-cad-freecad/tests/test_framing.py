#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The addon's copy of the Content-Length codec."""

import io

from partcad_freecad.framing import read_message, write_message


def test_round_trip():
    stream = io.BytesIO()
    write_message(stream, {"jsonrpc": "2.0", "id": 1, "method": "info"})
    stream.seek(0)
    assert read_message(stream) == {"jsonrpc": "2.0", "id": 1, "method": "info"}


def test_header_is_lsp_framing():
    stream = io.BytesIO()
    write_message(stream, {"a": 1})
    assert stream.getvalue() == b'Content-Length: 8\r\n\r\n{"a": 1}'


def test_non_ascii_length_counts_bytes():
    stream = io.BytesIO()
    write_message(stream, {"desc": "Ø"})
    stream.seek(0)
    assert read_message(stream) == {"desc": "Ø"}


def test_several_messages_in_one_stream():
    stream = io.BytesIO()
    write_message(stream, {"id": 1})
    write_message(stream, {"id": 2})
    stream.seek(0)
    assert read_message(stream) == {"id": 1}
    assert read_message(stream) == {"id": 2}
    assert read_message(stream) is None


def test_eof_returns_none():
    assert read_message(io.BytesIO(b"")) is None


def test_truncated_body_returns_none():
    assert read_message(io.BytesIO(b"Content-Length: 40\r\n\r\n{}")) is None
