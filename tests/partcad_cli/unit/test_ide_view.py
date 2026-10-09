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


@pytest.fixture
def shown(monkeypatch):
    sent = []

    def run(cli_ctx, method, params, **kwargs):
        sent.append((method, params))
        return None

    monkeypatch.setattr(view, "run", run)
    return sent


@pytest.mark.parametrize(
    "flag, tab",
    [
        ("--design-3d", "3d"),
        ("--design-2d", "2d"),
        ("--design-draft", "draft"),
        ("--analysis-fea", "fea"),
        ("--analysis-cfd", "cfd"),
        ("--manufacturing-bvb", "bvb"),
        ("--manufacturing-build", "build"),
        # The tab is labelled "Buy", and so is the flag; on the wire it is 'supply'.
        ("--manufacturing-buy", "supply"),
        ("--manufacturing-bom", "bom"),
        ("--manufacturing-assembly", "assembly"),
    ],
)
def test_a_tab_flag_asks_the_viewer_to_open_on_that_tab(click_runner, shown, flag, tab):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "view", flag, ":cube"])
    assert result.exit_code == 0, result.output
    ((method, params),) = shown
    assert method == "inspect.object"
    assert params["tab"] == tab


def test_every_viewer_tab_has_a_flag():
    from partcad_ide_client.protocol import viewer_tab_ids

    assert sorted(tab for _, tab in view._tab_flags()) == sorted(viewer_tab_ids())


def test_no_tab_flag_sends_no_tab(click_runner, shown):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "view", ":cube"])
    assert result.exit_code == 0, result.output
    assert "tab" not in shown[0][1]


def test_two_tabs_at_once_are_refused(click_runner, shown):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "view", "--design-2d", "--analysis-fea", ":cube"])
    assert result.exit_code != 0
    assert "one tab at a time" in result.output
    assert shown == []


def test_a_tab_with_a_verbal_answer_is_refused(click_runner, shown):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "view", "-V", "--design-2d", ":cube"])
    assert result.exit_code != 0
    assert shown == []


def test_the_old_name_takes_the_tab_flags_too(click_runner, shown):
    result = click_runner.invoke(cli, ["--no-ansi", "inspect", "--analysis-fea", ":cube"])
    assert result.exit_code == 0, result.output
    assert shown[0][1]["tab"] == "fea"
