#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the LSP-style Content-Length JSON-RPC framing codec."""

import io
import os
import threading

from partcad_utils.framing import Peer, as_bytes, encode_message, read_message, to_json, write_message


def test_write_message_emits_content_length_header_and_blank_line():
    buf = io.BytesIO()
    write_message(buf, {"jsonrpc": "2.0", "id": 1, "result": None})
    data = buf.getvalue()
    assert data.startswith(b"Content-Length: ")
    header, body = data.split(b"\r\n\r\n", 1)
    assert b"Content-Length: %d" % len(body) in header


def test_read_message_round_trips_a_written_message():
    buf = io.BytesIO()
    message = {"jsonrpc": "2.0", "id": 7, "method": "info", "params": {"a": 1}}
    write_message(buf, message)
    buf.seek(0)
    assert read_message(buf) == message


def test_read_message_reads_two_consecutive_messages():
    buf = io.BytesIO()
    first = {"jsonrpc": "2.0", "id": 1, "method": "a"}
    second = {"jsonrpc": "2.0", "id": 2, "method": "b"}
    write_message(buf, first)
    write_message(buf, second)
    buf.seek(0)
    assert read_message(buf) == first
    assert read_message(buf) == second


def test_read_message_returns_none_at_eof():
    assert read_message(io.BytesIO(b"")) is None


def test_read_message_handles_non_ascii_payload_via_content_length_bytes():
    buf = io.BytesIO()
    message = {"jsonrpc": "2.0", "id": 3, "result": "café ☕"}
    write_message(buf, message)
    buf.seek(0)
    assert read_message(buf) == message


# --- Attachments -------------------------------------------------------------
#
# A file in a message crosses as raw bytes after the body, for a peer that said
# it reads them, and as base64 inside it for any other -- which is what it was
# before attachments existed (see 'partcad_utils.framing').


def _frame(message, **options):
    return b"".join(encode_message(message, **options))


def test_bytes_go_after_the_body_and_come_back_where_they_were():
    message = {"jsonrpc": "2.0", "id": 1, "result": {"content": b"\x00\xff\n", "files": [b"a", b"bc"]}}
    buf = io.BytesIO(_frame(message, attachments=True))
    header = buf.getvalue().split(b"\r\n\r\n", 1)[0]
    assert b"Attachment-Lengths: 3,1,2" in header
    assert read_message(buf) == message


def test_the_frame_is_the_one_the_editor_reads():
    # Pinned byte for byte: 'ide/vscode/src/test/suite/framing.test.ts' reads
    # this very frame, so the two ends cannot come to disagree about it.
    picture = b"\x00\xff\n"
    message = {"id": 1, "result": {"content": picture, "again": picture, "other": b"ok"}}
    body = b'{"id": 1, "result": {"content": {"$attachment": 0}, "again": {"$attachment": 0}, "other": {"$attachment": 1}}}'
    assert _frame(message, attachments=True) == (
        b"Content-Length: %d\r\nAttachment-Lengths: 3,2\r\n\r\n" % len(body) + body + picture + b"ok"
    )


def test_one_object_named_twice_is_sent_once():
    picture = b"<svg/>" * 100
    frame = encode_message({"a": picture, "b": [picture, picture]}, attachments=True)
    assert frame[2:] == [picture]
    decoded = read_message(io.BytesIO(b"".join(frame)))
    assert decoded == {"a": picture, "b": [picture, picture]}
    # And read back as one object, which is what the editor's reader does too.
    assert decoded["b"][0] is decoded["a"]


def test_a_peer_that_reads_no_attachments_is_sent_base64_as_before():
    message = {"result": {"content": b"\x89PNG", "name": "a.png"}}
    data = _frame(message)
    assert b"Attachment-Lengths" not in data
    assert read_message(io.BytesIO(data)) == {"result": {"content": "iVBORw==", "name": "a.png"}}
    assert to_json(message) == '{"result": {"content": "iVBORw==", "name": "a.png"}}'


def test_a_file_is_bytes_whichever_way_it_came():
    assert as_bytes(b"\x89PNG") == b"\x89PNG"
    assert as_bytes("iVBORw==") == b"\x89PNG"
    assert as_bytes(bytearray(b"ab")) == b"ab"
    assert as_bytes(None) is None


def test_saying_it_reads_attachments_is_what_the_peer_records():
    data = _frame({"id": 1, "method": "render.inline"}, accept_attachments=True)
    assert b"\r\nAccept-Attachments: 1\r\n\r\n" in data
    peer = Peer()
    assert read_message(io.BytesIO(data), peer) == {"id": 1, "method": "render.inline"}
    assert peer.attachments is True

    older = Peer()
    read_message(io.BytesIO(_frame({"id": 2, "method": "info"})), older)
    assert older.attachments is False


def test_only_a_reference_by_itself_is_an_attachment():
    # An object that merely has the key among others is the data it says it is.
    message = {"a": {"$attachment": 0, "note": "not a reference"}, "b": b"x"}
    assert read_message(io.BytesIO(_frame(message, attachments=True))) == message


def test_a_message_cut_off_is_the_end_of_the_stream_not_an_error():
    data = _frame({"a": b"0123456789"}, attachments=True)
    assert read_message(io.BytesIO(data[:-3])) is None
    assert read_message(io.BytesIO(b"Content-Length: 2\r\n")) is None


def test_an_unbuffered_pipe_is_read_whole():
    # A raw pipe returns what one read had, which for a big file is less than
    # asked for; and it has no buffer for readline to look into, so the header is
    # read a byte at a time there, as it always was.
    payload = bytes(range(256)) * 4096  # 1 MiB, more than a pipe holds at once
    message = {"id": 1, "result": {"content": payload}}
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "rb", buffering=0)
    writer = os.fdopen(write_fd, "wb", buffering=0)

    def write():
        with writer:
            write_message(writer, message, attachments=True)
            write_message(writer, {"id": 2})

    thread = threading.Thread(target=write)
    thread.start()
    try:
        assert read_message(reader) == message
        assert read_message(reader) == {"id": 2}
        assert read_message(reader) is None
    finally:
        thread.join()
        reader.close()


def test_blank_lines_before_a_header_are_not_a_message():
    buf = io.BytesIO(b"\r\n" + _frame({"id": 1}))
    assert read_message(buf) == {"id": 1}
