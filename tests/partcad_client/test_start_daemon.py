#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `start_daemon` says when the launcher does not leave a daemon behind.

This is the only place that holds what `partcad-json-rpc` printed on its way
out: it captures both of the child's streams, and whatever it does not put in
the exception is gone. `subprocess.run(check=True)` was putting none of it there
-- a launcher that died on a traceback reached the user as "Command '[...]'
returned non-zero exit status 1", with the traceback captured and discarded, and
that is what the editor extension shows in its output channel.

The launcher here is a real child process rather than a fake `subprocess.run`,
because which of a child's streams survive into the message is exactly the
thing under test.
"""

import sys

import pytest
from partcad_client import client


def _launcher(script: str):
    """A stand-in `partcad-json-rpc`: this interpreter running ``script``.

    ``--socket`` and the daemon flags land in the script's ``sys.argv``, where
    it ignores them.
    """
    return lambda: [sys.executable, "-c", script]


def test_a_launcher_that_fails_reports_what_it_printed(monkeypatch):
    monkeypatch.setattr(
        client,
        "launcher_argv",
        _launcher("import sys; sys.stderr.write('ImportError: no name is_pipe_alive\\n'); sys.exit(1)"),
    )
    with pytest.raises(RuntimeError) as failure:
        client.start_daemon()
    message = str(failure.value)
    assert "exited with status 1" in message
    assert "ImportError: no name is_pipe_alive" in message


def test_a_launcher_that_fails_silently_says_so(monkeypatch):
    # Nothing to report is worth reporting: it rules out reading past the end of
    # a message for a reason that was never there.
    monkeypatch.setattr(client, "launcher_argv", _launcher("raise SystemExit(3)"))
    with pytest.raises(RuntimeError, match=r"exited with status 3:\n\(no output\)"):
        client.start_daemon()


def test_a_launcher_that_prints_no_endpoint_reports_its_output(monkeypatch):
    # Exit status 0 and no socket path: the launcher thinks it succeeded, so its
    # own output is all there is to go on.
    monkeypatch.setattr(
        client,
        "launcher_argv",
        _launcher("import sys; sys.stderr.write('daemon.log is full of it\\n')"),
    )
    with pytest.raises(RuntimeError) as failure:
        client.start_daemon()
    assert "did not print a socket path" in str(failure.value)
    assert "daemon.log is full of it" in str(failure.value)


def test_the_endpoint_is_the_first_line_the_launcher_prints(monkeypatch):
    monkeypatch.setattr(client, "launcher_argv", _launcher(r"print('\n\\\\.\\pipe\\partcad-0123\n')"))
    assert client.start_daemon() == r"\\.\pipe\partcad-0123"
