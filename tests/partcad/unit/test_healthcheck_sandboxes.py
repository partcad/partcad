#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The three checks that report what PartCAD can build a sandbox in.

Two of them -- conda and a container runtime -- report and let the command
succeed, because either one alone is a working machine. The third fails the
command, and only when both of the others have found nothing. What is pinned
here is that escalation, and that all three ask the questions the sandboxes
themselves ask rather than a cheaper spelling of them.
"""

import types

import pytest

import partcad as pc
from partcad import runtime
from partcad.healthcheck import conda_installed, docker_available, sandbox_available
from partcad.healthcheck import tests as healthcheck_tests
from partcad.runtime_python_conda import CondaPythonRuntime


@pytest.fixture(autouse=True)
def _errors_reset():
    """`had_errors` is global and is what "this check fails the run" means."""
    pc.logging.reset_errors()
    yield
    pc.logging.reset_errors()


@pytest.fixture(autouse=True)
def _nobody_declared_a_sandbox(monkeypatch):
    """Nothing said which sandbox to use, unless a test says otherwise.

    The default has to be pinned rather than inherited: the developer running
    this suite may well have 'pythonSandbox: conda' in their own
    '~/.partcad/config.yaml', and every assertion below about the undeclared
    machine would then be testing the declared branch instead -- passing or
    failing according to whose laptop it ran on.
    """
    monkeypatch.setattr(pc.user_config, "_python_sandbox_declared", False, raising=False)


@pytest.fixture
def no_conda(monkeypatch):
    monkeypatch.setattr(CondaPythonRuntime, "find_conda_executable", staticmethod(lambda: None))


@pytest.fixture
def some_conda(monkeypatch):
    monkeypatch.setattr(CondaPythonRuntime, "find_conda_executable", staticmethod(lambda: "/opt/conda/bin/mamba"))


@pytest.fixture
def no_docker(monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: False)
    monkeypatch.setattr(pc.user_config, "use_docker", True)


@pytest.fixture
def some_docker(monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(pc.user_config, "use_docker", True)


# --------------------------------------------------------------------------- #
# "Can PartCAD use Docker here" is one question with two halves                #
# --------------------------------------------------------------------------- #


def test_docker_is_enabled_when_allowed_and_answering(monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    assert runtime.docker_enabled(types.SimpleNamespace(use_docker=True)) is True


def test_docker_is_not_enabled_when_nothing_answers(monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: False)
    assert runtime.docker_enabled(types.SimpleNamespace(use_docker=True)) is False


def test_docker_is_not_enabled_when_it_was_turned_off(monkeypatch):
    """And the daemon is not asked at all.

    A machine that said 'useDocker: false' must not pay the SDK's API timeout
    to be told what it already decided -- which is the whole reason the
    permission is checked before the ping.
    """

    def _must_not_be_asked():
        raise AssertionError("the daemon was pinged although containers are turned off")

    monkeypatch.setattr(runtime, "docker_available", _must_not_be_asked)
    assert runtime.docker_enabled(types.SimpleNamespace(use_docker=False)) is False


# --------------------------------------------------------------------------- #
# DockerAvailable: reports, never fails                                        #
# --------------------------------------------------------------------------- #


def test_a_missing_container_runtime_is_a_warning(no_docker):
    check = docker_available.DockerAvailableCheck()
    assert check.severity == healthcheck_tests.SEVERITY_WARNING
    report = check.test()
    assert report.findings
    # The two things a reader can do about it, both named.
    assert any("Install Docker" in finding for finding in report.findings)
    assert any("useDocker" in finding for finding in report.findings)


def test_a_container_runtime_that_answers_is_a_clean_pass(some_docker):
    assert docker_available.DockerAvailableCheck().test().findings == []


def test_turning_containers_off_is_not_a_finding(monkeypatch):
    """A deliberate setting reported back on every run is noise, not a finding."""
    monkeypatch.setattr(pc.user_config, "use_docker", False)
    monkeypatch.setattr(runtime, "docker_available", lambda: False)
    assert docker_available.DockerAvailableCheck().test().findings == []


# --------------------------------------------------------------------------- #
# CondaAvailable: reports, never fails                                         #
# --------------------------------------------------------------------------- #


def test_a_missing_conda_is_a_warning(no_conda):
    check = conda_installed.CondaAvailableCheck()
    assert check.severity == healthcheck_tests.SEVERITY_WARNING
    assert check.test().findings


def test_a_conda_that_is_found_is_a_clean_pass(some_conda):
    assert conda_installed.CondaAvailableCheck().test().findings == []


# --------------------------------------------------------------------------- #
# SandboxAvailable: the one that fails, and only when nothing is left          #
# --------------------------------------------------------------------------- #


def test_neither_conda_nor_docker_is_an_error(no_conda, no_docker):
    check = sandbox_available.SandboxAvailableCheck()
    assert check.severity == healthcheck_tests.SEVERITY_ERROR
    report = check.test()
    assert report.findings
    assert any("Neither conda nor a container runtime" in finding for finding in report.findings)


def test_conda_alone_is_enough(some_conda, no_docker):
    assert sandbox_available.SandboxAvailableCheck().test().findings == []


def test_docker_alone_is_enough(no_conda, some_docker):
    assert sandbox_available.SandboxAvailableCheck().test().findings == []


def test_docker_turned_off_is_not_a_sandbox(no_conda, monkeypatch):
    """An answering daemon PartCAD may not use is a daemon it cannot render in."""
    monkeypatch.setattr(pc.user_config, "use_docker", False)
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    assert sandbox_available.SandboxAvailableCheck().test().findings


# --------------------------------------------------------------------------- #
# ...unless somebody said which sandbox to use, which is then the question     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def declared(monkeypatch):
    """Say 'pythonSandbox' was asked for, the way the configuration reports it."""

    def _declare(sandbox):
        monkeypatch.setattr(pc.user_config, "_python_sandbox", sandbox, raising=False)
        monkeypatch.setattr(pc.user_config, "_python_sandbox_declared", True, raising=False)

    return _declare


def test_a_declared_venv_needs_neither_conda_nor_docker(declared, no_conda, no_docker):
    """The CI job that means to build a virtual environment and says so.

    This is the regression the whole branch above exists for: asking such a
    machine for a conda it deliberately did without turns 'pc healthcheck'
    into something to switch off rather than something to read.
    """
    declared("venv")
    assert sandbox_available.SandboxAvailableCheck().test().findings == []


def test_a_declared_conda_that_is_there_passes(declared, some_conda, no_docker):
    declared("conda")
    assert sandbox_available.SandboxAvailableCheck().test().findings == []


def test_a_declared_conda_that_is_missing_fails(declared, no_conda, some_docker):
    """Being unable to do what was asked is not a reason to quietly do something else.

    Note the container runtime: it would have carried an *undeclared* machine,
    and does not excuse a 'conda' nobody can find.
    """
    declared("conda")
    findings = sandbox_available.SandboxAvailableCheck().test().findings
    assert findings and "set to 'conda'" in findings[0]


def test_a_declared_docker_that_is_missing_fails(declared, some_conda, no_docker):
    declared("docker")
    findings = sandbox_available.SandboxAvailableCheck().test().findings
    assert findings and "set to 'docker'" in findings[0]


def test_a_declared_remote_asks_nothing_of_this_machine(declared, no_conda, no_docker):
    """What it needs is a reachable service, which this check cannot ping."""
    declared("remote")
    assert sandbox_available.SandboxAvailableCheck().test().findings == []


def test_a_sandbox_that_does_not_exist_is_reported_here(declared, some_conda, some_docker):
    """Rather than by 'runtime_python_all.create' at the first part rendered."""
    declared("venvv")
    findings = sandbox_available.SandboxAvailableCheck().test().findings
    assert findings and "not a sandbox PartCAD has" in findings[0]


# --------------------------------------------------------------------------- #
# What the severity actually costs                                             #
# --------------------------------------------------------------------------- #


def test_an_error_severity_finding_fails_the_command(no_conda, no_docker):
    """`had_errors` is what the CLI turns into a non-zero exit code."""
    healthcheck_tests.run_healthchecks(filters="sandbox")
    assert pc.logging.had_errors is True


def test_findings_are_read_as_a_sentence_and_not_as_a_repr(caplog):
    """What a check wrote, not what Python prints a list of strings as.

    An error-severity finding is quoted again on the CLI's way out, so the
    brackets and quotes around it were the last thing a failing run said.
    """
    report = healthcheck_tests.HealthCheckReport("Example", [])
    with caplog.at_level("WARNING", logger="partcad"):
        report.finding(["Nothing is installed.", "Install something."])
    printed = caplog.text
    assert "Nothing is installed. Install something." in printed
    assert "['Nothing is installed." not in printed


def test_a_warning_severity_finding_does_not(no_conda, some_docker):
    """A machine with Docker and no conda is a working machine.

    This is the regression the severities exist for: reported at error level,
    `pc healthcheck` would exit non-zero on every machine that renders its
    parts in a container, which is the default wherever a daemon answers.
    """
    healthcheck_tests.run_healthchecks(filters="conda")
    assert pc.logging.had_errors is False
