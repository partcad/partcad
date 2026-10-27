#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Stopping the daemon a scenario started, before the scenario's directories go.

A scenario that runs `pc` does so in a workspace of its own -- `I am in ...
directory` makes a fresh temporary one -- usually under a `$HOME` of its own as
well, and the first command there starts that workspace's daemon. A daemon
outlives the command that started it, which is its point; nothing stopped it
outliving the scenario too, and it has no idle exit. So every scenario left one
behind: an idle process with PartCAD loaded and the scenario's package graph
warm, for the rest of the run, and the whole tree of them killed as orphans
when the job ended -- which also loses whatever coverage they had measured,
since a killed process writes none.

On POSIX that is memory. On Windows it is the disk as well. The scenario's
sandbox -- gigabytes of conda environment -- is built under its temporary
`$HOME`, and the cleanup that removes that directory cannot delete a file a live
process holds: what it cannot remove it leaves (see `remove_readonly` in
`steps/partcad-cli/commands/list/packages.py`), scenario after scenario, until
`pip install` in a later one fails with "No space left on device". Until `pc` on
Windows used the named-pipe daemon, each command was served by a one-shot
service that exited with it, and none of this came up there.

So `after_scenario` stops it -- behave runs that hook before the scenario's
cleanups, and so before either directory is removed -- and waits until the
process is gone, killing it (and anything it started that is still running) if
it does not go in time. Only the scenario's *own* daemon, found from the
scenario's own workspace: the directory was made for this scenario, so nothing
else, in this process or in another behavex worker on the same machine, can be
using its daemon. `stop_all_daemons()` would take the other workers' with it.
"""

import contextlib
import os
from typing import Optional

import psutil

from partcad_client import client
from partcad_client import daemon as pc_daemon
from partcad_utils import workspace

# How long a daemon that acknowledged the stop has to exit before it is killed.
# It finishes nothing first -- the scenario's commands are over -- but it does
# write its coverage data on the way out, which on a loaded runner takes a few
# seconds.
STOP_TIMEOUT = 30.0


def stop_scenario_daemon(context) -> None:
    """Stop the daemon serving this scenario's workspace, if one is running, and wait for it."""
    test_dir = getattr(context, "test_dir", None)
    if not test_dir or not os.path.isdir(test_dir):
        return
    # The root the scenario's commands reached their daemon by: they ran with
    # this directory as their working directory (see 'steps/run.py').
    root = client.workspace_root(test_dir)
    # On POSIX the daemon's socket and pid file are under the `$HOME` it was
    # started with, which is the scenario's; on Windows its pipe is named after
    # the root alone, wherever `$HOME` is.
    with _home(getattr(context, "home_dir", None)):
        processes = _daemon_processes(root)
        if not processes:
            return
        pc_daemon.stop_daemon(root)
    _, alive = psutil.wait_procs(processes, timeout=STOP_TIMEOUT)
    for process in alive:
        with contextlib.suppress(psutil.Error):
            process.kill()
    psutil.wait_procs(alive, timeout=5)


@contextlib.contextmanager
def _home(home: Optional[str]):
    """``$HOME`` as the scenario had it, for as long as the daemon is being looked for."""
    if not home:
        yield
        return
    saved = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = saved


def _daemon_processes(root: str) -> list:
    """The daemon serving ``root``, and whatever it started that is still running.

    Its children are taken now, while they are still its children: once it has
    gone, a sandbox process it left running is an orphan nothing can trace back
    to it, and one holding the sandbox is the very thing to be rid of.
    """
    daemon = _pipe_daemon(root) if os.name == "nt" else _socket_daemon(root)
    if daemon is None:
        return []
    try:
        return [daemon, *daemon.children(recursive=True)]
    except psutil.Error:
        return [daemon]


def _socket_daemon(root: str) -> Optional[psutil.Process]:
    """The POSIX daemon, by the pid file it writes beside its socket."""
    try:
        with open(workspace.pid_path(workspace.workspace_dir(root)), encoding="utf-8") as f:
            process = psutil.Process(int(f.read().strip()))
        # The pid file of a daemon that died without removing it can name a
        # process that has nothing to do with it by now.
        return process if _is_service(process.cmdline()) else None
    except (OSError, ValueError, psutil.Error):
        return None


def _pipe_daemon(root: str) -> Optional[psutil.Process]:  # pragma: no cover - Windows only
    """The Windows daemon, by the pipe it was told to serve: it writes no pid file."""
    from partcad_utils.win_pipe import pipe_name

    pipe = pipe_name(root)
    for process in psutil.process_iter(["cmdline"]):
        cmdline = process.info.get("cmdline") or []
        if "--serve-pipe" in cmdline and pipe in cmdline:
            return process
    return None


def _is_service(cmdline: list) -> bool:
    return any("partcad_service_json_rpc" in part or "partcad-json-rpc" in part for part in cmdline)
