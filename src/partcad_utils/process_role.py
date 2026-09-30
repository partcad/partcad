#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether this process is a PartCAD daemon or a command that ends.

One bit, and deliberately only one. A command runs, answers and exits, with a
person waiting on the prompt for it; a daemon is started once, keeps a warm
context, and serves every client of the workspace until somebody stops it. Where
that difference changes what a sane timeout is -- how long to wait before
concluding something rather than waiting longer -- the code asking needs to be
able to tell which one it is in.

It lives here because neither end owns it: `partcad` is what asks (the library
runs in both), and `partcad_service_json_rpc` is what answers by marking itself
as it starts serving. A copy on each side is a copy that can disagree, and this
disagreeing would mean a library reading the timeout of a process it is not in.

Set rather than detected. There is no reliable way to look around and conclude
"I am the daemon" -- the daemon is an ordinary Python process running ordinary
PartCAD code, and every heuristic for it (a process name, a missing terminal, an
environment variable) is something a user's own script can look like by
accident. The process that knows is the one that decided to serve, so that is
the one that says so.
"""

_is_daemon = False


def mark_daemon() -> None:
    """Record that this process serves, called by whatever starts serving.

    Idempotent, and there is no way back. A process that has begun serving does
    not stop being a daemon, and an "unmark" would exist only for tests -- which
    have `monkeypatch` for it and should not need a production entry point.
    """
    global _is_daemon
    _is_daemon = True


def is_daemon() -> bool:
    """True in a process that serves, False in a command and in a test."""
    return _is_daemon
