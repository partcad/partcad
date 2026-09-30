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
"""

import os
import pathlib

import pytest


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
