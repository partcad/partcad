#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc ide state`: the command's half. What the IDE answers is the extension's to test."""

import json

import pytest
import yaml

from partcad_cli.click.command import cli
from partcad_cli.click.commands.ide import state as state_command
from partcad_ide_client import StateNotSupported, ViewerNotAvailable

SHOWN = {
    "explorer": {"selection": [{"kind": "part", "path": "//pub/examples:cube", "package": "//pub/examples"}]},
    "inspector": {"kind": "part", "parameters": {"size": {"type": "float", "value": "10.0"}}},
    "viewer": {"open": True, "tab": "design", "subTab": "2d", "screenshot": "/tmp/partcad-viewer-2d.png"},
}


@pytest.fixture
def answered(monkeypatch):
    asked = []

    def state(reply_timeout):
        asked.append(reply_timeout)
        return SHOWN

    monkeypatch.setattr(state_command, "state", state)
    return asked


def test_json(click_runner, answered):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "state", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == SHOWN


def test_yaml_is_the_default_and_the_same_document(click_runner, answered):
    for args in ([], ["--yaml"]):
        result = click_runner.invoke(cli, ["--no-ansi", "ide", "state", *args])
        assert result.exit_code == 0, result.output
        assert yaml.safe_load(result.stdout) == SHOWN


def test_one_format_at_a_time(click_runner, answered):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "state", "--json", "--yaml"])
    assert result.exit_code != 0
    assert not answered


def test_the_timeout_reaches_the_question(click_runner, answered):
    click_runner.invoke(cli, ["--no-ansi", "ide", "state", "--json", "--timeout", "3"])
    assert answered == [3.0]


@pytest.mark.parametrize(
    "error, said",
    [
        (ViewerNotAvailable("refused"), "No PartCAD IDE is running on this machine"),
        (StateNotSupported("update the PartCAD extension"), "update the PartCAD extension"),
        (TimeoutError("timed out"), "did not answer"),
    ],
)
def test_what_went_wrong_is_said(click_runner, monkeypatch, error, said):
    def state(reply_timeout):
        raise error

    monkeypatch.setattr(state_command, "state", state)
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "state", "--json"])
    assert result.exit_code != 0
    assert said in result.output
