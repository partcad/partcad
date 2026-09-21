#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the exit status of a sandbox process means, said in words.

Every piece of geometry PartCAD touches is computed in a subprocess, so a fault
in the CAD kernel reaches the core as a number and nothing else. On POSIX that
number is negative -- Python reports a death by signal as the negated signal --
and "exit code -11" is what a segmentation fault inside OCCT looks like by the
time anyone reads it. It names neither the signal nor the fact that there was
one.

So the number is turned into a sentence here, once, for every runtime and every
caller: which signal it was and what that signal is called. A caller that has
nothing else to say about a failure says this.

What is deliberately not said is where the operating system left its crash
report. That file is a full register and thread dump of whatever crashed, which
on a remote daemon is somebody else's machine and more than the failure needs to
disclose; and naming it is macOS-specific in a way that the signal is not.
Whoever is debugging a crash on their own machine knows where their own reports
are kept.
"""

import signal

# Windows has no signals: a native fault surfaces as a large unsigned status
# code, and these two are the ones PartCAD's own sandboxes have produced. See
# https://github.com/CadQuery/cadquery/issues/1564 for the second one, which
# the Python runtimes deliberately tolerate.
WINDOWS_FAULTS = {
    3221225477: "EXCEPTION_ACCESS_VIOLATION",
    3221226356: "STATUS_HEAP_CORRUPTION",
}

# The signals that mean the process faulted rather than that something asked it
# to stop. Only these say anything about the sandbox: a SIGKILL is the operating
# system (or PartCAD's own timeout) ending a process that was working perfectly
# well.
FAULT_SIGNALS = frozenset(
    getattr(signal, name)
    for name in ("SIGSEGV", "SIGBUS", "SIGILL", "SIGFPE", "SIGABRT", "SIGTRAP")
    if hasattr(signal, name)
)


def killed_by_signal(returncode) -> bool:
    """Whether this exit status means the process was killed rather than ended."""
    return returncode is not None and (returncode < 0 or returncode in WINDOWS_FAULTS)


def describe_exit_code(returncode) -> str:
    """Describe a process exit code, naming the signal if it was killed by one."""
    if returncode is None:
        return "no exit code"
    # POSIX reports a signal death as a negative returncode
    if returncode < 0:
        try:
            name = signal.Signals(-returncode).name
        except ValueError:
            name = "unknown signal"
        return "killed by signal %d (%s)" % (-returncode, name)
    if returncode in WINDOWS_FAULTS:
        return "exit code %d (%s)" % (returncode, WINDOWS_FAULTS[returncode])
    return "exit code %d" % returncode


def command_failure(command, returncode) -> str:
    """The message a caller reports when a sandbox command failed.

    The one phrasing shared by every factory and every operation, so that a
    native crash reads the same wherever it is met.
    """
    return "Failed to execute command '%s': %s" % (
        " ".join(str(part) for part in command),
        describe_exit_code(returncode),
    )


def failure_detail(stderr, returncode) -> str:
    """What to say about a failed command: what it said, and how it ended.

    Both, rather than one or the other. A process that writes to stderr and is
    then killed has said something worth keeping *and* ended in a way worth
    naming, and reporting the first instead of the second is how "killed by
    SIGSEGV" turns back into a pip warning with no failure attached to it.
    """
    said = (stderr or "").strip()
    ended = describe_exit_code(returncode)
    return "%s (%s)" % (said, ended) if said else ended


def _faulted(returncode) -> bool:
    """Whether this process died of its own fault rather than being stopped."""
    if returncode in WINDOWS_FAULTS:
        return True
    return returncode is not None and returncode < 0 and -returncode in FAULT_SIGNALS


def describe_termination(cmd, returncode, where=None, silent=True):
    """Why a sandbox process ended the way it did, or None if it was not killed.

    Returned as the failure a caller reports, rather than logged here: the exit
    code alone reaches the user as a number with no cause attached to it, and
    this is the cause.

    'silent' says the process wrote neither a traceback nor a line of stderr,
    which is the case that needs a guess at what happened. One that crashed
    after saying something has already said more than a guess would.
    """
    if not killed_by_signal(returncode):
        return None
    command = cmd if isinstance(cmd, str) else " ".join(str(part) for part in cmd)
    message = "%s was %s." % (command, describe_exit_code(returncode))

    if not _faulted(returncode):
        # Stopped rather than crashed, so there is nothing about the sandbox
        # to suspect -- the one thing worth saying is what ends a CAD sandbox
        # from the outside, which on a model this size is almost always the
        # machine running out of memory.
        if returncode == -getattr(signal, "SIGKILL", -1):
            message += (
                " Nothing in the sandbox chose this: something outside it ended the process,"
                " which on a large model is usually the out-of-memory killer."
            )
        return message

    if silent:
        message += (
            " A sandbox that dies like this without saying anything crashed inside a native"
            " library: either a fault in the CAD kernel on the geometry it was given, or two"
            " incompatible native builds%s - mismatched cadquery-ocp versions above all."
            % (" in the sandbox at %s" % where if where else "")
        )
    return message
