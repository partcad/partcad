#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The processes a wrapper started, found and stopped from inside its sandbox.

A wrapper is the one piece of PartCAD that is always where the work is. PartCAD
itself may be on another machine, or outside the container the interpreter runs
in: in the ``docker`` sandbox what PartCAD started is a ``docker exec`` client,
and killing that leaves the interpreter, and the simulator the interpreter
started, running in the container with nothing left to stop them. So a wrapper
that bounds its run stops what it started itself, from where it is.

Standard library only, because it runs in sandboxes that carry nothing else --
a simulation plugin's sandbox has MuJoCo in it and no CAD stack, no psutil.

What counts as started by this process:

* every process whose chain of parents reaches it, which is what a simulator's
  server and the watchers beside it are, whichever process group they put
  themselves in;
* and every process in its process group (see `lead_a_group`), which is what
  reaches a process whose parent has already exited -- one the chain of
  parents no longer leads back from.

Found through ``/proc`` on Linux, which every sandbox container is, and through
``ps`` anywhere else that has one. On Windows a tree is taken whole by
``taskkill /T``, which is the one way there to stop a process and what it
started without a library.
"""

import os
import signal
import subprocess
import time

# How long the processes are given to stop after being asked, in seconds, before
# they are killed. Long enough for a server to close its files, short enough
# that a run which has already used its budget is not kept much beyond it.
GRACE = 2.0


def lead_a_group():
    """Make this process the leader of a process group of its own, if it can.

    So that what it starts, and what that starts, is one group -- including what
    outlives its own parent. Best effort and quiet: a process that already leads
    a session (PartCAD started it in one, see 'runtime.bounded_spawn_options')
    leads its group already and may not move, and a platform with no process
    groups has nothing to do.
    """
    if os.name == "nt":
        return
    try:
        if os.getpgid(0) != os.getpid():
            os.setpgid(0, 0)
    except OSError:
        pass


def _table():
    """Every process on this machine as (pid, parent, group, a zombie), or None if they cannot be listed."""
    if os.path.isdir("/proc/self"):
        rows = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open("/proc/%s/stat" % entry, "rb") as f:
                    stat = f.read().decode("utf-8", "replace")
            except OSError:
                continue
            # 'pid (comm) state ppid pgrp ...', where 'comm' may hold spaces and
            # parentheses of its own: everything after the last ')' is fields.
            fields = stat[stat.rfind(")") + 2 :].split()
            if len(fields) < 3:
                continue
            rows.append((int(entry), int(fields[1]), int(fields[2]), fields[0] == "Z"))
        return rows
    try:
        listed = subprocess.run(
            ["ps", "-A", "-o", "pid=", "-o", "ppid=", "-o", "pgid=", "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if listed.returncode != 0:
        return None
    rows = []
    for line in listed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].isdigit():
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[3].startswith("Z")))
    return rows


def started_by(root=None):
    """The live processes 'root' (this process) started, and what they started. Never 'root' itself.

    None when the processes cannot be listed here at all, which is not the same
    as there being none.
    """
    root = os.getpid() if root is None else root
    rows = _table()
    if rows is None:
        return None
    try:
        group = os.getpgid(root) if os.name != "nt" else None
    except OSError:
        group = None
    led = group == root
    children = {}
    for pid, parent, _group, _zombie in rows:
        children.setdefault(parent, []).append(pid)
    found = set()
    pending = [root]
    while pending:
        for child in children.get(pending.pop(), ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    if led:
        found.update(pid for pid, _parent, pgid, _zombie in rows if pgid == root)
    alive = {pid for pid, _parent, _group, zombie in rows if not zombie}
    found.discard(root)
    return sorted(found & alive)


def stop_started(grace=GRACE, root=None):
    """Stop everything 'root' (this process) started: asked first, killed after 'grace' seconds.

    Returns how many processes there were to stop. 'root' is left running --
    it still has an answer to give, or an exit code to choose.
    """
    if os.name == "nt":
        # 'taskkill /T' takes a process with its tree, and there is no way to
        # name the tree without the process; this one is spared by naming each
        # child instead, which needs a listing Windows has no standard-library
        # way to make. So nothing is done here: a wrapper on Windows that has to
        # stop its run stops itself with it ('stop_everything').
        return 0
    victims = started_by(root)
    if not victims:
        return 0
    _signal(victims, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        left = started_by(root)
        if not left:
            return len(victims)
        time.sleep(0.05)
    _signal(started_by(root) or [], signal.SIGKILL)
    return len(victims)


def stop_everything(exit_code):
    """Stop everything this process started, and then this process, with 'exit_code'.

    What a wrapper does when its bound is spent and its answer is already
    written. Never returns.
    """
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(os.getpid())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            stop_started()
        except Exception:  # pylint: disable=broad-except
            # The exit below is the point; nothing may stand in its way.
            pass
    os._exit(exit_code)


def _signal(pids, sig):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            pass
