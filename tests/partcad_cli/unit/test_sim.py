#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc sim`'s own options: `--plugin`, and `--before`/`--after`.

What is pinned is the wrapping rather than the simulation: what reaches the
daemon, and the files this process writes from what comes back. Nothing here
starts a simulator -- the daemon call is replaced. `--before` and `--after` are
written here and not by the daemon, because the daemon may be on another machine
and the path the user gave names a file on this one.
"""

import json

import pytest
import yaml
from click.testing import CliRunner

from partcad_cli.click.command import cli
from partcad_cli.click.commands import sim as sim_module

BEFORE = {"time": 0.0, "bodies": {"top": {"pos": [18.0, 0.0, 30.0], "quat": [1.0, 0.0, 0.0, 0.0]}}}
AFTER = {"time": 10.0, "bodies": {"top": {"pos": [29.7, 0.0, 9.8], "quat": [0.7, 0.0, 0.7, 0.0]}}}


def _simulation(name="falls", passed=True, error=None, result=None):
    return {
        "object": "//p:stack",
        "simulation": name,
        "passed": passed,
        "error": error,
        "result": {"before": BEFORE, "after": AFTER} if result is None else result,
    }


@pytest.fixture
def simulated(monkeypatch):
    """Record the request `pc sim` sends, and answer it however a test wants."""

    class Recorder:
        def __init__(self):
            self.calls = []
            self.result = {"simulations": [_simulation()], "total": 1, "failed": 0, "ok": True}

        def run(self, cli_ctx, method, params, needs_context=False):
            self.calls.append({"method": method, "params": params})
            return self.result

    recorder = Recorder()
    monkeypatch.setattr(sim_module, "run", recorder.run)
    return recorder


def _invoke(*args):
    return CliRunner().invoke(cli, ["--no-ansi", "sim", *args])


def test_another_plugin_is_asked_for_by_name(simulated):
    result = _invoke("-a", "stack", "--plugin", "//pub/feature/simulate/gazebo:gazebo")

    assert result.exit_code == 0, result.output
    (call,) = simulated.calls
    assert call["method"] == "simulate.run"
    assert call["params"]["plugin"] == "//pub/feature/simulate/gazebo:gazebo"


def test_without_it_each_simulation_runs_with_its_own(simulated):
    assert _invoke("-a", "stack").exit_code == 0
    assert simulated.calls[0]["params"]["plugin"] is None


def test_the_states_are_written_as_yaml(simulated, tmp_path):
    before, after = tmp_path / "before.yaml", tmp_path / "after.yml"

    result = _invoke("-a", "stack", "--before", str(before), "--after", str(after))

    assert result.exit_code == 0, result.output
    assert yaml.safe_load(before.read_text()) == BEFORE
    assert yaml.safe_load(after.read_text()) == AFTER
    # A vector is one line, not a column.
    assert "pos: [18.0, 0.0, 30.0]" in before.read_text()
    assert str(after) in result.stderr


def test_a_json_path_is_written_as_json_whatever_its_case(simulated, tmp_path):
    path = tmp_path / "after.JSON"

    assert _invoke("-a", "stack", "--after", str(path)).exit_code == 0
    assert json.loads(path.read_text()) == AFTER


def test_json_asks_for_json_whatever_the_path(simulated, tmp_path):
    path = tmp_path / "after.yaml"

    result = _invoke("-a", "stack", "--json", "--after", str(path))

    assert result.exit_code == 0, result.output
    assert json.loads(path.read_text()) == AFTER
    # And stdout is still the result alone, so it can be piped.
    assert json.loads(result.stdout)["simulations"][0]["simulation"] == "falls"


def test_the_state_of_a_run_that_did_not_validate_is_still_saved(simulated, tmp_path):
    """That is the run whose state somebody wants to look at."""
    simulated.result = {"simulations": [_simulation(passed=False)], "total": 1, "failed": 1, "ok": False}
    path = tmp_path / "after.yaml"

    result = _invoke("-a", "stack", "--after", str(path))

    assert result.exit_code == 1
    assert yaml.safe_load(path.read_text()) == AFTER


def test_one_simulation_at_a_time(simulated, tmp_path):
    """A file whose shape depended on how many ran is not one a script can read."""
    simulated.result = {
        "simulations": [_simulation("falls"), _simulation("stands")],
        "total": 2,
        "failed": 0,
        "ok": True,
    }

    result = _invoke("-a", "stack", "--after", str(tmp_path / "after.yaml"))

    assert result.exit_code == 1
    assert "-f" in result.stderr
    assert not (tmp_path / "after.yaml").exists()


def test_a_simulation_that_did_not_run_has_no_state_to_save(simulated, tmp_path):
    simulated.result = {
        "simulations": [_simulation(passed=None, error="No Gazebo found", result={})],
        "total": 1,
        "failed": 1,
        "ok": False,
    }

    result = _invoke("-a", "stack", "--before", str(tmp_path / "before.yaml"))

    assert result.exit_code == 1
    assert "No Gazebo found" in result.stderr
