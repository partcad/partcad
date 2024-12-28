import pytest
from partcad.logging import reset_errors


@pytest.fixture(autouse=True)
def setup_function() -> None:
    reset_errors()
