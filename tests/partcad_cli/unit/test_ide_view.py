#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc ide view`, the command that was `pc inspect`.

What it sends is `inspect.object`, and the daemon's handling of that is tested in
`tests/partcad_service_json_rpc`; what is pinned here is the command's own half:
that the summary it is handed back is printed, and that `-q` silences it -- which
it never did while the command read a parameter named "q" that does not exist.
"""

import pytest

from partcad_cli.click.command import cli
from partcad_cli.click.commands.ide import view


@pytest.fixture
def summarized(monkeypatch):
    sent = []

    def run(cli_ctx, method, params, **kwargs):
        sent.append((method, params))
        return {"summary": "a cube, 10 mm on a side"}

    monkeypatch.setattr(view, "run", run)
    return sent


def test_the_summary_is_printed(click_runner, summarized):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "view", "-V", ":cube"])
    assert result.exit_code == 0, result.output
    assert "a cube, 10 mm on a side" in result.stdout
    assert summarized[0][0] == "inspect.object"


def test_quiet_silences_the_summary(click_runner, summarized):
    result = click_runner.invoke(cli, ["--no-ansi", "-q", "ide", "view", "-V", ":cube"])
    assert result.exit_code == 0, result.output
    assert "a cube" not in result.stdout


def test_the_old_name_sends_the_same_request(click_runner, summarized):
    result = click_runner.invoke(cli, ["--no-ansi", "inspect", "-V", ":cube"])
    assert result.exit_code == 0, result.output
    assert "a cube, 10 mm on a side" in result.stdout
    assert "'pc inspect' is deprecated: use 'pc ide view'." in result.stderr
