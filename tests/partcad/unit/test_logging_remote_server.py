#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the server-side remote logging backend (partcad_utils).

The daemon uses this backend instead of the ANSI terminal renderer: rather than
drawing to a terminal, it forwards *structured* events (plain log records and
process/action start/end) to a hook, which the service ships to the client over
the JSON-RPC notification channel. It also tees real log records into a rotating
file, but never the pc_event control records.
"""

import logging

import partcad_utils.logging as pc_logging
import partcad_utils.logging_remote_server as remote_server


def setup_function():
    logging.getLogger("partcad").setLevel(logging.DEBUG)


def teardown_function():
    remote_server.fini()


def _collector():
    events = []
    return events, events.append


def test_log_record_forwarded_as_structured_event():
    events, hook = _collector()
    remote_server.init(hook)

    pc_logging.info("hello world")

    logs = [e for e in events if e["kind"] == "log"]
    assert any(e["message"] == "hello world" and e["levelname"] == "INFO" for e in logs)


def test_process_and_action_events_forwarded_in_order():
    events, hook = _collector()
    remote_server.init(hook)

    pc_logging.ops.process_start("build", "//pkg", "item")
    pc_logging.ops.action_start("render", "//pkg", "part")
    pc_logging.ops.action_end("render", "//pkg", "part")
    pc_logging.ops.process_end("build", "//pkg", "item")

    kinds = [e["kind"] for e in events if e["kind"] != "log"]
    assert kinds == ["process_start", "action_start", "action_end", "process_end"]

    start = next(e for e in events if e["kind"] == "process_start")
    assert start["op"] == "build"
    assert start["package"] == "//pkg"
    assert start["item"] == "item"


def test_fini_stops_forwarding():
    events, hook = _collector()
    remote_server.init(hook)
    remote_server.fini()

    pc_logging.info("after fini")

    assert events == []


def test_rotating_file_receives_logs_but_not_pc_events(tmp_path):
    events, hook = _collector()
    log_file = tmp_path / "partcad.log"
    remote_server.init(hook, log_file=str(log_file), file_level=logging.DEBUG)

    pc_logging.info("written to file")
    pc_logging.ops.process_start("build", "//pkg")

    remote_server.fini()

    content = log_file.read_text()
    assert "written to file" in content
    # The pc_event control records are not real log lines; they must not pollute
    # the persistent file.
    assert "process_start" not in content
