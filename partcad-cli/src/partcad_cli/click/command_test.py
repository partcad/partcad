from click.testing import CliRunner
from partcad_cli.click.command import cli
from partcad_cli import __version__


def test_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    haystack = [
        "PartCAD version: %s" % __version__,
        "PartCAD CLI version: %s" % __version__,
    ]
    for needle in haystack:
        assert needle in result.output
