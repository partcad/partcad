import pytest
from partcad.logging import reset_errors


@pytest.fixture(autouse=True)
def setup_function() -> None:
    reset_errors()

@pytest.hookimpl()
def pytest_sessionfinish(session: pytest.Session, exitstatus: int):
    if session.testsfailed == 0:
        with open(".pytest_success", "w") as f:
            f.write("success")
