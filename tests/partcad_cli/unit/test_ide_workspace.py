#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc ide workspace`: what it hands `partcad_client.ide`, and how it reports back."""

import json

import pytest

from partcad_cli.click.command import cli
from partcad_client import ide


@pytest.fixture
def opened(monkeypatch):
    calls = []

    def open_workspace(path, editor=None, editor_args=(), log=None):
        calls.append({"path": path, "editor": editor, "editor_args": editor_args})
        return {"ok": True, "editor": "/usr/bin/codium", "path": path, "workbench": True}

    monkeypatch.setattr(ide, "open_workspace", open_workspace)
    return calls


def test_a_directory_is_opened_with_what_follows_the_double_dash(click_runner, opened, tmp_path):
    result = click_runner.invoke(
        cli, ["--no-ansi", "ide", "workspace", "--with", "codium", str(tmp_path), "--", "--user-data-dir", "/u"]
    )
    assert result.exit_code == 0, result.output
    assert opened == [{"path": str(tmp_path), "editor": "codium", "editor_args": ("--user-data-dir", "/u")}]


def test_the_current_directory_is_the_default(click_runner, opened):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "workspace"])
    assert result.exit_code == 0, result.output
    assert opened[0]["path"] == "."


def test_json_says_where(click_runner, opened, tmp_path):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "workspace", "--json", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["workbench"] is True


def test_a_file_is_not_a_workspace(click_runner, opened, tmp_path):
    part = tmp_path / "cube.step"
    part.write_text("")
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "workspace", str(part)])
    assert result.exit_code != 0
    assert opened == []


def test_a_failure_is_reported_as_json_when_asked(click_runner, monkeypatch, tmp_path):
    def fail(path, editor=None, editor_args=(), log=None):
        raise ide.IdeError("No editor found")

    monkeypatch.setattr(ide, "open_workspace", fail)
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "workspace", "--json", str(tmp_path)])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"] == "No editor found"
