#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the LSP-style Content-Length JSON-RPC framing codec.

Every test runs against both copies of it: 'partcad_utils.framing', and
'partcad/wrappers/partcad_framing.py', which is what a sandbox runs, since a
sandbox cannot import 'partcad_utils'. The copy is the same bytes (a test in
'tests/partcad/unit/test_wrapper_frames.py' holds it to that), but it is loaded
there as a module of its own, beside nothing else of this package -- so it is
loaded that way here too, and an import the copy cannot satisfy on its own fails
here rather than in every sandbox.
"""

import importlib.util
import io
import os
import threading

import pytest

import partcad_utils.framing


def _sandbox_copy():
    """'partcad_framing' as a wrapper imports it: a file of its own, found without importing 'partcad'."""
    package = importlib.util.find_spec("partcad")
    path = os.path.join(package.submodule_search_locations[0], "wrappers", "partcad_framing.py")
    spec = importlib.util.spec_from_file_location("partcad_framing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module", params=["core", "sandbox"])
def framing(request):
    """The frame as the daemon and its clients have it, then as a wrapper has it."""
    if request.param == "core":
        return partcad_utils.framing
    return _sandbox_copy()


def test_write_message_emits_content_length_header_and_blank_line(framing):
    buf = io.BytesIO()
    framing.write_message(buf, {"jsonrpc": "2.0", "id": 1, "result": None})
    data = buf.getvalue()
    assert data.startswith(b"Content-Length: ")
    header, body = data.split(b"\r\n\r\n", 1)
    assert b"Content-Length: %d" % len(body) in header


def test_read_message_round_trips_a_written_message(framing):
    buf = io.BytesIO()
    message = {"jsonrpc": "2.0", "id": 7, "method": "info", "params": {"a": 1}}
    framing.write_message(buf, message)
    buf.seek(0)
    assert framing.read_message(buf) == message


def test_read_message_reads_two_consecutive_messages(framing):
    buf = io.BytesIO()
    first = {"jsonrpc": "2.0", "id": 1, "method": "a"}
    second = {"jsonrpc": "2.0", "id": 2, "method": "b"}
    framing.write_message(buf, first)
    framing.write_message(buf, second)
    buf.seek(0)
    assert framing.read_message(buf) == first
    assert framing.read_message(buf) == second


def test_read_message_returns_none_at_eof(framing):
    assert framing.read_message(io.BytesIO(b"")) is None


def test_read_message_handles_non_ascii_payload_via_content_length_bytes(framing):
    buf = io.BytesIO()
    message = {"jsonrpc": "2.0", "id": 3, "result": "café ☕"}
    framing.write_message(buf, message)
    buf.seek(0)
    assert framing.read_message(buf) == message


def test_a_value_json_has_no_form_for_is_refused_whoever_the_peer_is(framing):
    """Only bytes are given a form JSON lacks; anything else unknown is a bug to hear about, not to write."""
    for attachments in (False, True):
        with pytest.raises(TypeError, match="Object of type object is not JSON serializable"):
            framing.encode_message({"result": object()}, attachments=attachments)


# --- Attachments -------------------------------------------------------------
#
# A file in a message crosses as raw bytes after the body, for a peer that said
# it reads them, and as base64 inside it for any other -- which is what it was
# before attachments existed (see 'partcad_utils.framing').


def _frame(framing, message, **options):
    return b"".join(framing.encode_message(message, **options))


def test_bytes_go_after_the_body_and_come_back_where_they_were(framing):
    message = {"jsonrpc": "2.0", "id": 1, "result": {"content": b"\x00\xff\n", "files": [b"a", b"bc"]}}
    buf = io.BytesIO(_frame(framing, message, attachments=True))
    header = buf.getvalue().split(b"\r\n\r\n", 1)[0]
    assert b"Attachment-Lengths: 3,1,2" in header
    assert framing.read_message(buf) == message


def test_the_frame_is_the_one_the_editor_reads(framing):
    # Pinned byte for byte: 'ide/vscode/src/test/suite/framing.test.ts' reads
    # this very frame, so the two ends cannot come to disagree about it.
    picture = b"\x00\xff\n"
    message = {"id": 1, "result": {"content": picture, "again": picture, "other": b"ok"}}
    body = b'{"id": 1, "result": {"content": {"$attachment": 0}, "again": {"$attachment": 0}, "other": {"$attachment": 1}}}'
    assert _frame(framing, message, attachments=True) == (
        b"Content-Length: %d\r\nAttachment-Lengths: 3,2\r\n\r\n" % len(body) + body + picture + b"ok"
    )


def test_one_object_named_twice_is_sent_once(framing):
    picture = b"<svg/>" * 100
    frame = framing.encode_message({"a": picture, "b": [picture, picture]}, attachments=True)
    assert frame[2:] == [picture]
    decoded = framing.read_message(io.BytesIO(b"".join(frame)))
    assert decoded == {"a": picture, "b": [picture, picture]}
    # And read back as one object, which is what the editor's reader does too.
    assert decoded["b"][0] is decoded["a"]


def test_a_peer_that_reads_no_attachments_is_sent_base64_as_before(framing):
    message = {"result": {"content": b"\x89PNG", "name": "a.png"}}
    data = _frame(framing, message)
    assert b"Attachment-Lengths" not in data
    assert framing.read_message(io.BytesIO(data)) == {"result": {"content": "iVBORw==", "name": "a.png"}}
    assert framing.to_json(message) == '{"result": {"content": "iVBORw==", "name": "a.png"}}'


def test_a_file_is_bytes_whichever_way_it_came(framing):
    assert framing.as_bytes(b"\x89PNG") == b"\x89PNG"
    assert framing.as_bytes("iVBORw==") == b"\x89PNG"
    assert framing.as_bytes(bytearray(b"ab")) == b"ab"
    assert framing.as_bytes(None) is None


def test_saying_it_reads_attachments_is_what_the_peer_records(framing):
    data = _frame(framing, {"id": 1, "method": "render.inline"}, accept_attachments=True)
    assert b"\r\nAccept-Attachments: 1\r\n\r\n" in data
    peer = framing.Peer()
    assert framing.read_message(io.BytesIO(data), peer) == {"id": 1, "method": "render.inline"}
    assert peer.attachments is True

    older = framing.Peer()
    framing.read_message(io.BytesIO(_frame(framing, {"id": 2, "method": "info"})), older)
    assert older.attachments is False


def test_only_a_reference_by_itself_is_an_attachment(framing):
    # An object that merely has the key among others is the data it says it is.
    message = {"a": {"$attachment": 0, "note": "not a reference"}, "b": b"x"}
    assert framing.read_message(io.BytesIO(_frame(framing, message, attachments=True))) == message


def test_a_message_cut_off_is_the_end_of_the_stream_not_an_error(framing):
    data = _frame(framing, {"a": b"0123456789"}, attachments=True)
    # In an attachment, in the header, and in the body.
    assert framing.read_message(io.BytesIO(data[:-3])) is None
    assert framing.read_message(io.BytesIO(b"Content-Length: 2\r\n")) is None
    assert framing.read_message(io.BytesIO(b"Content-Length: 10\r\n\r\n{}")) is None


def test_an_unbuffered_pipe_is_read_whole(framing):
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
            framing.write_message(writer, message, attachments=True)
            framing.write_message(writer, {"id": 2})

    thread = threading.Thread(target=write)
    thread.start()
    try:
        assert framing.read_message(reader) == message
        assert framing.read_message(reader) == {"id": 2}
        assert framing.read_message(reader) is None
    finally:
        thread.join()
        reader.close()


def test_blank_lines_before_a_header_are_not_a_message(framing):
    buf = io.BytesIO(b"\r\n" + _frame(framing, {"id": 1}))
    assert framing.read_message(buf) == {"id": 1}


def test_a_pipe_frame_cut_off_is_the_end_of_the_stream():
    """The asyncio reader the named pipe is read with says so at a disconnect, not by raising.

    `read_frame` catches `asyncio.IncompleteReadError` by that name, so the
    module has to have `asyncio` imported where the except clause is evaluated
    -- which is only ever when a client goes away. Moved into the functions that
    open pipes, it was a NameError on every disconnect, and no test that only
    exchanges whole messages notices.
    """
    import asyncio

    from partcad_utils import win_pipe

    async def read(data: bytes):
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        return await win_pipe.read_frame(reader)

    assert asyncio.run(read(b"")) is None
    assert asyncio.run(read(b"Content-Length: 10\r\n")) is None
    assert asyncio.run(read(b"Content-Length: 10\r\n\r\n{}")) is None


# --- In a buffer -------------------------------------------------------------
#
# A wrapper's answer is read out of everything its process wrote, which can have
# something in front of it (see 'partcad_utils.framing').


def test_a_message_is_found_past_whatever_is_in_front_of_it(framing):
    frame = _frame(framing, {"id": 1, "result": b"\x00\xff"}, attachments=True)

    assert framing.find_message(frame) == 0
    assert framing.find_message(b"progress\n" + frame) == len(b"progress\n")
    # What a progress meter leaves: no newline before the message.
    assert framing.find_message(b"writing... " + frame) == len(b"writing... ")
    assert framing.find_message(b"no message here") is None


def test_a_header_that_is_not_whole_is_not_a_message(framing):
    frame = _frame(framing, {"id": 1, "result": b"\x00\xff"}, attachments=True)

    # Mentioned in passing, cut off, or saying nothing of its length.
    assert framing.find_message(b"Content-Length: 99\r\n\r\n{}") is None
    assert framing.find_message(frame[:-1]) is None
    assert framing.find_message(b"Content-Length: soon\r\n\r\n") is None
    # Nor is one whose headers never end: a line that names the header and stops.
    assert framing.find_message(b"Content-Length: 2\r\n") is None
    assert framing.find_message(b"Content-Length: 2\r\n{}") is None
    # ... while the whole one after them is.
    assert framing.find_message(b"Content-Length: soon\r\n\r\n" + frame) == len(b"Content-Length: soon\r\n\r\n")


def test_a_length_below_nothing_is_not_a_message(framing):
    """A header announcing a negative length would end before it began, and is text that only looks like one.

    Taken for a message, it would be "whole" with no bytes after it at all --
    and then fail to read, where it should have been passed over for the real
    one behind it.
    """
    frame = _frame(framing, {"id": 1, "result": b"\x00\xff"}, attachments=True)

    for text in (b"Content-Length: -1\r\n\r\n", b"Content-Length: 0\r\nAttachment-Lengths: 2,-2\r\n\r\n"):
        assert framing.find_message(text) is None
        assert framing.find_message(text + frame) == len(text)
        with pytest.raises(ValueError, match="no whole message"):
            framing.message_at(text)


def test_a_message_read_from_a_buffer_ends_where_it_says_and_owns_its_bytes(framing):
    picture = b"\x89PNG" * 1000
    message = {"id": 1, "result": {"a": picture, "b": picture, "c": b""}}
    data = bytearray(b"noise\n" + _frame(framing, message, attachments=True) + b"after")

    read, end = framing.message_at(data, framing.find_message(data))

    assert read == message
    assert read["result"]["a"] is read["result"]["b"]
    assert type(read["result"]["a"]) is bytes
    assert data[end:] == b"after"
    # Nothing read refers into the buffer it was read from.
    data[:] = b""
    assert read["result"]["a"] == picture


def test_there_is_no_message_where_none_is_whole(framing):
    with pytest.raises(ValueError, match="no whole message"):
        framing.message_at(b"Content-Length: 10\r\n\r\n{}")
