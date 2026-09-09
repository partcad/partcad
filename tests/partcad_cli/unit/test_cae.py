#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc cae fea` and `pc cae cfd`.

Both commands are `analysis_command()` with a different word, which is the whole
point of them sharing it: a user who has learned one has learned the other. What
is pinned here is the wrapping rather than the analysis -- what reaches the
daemon, and the two things this process does with what comes back.

The exit status is the part worth being careful about. A finding is what the user
asked about, so a run that produced one is a run whose answer is "no", and
`pc cae fea && ...` has to stop there. A run that found nothing is a pass and
exits zero, the same way `pc test` does. Nothing here starts a solver: the daemon
call is replaced, because which request is sent is the contract and what a solver
would do with it is not this command's business.
"""

import json

import pytest
from click.testing import CliRunner
from partcad_cli.click import analysis as analysis_module
from partcad_cli.click.command import cli


@pytest.fixture
def analysed(monkeypatch):
    """Record the request `pc cae` sends, and answer it however a test wants."""

    class Recorder:
        def __init__(self):
            self.calls = []
            self.result = {"findings": [], "filepath": "/w/bracket.fea.glb"}

        def run(self, cli_ctx, method, params, needs_context=False):
            self.calls.append({"method": method, "params": params, "needs_context": needs_context})
            return self.result

    recorder = Recorder()
    monkeypatch.setattr(analysis_module, "run", recorder.run)
    return recorder


def _invoke(*args):
    return CliRunner().invoke(cli, ["--no-ansi", "cae", *args])


def test_fea_asks_the_daemon_for_the_analysis_it_is_named_after(analysed):
    """The one word the two commands differ in is the one that travels."""
    result = _invoke("fea", ":bracket")
    assert result.exit_code == 0, result.output
    (call,) = analysed.calls
    assert call["method"] == "cae.analyze"
    assert call["params"]["analysis"] == "fea"
    assert call["params"]["object"] == ":bracket"
    assert call["needs_context"] is True


def test_cfd_is_the_same_command_with_the_other_word(analysed):
    """Two analyses, one implementation: the difference is the section named."""
    assert _invoke("cfd", ":duct").exit_code == 0
    (call,) = analysed.calls
    assert call["method"] == "cae.analyze"
    assert call["params"]["analysis"] == "cfd"


def test_a_finding_makes_the_command_fail(analysed):
    """`pc cae fea && ...` stops on a finding, as `pc test` stops on a failure."""
    analysed.result = {"findings": [{"message": "too thin", "severity": "error"}]}
    assert _invoke("fea", ":bracket").exit_code == 1


def test_finding_nothing_is_a_pass(analysed):
    """An analysis that said nothing is the answer "fine", and exits zero."""
    analysed.result = {"findings": [], "filepath": "/w/bracket.fea.glb"}
    assert _invoke("fea", ":bracket").exit_code == 0


def test_json_prints_the_findings_as_the_array_they_are(analysed):
    """A machine-readable answer has to reach *this* process's stdout to be piped."""
    analysed.result = {"findings": [{"message": "too thin"}]}
    result = _invoke("fea", "--json", ":bracket")
    # Non-zero all the same: `--json` changes how the answer is printed, not
    # what the answer is.
    assert result.exit_code == 1
    assert json.loads(result.output) == [{"message": "too thin"}]
    assert analysed.calls[0]["params"]["json"] is True


def test_json_of_a_clean_run_is_an_empty_array(analysed):
    """Not "null", and not nothing: something reading this parses JSON."""
    analysed.result = {"findings": []}
    result = _invoke("fea", "--json", ":bracket")
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_a_daemon_that_answered_with_nothing_is_not_a_failure(analysed):
    """No result is no findings, which is not the same as a finding."""
    analysed.result = None
    result = _invoke("fea", "--json", ":bracket")
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_the_implementation_override_travels_verbatim(analysed):
    """`--implementation` is this run's solver, and the daemon is told which."""
    assert _invoke("fea", "-i", "//pub/feature/cae/calculix:fea", ":bracket").exit_code == 0
    assert analysed.calls[0]["params"]["implementation"] == "//pub/feature/cae/calculix:fea"


def test_the_output_directory_is_made_absolute(analysed, tmp_path, monkeypatch):
    """The model belongs in the user's working directory, not the daemon's.

    A daemon can be somewhere else entirely -- another directory, another
    machine -- so a relative path resolved on its side lands somewhere the user
    never asked for.
    """
    (tmp_path / "out").mkdir()
    monkeypatch.chdir(tmp_path)
    assert _invoke("fea", "-O", "out", ":bracket").exit_code == 0
    assert analysed.calls[0]["params"]["output_dir"] == str(tmp_path / "out")


def test_no_output_directory_means_the_configuration_decides(analysed):
    """Left out, the file goes where the `cae:` section puts it."""
    assert _invoke("fea", ":bracket").exit_code == 0
    assert analysed.calls[0]["params"]["output_dir"] is None
