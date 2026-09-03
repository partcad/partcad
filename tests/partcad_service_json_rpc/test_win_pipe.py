#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How the Windows named-pipe daemon is started.

Windows has no `fork`, so the daemon is a *new process* rather than a copy of
this one -- which means the argv that starts it has to be right, and nothing
noticed when it was not. It was not: the frozen bundle is a single executable
that takes the service's own options, and it was being run as
`sys.executable -m partcad_service_json_rpc`, which it rejects. That bundle is
what the editor extension downloads and runs, so on Windows the daemon it asked
for was never there.

CI does run Windows, so these run there as well as on POSIX -- but a spawn that
only Windows can check is a spawn nothing checks on a pull request that fails
earlier, so everything here is behind a stand-in ``Popen``.

The spawn itself is Windows-only (detached process creation flags -- 0 on POSIX,
where they are asked for with `getattr`). What is pinned here is everything
about it that is not: the argv, and the redirection that gives a daemon dying
before it serves somewhere to say so.
"""

import subprocess
import sys

import pytest
from partcad_service_json_rpc import win_pipe
from partcad_service_json_rpc.win_pipe import _launcher_argv, spawn_pipe_daemon
from partcad_utils.win_pipe import pipe_name
from partcad_utils.workspace import workspace_hash


def test_a_source_checkout_runs_the_module(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert _launcher_argv() == [sys.executable, "-m", "partcad_service_json_rpc"]


def test_a_frozen_bundle_runs_itself(monkeypatch):
    # `partcad-json-rpc.exe --serve-pipe ...`, not `partcad-json-rpc.exe -m
    # partcad_service_json_rpc --serve-pipe ...`: the bundle's argument parser
    # has no `-m`, so the daemon exited before it served anything.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _launcher_argv() == [sys.executable]


WORKSPACE = r"C:\ws"


@pytest.fixture
def spawns(monkeypatch, tmp_path):
    """Records ``(argv, kwargs)`` of every spawn, and starts no process.

    The home directory is redirected because the spawn now opens the workspace's
    ``daemon.log`` before it starts anything. Both variables, because this test
    runs on the Windows legs of the matrix too and ``ntpath.expanduser`` reads
    ``USERPROFILE`` there -- it never consults ``HOME``.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs)))
    return calls


def test_the_daemon_is_told_what_the_launcher_was_told(spawns):
    # The POSIX daemon is a fork of the launcher and keeps every setting it was
    # given; the Windows one is a new process, so the settings have to be in the
    # argv that starts it. Without them `pc --python-sandbox conda daemon start`
    # printed a pipe served by a daemon using the default sandbox.
    spawn_pipe_daemon(WORKSPACE, ["--python-sandbox", "conda", "--offline"])

    [(argv, _)] = spawns
    assert argv == [sys.executable, "--serve-pipe", pipe_name(WORKSPACE), "--python-sandbox", "conda", "--offline"]


def test_a_daemon_with_nothing_to_carry_is_spawned_as_before(spawns):
    spawn_pipe_daemon(WORKSPACE)

    [(argv, _)] = spawns
    assert argv == [sys.executable, "--serve-pipe", pipe_name(WORKSPACE)]


def test_the_daemon_gets_somewhere_to_write_its_traceback(spawns, tmp_path):
    # DETACHED_PROCESS gives the child no console, so a daemon that dies before
    # it serves the pipe accounts for itself nowhere unless its output is
    # redirected. All the launcher can otherwise report is that the pipe never
    # appeared, 120 seconds later.
    spawn_pipe_daemon(WORKSPACE)

    [(_, kwargs)] = spawns
    log = kwargs["stdout"]
    assert kwargs["stderr"] is log
    assert log.name == str(tmp_path / ".partcad" / "workspaces" / workspace_hash(WORKSPACE) / "daemon.log")


def _raise(error):
    """A stand-in for a call that fails with ``error``."""

    def raiser(*args, **kwargs):
        raise error

    return raiser


def test_a_daemon_is_started_even_with_nowhere_to_log(spawns, monkeypatch):
    # Somewhere to log is worth having and not worth refusing to start over.
    monkeypatch.setattr(win_pipe.os, "makedirs", _raise(OSError("read-only")))

    spawn_pipe_daemon(WORKSPACE)

    [(_, kwargs)] = spawns
    assert kwargs["stdout"] is None and kwargs["stderr"] is None
