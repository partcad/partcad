#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import pytest

import partcad as pc


@pytest.fixture(autouse=True)
def setup_function() -> None:
    """
    Automatically resets error states before each test.
    This fixture ensures a clean slate for testing.
    """
    pc.logging.reset_errors()


@pytest.hookimpl()
def pytest_sessionfinish(session: pytest.Session, exitstatus: int):
    if session.testsfailed == 0:
        with open(".pytest_success", "w") as f:
            f.write("success")
