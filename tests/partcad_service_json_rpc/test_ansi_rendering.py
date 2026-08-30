#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Rendering the log display on the daemon, for clients that cannot.

The CLI receives structured events and replays them through
`logging_ansi_terminal`, which owns the colours and the multi-line progress
footer. The VS Code extension is TypeScript and cannot host that state machine,
so it printed `LEVEL: message` in one colour and dropped every process/action
marker -- and the alternative was a second implementation of the footer in
another language.

A client asks for `log.mode {"ansi": true}` once, on connecting, and from then
on its log events arrive already drawn. What is covered here is that the drawing
is the CLI's own, that asking turns the structured stream *off* rather than
doubling it, and that one connection's footer cannot reach another's terminal.
"""

import logging

from partcad_utils.logging_ansi_render import AnsiEventRenderer, event_to_record

ESC = chr(27)


def render(events):
    """Feed events to a renderer and return everything it drew."""
    drawn = []
    renderer = AnsiEventRenderer(drawn.append)
    for event in events:
        renderer.handle(event)
    renderer.close()
    return "".join(drawn)


def test_a_log_record_is_drawn_with_its_level_colour():
    out = render([{"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "hello"}])
    assert "hello" in out
    # COLOR_INFO, the green+bold the CLI prefixes an INFO line with.
    assert ESC + "[92m" + ESC + "[1m" in out
    assert "INFO:" in out


def test_the_message_is_not_read_as_a_format_string():
    """A '%' in a log line must survive: it arrives as data, not as a template."""
    out = render([{"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "100% of 5 %s done"}])
    assert "100% of 5 %s done" in out


def test_a_process_draws_the_progress_footer():
    out = render(
        [
            {"kind": "process_start", "op": "Load", "package": "//pub", "item": None},
            {"kind": "action_start", "op": "Fetch", "package": "//pub", "item": "index"},
            {"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "working"},
        ]
    )
    # The footer: the "[ running / total ]" line, the action beneath it, and the
    # no-wrap guard around them.
    assert "[ 1 / 1 ]" in out
    assert "Load" in out and "//pub:index" in out
    assert ESC + "[?7l" in out and ESC + "[?7h" in out


def test_the_footer_is_erased_before_the_next_line_is_written():
    """The redraw is cursor-relative: up one line and erase, once per footer line."""
    out = render(
        [
            {"kind": "process_start", "op": "Load", "package": "//pub", "item": None},
            {"kind": "action_start", "op": "Fetch", "package": "//pub", "item": "index"},
            {"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "working"},
        ]
    )
    assert ESC + "[1A" + ESC + "[2K" in out


def test_a_process_that_ends_takes_its_footer_with_it():
    out = render(
        [
            {"kind": "process_start", "op": "Load", "package": "//pub", "item": None},
            {"kind": "process_end", "op": "Load", "package": "//pub", "item": None},
        ]
    )
    # Nothing of the footer is left behind: the last thing drawn is the erase.
    assert out.endswith(ESC + "[2K") or out == ""


def test_an_unknown_event_is_not_drawn():
    assert render([{"kind": "items", "packages": []}]) == ""
    assert event_to_record({"kind": "stats"}) is None


def test_two_renderers_keep_their_own_footers():
    """One per connection: the footer erases by cursor position, so a shared
    renderer would have each client erasing lines from the other's terminal."""
    first, second = [], []
    a = AnsiEventRenderer(first.append)
    b = AnsiEventRenderer(second.append)
    a.handle({"kind": "process_start", "op": "Load", "package": "//a", "item": None})
    a.handle({"kind": "action_start", "op": "Fetch", "package": "//a", "item": "x"})
    a.handle({"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "a"})
    b.handle({"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "b"})
    a.close()
    b.close()

    # The second renderer never started a process, so it has no footer to erase
    # and must not emit the cursor movements the first one does.
    assert ESC + "[1A" in "".join(first)
    assert ESC + "[1A" not in "".join(second)
    assert "a" in "".join(first) and "b" in "".join(second)


# ---------------------------------------------------------------------------
# The transport half: asking replaces the structured stream, it does not add to
# it. Sending both would double the traffic and give the client two renderings
# of the same line to reconcile.
# ---------------------------------------------------------------------------

import base64
import io
import threading

from partcad_service_json_rpc.rpc.dispatcher import Handler
from partcad_service_json_rpc.transport import stdio
from partcad_utils.framing import read_message, write_message


class _Emitter:
    """The bit of the session the transport binds a sink to."""

    def __init__(self):
        self.sink = None

    def set_sink(self, sink):
        self.sink = sink

    def emit(self, event, payload=None):
        if self.sink is not None:
            self.sink(event, payload)


class _Session:
    def __init__(self):
        self.emitter = _Emitter()


def _serve(requests, handler):
    """Run the stdio transport over in-memory streams and return what it wrote."""
    inbound = io.BytesIO()
    for request in requests:
        write_message(inbound, request)
    inbound.seek(0)
    outbound = io.BytesIO()
    stdio.serve(inbound, outbound, _Session(), {"speak": handler})
    outbound.seek(0)

    messages = []
    while True:
        message = read_message(outbound)
        if message is None:
            return messages
        messages.append(message)


def _speak(session, params):
    session.emitter.emit("log", {"kind": "log", "levelno": logging.INFO, "levelname": "INFO", "message": "hello"})
    return {"said": True}


def test_without_asking_the_client_gets_the_structured_records():
    messages = _serve([{"jsonrpc": "2.0", "id": 1, "method": "speak", "params": {}}], _speak)
    methods = [m.get("method") for m in messages if "method" in m]
    assert methods == ["log"]


def test_asking_for_ansi_replaces_the_records_with_the_drawing():
    messages = _serve(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "log.mode", "params": {"ansi": True}},
            {"jsonrpc": "2.0", "id": 2, "method": "speak", "params": {}},
        ],
        _speak,
    )
    assert {"jsonrpc": "2.0", "id": 1, "result": {"ansi": True}} in messages

    methods = [m.get("method") for m in messages if "method" in m]
    assert "log" not in methods, "the structured stream must stop, not run beside the drawing"
    assert "terminal" in methods

    drawn = "".join(
        base64.b64decode(m["params"]["line"]).decode("utf-8") for m in messages if m.get("method") == "terminal"
    )
    assert "hello" in drawn
    assert ESC + "[92m" in drawn, "the drawing carries the colours, which the records did not"


def test_the_mode_can_be_turned_back_off():
    messages = _serve(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "log.mode", "params": {"ansi": True}},
            {"jsonrpc": "2.0", "id": 2, "method": "log.mode", "params": {"ansi": False}},
            {"jsonrpc": "2.0", "id": 3, "method": "speak", "params": {}},
        ],
        _speak,
    )
    assert {"jsonrpc": "2.0", "id": 2, "result": {"ansi": False}} in messages
    methods = [m.get("method") for m in messages if "method" in m]
    assert "log" in methods and "terminal" not in methods


def test_array_params_are_refused_rather_than_ending_the_connection():
    """`log.mode` bypasses the dispatcher, so it does its own parameter check.

    JSON-RPC allows `params` to be an array. `.get` on a list raises, and the
    transports catch neither -- the socket handler would drop the connection and
    the stdio loop would exit, both instead of answering the request.
    """
    messages = _serve(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "log.mode", "params": ["ansi"]},
            {"jsonrpc": "2.0", "id": 2, "method": "speak", "params": {}},
        ],
        _speak,
    )

    errors = [m for m in messages if m.get("id") == 1 and "error" in m]
    assert errors, f"expected an error for array params, got {messages}"
    assert errors[0]["error"]["code"] == -32602

    # And the connection is still serving: the request after it was answered.
    assert any(m.get("id") == 2 for m in messages), "the transport stopped instead of carrying on"


def test_absent_params_are_allowed():
    """`log.mode` with no params at all means "not ansi", not a protocol error."""
    messages = _serve([{"jsonrpc": "2.0", "id": 1, "method": "log.mode"}], _speak)
    assert {"jsonrpc": "2.0", "id": 1, "result": {"ansi": False}} in messages
