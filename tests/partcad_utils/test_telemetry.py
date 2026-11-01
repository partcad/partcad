#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The telemetry opt-out is a switch that something acts on.

'telemetry.type' is documented three ways ('pc system set telemetry type none',
'telemetry: type: none', PC_TELEMETRY_TYPE) and used to be written, read back by
'pc system telemetry info', and consulted by nothing that collects. These cover
the one function that now decides.
"""

import os
import subprocess
import sys
import types

import pytest

from partcad_utils import telemetry


def test_collecting_by_default(monkeypatch):
    monkeypatch.delenv("PC_TELEMETRY_TYPE", raising=False)
    assert telemetry.collecting() is True


def test_not_collecting_when_opted_out(monkeypatch):
    monkeypatch.setenv("PC_TELEMETRY_TYPE", "none")
    assert telemetry.collecting() is False


def test_collecting_when_a_backend_is_named(monkeypatch):
    monkeypatch.setenv("PC_TELEMETRY_TYPE", "sentry")
    assert telemetry.collecting() is True


def test_method_spans_are_off_by_default(monkeypatch):
    monkeypatch.delenv("PC_TELEMETRY_DETAIL", raising=False)
    telemetry.forget_settings()
    assert telemetry.method_spans() is False


def test_method_spans_when_asked_for(monkeypatch):
    monkeypatch.setenv("PC_TELEMETRY_DETAIL", telemetry.DETAIL_METHODS)
    telemetry.forget_settings()
    try:
        assert telemetry.method_spans() is True
    finally:
        telemetry.forget_settings()


def test_an_instrumented_method_is_called_either_way(monkeypatch):
    """The gate decides whether there is a span, never whether there is a call."""

    class Subject:
        def double(self, value):
            return value * 2

    instrumented = telemetry.instrument()(type("Subject", (Subject,), {"double": Subject.double}))

    for detail, expected in ((telemetry.DETAIL_ACTIONS, False), (telemetry.DETAIL_METHODS, True)):
        monkeypatch.setenv("PC_TELEMETRY_DETAIL", detail)
        telemetry.forget_settings()
        assert telemetry.method_spans() is expected
        assert instrumented().double(21) == 42
    telemetry.forget_settings()


def test_an_instrumented_function_is_called_either_way(monkeypatch):
    calls = []

    @telemetry.instrument_function("subject")
    def subject(value):
        calls.append(value)
        return value + 1

    for detail in (telemetry.DETAIL_ACTIONS, telemetry.DETAIL_METHODS):
        monkeypatch.setenv("PC_TELEMETRY_DETAIL", detail)
        telemetry.forget_settings()
        assert subject(1) == 2
    telemetry.forget_settings()
    assert calls == [1, 1]


# Loading the Sentry SDK was half of what importing the CLI cost (~150 ms of
# ~300 ms) on every command, collecting or not. It is loaded now when telemetry
# is first collected, and everything that hands Sentry something asks first
# whether this process has it.


def _modules_after(statement: str) -> set:
    """The modules a fresh interpreter has loaded after ``statement``."""
    script = "import sys\n%s\nprint('\\n'.join(sys.modules))" % statement
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True, env=env)
    return set(result.stdout.split())


def test_importing_the_cli_does_not_load_sentry():
    loaded = _modules_after("import partcad_cli.click.command")
    assert "sentry_sdk" not in loaded
    assert "partcad_utils.telemetry_sentry" not in loaded
    # The OpenTelemetry SDK came in with it; only the API is needed to start.
    assert "opentelemetry.sdk.trace" not in loaded


def test_reporting_an_error_does_not_load_sentry():
    # The logging functions are what every error passes through, on both ends.
    loaded = _modules_after("from partcad_utils import logging\nlogging.error('x')\nlogging.exception(ValueError('y'))")
    assert "sentry_sdk" not in loaded


def _recording_sentry():
    calls = []
    sentry = types.SimpleNamespace(
        capture_message=lambda message, level: calls.append(("message", message, level)),
        capture_exception=lambda error: calls.append(("exception", error)),
        flush=lambda timeout: calls.append(("flush", timeout)),
    )
    return sentry, calls


def test_a_process_with_sentry_hands_it_everything(monkeypatch):
    sentry, calls = _recording_sentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", sentry)
    error = ValueError("boom")

    telemetry.capture_message("said", level="error")
    telemetry.capture_exception(error)
    telemetry.flush(timeout=1.5)

    assert calls == [("message", "said", "error"), ("exception", error), ("flush", 1.5)]


def test_a_process_without_sentry_hands_it_nothing(monkeypatch):
    # Not loaded means not initialized, and an SDK that was never initialized
    # drops what it is given: skipping the call is what it would have done.
    monkeypatch.delitem(sys.modules, "sentry_sdk", raising=False)

    telemetry.capture_message("said", level="error")
    telemetry.capture_exception(ValueError("boom"))
    telemetry.flush(timeout=1.5)

    assert "sentry_sdk" not in sys.modules


def test_the_logging_functions_hand_sentry_what_they_always_did(monkeypatch):
    """Through 'telemetry' now, with the same arguments as when they imported the SDK."""
    from partcad_utils import logging as pc_logging

    sentry, calls = _recording_sentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", sentry)
    monkeypatch.setattr(pc_logging, "had_errors", pc_logging.had_errors)
    monkeypatch.setattr(pc_logging, "first_error", pc_logging.first_error)

    pc_logging.error("broken")
    pc_logging.critical("process_start: x")

    assert calls == [("message", "('broken',){}", "error"), ("message", "('process_start: x',){}", "debug")]


# An error logged as the interpreter finalizes -- by its last garbage collection,
# after the exit handlers have run -- reached Sentry's transport, which starts a
# thread for it, and starting a thread then never returns before Python 3.12:
# the process hung for good. See 'telemetry_sentry._close_at_exit'.

_LOGS_AS_IT_FINALIZES = """
import gc
import logging

from partcad_utils import telemetry_sentry

telemetry_sentry.init_sentry("0")


class LogsWhenCollected:
    def __del__(self):
        logging.getLogger("subject").error("logged as the interpreter finalizes")


# In a cycle, with nothing to collect it before the interpreter's own last
# collection: that one runs once the interpreter is finalizing, which is where
# a pending asyncio task is found and logged about.
gc.set_threshold(10**9)
cycle = LogsWhenCollected()
cycle.self = cycle
del cycle
"""


def test_an_error_logged_as_the_interpreter_finalizes_does_not_hold_up_its_exit(tmp_path):
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join(sys.path),
        HOME=str(tmp_path),  # where 'init_sentry' writes the telemetry id
        PC_TELEMETRY_SENTRY_DSN="http://key@127.0.0.1:9/1",  # a port nothing answers on
    )
    try:
        # Seconds, normally; the bound only has to tell that from never.
        result = subprocess.run(
            [sys.executable, "-c", _LOGS_AS_IT_FINALIZES], capture_output=True, text=True, env=env, timeout=120
        )
    except subprocess.TimeoutExpired as hung:
        stderr = (hung.stderr or b"").decode(errors="replace")  # bytes, whatever 'text' says
        pytest.fail("the process was still exiting after %ss: %s" % (hung.timeout, stderr))
    assert result.returncode == 0, result.stderr
    # And the error was logged, so the process did reach the case under test.
    assert "logged as the interpreter finalizes" in result.stderr
