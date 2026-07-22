#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import os

import pytest

import partcad as pc


@pytest.fixture(autouse=True)
def setup_function() -> None:
    """
    Automatically resets error states before each test.
    This fixture ensures a clean slate for testing.
    """
    pc.logging.reset_errors()


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Record the run's verdict for the pre-commit gate.

    pytest has been observed to exit 0 despite failures on some platforms
    (Windows in particular), so the pre-commit hook cannot trust the process
    exit code. When it wants a reliable verdict it passes a marker path via
    PYTEST_RESULT_MARKER; this writes "success" or "failure" there based on
    pytest's own internal counters rather than the exit code. The hook picks a
    PID-unique path so concurrent runs never collide, and removes the file as
    soon as it has read it.
    """
    marker = os.environ.get("PYTEST_RESULT_MARKER")
    if not marker:
        return
    # Under xdist only the controller sees the aggregate result; workers each
    # report their own subset and must not write the verdict.
    if hasattr(session.config, "workerinput"):
        return
    passed = exitstatus == 0 and session.testsfailed == 0
    with open(marker, "w") as f:
        f.write("success" if passed else "failure")
