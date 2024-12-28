from click.testing import CliRunner
from partcad_cli.click.command import cli
from partcad_cli import __version__
import logging
from typing import Iterator


def test_version(click_runner: Iterator[CliRunner]):
    result = click_runner.invoke(cli, ["version"])
    logging.debug("result.stdout: %s", result.stdout)
    # logging.debug("result.stderr: %s", result.stderr)
    assert result.exit_code == 0
    haystack = [
        "PartCAD Python Module version: %s" % __version__,
        "PartCAD CLI version: %s" % __version__,
    ]
    for needle in haystack:
        assert needle in result.output
