#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc ide install`: what it hands `partcad_client.ide`, and how it reports back."""

import json

import pytest

from partcad_cli.click.command import cli
from partcad_client import ide


@pytest.fixture
def installed(monkeypatch):
    calls = []

    def install_extension(**kwargs):
        kwargs.pop("log")
        calls.append(kwargs)
        return {"ok": True, "editor": "/usr/bin/codium", "extension": ide.EXTENSION_ID, "vsix": "partcad-1.vsix"}

    monkeypatch.setattr(ide, "install_extension", install_extension)
    return calls


def test_install_takes_the_latest_release_by_default(click_runner, installed):
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "install"])
    assert result.exit_code == 0, result.output
    assert installed == [{"editor": None, "version": None, "vsix": None, "editor_args": ()}]
    assert "Installed PartCAD.partcad-official into /usr/bin/codium." in result.stdout


def test_install_passes_what_follows_the_double_dash_to_the_editor(click_runner, installed):
    result = click_runner.invoke(
        cli,
        ["--no-ansi", "ide", "install", "--with", "codium", "--version", "0.8.159", "--", "--extensions-dir", "/x"],
    )
    assert result.exit_code == 0, result.output
    assert installed == [
        {"editor": "codium", "version": "0.8.159", "vsix": None, "editor_args": ("--extensions-dir", "/x")}
    ]


def test_a_package_and_a_release_are_two_answers(click_runner, installed, tmp_path):
    package = tmp_path / "p.vsix"
    package.write_bytes(b"PK")
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "install", "--vsix", str(package), "--version", "1"])
    assert result.exit_code != 0
    assert installed == []


def test_a_failure_is_reported_as_json_when_asked(click_runner, monkeypatch):
    def fail(**kwargs):
        raise ide.IdeError("No editor found")

    monkeypatch.setattr(ide, "install_extension", fail)
    result = click_runner.invoke(cli, ["--no-ansi", "ide", "install", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {"ok": False, "error": "No editor found"}
