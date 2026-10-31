#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Stopping the daemon a scenario started, and saying so when a scenario leaves anything behind.

A scenario that runs `pc` does so in a workspace of its own -- `I am in ...
directory` makes a fresh temporary one -- usually under a `$HOME` of its own as
well, and the first command there starts that workspace's daemon. A daemon
outlives the command that started it, which is its point; nothing stopped it
outliving the scenario too, and it has no idle exit. So every scenario left one
behind: an idle process with PartCAD loaded, for the rest of the run, and the
whole tree of them killed as orphans when the job ended -- losing whatever
coverage they had measured, since a killed process writes none.

So `after_scenario` stops it -- behave runs that hook before the scenario's
cleanups, and so before either directory is removed -- and waits until the
process is gone, killing it (and anything it started that is still running) if
it does not go in time. Only the scenario's *own* daemon, found from the
scenario's own workspace: the directory was made for this scenario, so nothing
else, in this process or in another behavex worker on the same machine, can be
using its daemon. `stop_all_daemons()` would take the other workers' with it.

And then it checks. A scenario's sandbox is gigabytes, and one that is not
removed is an error nowhere: the cleanup that removes the scenario's `$HOME`
warns into the scenario's captured log, which nobody sees when the scenario
passes. That is how the Windows legs ran out of disk with nothing to say why --
several scenarios later, in whichever one happened to need the space. So
whatever is left after the scenario's cleanups, and whatever could not be found
or stopped, is reported as a WARNING on the run's own stderr, past behave's
capture: what is left, how big, and which processes still hold it.
"""

import contextlib
import os
import shutil
import sys
from typing import Optional

import psutil

from partcad_client import client
from partcad_client import daemon as pc_daemon
from partcad_utils import workspace

# How long a daemon that was asked to stop has to exit before it is killed. It
# finishes nothing first -- the scenario's commands are over -- but it writes
# its coverage data on the way out, which on a loaded runner takes seconds.
STOP_TIMEOUT = 30.0

# How many of the largest leftovers a warning names.
LARGEST = 5

# How much of what a daemon that had to be killed wrote after it was asked to
# stop is shown, and for how many of them in one behave process: on Windows it
# writes where each of its threads is while it fails to exit
# ('win_pipe.STOPPED_STACKS_SECONDS'), and a few of those say what there is to
# say.
STOPPED_LOG_BYTES = 32 * 1024
STOPPED_LOGS_SHOWN = 3

_stopped_logs_shown = 0


def watch_scenario_directories(context) -> None:
    """Check, once the scenario's cleanups have run, that its directories are gone.

    Called from `before_scenario`: a cleanup registered before any step is the
    first one behave holds for the scenario, and behave runs them newest first,
    so this one runs after every directory a step registered for removal.
    """
    context.add_cleanup(_check_removed, context)


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
            if _answering(root):
                _warn(
                    "a daemon answers for the workspace %s (%s), but no process serving it was found, so it was "
                    "not stopped and may still hold the scenario's files. Service processes running: %s"
                    % (test_dir, _endpoint(root), _describe(_service_processes()) or "none")
                )
            return
        log = os.path.join(workspace.workspace_dir(root), "daemon.log")
        written = _file_size(log)
        acknowledged = pc_daemon.stop_daemon(root)
    _, alive = psutil.wait_procs(processes, timeout=STOP_TIMEOUT)
    if not alive:
        return
    _warn(
        "the daemon for the workspace %s %s the stop, and %d of its processes were still running %gs later; "
        "killing them: %s"
        % (
            test_dir,
            "acknowledged" if acknowledged else "did not acknowledge",
            len(alive),
            STOP_TIMEOUT,
            _describe(alive),
        )
    )
    for process in alive:
        with contextlib.suppress(psutil.Error):
            process.kill()
    _, survivors = psutil.wait_procs(alive, timeout=5)
    if survivors:
        _warn("could not kill: %s" % _describe(survivors))
    _show_stopped_log(log, written)


def _show_stopped_log(log: str, since: int) -> None:
    """What a daemon that had to be killed wrote to its log after it was asked to stop."""
    global _stopped_logs_shown
    if _stopped_logs_shown >= STOPPED_LOGS_SHOWN:
        return
    _stopped_logs_shown += 1
    try:
        with open(log, "rb") as f:
            f.seek(since)
            tail = f.read(STOPPED_LOG_BYTES)
    except OSError as e:
        _warn("its log %s could not be read: %s" % (log, e))
        return
    _warn(
        "what it wrote to %s after it was asked to stop:\n%s"
        % (log, tail.decode("utf-8", errors="replace").rstrip() or "(nothing)")
    )


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _check_removed(context) -> None:
    if os.environ.get("BEHAVE_NO_CLEANUP", "0") == "1":
        return  # kept on purpose
    for what in ("home_dir", "test_dir"):
        path = getattr(context, what, None)
        if not path:
            continue
        if os.path.exists(path):
            _report_leftover(path, "was not fully removed by the scenario's cleanup")
        # A path with a root and no drive -- '/tmp/sandbox/home\\...', which is
        # what the harness makes on Windows -- is a directory on whatever drive
        # is current, and a process running on another drive puts its files on
        # that one. Nothing removes those, so they are looked for, reported, and
        # removed: a scenario's sandbox is gigabytes.
        for elsewhere in _same_path_on_other_drives(path):
            _report_leftover(elsewhere, "is this scenario's %s on another drive, and something wrote to it" % what)
            shutil.rmtree(elsewhere, onerror=_note_failure)


def _report_leftover(path: str, why: str) -> None:
    total, largest, samples = _measure(path)
    _warn(
        "%s %s: %s left. Largest: %s. For example: %s. Held by: %s. Free on that volume: %s."
        % (
            path,
            why,
            _size(total),
            ", ".join("%s (%s)" % (p, _size(n)) for p, n in largest) or "nothing",
            ", ".join(samples) or "nothing",
            _describe(_holders(path)) or "no process psutil can see",
            _free(path),
        )
    )


def _same_path_on_other_drives(path: str) -> list:
    if os.name != "nt" or os.path.splitdrive(path)[0] or path[:1] not in ("/", "\\"):
        return []
    here = os.path.normcase(os.path.abspath(path))
    found = []
    for partition in psutil.disk_partitions(all=False):
        candidate = os.path.join(partition.mountpoint, path.lstrip("/\\"))
        if os.path.normcase(os.path.abspath(candidate)) != here and os.path.exists(candidate):
            found.append(candidate)
    return found


def _measure(path: str):
    """The size of what is under ``path``, its largest directories, and a few of its files.

    Directories are credited up to three levels down, which is where a
    sandbox, its environments and their packages are.
    """
    sizes = {}
    samples = []
    total = 0
    for directory, _, files in os.walk(path):
        here = 0
        for name in files:
            full = os.path.join(directory, name)
            with contextlib.suppress(OSError):
                here += os.lstat(full).st_size
            if len(samples) < 3:
                samples.append(full)
        total += here
        relative = os.path.relpath(directory, path)
        parts = [] if relative == os.curdir else relative.replace("\\", "/").split("/")
        for depth in range(1, min(len(parts), 3) + 1):
            key = os.path.join(path, *parts[:depth])
            sizes[key] = sizes.get(key, 0) + here
    largest = sorted(sizes.items(), key=lambda item: item[1], reverse=True)[:LARGEST]
    return total, largest, samples


def _holders(path: str) -> list:
    """Processes whose working directory, executable or open files are under ``path``."""
    prefix = os.path.normcase(os.path.abspath(path))
    holders = []
    for process in psutil.process_iter():
        try:
            names = [process.cwd(), process.exe()] + [f.path for f in process.open_files()]
        except psutil.Error:
            continue
        if any(name and os.path.normcase(os.path.abspath(name)).startswith(prefix) for name in names):
            holders.append(process)
    return holders


def _note_failure(function, path, exc_info) -> None:
    _warn("could not remove %s: %s" % (path, exc_info[1]))


def _warn(message: str) -> None:
    # The real stderr rather than sys.stderr: behave captures the latter while a
    # scenario runs and shows it only for one that failed, and the scenario a
    # leak belongs to has usually passed.
    stream = sys.__stderr__ or sys.stderr
    stream.write("WARNING: [behave cleanup] %s\n" % message)
    stream.flush()


def _describe(processes) -> str:
    described = []
    for process in processes:
        try:
            described.append("pid %d (%s)" % (process.pid, " ".join(process.cmdline())[:200]))
        except psutil.Error:
            described.append("pid %d" % process.pid)
    return "; ".join(described)


def _size(n: int) -> str:
    return "%.1f MB" % (n / 1e6)


def _free(path: str) -> str:
    try:
        return _size(shutil.disk_usage(path).free)
    except OSError:
        return "unknown"


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


def _endpoint(root: str) -> str:
    if os.name == "nt":
        from partcad_utils.win_pipe import pipe_name

        return pipe_name(root)
    return workspace.socket_path(root)


def _answering(root: str) -> bool:
    if os.name == "nt":
        from partcad_utils.win_pipe import is_pipe_alive

        return is_pipe_alive(_endpoint(root))
    return workspace.is_alive(_endpoint(root))


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


def _pipe_daemon(root: str) -> Optional[psutil.Process]:
    """The Windows daemon, by the pipe it was told to serve: it writes no pid file.

    Matched on that argument rather than on the executable, which is whichever
    interpreter the launcher ran -- in a virtual environment a redirector, whose
    child, the real interpreter, has the same arguments. The oldest match is
    the outermost, and its children include the other.
    """
    pipe = os.path.normcase(_endpoint(root))
    matches = []
    for process in psutil.process_iter(["cmdline", "create_time"]):
        cmdline = process.info.get("cmdline") or []
        for i, part in enumerate(cmdline[:-1]):
            if part == "--serve-pipe" and os.path.normcase(cmdline[i + 1]) == pipe:
                matches.append(process)
                break
    matches.sort(key=lambda process: process.info.get("create_time") or 0)
    return matches[0] if matches else None


def _service_processes() -> list:
    return [process for process in psutil.process_iter(["cmdline"]) if _is_service(process.info.get("cmdline") or [])]


def _is_service(cmdline: list) -> bool:
    return any("partcad_service_json_rpc" in part or "partcad-json-rpc" in part for part in cmdline)
