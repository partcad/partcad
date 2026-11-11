#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The one thing every pytest run in this repository can be asked to record: its own verdict.

pytest's process exit code is not the session's verdict. It has been observed to
disagree in both directions on Windows -- exiting 0 with a test having failed,
which is what #444 was written for, and exiting non-zero after a session in
which every test passed, which is what the `Pytest (windows-*, 3.12)` cells do
today: `2639 passed, 38 skipped` and then `Process completed with exit code 127`,
with nothing printed in between. So neither a caller that must not miss a
failure nor one that must not invent one can build on the exit code alone.

A caller that wants the truth passes a path in `PYTEST_RESULT_MARKER`; the hook
below writes `success` into it only when pytest's own exit status is clean *and*
pytest counted no failed tests, and `failure` otherwise. Two callers do:

* `.devcontainer/pytest_hook.sh`, the pre-commit gate, which is where the
  mechanism started (#444).
* the `Pytest` job in `.github/workflows/test.yml`.

Both choose a path carrying their shell's PID, so concurrent runs never collide,
and both remove it before and after the run; neither leaves anything behind. A
run that never reaches this hook -- a crash mid-suite, a runner that goes away,
an exception in another session hook -- writes no marker at all, and a caller
that finds none must fail. (A collection error does reach it: pytest reports
that as exit status 2, so it is recorded as `failure` like any other unclean
session.) That is the property that keeps this from being a way to paint a
broken run green: it can only ever forgive an exit code that contradicts a
session pytest itself called clean.

This lives at the repository root rather than beside one package's tests so that
the verdict is recorded for whatever paths a caller passes. It used to live in
`tests/partcad/conftest.py`, which recorded nothing for a run that did not
collect that directory -- and `pyproject.toml` already carries the scar of a job
that ran nothing and reported success.

The other hooks here make a test that never returns say where it was stuck, for
the same callers: see `timeout` and `faulthandler_timeout` in `pyproject.toml`.
"""

import os
import pathlib
import sys
import threading
import traceback

import pytest

#: How much of a timed-out test's captured log and output goes with its stacks:
#: the end of each, which is what it was doing when it stopped.
TIMEOUT_REPORT_TAIL = 20000


def _stderr_for_dumps(config):
    """Where pytest's faulthandler plugin writes its dumps, or None.

    A copy of stderr made before any capturing, which pytest keeps under this
    key and nowhere public. Under pytest-xdist it is the stderr a worker
    inherited from the controller, so what is written to it reaches the job's
    log; the worker's stdout does not (execnet points it at the null device).
    """
    try:
        from _pytest.faulthandler import fault_handler_stderr_fd_key

        return config.stash[fault_handler_stderr_fd_key]
    except (ImportError, KeyError):
        return None


@pytest.hookimpl(trylast=True)
def pytest_exception_interact(node, call, report):
    """Watch the teardown of a test that failed, as every other phase is watched.

    pytest's faulthandler plugin and pytest-timeout both cancel their timers
    here - so that a debugger is not interrupted - and neither sets one again,
    which left the fixtures of every failed test free to hang until the job's
    own `timeout-minutes`, naming nothing. This runs after them (and after a
    debugger, which runs here too), and sets faulthandler's again for what is
    left of the test: the C watchdog that dumps every stack and, with
    `faulthandler_exit_on_timeout`, ends the process (see `pyproject.toml`).
    """
    timeout = float(node.config.getini("faulthandler_timeout") or 0.0)
    if timeout <= 0 or not isinstance(node, pytest.Item):
        return
    stderr = _stderr_for_dumps(node.config)
    if stderr is None:
        return
    import faulthandler

    faulthandler.dump_traceback_later(
        timeout, file=stderr, exit=bool(node.config.getini("faulthandler_exit_on_timeout"))
    )


@pytest.hookimpl(optionalhook=True, tryfirst=True)
def pytest_timeout_set_timer(item, settings):
    """pytest-timeout's thread method, with its report written where it is read.

    The thread method is what pytest-timeout uses wherever there is no SIGALRM,
    which is Windows. When it fires it writes the test's stacks with pytest's
    terminal writer, to stdout, and ends the process -- and under pytest-xdist
    a worker's stdout is the null device. So a hung test on Windows was ended
    on time and reported as nothing but "worker 'gw1' crashed while running
    ...": `Pytest (windows-2022, 3.14)` lost three tests that way at once, on
    #948, with not a line to say what any of them was waiting for.

    This is the same timer, cancelled the same way (pytest-timeout's own
    `pytest_timeout_cancel_timer` calls `item.cancel_timeout`), writing the
    same report -- the test, what it had logged and printed, and every
    thread's stack -- to the stream faulthandler's dumps go to. The signal
    method fails the test with the stacks in its own report, and is left to
    pytest-timeout, as is everything when that stream is not there.
    """
    stderr = _stderr_for_dumps(item.config)
    if settings.method != "thread" or stderr is None:
        return None
    timer = threading.Timer(settings.timeout, _timed_out, (item, settings, stderr))
    timer.name = "timeout %s" % item.nodeid
    # Unlike pytest-timeout's own, a daemon: a timer nobody cancelled must not
    # keep a finished process alive until it fires and turns it into a failure.
    timer.daemon = True

    def cancel():
        timer.cancel()
        timer.join()

    item.cancel_timeout = cancel
    timer.start()
    return True


def _timed_out(item, settings, stderr):
    """Report a test that ran past its timeout, then end the process, as the thread method does."""
    import pytest_timeout

    if not settings.disable_debugger_detection and pytest_timeout.is_debugging():
        return
    try:
        with os.fdopen(os.dup(stderr), "w", encoding="utf-8", errors="backslashreplace") as out:
            try:
                _write_timeout_report(out, item, settings.timeout)
            except Exception:
                traceback.print_exc(file=out)
    finally:
        os._exit(1)


def _write_timeout_report(out, item, timeout):
    """The test, the end of what it logged and printed, and the stack of every other thread."""
    out.write("\n%s Timeout %s\n%s ran for more than %gs\n" % ("+" * 30, "+" * 30, item.nodeid, timeout))
    sections = []
    # What the test logged in the phase it is stuck in, which pytest resets
    # at the start of each one.
    handler = getattr(item.config.pluginmanager.get_plugin("logging-plugin"), "report_handler", None)
    if handler is not None:
        sections.append(("Captured log", handler.stream.getvalue()))
    capture = item.config.pluginmanager.get_plugin("capturemanager")
    try:
        captured = capture.read_global_capture()
        sections += [("Captured stdout", captured.out), ("Captured stderr", captured.err)]
    except Exception:  # `-s`, or nothing being captured: nothing to show
        pass
    for title, text in sections:
        if text:
            cut = " (the end of it)" if len(text) > TIMEOUT_REPORT_TAIL else ""
            out.write("%s %s%s %s\n%s\n" % ("~" * 10, title, cut, "~" * 10, text[-TIMEOUT_REPORT_TAIL:]))
    current = threading.get_ident()
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    for ident, frame in sys._current_frames().items():
        if ident != current:
            name = names.get(ident, "<unknown>")
            out.write("%s Stack of %s (%s) %s\n" % ("~" * 10, name, ident, "~" * 10))
            out.write("".join(traceback.format_stack(frame)))
    out.write("%s\n" % ("+" * 69))


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    """Write the session's verdict to `PYTEST_RESULT_MARKER`, if a caller asked for one.

    A wrapper, and `tryfirst` so that it is the outermost one, because the
    `exitstatus` handed to this hook is not always the status pytest goes on to
    exit with. pytest's own terminal reporter implements `pytest_sessionfinish`
    as a wrapper too, and after the inner hooks have run it can still raise
    `session.exitstatus` -- `--max-warnings` being exceeded turns a `0` into
    `ExitCode.MAX_WARNINGS_ERROR` there. A plain `trylast` hook reading the
    argument would record "success" for a session pytest then failed, which is
    the one direction this must never get wrong. Running last of all, after the
    yield, and reading `session.exitstatus` rather than the argument, is what
    makes the verdict the final one.
    """
    result = yield

    marker = os.environ.get("PYTEST_RESULT_MARKER")
    if not marker:
        return result

    # Under xdist only the controller sees the aggregate result; the workers
    # each report their own subset and must not write the verdict.
    if hasattr(session.config, "workerinput"):
        return result

    path = pathlib.Path(marker)
    if not path.is_absolute():
        # Anchor a relative path to the directory pytest was started in rather
        # than to the current one, so that a test which changed directory
        # cannot decide where the verdict lands. A relative path is what lets
        # the caller and the session name the same file on Windows, where a
        # POSIX path means one thing to Git Bash and another to the native
        # interpreter this hook runs in.
        path = pathlib.Path(session.config.invocation_params.dir) / path

    # An exit status of 5 (no tests collected) is a failure here, deliberately:
    # a run that tested nothing is not a run that passed.
    passed = session.exitstatus == 0 and session.testsfailed == 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("success" if passed else "failure")
    return result
