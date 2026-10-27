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
import os
import signal
import sys
import textwrap
import time
import types

import psutil
import pytest

from partcad import runtime, runtime_python, sandbox_lock, sandbox_zygote

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
    (zygote,) = [z for z in sandbox_zygote.zygotes() if z.environment == os.path.normpath(_environment(tmp_path))]
    return zygote.pid


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
    _settled(tmp_path)
    (refused,) = [entry for key, entry in sandbox_zygote._unusable.items() if key[0] == _environment(tmp_path)]
    assert "not today" in refused[3]
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
    _settled(tmp_path)
    (refused,) = [entry for key, entry in sandbox_zygote._unusable.items() if key[0] == _environment(tmp_path)]
    assert "threads" in refused[3]
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
    (site / "slow_to_import.py").write_text("import time\ntime.sleep(3)\n")
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
    # Generously short of the three seconds the zygote spends importing.
    assert took < 2.5
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
    assert psutil.Process().children(recursive=True) == []
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
