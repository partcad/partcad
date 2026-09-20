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
one, and the operating system has usually written a full crash report that
nothing points at.

So the number is turned into a sentence here, once, for every runtime and every
caller: which signal it was, what that signal is called, and where the crash
report is. A caller that has nothing else to say about a failure says this.

Nothing here raises. A diagnostic that fails must not replace the failure it was
called to explain, so every lookup below is best effort and falls back to the
plain description of the exit code.
"""

import json
import os
import signal
import sys
import time

# Windows has no signals: a native fault surfaces as a large unsigned status
# code, and these two are the ones PartCAD's own sandboxes have produced. See
# https://github.com/CadQuery/cadquery/issues/1564 for the second one, which
# the Python runtimes deliberately tolerate.
WINDOWS_FAULTS = {
    3221225477: "EXCEPTION_ACCESS_VIOLATION",
    3221226356: "STATUS_HEAP_CORRUPTION",
}

# The signals that mean the process faulted rather than that something asked it
# to stop. Only these are worth looking for a crash report for, and only these
# say anything about the sandbox: a SIGKILL is the operating system (or PartCAD's
# own timeout) ending a process that was working perfectly well.
FAULT_SIGNALS = frozenset(
    getattr(signal, name)
    for name in ("SIGSEGV", "SIGBUS", "SIGILL", "SIGFPE", "SIGABRT", "SIGTRAP")
    if hasattr(signal, name)
)

# Where macOS leaves the crash report of a process that died on a signal.
CRASH_REPORT_DIR = "~/Library/Logs/DiagnosticReports"

# How long to keep looking for it. The report is written by a system service
# after the process is already reaped, so it does not exist yet at the moment
# the exit code is read -- and a wait is only ever paid on a path that has
# already failed.
CRASH_REPORT_TIMEOUT = 3.0
CRASH_REPORT_POLL = 0.2


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


def _report_pid(path) -> int:
    """The pid a macOS .ips crash report is about, or -1 if it cannot be read.

    An .ips file is two JSON documents on consecutive lines: a short header and
    the report itself. Only the second one carries the pid, and it is megabytes
    on a process with many threads -- but it is read in full rather than
    pattern-matched, because a pid that happens to appear in a stack frame is
    not the pid of the process that crashed.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.readline()
            return int(json.loads(f.read()).get("pid", -1))
    except Exception:
        return -1


def crash_report(pid, since=None, timeout=CRASH_REPORT_TIMEOUT):
    """The path of the crash report for 'pid', or None.

    macOS only: it is the one platform PartCAD supports that writes a symbolized
    report for every crash without anything having to be enabled first. A Linux
    core dump depends on 'ulimit -c' and on whatever the distribution's core
    handler does with it, and there is no path that can be named without asking
    both; Windows leaves nothing by default at all.

    Matched on the pid recorded inside the report rather than on its name and
    timestamp, because several sandboxes run at once and they are all called
    'python'.
    """
    if sys.platform != "darwin" or not pid:
        return None
    directory = os.path.expanduser(CRASH_REPORT_DIR)
    if not os.path.isdir(directory):
        return None
    deadline = time.monotonic() + timeout
    while True:
        try:
            for name in os.listdir(directory):
                if not name.endswith(".ips"):
                    continue
                path = os.path.join(directory, name)
                if since is not None and os.path.getmtime(path) < since:
                    continue
                if _report_pid(path) == pid:
                    return path
        except OSError:
            return None
        if time.monotonic() >= deadline:
            return None
        time.sleep(CRASH_REPORT_POLL)


def _faulted(returncode) -> bool:
    """Whether this process died of its own fault rather than being stopped."""
    if returncode in WINDOWS_FAULTS:
        return True
    return returncode is not None and returncode < 0 and -returncode in FAULT_SIGNALS


def describe_termination(cmd, returncode, pid=None, since=None, where=None, silent=True):
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
        # Stopped rather than crashed. There is no crash report to look for and
        # nothing about the sandbox to suspect -- the one thing worth saying is
        # what ends a CAD sandbox from the outside, which on a model this size
        # is almost always the machine running out of memory.
        if returncode == -getattr(signal, "SIGKILL", -1):
            message += (
                " Nothing in the sandbox chose this: something outside it ended the process,"
                " which on a large model is usually the out-of-memory killer."
            )
        return message

    report = crash_report(pid, since=since)
    if report:
        message += " The crash report is at %s." % report
    if silent:
        message += (
            " A sandbox that dies like this without saying anything crashed inside a native"
            " library: either a fault in the CAD kernel on the geometry it was given, or two"
            " incompatible native builds%s - mismatched cadquery-ocp versions above all."
            % (" in the sandbox at %s" % where if where else "")
        )
    return message
