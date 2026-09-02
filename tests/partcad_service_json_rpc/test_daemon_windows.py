#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`ensure_daemon`'s Windows branch.

CI does run Windows (`windows-latest` and `windows-2022` in `test.yml`), but
nothing ran *this*: `test_daemon.py` guards itself on `socket.AF_UNIX`, which
CPython does not define on Windows, so the module holding the daemon's tests is
skipped on the one platform this branch is for. The branch shipped importing a
name its own `win_pipe` does not define (`is_pipe_alive`, which lives in
`partcad_utils.win_pipe` with the rest of the rendezvous), so every
`partcad-json-rpc --socket` on Windows died of an ImportError on the branch's
first line, before spawning anything, and all the editor extension could report
was "exited 1".

Hence a module of its own, with no AF_UNIX guard: these run on Windows, where
the branch is real, *and* on POSIX, where `_pretending_to_be_windows` supplies
the only thing missing. Everything Windows-specific is behind a fake, so there
is nothing here that needs a Windows kernel -- which is the point, since a test
only Windows can run is a test that was not protecting this branch before.
"""

import contextlib
import os

import pytest
from partcad_service_json_rpc import daemon
from partcad_service_json_rpc import win_pipe as service_win_pipe
from partcad_utils import win_pipe as rendezvous

WORKSPACE = r"C:\ws"
SANDBOX_ARGV = ["--python-sandbox", "conda"]


@contextlib.contextmanager
def _pretending_to_be_windows():
    """Take the Windows branch. A no-op where it is the branch anyway.

    A context manager rather than a fixture, because on POSIX ``os.name`` has to
    be back before pytest formats a failure: while it says "nt", ``pathlib.Path``
    builds a ``WindowsPath`` and reporting a failed assertion dies of
    NotImplementedError -- turning a regression here into an INTERNALERROR
    instead of a message naming it.
    """
    saved = os.name
    os.name = "nt"
    try:
        yield
    finally:
        os.name = saved


@pytest.fixture
def spawned(monkeypatch):
    """Records ``(root, extra_args)`` of every daemon spawn, and spawns nothing.

    Patched in as a module attribute rather than by faking the import: the
    branch under test still runs its own ``from ... import ...``, so a name that
    moves away again fails here instead of on a user's machine.
    """
    calls = []
    monkeypatch.setattr(service_win_pipe, "spawn_pipe_daemon", lambda root, extra=(): calls.append((root, list(extra))))
    return calls


def _answers(monkeypatch, *replies):
    """Make ``is_pipe_alive`` return ``replies`` in turn, then its last value."""
    remaining = list(replies)
    monkeypatch.setattr(
        rendezvous,
        "is_pipe_alive",
        lambda name, timeout=1.0: remaining.pop(0) if len(remaining) > 1 else remaining[0],
    )


def test_windows_reuses_the_daemon_already_serving_the_pipe(spawned, monkeypatch, capsys):
    _answers(monkeypatch, True)
    with _pretending_to_be_windows():
        pipe = daemon.ensure_daemon(lambda wdir: None, root_path=WORKSPACE, daemon_argv=SANDBOX_ARGV)
    assert pipe == rendezvous.pipe_name(WORKSPACE)
    assert capsys.readouterr().out.strip() == pipe  # the endpoint goes to stdout
    assert spawned == []


def test_windows_starts_a_daemon_and_waits_for_it_to_answer(spawned, monkeypatch, capsys):
    # Dead, then alive: the launcher must not name the pipe until something is
    # serving it, because connecting to a pipe that does not exist yet fails
    # outright rather than waiting.
    _answers(monkeypatch, False, True)
    with _pretending_to_be_windows():
        pipe = daemon.ensure_daemon(lambda wdir: None, root_path=WORKSPACE, daemon_argv=SANDBOX_ARGV)
    assert capsys.readouterr().out.strip() == pipe
    # The settings the launcher was given reach the daemon. Windows has no
    # `fork`, so nothing carries them across on its own: without this the
    # daemon behind `pc --python-sandbox conda daemon start` served with the
    # defaults, and said nothing about it.
    assert spawned == [(WORKSPACE, SANDBOX_ARGV)]


def test_windows_reports_a_daemon_that_never_starts_serving(spawned, monkeypatch):
    monkeypatch.setattr(daemon, "START_TIMEOUT", 0.05)
    _answers(monkeypatch, False)
    with pytest.raises(RuntimeError, match="did not start serving"):
        with _pretending_to_be_windows():
            daemon.ensure_daemon(lambda wdir: None, root_path=WORKSPACE)
    assert spawned == [(WORKSPACE, [])]
