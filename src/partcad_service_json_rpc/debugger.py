#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Attaching the serving process to a Python debugger, for PartCAD's own development.

``PC_DEBUGPY=[HOST:]PORT`` in the environment makes every serving process --
the socket daemon, the Windows pipe child, stdio and HTTP -- connect to a
debugpy adapter listening there before it builds its session. That is the
"Python" half of the repository's ``Debug Extension and Python`` launch
configuration: it starts the listener, the extension host it launches inherits
the variable, and so does every ``pc daemon start`` the extension runs.

A daemon outlives the debug session that started it, and a warm one started
before it never saw the variable at all. So the extension asks, once, through
``daemon.debug`` (see :func:`status`), whether the daemon it reached is this
source tree's and attached; if it is this tree's and not attached, it stops the
daemon and connects again, which starts one that is. A daemon from anywhere else
-- a downloaded bundle, another checkout -- is left alone: stopping it would
start the same code again, no nearer to the debugger.

Nothing here is a user feature, and nothing fails over it: an unset variable is
the normal case and costs one environment lookup, and a listener that is not
there, or an interpreter without ``debugpy``, is reported in the daemon's log and
served past.
"""

import os
import sys
import threading

ENV = "PC_DEBUGPY"

# How long to wait for the adapter to send the breakpoints once connected. A
# listener that accepted the connection and never finished the handshake must
# not keep the service from serving.
HANDSHAKE_TIMEOUT = 30.0


def _address(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    return host or "localhost", int(port)


def attach_from_env() -> bool:
    """Connect to the debugpy adapter ``PC_DEBUGPY`` names; True once attached."""
    value = os.environ.get(ENV, "").strip()
    if not value:
        return False
    try:
        import debugpy
    except ImportError:
        print("%s=%s, but debugpy is not installed here; serving without a debugger" % (ENV, value), file=sys.stderr)
        return False
    try:
        # Not into sandboxed runtimes: they are other interpreters, often other
        # Python versions, and debugpy would rewrite their command lines to load
        # a copy of itself they may not be able to import.
        debugpy.configure(subProcess=False)
        debugpy.connect(_address(value))
        # Until the adapter has sent the breakpoints, so that one in startup
        # code -- building the session, loading the first package -- is hit.
        # Bounded: past the timeout the wait is cancelled and the service
        # serves on, still connected, with breakpoints arriving when they do.
        timer = threading.Timer(HANDSHAKE_TIMEOUT, debugpy.wait_for_client.cancel)
        timer.daemon = True
        timer.start()
        try:
            debugpy.wait_for_client()
        finally:
            timer.cancel()
    except Exception as e:  # pylint: disable=broad-except
        print("%s=%s: could not attach (%s); serving without a debugger" % (ENV, value, e), file=sys.stderr)
        return False
    return True


def status(session, params):  # pylint: disable=unused-argument
    """Report where this service runs from and whether a debugger is attached."""
    debugpy = sys.modules.get("debugpy")
    return {
        # The package directory, which in a checkout is `<tree>/src/<package>`:
        # what the extension compares with its own tree.
        "source": os.path.dirname(os.path.abspath(__file__)),
        "pid": os.getpid(),
        "debugger": bool(debugpy is not None and debugpy.is_client_connected()),
    }
