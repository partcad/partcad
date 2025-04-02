from click.testing import CliRunner
import logging
from collections.abc import Iterator

from partcad_cli.click.command import cli
from partcad_cli import __version__


def test_version(click_runner: Iterator[CliRunner]) -> None:
    result = click_runner.invoke(cli, ["version"])
    logging.debug("result.stdout: %s", result.stdout)
    assert result.exit_code == 0
    haystack = [
        f"PartCAD Python Module version: {__version__}",
        f"PartCAD CLI version: {__version__}",
    ]
    for needle in haystack:
        assert needle in result.output
