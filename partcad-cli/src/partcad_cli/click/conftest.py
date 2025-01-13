import pytest
from click.testing import CliRunner, Result
from typing import Iterator
from partcad.logging import reset_errors


@pytest.fixture(autouse=True)
def setup_function() -> None:
    """
    Automatically resets error states before each test.
    This fixture ensures a clean slate for testing.
    """
    reset_errors()


@pytest.fixture
def click_runner(capsys: pytest.CaptureFixture[str]) -> Iterator[CliRunner]:
    """
    Returns a custom Click CLI runner that handles output capturing correctly.

    This fixture addresses the Click issue #824 where output capturing interferes
    with pytest's capsys. It yields a MyCliRunner instance that temporarily
    disables capsys during command invocation.
    """

    class MyCliRunner(CliRunner):
        """Override CliRunner to disable capsys"""

        def invoke(self, *args, **kwargs) -> Result:
            # Way to fix https://github.com/pallets/click/issues/824
            with capsys.disabled():
                return super().invoke(*args, **kwargs)

    yield MyCliRunner()
