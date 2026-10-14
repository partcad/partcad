#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc sim' names a scene the way every other command does: with '-S'.

A stack of blocks is an arrangement rather than a product, so it is a scene, and
it declares 'simulate:' like a part does (docs/design/simulation.md, section 7).
What is pinned here is what reaches the daemon; what the daemon does with it is
tested beside 'operations._simulate_async'.
"""

from click.testing import CliRunner

from partcad_cli.click.command import cli
from partcad_cli.click.commands import sim


def _calls(monkeypatch):
    calls = []

    def run(cli_ctx, method, params, needs_context=False):
        calls.append((method, params))
        return {"ok": True, "total": 1, "failed": 0, "simulations": []}

    monkeypatch.setattr(sim, "run", run)
    return calls


def test_a_scene_is_named_with_s(monkeypatch):
    calls = _calls(monkeypatch)
    result = CliRunner().invoke(cli, ["--no-ansi", "sim", "-S", "stable"])
    assert result.exit_code == 0, result.output
    ((method, params),) = calls
    assert method == "simulate.run"
    assert (params["object"], params["scene"], params["assembly"]) == ("stable", True, False)


def test_an_object_is_an_assembly_or_a_scene_not_both(monkeypatch):
    calls = _calls(monkeypatch)
    result = CliRunner().invoke(cli, ["--no-ansi", "sim", "-a", "-S", "stable"])
    assert result.exit_code == 2
    assert "not both" in result.output
    assert calls == []
