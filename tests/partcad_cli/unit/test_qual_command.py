#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc qual test` and `pc qual add`: what each asks the daemon."""

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli
from partcad_cli.click.commands.qual import add, test


def _calls(monkeypatch, module):
    calls = []

    def run(cli_ctx, method, params, needs_context=False):
        calls.append((method, params))
        return None

    monkeypatch.setattr(module, "run", run)
    return calls


@pytest.mark.parametrize(
    "flags, subtypes",
    [
        ([], []),
        (["--basic"], ["basic"]),
        (["--topology", "--other"], ["topology", "other"]),
        (["--simulation"], ["sim"]),
        (["--sim", "--basic"], ["basic", "sim"]),
    ],
)
def test_qual_test_asks_for_the_subtypes_named(monkeypatch, flags, subtypes):
    calls = _calls(monkeypatch, test)
    result = CliRunner().invoke(cli, ["--no-ansi", "qual", "test", *flags, ":bracket"])
    assert result.exit_code == 0, result.output
    ((method, params),) = calls
    assert method == "qual.run"
    assert params["subtypes"] == subtypes
    assert params["object"] == ":bracket"


def test_qual_add_declares_a_plugins_test_with_its_parameters(monkeypatch):
    calls = _calls(monkeypatch, add)
    result = CliRunner().invoke(
        cli,
        [
            "--no-ansi",
            "qual",
            "add",
            "--other",
            "--path",
            "//pub/qual/lockwire:lockwire",
            "--set",
            "lockfile=rover.lockwire.yaml",
            "--set",
            "strict=true",
            "-a",
            "rover",
            "budgets",
        ],
    )
    assert result.exit_code == 0, result.output
    ((method, params),) = calls
    assert method == "qual.add"
    assert (params["subtype"], params["name"], params["path"], params["object"], params["assembly"]) == (
        "other",
        "budgets",
        "//pub/qual/lockwire:lockwire",
        "rover",
        True,
    )
    # A value is read as YAML: 'true' is a boolean.
    assert params["entry"] == {"lockfile": "rover.lockwire.yaml", "strict": True}


def test_qual_add_of_a_built_in_checks_parameters_names_no_plugin(monkeypatch):
    calls = _calls(monkeypatch, add)
    result = CliRunner().invoke(
        cli, ["--no-ansi", "qual", "add", "--topology", "--set", "minArea=1.0", "bracket", "tolerance-surfaces"]
    )
    assert result.exit_code == 0, result.output
    ((_, params),) = calls
    assert (params["subtype"], params["path"], params["entry"]) == ("topology", None, {"minArea": 1.0})


def test_a_setting_that_is_not_key_value_is_refused(monkeypatch):
    calls = _calls(monkeypatch, add)
    result = CliRunner().invoke(cli, ["--no-ansi", "qual", "add", "--set", "nonsense", "bracket", "x"])
    assert result.exit_code != 0
    assert calls == []
