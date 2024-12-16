import pytest
from click.testing import CliRunner, Result
from typing import Iterator


@pytest.fixture
def click_runner(capsys: pytest.CaptureFixture[str]) -> Iterator[CliRunner]:
    """
    Convenience fixture to return a click.CliRunner for cli testing
    """

    class MyCliRunner(CliRunner):
        """Override CliRunner to disable capsys"""

        def invoke(self, *args, **kwargs) -> Result:
            # Way to fix https://github.com/pallets/click/issues/824
            with capsys.disabled():
                result = super().invoke(*args, **kwargs)
            return result

    yield MyCliRunner()
