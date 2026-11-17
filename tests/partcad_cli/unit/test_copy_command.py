#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc copy': what reaches the daemon, and what a dry run prints.

What the daemon writes is pinned beside 'partcad.serialize' and in
'tests/partcad_service_json_rpc/test_operations_tab.py'; what is pinned here is
the command: a daemon client that sends both names as they were typed, and on
'--dry-run' prints the declaration the daemon answers with.
"""

import importlib

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli


class _Recorder:
    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer

    def run(self, cli_ctx, method, params, needs_context=False, **kwargs):
        self.calls.append((method, params, needs_context))
        return self.answer


@pytest.fixture
def recorder(monkeypatch):
    recorder = _Recorder({"declaration": "big:\n  type: basic\n  cuboid: 20\n"})
    monkeypatch.setattr(importlib.import_module("partcad_cli.click.commands.copy"), "run", recorder.run)
    return recorder


def test_both_names_reach_the_daemon_as_typed(recorder):
    result = CliRunner().invoke(cli, ["--no-ansi", "copy", "-P", "//pkg", "//pkg@v1.2:cube", "big"])

    assert result.exit_code == 0, result.output
    ((method, params, needs_context),) = recorder.calls
    assert method == "copy.object"
    assert needs_context
    assert params == {"package": "//pkg", "object": "//pkg@v1.2:cube", "target": "big", "dry_run": False}


def test_a_dry_run_prints_the_declaration_it_would_write(recorder):
    result = CliRunner().invoke(cli, ["--no-ansi", "copy", "--dry-run", ":cube", "big"])

    assert result.exit_code == 0, result.output
    assert recorder.calls[0][1]["dry_run"] is True
    assert "big:\n  type: basic\n  cuboid: 20\n" in result.output


def test_both_names_are_needed():
    result = CliRunner().invoke(cli, ["--no-ansi", "copy", ":cube"])

    assert result.exit_code != 0
