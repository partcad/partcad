#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Wrappers forked from a zygote: what a child is, how it ends, and what becomes of the zygote.

None of these needs a CAD sandbox. The zygote is this interpreter, made to
preload something from the standard library instead of the CAD stack
(`sandbox_zygote.PRELOAD`), and the "wrappers" are scripts written into the
test's own directory -- which is all a zygote ever sees of a wrapper: a script
path, an argv, a directory and three pipes.

A zygote is started in the background once an environment has had
`WARM_AFTER` calls, and calls meanwhile run fresh; the fixture below makes that
the first call, and `_forked` asks until the zygote is there. Each test has an
environment of its own (`_environment`), so no two share a zygote, and the
fixture retires every zygote a test started and waits for its process to be
gone: a test leaves no process and no socket behind for whatever the worker
runs next (see "pytest runs in parallel" in the root `AGENTS.md`).
"""

import asyncio
import errno
import io
import json
import os
import signal
import socket
import sys
import textwrap
import time
import types

import psutil
import pytest

from partcad import runtime, runtime_python, sandbox_lock, sandbox_zygote
from partcad_utils import container_service

pytestmark = pytest.mark.skipif(not sandbox_zygote.supported(), reason="zygotes are Linux only")

FLAGS = ["-sOOu"]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """A cheap preload, and every zygote this test started gone by the end of it."""
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("json",))
    monkeypatch.setattr(sandbox_zygote, "WARM_AFTER", 1)
    _measured(monkeypatch)
    before = {id(zygote) for zygote in sandbox_zygote.zygotes()}
    yield
    _retire_started(before)


def _measured(monkeypatch):
    """Have the zygotes, and the children they fork, measured by the coverage this test is measured by.

    The code that runs in a zygote runs in no process of pytest's own, and
    `wrappers/zygote.py` would otherwise count as untested however many tests
    drive it. The zygote is this interpreter, which starts coverage itself when
    'COVERAGE_PROCESS_START' names a configuration (coverage's own '.pth'
    hook), and a forked child saves its own data on the way out ('atexit').
    The data lands beside this process's, where pytest-cov combines it.
    """
    try:
        import coverage

        current = coverage.Coverage.current()
    except Exception:
        current = None
    config_file = getattr(getattr(current, "config", None), "config_file", None)
    if not config_file:
        return
    monkeypatch.setenv("COVERAGE_PROCESS_START", os.path.abspath(config_file))
    monkeypatch.setenv("COVERAGE_FILE", os.path.abspath(current.config.data_file))


def _retire_started(before):
    started = [zygote for zygote in sandbox_zygote.zygotes() if id(zygote) not in before]
    for zygote in started:
        sandbox_zygote.retire(zygote.environment)
    for zygote in started:
        assert zygote.ready.wait(120)
        if zygote.popen is not None:
            zygote.popen.wait(timeout=60)


def _environment(tmp_path):
    return str(tmp_path / "environment")


def _script(tmp_path, body, name="wrapper.py"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body))
    return str(path)


def _site(tmp_path):
    """A directory to import a module from, the way a zygote imports its stack from site-packages.

    With its '__pycache__' already there: the first import writes into that,
    and a directory made by it would be a change to what the zygote imported
    from, made while it imported it -- which is a reason to start another.
    """
    site = tmp_path / "site"
    (site / "__pycache__").mkdir(parents=True)
    return site


def _argv(script, *args):
    return [sys.executable, *FLAGS, script, *args]


async def _forked(tmp_path, argv, cwd=None, env=None, new_session=False):
    """``argv`` forked from its environment's zygote, asking until there is one to fork it from."""
    deadline = time.monotonic() + 120
    while True:
        p = await sandbox_zygote.process_async(
            _environment(tmp_path),
            argv,
            sandbox_zygote.script_index(argv, FLAGS),
            cwd=cwd or str(tmp_path),
            env=env,
            new_session=new_session,
        )
        if p is not None:
            return p
        assert time.monotonic() < deadline, "no zygote to fork from"
        await asyncio.sleep(0.05)


async def _call(tmp_path, script, *args, stdin=b"", timeout=None, cwd=None, env=None):
    """One call through a zygote, read the way a runtime reads it: (process, stdout, stderr)."""
    p = await _forked(tmp_path, _argv(script, *args), cwd=cwd, env=env, new_session=timeout is not None)
    stdout, stderr = await runtime.communicate(p, stdin, timeout)
    return p, stdout, stderr


def _settled(tmp_path, within=120):
    """Wait for whatever zygote this environment is starting to be ready, or to have failed."""
    deadline = time.monotonic() + within
    environment = os.path.normpath(_environment(tmp_path))
    while time.monotonic() < deadline:
        starting = [z for z in sandbox_zygote.zygotes() if z.environment == environment and not z.ready.is_set()]
        if not starting:
            return
        time.sleep(0.05)
    raise AssertionError("a zygote is still starting")


def _fresh(script, *args, stdin=b"", cwd=None):
    import subprocess

    done = subprocess.run(_argv(script, *args), input=stdin, capture_output=True, cwd=cwd, timeout=60)
    return done.returncode, done.stdout, done.stderr


# --------------------------------------------------------------------------- #
# What a child is                                                              #
# --------------------------------------------------------------------------- #

ECHO = """
    import os, sys
    data = sys.stdin.buffer.read()
    print("argv=%r" % (sys.argv,))
    print("cwd=%s" % os.getcwd())
    print("main=%s file=%s" % (__name__, __file__))
    print("in=%d" % len(data))
    sys.stderr.write("said something\\n")
"""


def test_a_forked_wrapper_is_run_as_its_script_on_the_runtimes_pipes(tmp_path):
    script = _script(tmp_path, ECHO)
    work = tmp_path / "work"
    work.mkdir()

    p, stdout, stderr = asyncio.run(_call(tmp_path, script, "a", "b", stdin=b"x" * 100000, cwd=str(work)))

    assert p.returncode == 0, stderr
    assert stdout.decode() == _fresh(script, "a", "b", stdin=b"x" * 100000, cwd=str(work))[1].decode()
    assert b"in=100000" in stdout
    assert stderr == b"said something\n"
    # The zygote's child, not this process's: that is what reaps it and
    # reports how it ended.
    assert p.parent_pid != os.getpid()


def test_a_large_answer_comes_back_whole(tmp_path):
    """Several pipe buffers' worth, read as it is written -- neither side may wait for the other to finish."""
    script = _script(tmp_path, "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read() * 3)\n")
    request = os.urandom(1 << 20)

    p, stdout, _ = asyncio.run(_call(tmp_path, script, stdin=request))

    assert p.returncode == 0
    assert stdout == request * 3


STATE = """
    import json, os, sys
    # What an earlier request could have left behind, if a child were not a
    # copy of a zygote that has run none.
    print("left=%r" % (getattr(json, "left_behind", None),))
    print("cwd=%s" % os.getcwd())
    print("env=%r" % (os.environ.get("LEFT_BEHIND"),))
    print("modules=%r" % ("decimal" in sys.modules,))
    json.left_behind = sys.argv[1]
    os.environ["LEFT_BEHIND"] = sys.argv[1]
    os.chdir("/")
    import decimal
"""


def test_a_request_answers_the_same_alone_and_after_others(tmp_path):
    script = _script(tmp_path, STATE)

    async def calls():
        _, alone, _ = await _call(tmp_path, script, "first")
        for i in range(5):
            await _call(tmp_path, script, "other-%d" % i)
        _, after, _ = await _call(tmp_path, script, "last")
        return alone, after

    alone, after = asyncio.run(calls())

    assert alone == after
    assert b"left=None" in alone
    assert ("cwd=%s" % tmp_path).encode() in alone
    assert b"modules=False" in alone
    # And what a fresh interpreter answers.
    assert alone == _fresh(script, "fresh", cwd=str(tmp_path))[1]


def test_requests_in_parallel_each_get_their_own_answer(tmp_path):
    script = _script(tmp_path, "import sys, time\ntime.sleep(0.2)\nsys.stdout.write(sys.stdin.read()[::-1])\n")

    async def calls():
        return await asyncio.gather(*(_call(tmp_path, script, stdin=("request %d" % i).encode()) for i in range(8)))

    answers = asyncio.run(calls())

    assert [stdout for _, stdout, _ in answers] == [("request %d" % i)[::-1].encode() for i in range(8)]
    assert len({p.pid for p, _, _ in answers}) == 8


SHUTDOWN = """
    import atexit, sys
    atexit.register(lambda: sys.stderr.write("atexit ran\\n"))
    left_open = open(sys.argv[1], "w")
    left_open.write("buffered, never flushed")
    class Finalized:
        def __del__(self):
            sys.stderr.write("finalized\\n")
    kept = Finalized()
"""


def test_a_child_ends_the_way_a_fresh_interpreter_would(tmp_path):
    """Its 'atexit' handlers run, a file it left open is written out, and its objects are finalized."""
    script = _script(tmp_path, SHUTDOWN)
    forked, fresh = tmp_path / "forked.txt", tmp_path / "fresh.txt"

    p, _, stderr = asyncio.run(_call(tmp_path, script, str(forked)))
    returncode, _, fresh_stderr = _fresh(script, str(fresh))

    assert (p.returncode, stderr) == (returncode, fresh_stderr) == (0, b"atexit ran\nfinalized\n")
    assert forked.read_text() == fresh.read_text() == "buffered, never flushed"


@pytest.mark.parametrize(
    "body,expected",
    [
        ("import sys\nsys.exit(3)\n", 3),
        ("import sys\nsys.exit('a message')\n", 1),
        ("raise ValueError('boom')\n", 1),
        ("def broken(:\n", 1),
        ("raise KeyboardInterrupt\n", -signal.SIGINT),
    ],
    ids=["exit-code", "exit-message", "exception", "syntax-error", "interrupt"],
)
def test_how_a_script_ends_is_its_exit_status_and_what_it_said(tmp_path, body, expected):
    script = _script(tmp_path, body)

    p, _, stderr = asyncio.run(_call(tmp_path, script))
    returncode, _, fresh_stderr = _fresh(script)

    assert p.returncode == returncode == expected
    # Word for word: a traceback starts in the script, as a fresh one does,
    # not in the zygote that ran it.
    assert stderr == fresh_stderr


def test_a_crash_is_the_signal_that_killed_it(tmp_path):
    script = _script(tmp_path, "import ctypes\nctypes.string_at(0)\n")

    p, _, _ = asyncio.run(_call(tmp_path, script))

    assert p.returncode == -signal.SIGSEGV


def test_a_crash_leaves_the_zygote_serving(tmp_path):
    crash = _script(tmp_path, "import ctypes\nctypes.string_at(0)\n", name="crash.py")
    echo = _script(tmp_path, ECHO)

    async def calls():
        first, _, _ = await _call(tmp_path, crash)
        second, stdout, _ = await _call(tmp_path, echo)
        return first, second, stdout

    first, second, stdout = asyncio.run(calls())

    assert first.returncode == -signal.SIGSEGV
    assert second.returncode == 0 and b"main=__main__" in stdout
    assert first.parent_pid == second.parent_pid


def test_a_bounded_call_leads_a_session_of_its_own(tmp_path):
    """What 'start_new_session' makes of a fresh interpreter, so that the bound can stop all of it at once."""
    script = _script(tmp_path, "import os\nprint(os.getsid(0) == os.getpid(), os.getpgid(0) == os.getpid())\n")

    p, stdout, _ = asyncio.run(_call(tmp_path, script, timeout=60))

    assert p.returncode == 0
    assert stdout.split() == [b"True", b"True"]


def test_children_draw_random_numbers_of_their_own(tmp_path, monkeypatch):
    """numpy's global generator was seeded once, in the zygote, and every child would draw the same numbers from it."""
    pytest.importorskip("numpy")
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("numpy.random",))
    script = _script(tmp_path, "import random, numpy.random\nprint(numpy.random.random(), random.random())\n")

    async def calls():
        return [(await _call(tmp_path, script))[1].split() for _ in range(2)]

    first, second = asyncio.run(calls())

    assert first[0] != second[0]
    assert first[1] != second[1]


@pytest.mark.parametrize(
    "body,expected",
    [
        ("import sys, time\ntime.sleep(0.5)\nsys.stdout.write(str(len(sys.stdin.buffer.read())))\n", b"1048576"),
        ("import sys\nsys.stdout.write('not listening')\n", b"not listening"),
    ],
    ids=["read-late", "never-read"],
)
def test_a_request_is_written_as_the_child_reads_it(tmp_path, body, expected):
    """More than a pipe holds: the rest waits for room, and stops when the child has stopped reading.

    As asyncio's own 'communicate' does, which is what a fresh interpreter's
    request is written with.
    """
    script = _script(tmp_path, body)
    request = b"x" * (1 << 20)

    p, stdout, _ = asyncio.run(_call(tmp_path, script, stdin=request))

    assert (p.returncode, stdout) == (0, expected)
    assert _fresh(script, stdin=request)[:2] == (0, expected)


# --------------------------------------------------------------------------- #
# Stopping a child                                                             #
# --------------------------------------------------------------------------- #

SLEEPER = """
    import os, sys, time
    sys.stdout.write("%d\\n" % os.getpid())
    sys.stdout.flush()
    time.sleep(120)
"""


def _dead(pid, within=30):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


def test_a_bound_kills_the_child(tmp_path):
    script = _script(tmp_path, SLEEPER)
    seen = {}

    async def call():
        p = await _forked(tmp_path, _argv(script), new_session=True)
        seen["pid"] = p.pid
        await runtime.communicate(p, b"", timeout=1)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(call())

    assert _dead(seen["pid"])


def test_cancelling_a_call_kills_the_child(tmp_path):
    script = _script(tmp_path, SLEEPER)
    seen = {}

    async def call():
        p = await _forked(tmp_path, _argv(script))
        seen["pid"] = p.pid
        task = asyncio.ensure_future(runtime.communicate(p, b""))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(call())

    assert _dead(seen["pid"])


def test_what_a_child_started_and_left_holding_its_output_is_stopped(tmp_path):
    """The rule every sandbox process is held to (`runtime.communicate`), through the zygote's pipes."""
    script = _script(
        tmp_path,
        """
        import subprocess, sys
        held = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        print(held.pid)
        """,
    )

    p, stdout, _ = asyncio.run(_call(tmp_path, script))

    assert p.returncode == 0
    assert _dead(int(stdout.split()[-1]))


def test_output_held_by_what_could_not_be_stopped_is_cut_off_from_this_end(tmp_path, monkeypatch):
    """The last resort of `runtime.communicate`, through the zygote's pipes: what was read by then is the answer.

    `stop_holders` finds nothing here, as it finds nothing where no tool can
    say which process holds a pipe, or the one that does will not die.
    """
    monkeypatch.setattr(container_service, "EXIT_GRACE", 0.5)
    monkeypatch.setattr(container_service, "stop_holders", lambda files: [])
    held = tmp_path / "held"
    script = _script(
        tmp_path,
        """
        import subprocess, sys
        held = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        open(sys.argv[1], "w").write(str(held.pid))
        print("answered")
        """,
    )

    try:
        p, stdout, _ = asyncio.run(_call(tmp_path, script, str(held)))
        assert not _dead(int(held.read_text()), within=0.5)
    finally:
        if held.exists():
            try:
                os.kill(int(held.read_text()), signal.SIGKILL)
            except OSError:
                pass

    assert p.returncode == 0
    assert stdout == b"answered\n"


def test_a_child_whose_zygote_dies_is_reported_killed(tmp_path):
    script = _script(tmp_path, SLEEPER)

    async def call():
        p = await _forked(tmp_path, _argv(script))
        task = asyncio.ensure_future(runtime.communicate(p, b""))
        await asyncio.sleep(0.5)
        os.kill(p.parent_pid, signal.SIGKILL)
        await asyncio.wait_for(task, 60)
        return p

    p = asyncio.run(call())

    assert p.zygote_lost
    assert p.returncode == -signal.SIGKILL
    assert _dead(p.pid)


def test_the_owner_of_a_forked_child_is_found_under_its_zygote(tmp_path):
    """`kill_process_tree` checks a pid against its parent first, and a forked child's parent is the zygote."""
    script = _script(tmp_path, SLEEPER)

    async def call():
        p = await _forked(tmp_path, _argv(script), new_session=True)
        owner = runtime.process_owner(p)
        runtime.kill_process_tree(p, owner=owner)
        await asyncio.wait_for(p.wait(), 30)
        return p, owner

    p, owner = asyncio.run(call())

    assert owner is not None and owner.pid == p.pid
    assert p.returncode == -signal.SIGKILL


# --------------------------------------------------------------------------- #
# The zygote's lifetime                                                        #
# --------------------------------------------------------------------------- #


def _zygote_pid(tmp_path):
    return _starting(tmp_path).pid


def _starting(tmp_path):
    """The one zygote this test's environment has, ready or not."""
    (zygote,) = [z for z in sandbox_zygote.zygotes() if z.environment == os.path.normpath(_environment(tmp_path))]
    return zygote


def _refused(tmp_path, within=120):
    """Why this test's environment could not have a zygote, once that has been found out.

    Asked for rather than read at once: it is written after the zygote says it
    is over, by the thread that started it.
    """
    deadline = time.monotonic() + within
    environment = os.path.normpath(_environment(tmp_path))
    while time.monotonic() < deadline:
        with sandbox_zygote._registry_lock:
            found = [entry for key, entry in sandbox_zygote._unusable.items() if key[0] == environment]
        if found:
            return found[0]
        time.sleep(0.05)
    raise AssertionError("nothing says why %s has no zygote" % environment)


def _held_against(tmp_path):
    with sandbox_zygote._registry_lock:
        return [key for key in sandbox_zygote._unusable if key[0] == os.path.normpath(_environment(tmp_path))]


def _asked(tmp_path, argv, env=None, lock=None):
    """One call's question to its environment's zygote, for a test in which no process is to be forked."""
    return asyncio.run(
        sandbox_zygote.process_async(_environment(tmp_path), argv, 2, cwd=str(tmp_path), env=env, lock=lock)
    )


def _start_held(tmp_path, monkeypatch, argv, env=None):
    """Have a zygote started, and hand it over before it starts: it waits for a process slot until this returns."""
    slots = sandbox_lock.ProcessSlots(1)
    monkeypatch.setattr(sandbox_lock, "process_slots", slots)
    with slots.slot():
        assert _asked(tmp_path, argv, env=env) is None
        return _starting(tmp_path)


def test_one_zygote_serves_every_call_of_an_environment(tmp_path):
    script = _script(tmp_path, ECHO)

    async def calls():
        return [(await _call(tmp_path, script))[0].parent_pid for _ in range(3)]

    assert len(set(asyncio.run(calls()))) == 1


def test_an_install_retires_the_zygote(tmp_path):
    """What 'record_install' does, after every install into an environment, whichever process asked."""
    script = _script(tmp_path, ECHO)
    runtime_ = runtime_python.PythonRuntime(_ctx(tmp_path), "test", "3.11")

    async def calls():
        first = (await _call(tmp_path, script))[0].parent_pid
        runtime_.record_install("anything", _environment(tmp_path))
        second = (await _call(tmp_path, script))[0].parent_pid
        return first, second

    os.makedirs(_environment(tmp_path))
    first, second = asyncio.run(calls())

    assert first != second
    assert _dead(first)


def test_an_install_into_the_sandbox_retires_the_zygotes_of_its_layers(tmp_path):
    """A layer sees the sandbox's own packages after its own, so its zygote imported what was just replaced."""
    script = _script(tmp_path, ECHO)
    sandbox = tmp_path / "sandbox"
    layer = sandbox / (runtime_python.VENV_PREFIX + "0123456789abcdef")
    elsewhere = tmp_path / "sandbox-other"

    async def forked_from(environment):
        argv = _argv(script)
        deadline = time.monotonic() + 120
        while True:
            p = await sandbox_zygote.process_async(str(environment), argv, 2, cwd=str(tmp_path))
            if p is not None:
                await runtime.communicate(p, b"")
                return p.parent_pid
            assert time.monotonic() < deadline
            await asyncio.sleep(0.05)

    async def calls():
        before = {name: await forked_from(path) for name, path in (("layer", layer), ("elsewhere", elsewhere))}
        sandbox_zygote.retire(str(sandbox))
        after = {name: await forked_from(path) for name, path in (("layer", layer), ("elsewhere", elsewhere))}
        return before, after

    before, after = asyncio.run(calls())

    assert before["layer"] != after["layer"]
    # A sibling whose name merely starts the same way is another environment.
    assert before["elsewhere"] == after["elsewhere"]


def test_a_change_to_what_it_imported_from_retires_it(tmp_path):
    """An install by another process: nothing here hears of it, and the directory it wrote to says so."""
    script = _script(tmp_path, ECHO)
    imported_from = tmp_path / "site"
    imported_from.mkdir()
    env = dict(os.environ, PYTHONPATH=str(imported_from))

    async def calls():
        first = (await _call(tmp_path, script, env=env))[0].parent_pid
        # Past the granularity of a directory's timestamp, generously.
        await asyncio.sleep(0.1)
        (imported_from / "installed.py").write_text("")
        second = (await _call(tmp_path, script, env=env))[0].parent_pid
        third = (await _call(tmp_path, script, env=env))[0].parent_pid
        return first, second, third

    first, second, third = asyncio.run(calls())

    assert first != second == third


def test_a_zygote_that_cannot_be_started_is_not_asked_again(tmp_path, monkeypatch):
    broken = _site(tmp_path)
    (broken / "broken_on_import.py").write_text("raise RuntimeError('not today')\n")
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("broken_on_import",))
    env = dict(os.environ, PYTHONPATH=str(broken))
    script = _script(tmp_path, ECHO)
    argv = _argv(script)

    async def call():
        return await sandbox_zygote.process_async(_environment(tmp_path), argv, 2, cwd=str(tmp_path), env=env)

    assert asyncio.run(call()) is None
    assert "not today" in _refused(tmp_path)[3]
    assert asyncio.run(call()) is None
    # The second call found the refusal remembered, and started nothing.
    assert [z for z in sandbox_zygote.zygotes() if z.environment == os.path.normpath(_environment(tmp_path))] == []


def test_a_zygote_that_starts_a_thread_is_not_used(tmp_path, monkeypatch):
    """Forking a process with a thread in it is what must not happen, so a zygote with one says no."""
    site = _site(tmp_path)
    (site / "starts_a_thread.py").write_text(
        "import threading, time\nthreading.Thread(target=time.sleep, args=(120,), daemon=True).start()\n"
    )
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("starts_a_thread",))
    env = dict(os.environ, PYTHONPATH=str(site))
    argv = _argv(_script(tmp_path, ECHO))

    async def call():
        return await sandbox_zygote.process_async(_environment(tmp_path), argv, 2, cwd=str(tmp_path), env=env)

    assert asyncio.run(call()) is None
    assert "threads" in _refused(tmp_path)[3]
    assert asyncio.run(call()) is None


def test_a_dead_zygote_is_replaced(tmp_path):
    script = _script(tmp_path, ECHO)

    async def calls():
        first = (await _call(tmp_path, script))[0].parent_pid
        os.kill(first, signal.SIGKILL)
        assert _dead(first)
        second = (await _call(tmp_path, script))[0].parent_pid
        return first, second

    first, second = asyncio.run(calls())

    assert first != second


def test_a_zygote_that_dies_under_a_call_is_a_fresh_interpreter_for_it(tmp_path, monkeypatch):
    """Between being found and being asked: the call is started the ordinary way, and nothing ran twice."""
    script = _script(tmp_path, ECHO)
    argv = _argv(script)

    async def calls():
        first = (await _call(tmp_path, script))[0].parent_pid
        os.kill(first, signal.SIGKILL)
        assert _dead(first)
        # Found as if still alive: this is the instant after the check.
        monkeypatch.setattr(sandbox_zygote.Zygote, "stale", lambda self: False)
        return await sandbox_zygote.process_async(_environment(tmp_path), argv, 2, cwd=str(tmp_path))

    assert asyncio.run(calls()) is None


def test_an_idle_zygote_goes_by_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_zygote, "IDLE", 0.5)
    script = _script(tmp_path, ECHO)

    async def call():
        return (await _call(tmp_path, script))[0].parent_pid

    pid = asyncio.run(call())

    assert _dead(pid)


def test_no_call_waits_for_a_zygote_to_start(tmp_path, monkeypatch):
    """The first calls of an environment, and every call while its zygote imports, are started the ordinary way."""
    site = _site(tmp_path)
    # Far longer than the bound below, so that a call that waited for it could
    # not pass however slow the machine is.
    (site / "slow_to_import.py").write_text("import time\ntime.sleep(20)\n")
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("slow_to_import",))
    monkeypatch.setattr(sandbox_zygote, "WARM_AFTER", 2)
    env = dict(os.environ, PYTHONPATH=str(site))
    argv = _argv(_script(tmp_path, ECHO))

    async def call():
        started = time.monotonic()
        p = await sandbox_zygote.process_async(_environment(tmp_path), argv, 2, cwd=str(tmp_path), env=env)
        return p, time.monotonic() - started

    environment = os.path.normpath(_environment(tmp_path))
    first, _ = asyncio.run(call())
    assert first is None
    # One call is not reason enough to start one.
    assert [z for z in sandbox_zygote.zygotes() if z.environment == environment] == []
    second, took = asyncio.run(call())
    assert second is None
    # A fresh interpreter's start, with seconds to spare on a loaded worker, and
    # still far short of the twenty the zygote spends importing.
    assert took < 5
    (starting,) = [z for z in sandbox_zygote.zygotes() if z.environment == environment]
    assert starting.ready.wait(120) and starting.usable


def test_a_zygote_starts_in_a_process_slot_of_its_own(tmp_path, monkeypatch):
    """It is an interpreter importing a CAD stack, which is what the slots count: it waits for one."""
    slots = sandbox_lock.ProcessSlots(1)
    monkeypatch.setattr(sandbox_lock, "process_slots", slots)
    argv = _argv(_script(tmp_path, ECHO))
    environment = os.path.normpath(_environment(tmp_path))

    async def call():
        return await sandbox_zygote.process_async(_environment(tmp_path), argv, 2, cwd=str(tmp_path))

    with slots.slot():
        assert asyncio.run(call()) is None
        (starting,) = [z for z in sandbox_zygote.zygotes() if z.environment == environment]
        time.sleep(1)
        assert starting.popen is None and not starting.ready.is_set()
    assert starting.ready.wait(120) and starting.usable


def test_a_zygote_in_use_does_not_give_way_to_another(tmp_path, monkeypatch):
    """Two environments used by turns would take each other's place on every call; one goes without instead."""
    monkeypatch.setattr(sandbox_zygote, "MAX_ZYGOTES", 1)
    script = _script(tmp_path, ECHO)
    other = tmp_path / "other"
    other.mkdir()

    async def calls():
        await _call(tmp_path, script)
        return await sandbox_zygote.process_async(str(other / "environment"), _argv(script), 2, cwd=str(tmp_path))

    assert asyncio.run(calls()) is None
    assert [z.environment for z in sandbox_zygote.zygotes()] == [os.path.normpath(_environment(tmp_path))]

    # Unused long enough, it does.
    monkeypatch.setattr(sandbox_zygote, "EVICT_AFTER", 0.0)
    assert asyncio.run(calls()) is None
    _settled(other)
    assert [z.environment for z in sandbox_zygote.zygotes()] == [os.path.normpath(str(other / "environment"))]


@pytest.mark.parametrize("why", ["no interpreter", "no room for its log"])
def test_a_zygote_that_cannot_be_started_says_why(tmp_path, monkeypatch, why):
    """Whatever stops it, the calls go on in fresh interpreters, and what stopped it is what is remembered."""
    argv = _argv(_script(tmp_path, ECHO))
    if why == "no interpreter":
        argv[0] = str(tmp_path / "no-such-python")
        expected = "no-such-python"
    else:
        full = _raises(OSError(errno.ENOSPC, "No space left on device"))
        monkeypatch.setattr(sandbox_zygote, "tempfile", types.SimpleNamespace(TemporaryFile=full))
        expected = "No space left on device"

    assert _asked(tmp_path, argv) is None

    refused = _refused(tmp_path)[3]
    assert "could not start it" in refused and expected in refused


@pytest.mark.parametrize(
    "body",
    [
        "raise RuntimeError('too late')\n",
        "import threading\nthreading.Thread(target=time.sleep, args=(120,), daemon=True).start()\n",
    ],
    ids=["fails", "starts-a-thread"],
)
def test_a_zygote_the_runtime_stopped_waiting_for_exits_by_itself(tmp_path, monkeypatch, body):
    """It goes to say why it cannot serve, finds nobody to say it to, and goes -- rather than wait to be killed."""
    site = _site(tmp_path)
    (site / "slow_to_answer.py").write_text("import time\ntime.sleep(1.5)\n" + body)
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("slow_to_answer",))
    monkeypatch.setattr(sandbox_zygote, "START_TIMEOUT", 0.3)
    # Long enough that only a zygote that did not go by itself is killed.
    monkeypatch.setattr(sandbox_zygote, "_REFUSED_EXIT", 60.0)
    env = dict(os.environ, PYTHONPATH=str(site))

    starting = _start_held(tmp_path, monkeypatch, _argv(_script(tmp_path, ECHO)), env=env)

    assert starting.ready.wait(120)
    assert not starting.usable and "did not answer" in starting.reason
    assert starting.popen.wait(60) == 0


def test_a_zygote_stuck_in_its_imports_is_killed(tmp_path, monkeypatch):
    site = _site(tmp_path)
    (site / "stuck_on_import.py").write_text("import time\ntime.sleep(120)\n")
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("stuck_on_import",))
    monkeypatch.setattr(sandbox_zygote, "START_TIMEOUT", 0.3)
    monkeypatch.setattr(sandbox_zygote, "_REFUSED_EXIT", 0.5)
    env = dict(os.environ, PYTHONPATH=str(site))

    stuck = _start_held(tmp_path, monkeypatch, _argv(_script(tmp_path, ECHO)), env=env)

    assert stuck.ready.wait(120)
    assert stuck.popen.wait(60) == -signal.SIGKILL
    assert "did not answer" in _refused(tmp_path)[3]


def test_a_zygote_of_another_release_is_not_used(tmp_path, monkeypatch):
    """A checkout whose files moved under a daemon still running the old code: the two ends would not agree."""
    monkeypatch.setattr(sandbox_zygote, "PROTOCOL", sandbox_zygote.PROTOCOL + 1)
    monkeypatch.setattr(sandbox_zygote, "_REFUSED_EXIT", 60.0)

    other = _start_held(tmp_path, monkeypatch, _argv(_script(tmp_path, ECHO)))

    assert "protocol" in _refused(tmp_path)[3]
    # Told nothing, it takes the closed control socket for its retirement.
    assert other.popen.wait(60) == 0


def test_a_zygote_whose_files_changed_while_it_imported_is_not_used_and_the_next_call_starts_another(
    tmp_path, monkeypatch
):
    """An install by another process, half done as it imported: some of each, which no fresh interpreter would be."""
    site = _site(tmp_path)
    (site / "installs_as_imported.py").write_text(
        "import os\nopen(os.path.join(os.path.dirname(__file__), 'installed.py'), 'a').close()\n"
    )
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("installs_as_imported",))
    env = dict(os.environ, PYTHONPATH=str(site))
    script = _script(tmp_path, ECHO)

    first = _start_held(tmp_path, monkeypatch, _argv(script), env=env)

    assert first.ready.wait(120)
    assert not first.usable and "changed while it imported" in first.reason
    # Not held against the environment: the install is over by the next call.
    p, stdout, _ = asyncio.run(_call(tmp_path, script, env=env))
    assert p.returncode == 0 and b"main=__main__" in stdout
    assert p.parent_pid != first.pid


def test_an_environment_that_could_not_have_a_zygote_asks_again_once_what_it_imports_from_changes(
    tmp_path, monkeypatch
):
    """An install by another process, which nothing here hears of: the directory it installed into says so."""
    site = _site(tmp_path)
    (site / "needs_a_dependency.py").write_text("import partcad_zygote_dependency\n")
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("needs_a_dependency",))
    env = dict(os.environ, PYTHONPATH=str(site))
    script = _script(tmp_path, ECHO)

    assert _asked(tmp_path, _argv(script), env=env) is None
    assert "partcad_zygote_dependency" in _refused(tmp_path)[3]
    assert _asked(tmp_path, _argv(script), env=env) is None
    # Past the granularity of a directory's timestamp, generously.
    time.sleep(0.1)
    (site / "partcad_zygote_dependency.py").write_text("")

    p, stdout, _ = asyncio.run(_call(tmp_path, script, env=env))

    assert p.returncode == 0 and b"main=__main__" in stdout


def test_an_install_forgets_that_an_environment_could_not_have_a_zygote(tmp_path, monkeypatch):
    """What was installed may be what it lacked."""
    broken = _site(tmp_path)
    (broken / "broken_on_import.py").write_text("raise RuntimeError('not today')\n")
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("broken_on_import",))
    env = dict(os.environ, PYTHONPATH=str(broken))
    os.makedirs(_environment(tmp_path))
    assert _asked(tmp_path, _argv(_script(tmp_path, ECHO)), env=env) is None
    _refused(tmp_path)

    runtime_python.PythonRuntime(_ctx(tmp_path), "test", "3.11").record_install("anything", _environment(tmp_path))

    assert _held_against(tmp_path) == []


def test_a_zygote_retired_before_its_turn_never_starts(tmp_path, monkeypatch):
    """Retired while it waited for a slot -- by an install, which is what it waited behind: what it would import changed."""
    script = _script(tmp_path, ECHO)
    slots = sandbox_lock.ProcessSlots(1)
    monkeypatch.setattr(sandbox_lock, "process_slots", slots)

    with slots.slot():
        assert _asked(tmp_path, _argv(script)) is None
        waiting = _starting(tmp_path)
        sandbox_zygote.retire(_environment(tmp_path))
        # Twice is once.
        waiting.retire()

    assert waiting.ready.wait(120)
    assert (waiting.popen, waiting.usable, waiting.reason) == (None, False, "retired before it started")
    # Nor is it held against the environment: the next call has one of its own.
    p, _, _ = asyncio.run(_call(tmp_path, script))
    assert p.returncode == 0


def test_a_zygote_retired_while_it_imports_is_stopped(tmp_path, monkeypatch):
    """What it is importing nothing will use, and it has no child yet: there is nothing to wait for."""
    site = _site(tmp_path)
    (site / "slow_to_import.py").write_text("import time\ntime.sleep(120)\n")
    monkeypatch.setattr(sandbox_zygote, "PRELOAD", ("slow_to_import",))
    env = dict(os.environ, PYTHONPATH=str(site))

    importing = _start_held(tmp_path, monkeypatch, _argv(_script(tmp_path, ECHO)), env=env)
    deadline = time.monotonic() + 120
    while importing.popen is None:
        assert time.monotonic() < deadline, "the zygote was never started"
        time.sleep(0.05)
    sandbox_zygote.retire(_environment(tmp_path))

    assert importing.ready.wait(120)
    assert not importing.usable
    assert importing.popen.wait(60) == -signal.SIGKILL


def test_a_zygote_retired_as_it_becomes_ready_is_let_go_of(tmp_path, monkeypatch):
    """Ready, and retired before 'start' has said so: nothing will ever use it, so nothing may keep it."""
    original = sandbox_zygote.Zygote._start
    held = {}

    def _start(self):
        original(self)
        held["control"] = self.control
        # What an install does at this instant.
        sandbox_zygote.retire(self.environment)

    monkeypatch.setattr(sandbox_zygote.Zygote, "_start", _start)

    became = _start_held(tmp_path, monkeypatch, _argv(_script(tmp_path, ECHO)))

    assert became.ready.wait(120)
    # Let go of by 'start' once it is over: its control socket closed, and the process reaped.
    deadline = time.monotonic() + 60
    while held["control"].fileno() != -1 or became.popen.returncode is None:
        assert time.monotonic() < deadline, "the zygote was kept"
        time.sleep(0.05)
    assert not became.usable and became.reason is None


def test_a_zygote_whose_environment_cannot_be_locked_is_not_started(tmp_path):
    """The lock it imports under, which 'start' never reaches: a reason like any other."""

    class Unlockable:
        def acquire(self, write=False):
            raise RuntimeError("the lock is gone")

    assert _asked(tmp_path, _argv(_script(tmp_path, ECHO)), lock=Unlockable()) is None

    assert "the lock is gone" in _refused(tmp_path)[3]


def test_a_zygote_that_stops_answering_is_retired_and_the_call_started_the_ordinary_way(tmp_path, monkeypatch):
    """Stopped -- here by SIGSTOP; a zygote swapped out would do -- it is of no use to this call or the next."""
    monkeypatch.setattr(sandbox_zygote, "SPAWN_TIMEOUT", 1.0)
    script = _script(tmp_path, ECHO)

    async def calls():
        first, _, _ = await _call(tmp_path, script)
        stopped = _starting(tmp_path)
        os.kill(stopped.pid, signal.SIGSTOP)
        try:
            return stopped, await sandbox_zygote.process_async(
                _environment(tmp_path), _argv(script), 2, cwd=str(tmp_path)
            )
        finally:
            os.kill(stopped.pid, signal.SIGCONT)

    stopped, p = asyncio.run(calls())

    assert p is None
    assert stopped.retired and "did not answer a request" in stopped.reason
    assert stopped not in sandbox_zygote.zygotes()
    # Woken, it finds the request's caller gone, forks nothing, and goes.
    assert stopped.popen.wait(60) == 0


def test_a_call_with_no_directory_is_run_in_this_processs_own(tmp_path, monkeypatch):
    """As a fresh interpreter started without one would be -- and in none, when this process's own is gone."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    argv = _argv(_script(tmp_path, ECHO))

    async def calls():
        deadline = time.monotonic() + 120
        while True:
            p = await sandbox_zygote.process_async(_environment(tmp_path), argv, 2)
            if p is not None:
                break
            assert time.monotonic() < deadline, "no zygote to fork from"
            await asyncio.sleep(0.05)
        stdout, _ = await runtime.communicate(p, b"")
        work.rmdir()
        return stdout, await sandbox_zygote.process_async(_environment(tmp_path), argv, 2)

    stdout, gone = asyncio.run(calls())

    assert ("cwd=%s" % os.path.realpath(work)).encode() in stdout
    assert gone is None


def test_only_a_script_is_forked():
    assert sandbox_zygote.script_index(["python", "-sOOu", "/w/wrapper.py", "a"], FLAGS) == 2
    assert sandbox_zygote.script_index(["python", "-sOOu", "-m", "pip"], FLAGS) is None
    assert sandbox_zygote.script_index(["python", "-sOOu", "-c", "pass"], FLAGS) is None
    assert sandbox_zygote.script_index(["python", "-sOOIu", "/w/wrapper.py"], FLAGS) is None
    assert sandbox_zygote.script_index(["python", "-sOOu", "/w/node.mjs"], FLAGS) is None
    assert sandbox_zygote.script_index(["python", "-sOOu"], FLAGS) is None


# --------------------------------------------------------------------------- #
# Through the runtime                                                          #
# --------------------------------------------------------------------------- #


def _ctx(tmp_path, zygote=True):
    return types.SimpleNamespace(
        user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path), python_sandbox_zygote=zygote)
    )


@pytest.fixture
def one_slot(monkeypatch):
    slots = sandbox_lock.ProcessSlots(4)
    monkeypatch.setattr(sandbox_lock, "process_slots", slots)
    return slots


def _python_runtime(tmp_path, zygote=True):
    made = runtime_python.PythonRuntime(_ctx(tmp_path, zygote), "test", "3.11")
    made.exec_path = sys.executable
    made.provisioned = True
    made.python_flags = list(FLAGS)
    return made


PARENT = "import os, sys\nsys.stdin.read()\nprint(os.getppid())\n"


def _runtime_zygote(made, within=120):
    """The zygote of ``made``'s own environment, once it is ready."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        ready = [
            z
            for z in sandbox_zygote.zygotes()
            if z.environment == os.path.normpath(made.path) and z.ready.is_set() and z.usable
        ]
        if ready:
            return ready[0]
        time.sleep(0.05)
    raise AssertionError("no zygote for %s" % made.path)


@pytest.mark.parametrize("zygote", [True, False])
def test_the_python_runtime_forks_a_wrapper_where_it_may(tmp_path, one_slot, zygote):
    made = _python_runtime(tmp_path, zygote)
    script = _script(tmp_path, PARENT)

    # The first call is started the ordinary way, and starts a zygote for the
    # next: no call waits for one.
    exitcode, stdout, stderr = asyncio.run(made.run_async_onced([script], stdin="request"))
    assert exitcode == 0, stderr
    assert int(stdout) == os.getpid()

    if zygote:
        forked_from = _runtime_zygote(made).pid
        exitcode, stdout, stderr = asyncio.run(made.run_async_onced([script], stdin="request"))
        assert exitcode == 0, stderr
        assert int(stdout) == forked_from
    else:
        assert [z for z in sandbox_zygote.zygotes() if z.environment == os.path.normpath(made.path)] == []
    assert one_slot._in_use == 0


def test_the_python_runtime_describes_a_forked_crash_as_it_describes_any(tmp_path, one_slot):
    made = _python_runtime(tmp_path)
    script = _script(tmp_path, "import ctypes, sys\nsys.stdin.read()\nctypes.string_at(0)\n")
    asyncio.run(made.run_async_onced([_script(tmp_path, PARENT, name="warm.py")], stdin="request"))
    _runtime_zygote(made)

    exitcode, _, stderr = asyncio.run(made.run_async_onced([script], stdin="request"))

    assert exitcode == -signal.SIGSEGV
    assert "killed by signal %d (SIGSEGV)" % signal.SIGSEGV in stderr


def test_the_python_runtime_says_why_a_wrapper_went_with_its_zygote(tmp_path, one_slot):
    """Reported killed, which it was -- by its zygote going, which is the part worth saying."""
    made = _python_runtime(tmp_path)
    asyncio.run(made.run_async_onced([_script(tmp_path, PARENT, name="warm.py")], stdin="request"))
    _runtime_zygote(made)
    script = _script(
        tmp_path,
        "import os, signal, sys, time\nsys.stdin.read()\nos.kill(os.getppid(), signal.SIGKILL)\ntime.sleep(60)\n",
    )

    exitcode, _, stderr = asyncio.run(made.run_async_onced([script], stdin="request"))

    assert exitcode == -signal.SIGKILL
    assert "stopped while it ran, and took it along" in stderr


def test_a_sandbox_whose_interpreter_is_elsewhere_is_never_forked(tmp_path, one_slot, monkeypatch):
    made = _python_runtime(tmp_path)
    monkeypatch.setattr(made, "FORK_WRAPPERS", False)
    script = _script(tmp_path, PARENT)

    exitcode, stdout, _ = asyncio.run(made.run_async_onced([script], stdin="request"))

    assert exitcode == 0 and int(stdout) == os.getpid()


def test_nothing_is_left_behind(tmp_path):
    """No process and no descriptor outlives the zygote it came from, whatever its calls did."""
    import gc

    echo = _script(tmp_path, ECHO)
    crash = _script(tmp_path, "import ctypes\nctypes.string_at(0)\n", name="crash.py")
    sleeper = _script(tmp_path, SLEEPER, name="sleeper.py")
    before = {id(zygote) for zygote in sandbox_zygote.zygotes()}
    # What this worker had running already - another test's zygote waiting out
    # its idle time - is not this test's to answer for.
    children = {child.pid for child in psutil.Process().children(recursive=True)}
    descriptors = len(os.listdir("/proc/self/fd"))

    async def calls():
        await _call(tmp_path, echo)
        await _call(tmp_path, crash)
        with pytest.raises(asyncio.TimeoutError):
            await _call(tmp_path, sleeper, timeout=1)
        return _zygote_pid(tmp_path)

    zygote = asyncio.run(calls())
    _retire_started(before)
    gc.collect()

    assert _dead(zygote)
    assert [child for child in psutil.Process().children(recursive=True) if child.pid not in children] == []
    deadline = time.monotonic() + 30
    while len(os.listdir("/proc/self/fd")) > descriptors and time.monotonic() < deadline:
        # The reaper thread closes the zygote's log once it has waited for it.
        time.sleep(0.05)
    assert len(os.listdir("/proc/self/fd")) <= descriptors


def test_a_request_the_zygote_refuses_is_started_the_ordinary_way(tmp_path):
    """A missing script or directory is the error a fresh interpreter reports, so a fresh one has to report it."""
    script = _script(tmp_path, ECHO)

    async def calls():
        await _call(tmp_path, script)
        missing_script = await sandbox_zygote.process_async(
            _environment(tmp_path), _argv(str(tmp_path / "missing.py")), 2, cwd=str(tmp_path)
        )
        missing_directory = await sandbox_zygote.process_async(
            _environment(tmp_path), _argv(script), 2, cwd=str(tmp_path / "missing")
        )
        served = (await _call(tmp_path, script))[0]
        return missing_script, missing_directory, served

    missing_script, missing_directory, served = asyncio.run(calls())

    assert missing_script is None and missing_directory is None
    # A refusal is not a failure of the zygote.
    assert served.returncode == 0


# --------------------------------------------------------------------------- #
# The zygote's own pieces, in this process                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def zygote():
    """'wrappers/zygote.py' as a module of this process, not run: what it does in a child, done here."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("zygote_under_test", sandbox_zygote.SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_what_is_not_installed_is_passed_over(zygote):
    assert zygote._preload(["json", "partcad_zygote_no_such_module"]) == (["json"], ["partcad_zygote_no_such_module"])


def test_what_is_installed_and_broken_stops_the_preload(zygote, tmp_path, monkeypatch):
    """A dependency missing is not the module missing: what half-imported is not what a fresh import would be."""
    (tmp_path / "partcad_zygote_half_installed.py").write_text("import partcad_zygote_no_such_dependency\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ModuleNotFoundError):
        zygote._preload(["partcad_zygote_half_installed"])
    assert "partcad_zygote_half_installed" not in sys.modules


def test_a_message_with_too_many_descriptors_is_refused(zygote):
    import socket

    mine, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    descriptors = [os.dup(0) for _ in range(zygote.MAX_FDS + 1)]
    try:
        socket.send_fds(mine, [b"{}"], descriptors)
        with pytest.raises(ValueError):
            zygote._receive(theirs)
        mine.close()
        assert zygote._receive(theirs) == (None, [])
    finally:
        for fd in descriptors:
            os.close(fd)
        theirs.close()


def test_a_file_left_open_is_written_out(zygote, tmp_path):
    left_open = open(tmp_path / "left-open.txt", "w")
    left_open.write("buffered")

    zygote._flush_writers()

    assert (tmp_path / "left-open.txt").read_text() == "buffered"
    left_open.close()


def test_what_a_child_imported_is_released_the_way_shutdown_releases_it(zygote, monkeypatch):
    finalized = []

    class Finalized:
        def __del__(self):
            finalized.append(True)

    main, late, inherited = (types.ModuleType(name) for name in ("__main__", "late", "inherited"))
    main.kept = Finalized()
    late._private, late.public = object(), object()
    inherited.state = object()
    modules = {"__main__": main, "inherited": inherited, "late": late}
    monkeypatch.setattr(zygote, "sys", types.SimpleNamespace(modules=modules))
    still_held = late

    zygote._release({"__main__", "inherited"})

    assert finalized == [True]
    assert list(modules) == ["inherited"] and inherited.state is not None
    # Alive after the collection, so cleared as the interpreter clears one.
    assert still_held._private is None and still_held.public is None


@pytest.mark.parametrize(
    "body,expected",
    [
        ("pass\n", 0),
        ("import sys\nsys.exit()\n", 0),
        ("import sys\nsys.exit(4)\n", 4),
        ("import sys\nsys.exit('said')\n", 1),
        ("raise RuntimeError('raised')\n", 1),
        ("raise KeyboardInterrupt\n", -signal.SIGINT),
    ],
)
def test_how_a_script_ended_is_read_as_the_interpreter_reads_it(zygote, tmp_path, capsys, body, expected):
    script = _script(tmp_path, body)

    assert zygote._run(types.ModuleType("__main__"), script) == expected
    stderr = capsys.readouterr().err
    if expected == 1:
        assert "said" in stderr or "RuntimeError: raised" in stderr


def test_a_libc_that_cannot_be_loaded_is_no_prctl(zygote, monkeypatch):
    """A child is then not tied to its zygote's life, and is still reported as its socket says."""
    import ctypes

    with monkeypatch.context() as m:
        m.setattr(ctypes, "CDLL", _raises(OSError("no libc here")))
        prctl = zygote._libc_prctl()

    assert prctl is None


def test_without_proc_the_threads_are_the_interpreters_count(zygote, monkeypatch):
    """Native threads included where the kernel says; Python's own, where it cannot be asked."""
    import threading

    monkeypatch.setattr(zygote, "os", _System(listdir=_raises(FileNotFoundError("/proc/self/task"))))
    with monkeypatch.context() as m:
        m.setattr(threading, "active_count", lambda: 5)
        threads = zygote._threads()

    assert threads == 5


def test_settling_forks_once_and_waits_for_what_it_forked(zygote, monkeypatch):
    """In this process, with stand-ins for the fork: a pytest that forked would go on running the test twice."""
    exited = []

    def exit_(status):
        exited.append(status)
        raise SystemExit(status)

    monkeypatch.setattr(zygote, "_threads", lambda: 2)
    # A fork that fails leaves the threads where they were, and says so by counting them.
    monkeypatch.setattr(zygote, "os", _System(fork=_raises(OSError(errno.EAGAIN, "no fork"))))
    zygote._settle()
    # Its child goes at once, and does nothing else.
    monkeypatch.setattr(zygote, "os", _System(fork=lambda: 0, _exit=exit_))
    with pytest.raises(SystemExit):
        zygote._settle()
    assert exited == [0]
    # Its parent waits for it, and does not mind finding it reaped already.
    monkeypatch.setattr(zygote, "os", _System(fork=lambda: NO_SUCH_PID, waitpid=_raises(ChildProcessError())))
    zygote._settle()


def test_a_preload_that_takes_the_wrappers_off_the_path_itself_is_let_be(zygote, tmp_path, monkeypatch):
    """The wrappers' directory is on the path only while preloading, and what it imports may have moved it already."""
    import importlib

    (tmp_path / "partcad_zygote_path_taker.py").write_text("import sys\nsys.path.remove(%r)\n" % zygote.WRAPPERS)
    monkeypatch.setattr(sys, "path", [str(tmp_path)] + [entry for entry in sys.path if entry != zygote.WRAPPERS])
    importlib.invalidate_caches()

    try:
        assert zygote._preload(["partcad_zygote_path_taker"]) == (["partcad_zygote_path_taker"], [])
    finally:
        sys.modules.pop("partcad_zygote_path_taker", None)
    assert zygote.WRAPPERS not in sys.path


def test_the_two_ends_read_each_others_messages(zygote):
    """The runtime's half and the zygote's frame a message the same way, and pass a descriptor with one alike."""
    runtime_end, zygote_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    r, w = os.pipe()
    try:
        sandbox_zygote._send(runtime_end, {"asked": 1})
        assert zygote._receive(zygote_end) == ({"asked": 1}, [])

        zygote._send(zygote_end, {"pid": 7}, [w])
        message, fds = sandbox_zygote._receive(runtime_end)
        assert message == {"pid": 7} and len(fds) == 1
        # The same pipe, under another number.
        os.write(fds[0], b"through")
        os.close(fds[0])
        assert os.read(r, 7) == b"through"
    finally:
        os.close(r)
        os.close(w)
        runtime_end.close()
        zygote_end.close()


def test_an_empty_message_is_the_end_and_what_came_with_it_is_closed(zygote):
    """Nothing to read is the end of the stream, at either end; a descriptor sent with nothing is not kept."""
    for receive in (zygote._receive, sandbox_zygote._receive):
        mine, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        r, w = os.pipe()
        try:
            socket.send_fds(mine, [b""], [w])
            os.close(w)

            assert receive(theirs) == (None, [])
            # Every writing end of the pipe is closed, so its reader is at the end.
            os.set_blocking(r, False)
            assert os.read(r, 1) == b""
        finally:
            os.close(r)
            mine.close()
            theirs.close()


def test_closing_what_is_not_open_is_not_an_error(zygote):
    import resource

    soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    # No descriptor can be numbered past the limit.
    beyond = soft if 0 < soft < (1 << 30) else (1 << 30)

    zygote._close(beyond)
    sandbox_zygote._close(beyond)
    sandbox_zygote._close(None)


def test_a_stamp_is_the_same_at_both_ends(zygote, tmp_path):
    """The zygote stamps what it imports from before it starts, and the runtime compares that with what is there."""
    there, missing = tmp_path / "there", tmp_path / "missing"
    there.write_text("x")

    # As it travels: JSON, which has no tuples.
    sent = json.loads(json.dumps(zygote._stamps([str(there), str(missing)])))

    assert sent[1] == [str(missing), None]
    assert tuple(sandbox_zygote._as_stamp(stamp) for _, stamp in sent) == sandbox_zygote._stamp(
        [str(there), str(missing)]
    )


def test_what_cannot_be_said_does_not_change_how_a_script_ended(zygote, tmp_path, monkeypatch):
    """A message with nowhere to go, an excepthook that fails: the status is the interpreter's all the same."""
    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr(sys, "stderr", closed)
    monkeypatch.setattr(sys, "excepthook", _raises(RuntimeError("no hook")))

    assert zygote._run(types.ModuleType("__main__"), _script(tmp_path, "import sys\nsys.exit('unsaid')\n", "a.py")) == 1
    assert zygote._run(types.ModuleType("__main__"), _script(tmp_path, "raise ValueError('unshown')\n", "b.py")) == 1


def test_a_traceback_is_handed_on_starting_in_the_script(zygote, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "excepthook", zygote._without_this_frame(lambda kind, value, tb: seen.append((value, tb))))
    script = _script(tmp_path, "raise ValueError('here')\n")

    assert zygote._run(types.ModuleType("__main__"), script) == 1

    ((value, tb),) = seen
    assert tb.tb_frame.f_code.co_filename == script and value.__traceback__ is tb
    # Whatever it is handed: one that cannot take a traceback goes on as it is.
    seen.clear()
    sys.excepthook(ValueError, None, None)
    assert seen == [(None, None)]


@pytest.mark.parametrize("status,fails", [(3, False), (-signal.SIGINT, True)], ids=["exit", "interrupt"])
def test_a_child_ends_in_shutdowns_order_whatever_fails_on_the_way(zygote, monkeypatch, status, fails):
    """In this process, with stand-ins for whatever would end it or reach the interpreter's own state."""
    done = []

    def step(name, failing=False):
        def run(*args):
            done.append(name)
            if failing:
                raise RuntimeError(name)

        return run

    with monkeypatch.context() as m:
        m.setattr(
            zygote,
            "sys",
            types.SimpleNamespace(
                modules={"threading": types.SimpleNamespace(_shutdown=step("threads", fails))},
                stdout=types.SimpleNamespace(flush=step("stdout", fails)),
                stderr=types.SimpleNamespace(flush=step("stderr", fails)),
            ),
        )
        m.setitem(sys.modules, "atexit", types.SimpleNamespace(_run_exitfuncs=step("atexit", fails)))
        m.setattr(zygote, "_flush_writers", step("flush"))
        m.setattr(zygote, "_release", step("release", fails))
        m.setattr(
            zygote,
            "signal",
            types.SimpleNamespace(
                SIGINT=signal.SIGINT,
                SIG_DFL=signal.SIG_DFL,
                signal=lambda signum, handler: done.append(("handler", signum, handler)),
            ),
        )
        m.setattr(
            zygote,
            "os",
            _System(kill=lambda pid, signum: done.append(("kill", pid, signum)), _exit=lambda code: done.append(code)),
        )
        zygote._finish(status, {"inherited"})

    ended = ["threads", "atexit", "flush", "release", "stdout", "stderr"]
    if status == -signal.SIGINT:
        # By the signal itself, as an interpreter ends on an interrupt nothing caught.
        ended += [("handler", signal.SIGINT, signal.SIG_DFL), ("kill", os.getpid(), signal.SIGINT)]
    assert done == ended + [status & 0xFF]


def test_a_file_that_cannot_be_written_out_does_not_keep_the_others_from_it(zygote, tmp_path):
    class Unwritable(io.BufferedWriter):
        failing = True

        def flush(self):
            if self.failing:
                raise OSError(errno.ENOSPC, "No space left on device")
            super().flush()

    stuck = Unwritable(io.BytesIO())
    stuck.write(b"stuck")
    left_open = open(tmp_path / "left-open.txt", "w")
    left_open.write("buffered")
    try:
        zygote._flush_writers()

        assert (tmp_path / "left-open.txt").read_text() == "buffered"
    finally:
        stuck.failing = False
        stuck.close()
        left_open.close()


def test_a_module_blocked_or_gone_already_is_passed_over_on_release(zygote, monkeypatch):
    """'sys.modules' may hold None -- an import blocked on purpose -- and a module only it held is gone once dropped."""
    modules = {"inherited": types.ModuleType("inherited"), "blocked": None, "gone": types.ModuleType("gone")}
    monkeypatch.setattr(zygote, "sys", types.SimpleNamespace(modules=modules))

    zygote._release({"inherited"})

    assert list(modules) == ["inherited"]


# --------------------------------------------------------------------------- #
# The zygote's half of a request, in this process                             #
# --------------------------------------------------------------------------- #

# Past any 'pid_max': kill() and getpgid() of it fail, as they do for a child that is gone.
NO_SUCH_PID = 1 << 30


def _raises(error):
    def raising(*args, **kwargs):
        raise error

    return raising


class _System:
    """'os' as `wrappers/zygote.py` sees it, with whatever may not be done in this process for real done instead."""

    def __init__(self, **instead):
        self.__dict__.update(instead)

    def __getattr__(self, name):
        return getattr(os, name)


class _Parent:
    """A `_Zygote` in this process, and the runtime's end of its control socket.

    Nothing here may fork -- a fork of pytest would go on running the test --
    so its 'fork' fails unless a test says what it does instead.
    """

    def __init__(self, zygote, monkeypatch):
        self.system = _System(fork=_raises(AssertionError("forked in a test")))
        monkeypatch.setattr(zygote, "os", self.system)
        monkeypatch.setattr(zygote, "_threads", lambda: 1)
        self.control, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.zygote = zygote._Zygote(theirs, 0)
        # The runtime's ends of every request's standard streams: input, output, error.
        self.streams = []

    def ask(self, request, reply=None):
        """Send ``request`` as the runtime does, and have it answered; the runtime's end of its socket, if it has one."""
        mine, theirs = (None, reply) if reply is not None else socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        (stdin_r, stdin_w), (stdout_r, stdout_w), (stderr_r, stderr_w) = os.pipe(), os.pipe(), os.pipe()
        sandbox_zygote._send(self.control, request, [stdin_r, stdout_w, stderr_w, theirs.fileno()])
        for fd in (stdin_r, stdout_w, stderr_w):
            os.close(fd)
        theirs.close()
        self.streams = [stdin_w, stdout_r, stderr_r]
        assert self.zygote._request() is None
        return mine

    def output_closed(self):
        """Whether the zygote let go of the child's end of its standard output."""
        os.set_blocking(self.streams[1], False)
        try:
            return os.read(self.streams[1], 1) == b""
        except BlockingIOError:
            return False

    def close(self):
        self.zygote.selector.close()
        for sock in [self.zygote.control, self.control, *self.zygote.children.values()]:
            sock.close()
        for fd in [self.zygote.wake_r, self.zygote.wake_w, *self.streams]:
            os.close(fd)


@pytest.fixture
def parent(zygote, monkeypatch):
    made = _Parent(zygote, monkeypatch)
    yield made
    made.close()


def _request(tmp_path):
    script = _script(tmp_path, ECHO)
    return {"argv": [sys.executable, *FLAGS, script], "script": 1 + len(FLAGS), "cwd": str(tmp_path), "session": False}


def test_the_zygote_answers_with_the_childs_pid_and_pidfd_and_then_how_it_ended(parent, tmp_path):
    """Its half of the protocol, read by the runtime's half: what a `ZygoteProcess` is made from."""
    stand_in_r, stand_in_w = os.pipe()
    parent.system.fork = lambda: NO_SUCH_PID
    parent.system.pidfd_open = lambda pid: os.dup(stand_in_r)
    # A child it did not fork for a request comes first, and is not reported to anybody.
    reaped = iter([(NO_SUCH_PID + 1, 0), (NO_SUCH_PID, 3 << 8)])
    parent.system.waitpid = lambda pid, options: next(reaped)
    reply = None
    try:
        reply = parent.ask(_request(tmp_path))

        message, fds = sandbox_zygote._receive(reply)
        assert message == {"pid": NO_SUCH_PID} and len(fds) == 1
        os.write(stand_in_w, b"pidfd")
        assert os.read(fds[0], 5) == b"pidfd"
        os.close(fds[0])
        # The child's ends of its streams are the child's alone.
        assert parent.output_closed()

        parent.zygote._reap()

        assert sandbox_zygote._receive(reply) == ({"exit": 3}, [])
        assert sandbox_zygote._receive(reply) == (None, [])
        assert parent.zygote.children == {}
    finally:
        os.close(stand_in_r)
        os.close(stand_in_w)
        if reply is not None:
            reply.close()


def test_a_caller_that_gives_up_as_its_child_is_forked_has_the_child_killed(parent, tmp_path):
    """Gone before the pid could be sent to it: nobody is left to read what the child says, so it does not run on."""
    mine, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    killed = []

    def fork():
        mine.close()
        return NO_SUCH_PID

    def kill(pid, signum):
        killed.append((pid, signum))
        # No such process, as for a child that has died meanwhile.
        os.kill(pid, signum)

    parent.system.fork = fork
    parent.system.kill = kill
    parent.ask(_request(tmp_path), reply=theirs)
    assert NO_SUCH_PID in parent.zygote.children

    # What the loop does when that socket reads as closed.
    parent.zygote._caller_gone(NO_SUCH_PID)
    # Heard of again, as nothing makes it, or of a child it does not have: nothing changes.
    parent.zygote._caller_gone(NO_SUCH_PID)
    parent.zygote._caller_gone(NO_SUCH_PID + 1)

    assert killed == [(NO_SUCH_PID, signal.SIGKILL)] * 2
    # Reaped by the time it is waited for, as nothing makes it either: it waits for the next.
    parent.system.waitpid = _raises(ChildProcessError())
    parent.zygote._reap()
    assert NO_SUCH_PID in parent.zygote.children


@pytest.mark.parametrize("case", ["threads", "not-a-request", "no-fork", "caller-gone", "caller-unconnected"])
def test_a_request_that_cannot_be_forked_is_refused_saying_why(parent, zygote, tmp_path, monkeypatch, case):
    """Refused, the call is started the ordinary way; nothing of the request is kept, and the reason goes back."""
    request, reply, expected = _request(tmp_path), None, None
    if case == "threads":
        monkeypatch.setattr(zygote, "_threads", lambda: 2)
        expected = "this process has 2 threads"
    elif case == "not-a-request":
        request = {"argv": []}
        expected = "not a request"
    elif case == "no-fork":
        parent.system.fork = _raises(OSError(errno.EAGAIN, "Resource temporarily unavailable"))
        expected = "fork failed"
    elif case == "caller-gone":
        mine, reply = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        mine.close()
    else:
        # Not even connected: it cannot be asked whether it is still there.
        reply = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)

    mine = parent.ask(request, reply=reply)

    if mine is not None:
        try:
            message, _ = sandbox_zygote._receive(mine)
            assert expected in message["error"]
        finally:
            mine.close()
    assert parent.zygote.children == {}
    assert parent.output_closed()
    # A process with a thread in it forks nothing more, ever.
    assert parent.zygote.accepting == (case != "threads")


def test_what_is_not_a_request_on_the_control_socket_is_passed_over(parent, zygote):
    """Too many descriptors, or not the four a request comes with: dropped, closed, and the zygote serves on."""
    r, w = os.pipe()
    try:
        socket.send_fds(parent.control, [b"{}"], [w] * (zygote.MAX_FDS + 1))
        assert parent.zygote._request() is None
        socket.send_fds(parent.control, [b"{}"], [w])
        assert parent.zygote._request() is None
        os.close(w)
        w = None

        # Every copy it was sent is closed.
        os.set_blocking(r, False)
        assert os.read(r, 1) == b""
        assert parent.zygote.accepting
    finally:
        os.close(r)
        if w is not None:
            os.close(w)


# --------------------------------------------------------------------------- #
# The runtime's half of a child, in this process                               #
# --------------------------------------------------------------------------- #


class _Child:
    """A `ZygoteProcess` for no process at all: the zygote's end of its socket, and the far ends of its pipes."""

    def __init__(self, pidfd=None):
        loop = asyncio.get_running_loop()
        mine, self.zygote_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        mine.setblocking(False)
        (stdin_r, stdin_w), (stdout_r, stdout_w), (stderr_r, stderr_w) = os.pipe(), os.pipe(), os.pipe()
        self.far = [stdin_r, stdout_w, stderr_w]
        self.process = sandbox_zygote.ZygoteProcess(
            loop, NO_SUCH_PID, os.getpid(), pidfd, mine, stdin=stdin_w, stdout=stdout_r, stderr=stderr_r
        )

    def close(self):
        self.process.close_output()
        self.process._reply.close()
        self.zygote_end.close()
        for fd in self.far:
            os.close(fd)


async def _until(condition, within=30):
    deadline = time.monotonic() + within
    while not condition():
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)


def test_what_the_zygote_says_besides_how_the_child_ended_is_passed_over(zygote):
    """Read as it comes, and nothing but an exit status ends the child; a descriptor that came with it is not kept."""

    async def main():
        child = _Child()
        r, w = os.pipe()
        try:
            # Woken with nothing to read.
            child.process._on_reply()
            zygote._send(child.zygote_end, {"said": "something else"}, [w])
            os.close(w)
            # Nothing is ever written into the pipe: it reads once its last writer is closed.
            await _until(lambda: _is_readable(r))
            assert os.read(r, 1) == b""
            assert child.process.returncode is None

            zygote._send(child.zygote_end, {"exit": 3})
            assert await asyncio.wait_for(child.process.wait(), 30) == 3
            # Ended once: whatever says so after that changes nothing.
            child.process._end(0)
            child.process.send_signal(signal.SIGKILL)
            assert child.process.returncode == 3
        finally:
            os.close(r)
            child.close()

    asyncio.run(main())


def _is_readable(fd):
    import select

    return bool(select.select([fd], [], [], 0)[0])


@pytest.mark.parametrize("pidfd", [True, False], ids=["pidfd", "no-pidfd"])
def test_a_child_whose_zygote_answers_nonsense_is_reported_killed(zygote, pidfd):
    """A reply that cannot be read is no reply: the zygote is lost to the child, which went with it.

    With a pidfd the child is killed through it, and is over when the pidfd
    says so. A pipe stands in for one -- both read as ready once what they are
    of is over -- because pidfds are not to be had everywhere (a container's
    seccomp profile can refuse them), and this is about what is done with one.
    Without one, nothing can reach the child safely, and it is over at once.
    """

    async def main():
        stand_in_r, stand_in_w = os.pipe() if pidfd else (None, None)
        child = _Child(pidfd=stand_in_r)
        try:
            child.process.terminate()
            assert child.process.returncode is None
            child.zygote_end.send(b"not a message")
            await _until(lambda: child.process.zygote_lost)
            if pidfd:
                assert child.process.returncode is None
                # The child is gone.
                os.close(stand_in_w)
                stand_in_w = None
            assert await asyncio.wait_for(child.process.wait(), 30) == -signal.SIGKILL
        finally:
            if stand_in_w is not None:
                os.close(stand_in_w)
            child.close()

    asyncio.run(main())
