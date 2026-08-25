#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import copy
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


@pytest.fixture(autouse=True)
def restore_parameter_config():
    """
    Restores the user configuration parameter overrides after each test.

    'pc.user_config' is a process-wide singleton, so a test that overrides an
    object's parameters would otherwise leak them into every test that happens
    to run afterwards, making the outcome depend on the test order.
    """
    saved = copy.deepcopy(pc.user_config.parameter_config.to_dict())
    yield
    parameter_config = pc.user_config.parameter_config
    for key in list(parameter_config):
        del parameter_config[key]
    for key, value in saved.items():
        parameter_config[key] = value


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Record the run's verdict for the pre-commit gate.

    pytest has been observed to exit 0 despite failures on some platforms
    (Windows in particular), so the pre-commit hook cannot rely on the process
    exit code alone. When it wants a reliable verdict it passes a marker path
    via PYTEST_RESULT_MARKER; this writes "success" only when the exit status is
    clean AND pytest counted no failed tests, so a run that exits 0 with a
    failure (via session.testsfailed) is still recorded as "failure". The hook
    (.devcontainer/pytest_hook.sh) chooses a PID-unique path so concurrent runs
    never collide, and it is the hook that reads this file and removes it.
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
