#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The safety nets under a simulation run, each proven by a plugin that needs it.

A simulation plugin is somebody else's program driving somebody else's engine,
and it can go wrong in every way a program can: it can hang, it can die, it can
answer with something that is not an answer, and it can leave a process behind
that keeps the run open after it has returned. Each of those is a **stub plugin**
here, run for real through PartCAD's own 'wrapper_simulate.py' by this
interpreter, through the same bounded spawn and the same 'communicate' every
sandbox uses -- so what is proven is the code that runs, with budgets of a second
or two so that each test takes seconds. Those are for the runs that are meant to
run out of time; a run that is meant to end some other way is given room, so
that a busy runner cannot turn its crash into a timeout.

What is left out is what would make every test a sandbox build, as in
'test_sim_check.py': the sandbox (a runtime that is this interpreter) and the
export of the scene (the stubs never read it).
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
import textwrap
import time
import types

import psutil
import pytest

import partcad as pc
from partcad import runtime as pc_runtime
from partcad import simulation
from partcad.cache import Cache
from partcad.test.sim import SimTest
from partcad.test.test import Test
from partcad_utils.user_config import UserConfig

POSIX = os.name != "nt"

# Every stub, by what it does. Each writes the process ids of whatever it
# started into the run directory ('path'), so that a test can look for them
# afterwards: a net that stops the run and leaves its children running has
# moved the leak rather than closed it.
STUB = textwrap.dedent("""
    import os
    import signal
    import subprocess
    import sys
    import time

    def remember(path, process):
        with open(os.path.join(path, "started.txt"), "a") as f:
            f.write("%d\\n" % process.pid)

    def sleeper():
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])

    def answer():
        return {
            "success": True,
            "before": {"bodies": {"block": {"pos": [0.0, 0.0, 10.0]}}},
            "after": {"bodies": {"block": {"pos": [0.0, 0.0, 9.9]}}},
        }

    def process(path, request):
        how = request.get("how")
        if how == "hang":
            # A simulator that waits for an engine that never answers, with the
            # engine running beside it.
            remember(path, sleeper())
            time.sleep(600)
        if how == "freeze":
            # Wedged so that nothing in this process can act: what an
            # interpreter held in native code looks like from the outside.
            remember(path, sleeper())
            os.kill(os.getpid(), signal.SIGSTOP)
        if how == "exit":
            for line in range(200):
                sys.stderr.write("chatter %d\\n" % line)
            sys.stderr.write("the engine refused the model\\n")
            sys.stderr.flush()
            os._exit(3)
        if how == "signal":
            sys.stderr.write("about to fault\\n")
            sys.stderr.flush()
            import resource

            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # a crash, without a core file
            os.kill(os.getpid(), signal.SIGSEGV)
            time.sleep(10)
        if how == "silent":
            os._exit(0)
        if how == "garbage":
            import wrapper_common

            os.write(wrapper_common._response_fd or 1, b"<html>not a result</html>")
            os._exit(0)
        if how == "leave":
            # Answers, and leaves a process behind holding standard error open.
            remember(path, sleeper())
        return answer()
    """)

PACKAGE = """
name: //sim

simulation:
  stub:
    path: stub_sim.py
    format: stubfmt
    duration: 10.0
  patient:
    path: stub_sim.py
    format: stubfmt
    timeout: 7
export:
  stubfmt:
    path: write_scene.py
    extension: txt

parts:
  block:
    type: step
    path: cube.step
    simulate:
      stays:
        simulation: :stub
        validation: after["bodies"]["block"]["pos"][2] > 5.0
"""


class HostRuntime:
    """A sandbox that is this interpreter, spawned and bounded the way every sandbox is."""

    def get_session(self, name):
        # What a caller asks for beyond the base goes into a layer; nothing
        # is installed here, so there is no layer to name.
        return None

    async def prepare_for_package(self, project, session=None):
        return None

    async def ensure_async(self, requirement, session=None):
        return None

    async def run_async(self, command, stdin="", cwd=None, session=None, timeout=None):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **pc_runtime.bounded_spawn_options(timeout),
        )
        out, err = await pc_runtime.communicate(process, stdin.encode("utf-8"), timeout)
        return process.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _cache(tmp_path, name):
    return Cache(
        name,
        types.SimpleNamespace(
            cache=True,
            internal_state_dir=str(tmp_path / "state"),
            cache_min_entry_size=1,
            cache_max_entry_size=10 * 1024 * 1024,
        ),
    )


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "cube.step").write_text("ISO-10303-21; cube", encoding="utf-8")
    (root / "stub_sim.py").write_text(STUB, encoding="utf-8")
    (root / "write_scene.py").write_text("output = {'success': True}\n", encoding="utf-8")
    (root / "partcad.yaml").write_text(PACKAGE, encoding="utf-8")
    ctx = pc.Context(str(root))
    monkeypatch.setattr(ctx, "get_python_runtime", lambda *args, **kwargs: HostRuntime())
    monkeypatch.setattr(ctx.user_config, "simulation_timeout", None)
    monkeypatch.setattr(pc_runtime, "docker_available", lambda: True)
    ctx.cache_artifacts = _cache(tmp_path, "artifacts")
    ctx.cache_tests = _cache(tmp_path, "tests")

    async def export(_ctx, _scene, impl, directory):
        path = os.path.join(directory, "scene.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("scene for %s" % impl.format_name)
        return path

    monkeypatch.setattr(simulation, "_export_scene_async", export)
    runs = tmp_path / "runs"
    monkeypatch.setattr(simulation, "run_directory", lambda _ctx, obj, name: _made(runs / name))
    return ctx


def _made(path):
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _part(ctx):
    return ctx.get_project("//sim").get_part("block")


def _run(ctx, how, timeout=30.0, plugin=":stub"):
    """One run of the stub, told 'how' to misbehave, under a budget of 'timeout' seconds.

    The default is for a run that is meant to end before its budget does -- by
    answering, crashing, or saying something that is not an answer. A second
    and a half was enough for that on an idle machine and not on a loaded one,
    where the interpreter alone can take most of it to start, and a run that
    ran out of time instead failed the test for the wrong reason. A test of the
    budget itself passes a short one.
    """
    part = _part(ctx)
    (declaration,) = simulation.of_shape(part)
    declaration.simulation = plugin
    declaration.params = {"how": how, "timeout": timeout}
    started = time.monotonic()
    result = asyncio.run(simulation.run_async(ctx, part, "part", declaration, report=False))
    return result, time.monotonic() - started


def _started(tmp_path):
    listed = tmp_path / "runs" / "stays" / "started.txt"
    if not listed.exists():
        return []
    return [int(line) for line in listed.read_text().split()]


def _gone(pid, within=15.0):
    """Whether 'pid' is no longer running (a zombie nobody reaped counts as gone)."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


def _tree_script(pids):
    """A process that starts one of its own, writes that one's pid to 'pids', and waits."""
    return (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        f"open({str(pids)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(600)\n"
    )


# --------------------------------------------------------------------------- #
# The budget                                                                  #
# --------------------------------------------------------------------------- #


def _budget(ctx, plugin=":stub", **params):
    part = _part(ctx)
    (declaration,) = simulation.of_shape(part)
    declaration.simulation = plugin
    declaration.params = params
    impl = simulation.resolve_plugin(ctx, "//sim", plugin)
    return simulation.run_budget(ctx, impl, declaration)


def test_a_run_nothing_bounds_gets_five_minutes(package):
    budget, source = _budget(package)

    assert budget == simulation.DEFAULT_TIMEOUT == 300.0
    assert "default" in source


def test_a_long_run_gets_a_budget_that_grows_with_it(package):
    """Ten wall-clock seconds for every simulated one, once that is more than five minutes."""
    assert _budget(package, duration=100.0)[0] == 1000.0
    assert _budget(package, duration=20.0)[0] == 300.0


def test_a_plugin_states_how_long_its_engine_takes(package):
    budget, source = _budget(package, plugin=":patient")

    assert budget == 7.0
    assert "plugin" in source


def test_a_simulation_states_how_long_it_takes_over_its_plugin(package):
    budget, source = _budget(package, plugin=":patient", timeout=12)

    assert budget == 12.0
    assert "params" in source


def test_this_machine_s_configuration_is_over_everything(package, monkeypatch):
    """The one knob for somebody who cannot edit the package -- a slow machine, a CI job."""
    monkeypatch.setattr(package.user_config, "simulation_timeout", 45.0)

    budget, source = _budget(package, plugin=":patient", timeout=12)

    assert budget == 45.0
    assert "PC_SIMULATION_TIMEOUT" in source


@pytest.mark.parametrize("nonsense", [0, -5, "soon", True, float("inf"), None])
def test_a_budget_that_is_not_one_is_passed_over_rather_than_switching_the_bound_off(package, nonsense):
    assert _budget(package, timeout=nonsense)[0] == 300.0


def test_the_machine_s_budget_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("PC_SIMULATION_TIMEOUT", "90")
    assert UserConfig().simulation_timeout == 90.0
    assert UserConfig().to_dict()["simulation.timeout"] == "90"

    for nonsense in ("0", "-1", "soon"):
        monkeypatch.setenv("PC_SIMULATION_TIMEOUT", nonsense)
        assert UserConfig().simulation_timeout is None


def test_the_plugin_is_handed_the_budget_it_is_held_to(package, monkeypatch):
    seen = {}

    async def run_async(command, stdin="", cwd=None, session=None, timeout=None):
        seen["request"] = stdin
        seen["timeout"] = timeout
        return 0, '{"success": true, "before": {}, "after": {}}', ""

    monkeypatch.setattr(HostRuntime, "run_async", staticmethod(run_async))
    _run(package, "answer", timeout=4)

    assert '"timeout": 4' in seen["request"]
    # PartCAD's own bound is the budget and the grace beside it: the wrapper is
    # the one that stops the run on time.
    assert seen["timeout"] == 4 + simulation.TIMEOUT_GRACE


def _keys(ctx, **params):
    part = _part(ctx)
    (declaration,) = simulation.of_shape(part)
    declaration.params = params
    run = asyncio.run(simulation.question_key_async(ctx, part, "part", declaration))
    verdict = asyncio.run(SimTest().cache_key_suffix(ctx, _declared(part, params)))
    return run, verdict


def _declared(part, params):
    """The part, declaring its simulation with 'params', as an edit to 'partcad.yaml' would."""
    config = dict(part.config)
    stays = dict(config["simulate"]["stays"], params=params)
    config["simulate"] = {"stays": stays}
    part.config = config
    return part


def test_a_budget_is_in_no_key_so_giving_a_run_longer_runs_nothing_again(package):
    """A budget bounds a run and does not change its answer."""
    short, long_ = _keys(package, timeout=5), _keys(package, timeout=500)
    none = _keys(package)

    assert short[0] is not None
    assert short == long_ == none
    assert _keys(package, duration=5.0) != none  # what does change the answer does change the key


# --------------------------------------------------------------------------- #
# A run that does not finish                                                  #
# --------------------------------------------------------------------------- #


def test_a_plugin_that_hangs_is_stopped_on_its_budget_with_everything_it_started(package, tmp_path):
    result, took = _run(package, "hang", timeout=1.5)

    assert isinstance(result.exception, simulation.SimulationTimeout)
    # The wrapper's own watchdog, not PartCAD's bound a 'TIMEOUT_GRACE' later.
    assert took < 25
    message = result.error
    assert message.startswith("timed out after 1.5 s")
    assert "//sim:stub" in message  # the plugin
    assert "budget of 1.5 s" in message  # the budget
    assert "'params:'" in message  # what set it
    assert "PC_SIMULATION_TIMEOUT" in message  # and how to raise it
    (child,) = _started(tmp_path)
    assert _gone(child), "the engine the plugin started outlived the run"


@pytest.mark.skipif(not POSIX, reason="SIGSTOP is how a process is frozen here; Windows has no such signal")
def test_a_run_too_wedged_to_stop_itself_is_killed_from_outside_with_its_children(package, tmp_path, monkeypatch):
    """The wrapper's own watchdog cannot act in a process that is not running at
    all; PartCAD's bound, a grace period later, kills the process group."""
    monkeypatch.setattr(simulation, "TIMEOUT_GRACE", 1.0)

    result, took = _run(package, "freeze", timeout=1.0)

    assert isinstance(result.exception, simulation.SimulationTimeout)
    assert took < 60
    assert "killed it, with everything it started" in result.error
    (child,) = _started(tmp_path)
    assert _gone(child)


# --------------------------------------------------------------------------- #
# A plugin that ends without an answer                                        #
# --------------------------------------------------------------------------- #


def test_a_plugin_that_exits_non_zero_fails_with_the_end_of_what_it_said(package):
    result, took = _run(package, "exit")

    assert isinstance(result.exception, simulation.SimulationCrash)
    assert took < 15
    assert "exit code 3" in result.error
    assert "the engine refused the model" in result.error
    # The end, not all of it: a crash report is read, not scrolled.
    assert "chatter 0\n" not in result.error
    assert result.error.count("chatter") < simulation.STDERR_TAIL_LINES


@pytest.mark.skipif(not POSIX, reason="a signal death is how POSIX reports a crash")
def test_a_plugin_that_crashes_is_reported_as_killed_by_its_signal(package):
    result, _ = _run(package, "signal")

    assert isinstance(result.exception, simulation.SimulationCrash)
    assert "SIGSEGV" in result.error
    assert "about to fault" in result.error


def test_a_plugin_that_exits_without_answering_fails_saying_so(package):
    result, _ = _run(package, "silent")

    assert isinstance(result.exception, simulation.SimulationCrash)
    assert "produced no result" in result.error


def test_a_plugin_that_answers_with_something_else_fails_quoting_it(package):
    result, _ = _run(package, "garbage")

    assert isinstance(result.exception, simulation.SimulationCrash)
    assert "not a result" in result.error
    assert "<html>not a result</html>" in result.error


def test_an_answer_that_is_not_an_object_is_not_one(package, monkeypatch):
    async def run_async(command, stdin="", cwd=None, session=None, timeout=None):
        return 0, "[1, 2, 3]", ""

    monkeypatch.setattr(HostRuntime, "run_async", staticmethod(run_async))
    result, _ = _run(package, "answer")

    assert isinstance(result.exception, simulation.SimulationCrash)
    assert "rather than an object" in result.error


@pytest.mark.skipif(not POSIX, reason="leftover processes are found through /proc or ps")
def test_what_a_plugin_leaves_running_does_not_hold_the_run_open(package, tmp_path):
    """The process it left behind holds standard error, so the run would last
    as long as it does -- ten minutes here -- if the wrapper did not stop it."""
    result, took = _run(package, "leave", timeout=60)

    assert result.error is None
    assert result.passed is True
    assert took < 15
    (child,) = _started(tmp_path)
    assert _gone(child)


# --------------------------------------------------------------------------- #
# What becomes of them                                                        #
# --------------------------------------------------------------------------- #


def test_neither_a_timeout_nor_a_crash_is_cached_and_an_answer_is(package, monkeypatch):
    """#753 caches only a run that answered. Installing an engine, or giving a
    run longer, changes no key -- so a cached failure would be served forever."""
    stored = []
    real = simulation.cache_artifacts.store_async

    async def spy(cache, hash, result, files=None, directory=None):
        stored.append(result)
        return await real(cache, hash, result, files=files, directory=directory)

    monkeypatch.setattr(simulation.cache_artifacts, "store_async", spy)

    for how in ("hang", "exit", "garbage"):
        result, _ = _run(package, how, timeout=1.0)
        assert result.error is not None and result.artifact_key is not None
    assert stored == []

    result, _ = _run(package, "answer")
    assert result.passed is True
    assert len(stored) == 1


# A short budget for the run that is meant to run out of it, and room for the one
# that is meant to crash before it does (see '_run').
@pytest.mark.parametrize("how, budget, kind", [("hang", 1.5, "timed out after"), ("exit", 30.0, "exit code 3")])
def test_pc_test_fails_a_run_that_did_not_deliver_and_says_why(package, monkeypatch, caplog, how, budget, kind):
    part = _part(package)
    config = dict(part.config)
    config["simulate"] = {
        "stays": {
            "simulation": ":stub",
            "params": {"how": how, "timeout": budget},
            "validation": 'after["bodies"]["block"]["pos"][2] > 5.0',
        }
    }
    monkeypatch.setattr(part, "config", config)
    test_ctx = {}

    with caplog.at_level(logging.ERROR):
        verdict = asyncio.run(SimTest().test([], package, part, test_ctx))

    assert verdict == Test.TEST_FAILED
    assert test_ctx.get(Test.NOT_CACHEABLE) is True
    report = "\n".join(record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR)
    assert "//sim:block" in report and "'stays'" in report and "//sim:stub" in report
    assert kind in report


def test_a_wedged_process_tree_is_killed_whole(tmp_path):
    """'communicate' on its own, as every bounded sandbox run uses it."""
    pids = tmp_path / "pids"
    script = _tree_script(pids)

    async def main():
        p = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **pc_runtime.bounded_spawn_options(1.0),
        )
        deadline = time.monotonic() + 10
        while not pids.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await pc_runtime.communicate(p, b"", timeout=1.0)
        await asyncio.wait_for(p.wait(), 10)

    asyncio.run(main())
    assert _gone(int(pids.read_text()))


@pytest.mark.skipif(not POSIX, reason="what blocks the loop here is a waitpid on a stopped child, a POSIX notion")
def test_the_bound_holds_when_the_event_loop_itself_is_held_up(monkeypatch, tmp_path):
    """What macOS's child watcher does to a stopped child: blocks the loop's own thread.

    Here the loop is held by a blocking wait on the child in a callback, the
    way 'waitpid' holds it there, so wait_for's timer cannot fire; the backstop
    thread has to kill the child for anything to happen at all.
    """
    monkeypatch.setattr(pc_runtime, "BACKSTOP", 0.5)
    pids = tmp_path / "pids"
    script = _tree_script(pids)

    async def main():
        p = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **pc_runtime.bounded_spawn_options(0.5),
        )
        deadline = time.monotonic() + 10
        while not pids.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        # Polled rather than waited for, which would reap the child under the
        # loop's own watcher; held either way until something kills it.
        asyncio.get_running_loop().call_later(0.1, _gone, p.pid, 30.0)
        started = time.monotonic()
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await pc_runtime.communicate(p, b"", timeout=0.5)
        await asyncio.wait_for(p.wait(), 10)
        return time.monotonic() - started

    took = asyncio.run(main())
    assert took < 10
    assert _gone(int(pids.read_text()))


@pytest.mark.skipif(not POSIX, reason="what blocks the loop here is a waitpid on a stopped child, a POSIX notion")
def test_the_backstop_asks_for_the_run_again_when_it_could_not_be_had_at_the_start(monkeypatch):
    monkeypatch.setattr(pc_runtime, "BACKSTOP", 0.5)
    real = pc_runtime.process_owner
    asked = []

    def first_time_nothing(p):
        asked.append(p.pid)
        return None if len(asked) == 1 else real(p)

    monkeypatch.setattr(pc_runtime, "process_owner", first_time_nothing)

    async def main():
        p = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(600)",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **pc_runtime.bounded_spawn_options(0.5),
        )
        asyncio.get_running_loop().call_later(0.1, _gone, p.pid, 30.0)
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await pc_runtime.communicate(p, b"", timeout=0.5)
        await asyncio.wait_for(p.wait(), 10)

    started = time.monotonic()
    asyncio.run(main())
    assert time.monotonic() - started < 10
    assert len(asked) >= 2


@pytest.mark.skipif(not POSIX, reason="a reused process group id is a POSIX notion")
def test_a_kill_that_finds_its_run_gone_spares_whatever_has_its_number_now():
    """A reaped run's pid, and the group id it led, can be handed to anything.

    Stood in for here by a process leading a group of its own under the run's
    number, and an owner that says the run it was taken from is gone.
    """
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True)
    try:
        run = types.SimpleNamespace(pid=other.pid, returncode=None)
        gone = types.SimpleNamespace(is_running=lambda: False)
        pc_runtime.kill_process_tree(run, from_thread=True, owner=gone)
        pc_runtime.kill_process_tree(run, owner=gone)
        assert not _gone(other.pid, within=0.5)
    finally:
        other.kill()
        other.wait(10)


def test_an_unbounded_run_is_started_as_it_always_was():
    assert pc_runtime.bounded_spawn_options(None) == {}
    assert pc_runtime.bounded_spawn_options(5) != {}


@pytest.mark.skipif(not POSIX, reason="a process group is a POSIX notion")
def test_killing_a_tree_never_kills_the_group_it_did_not_start():
    """An unbounded run shares PartCAD's own process group; that one is not its to kill."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    try:
        pc_runtime.kill_process_tree(p)
        p.wait(10)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == -signal.SIGKILL
    # And this process, in the group the child was in, is still here to say so.


# --------------------------------------------------------------------------- #
# The wrapper's own pieces, in this process                                   #
#                                                                             #
# What the stubs above prove through a subprocess, measured here too: the     #
# wrapper runs in a sandbox interpreter that coverage does not follow.        #
# --------------------------------------------------------------------------- #


def _wrappers(monkeypatch):
    from partcad import wrapper as pc_wrapper

    monkeypatch.syspath_prepend(os.path.dirname(pc_wrapper.get("simulate.py")))
    import process_tree
    import wrapper_simulate

    return process_tree, wrapper_simulate


# A process that starts one that will not stop when asked, and reports its id.
STUBBORN = (
    "import signal, subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', "
    "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print(1, flush=True); time.sleep(600)'],"
    " stdout=subprocess.PIPE)\n"
    "child.stdout.readline()\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(600)\n"
)


@pytest.fixture
def stubborn():
    parent = subprocess.Popen([sys.executable, "-c", STUBBORN], stdout=subprocess.PIPE, start_new_session=POSIX)
    child = int(parent.stdout.readline())
    yield parent, child
    parent.kill()
    parent.wait(10)
    try:
        os.kill(child, signal.SIGKILL)
    except OSError:
        pass


@pytest.mark.skipif(not POSIX, reason="a process tree is listed through /proc or ps")
@pytest.mark.parametrize("listing", ["proc", "ps"])
def test_what_a_process_started_is_found_however_processes_are_listed(monkeypatch, stubborn, listing):
    process_tree, _ = _wrappers(monkeypatch)
    parent, child = stubborn
    if listing == "ps":
        monkeypatch.setattr(process_tree.os.path, "isdir", lambda _path: False)

    assert child in process_tree.started_by(parent.pid)
    assert parent.pid not in process_tree.started_by(parent.pid)


@pytest.mark.skipif(not POSIX, reason="a process tree is listed through /proc or ps")
def test_what_will_not_stop_when_asked_is_killed_and_the_one_that_started_it_is_spared(monkeypatch, stubborn):
    process_tree, _ = _wrappers(monkeypatch)
    parent, child = stubborn

    assert process_tree.stop_started(grace=0.3, root=parent.pid) == 1

    assert _gone(child)
    assert parent.poll() is None
    assert process_tree.stop_started(grace=0.3, root=parent.pid) == 0


def test_processes_that_cannot_be_listed_are_not_guessed_at(monkeypatch):
    process_tree, _ = _wrappers(monkeypatch)
    monkeypatch.setattr(process_tree.os.path, "isdir", lambda _path: False)

    def refuse(*_args, **_kwargs):
        raise OSError("no ps here")

    monkeypatch.setattr(process_tree.subprocess, "run", refuse)

    assert process_tree.started_by() is None
    if POSIX:
        assert process_tree.stop_started() == 0


@pytest.mark.skipif(not POSIX, reason="a process group is a POSIX notion")
def test_the_wrapper_leads_a_group_unless_it_leads_one_already(monkeypatch):
    process_tree, _ = _wrappers(monkeypatch)
    calls = []
    monkeypatch.setattr(process_tree.os, "setpgid", lambda *args: calls.append(args))

    monkeypatch.setattr(process_tree.os, "getpgid", lambda _pid: os.getpid())
    process_tree.lead_a_group()
    assert calls == []

    monkeypatch.setattr(process_tree.os, "getpgid", lambda _pid: 1)
    process_tree.lead_a_group()
    assert calls == [(0, 0)]

    def refuse(*_args):
        raise PermissionError("a session leader may not move")

    monkeypatch.setattr(process_tree.os, "setpgid", refuse)
    process_tree.lead_a_group()  # and says nothing


def test_stopping_everything_exits_with_the_status_asked_for_whatever_stopping_did(monkeypatch):
    process_tree, _ = _wrappers(monkeypatch)

    def leave(code):
        raise SystemExit(code)

    def broken(*_args, **_kwargs):
        raise RuntimeError("could not list anything")

    monkeypatch.setattr(process_tree.os, "_exit", leave)
    monkeypatch.setattr(process_tree, "stop_started", broken)
    monkeypatch.setattr(process_tree.subprocess, "run", broken)
    monkeypatch.setattr(process_tree.time, "sleep", lambda _seconds: None)

    with pytest.raises(SystemExit) as left:
        process_tree.stop_everything(124)
    assert left.value.code == 124


def test_a_windows_wrapper_whose_taskkill_came_back_stays_for_partcad_to_stop_its_tree(monkeypatch, capsys):
    """taskkill takes the wrapper too, so returning at all means the tree is still there."""
    process_tree, _ = _wrappers(monkeypatch)
    waited = []

    def leave(code):
        raise SystemExit(code)

    monkeypatch.setattr(process_tree.os, "name", "nt")
    monkeypatch.setattr(process_tree.os, "_exit", leave)
    monkeypatch.setattr(process_tree.subprocess, "run", lambda *_a, **_k: subprocess.CompletedProcess([], 128))
    monkeypatch.setattr(process_tree.time, "sleep", waited.append)

    with pytest.raises(SystemExit) as left:
        process_tree.stop_everything(124)
    assert left.value.code == 124
    assert waited == [process_tree.OUTLAST]
    assert "exit status 128" in capsys.readouterr().err


@pytest.mark.parametrize(
    "value, budget", [(5, 5.0), ("2.5", 2.5), (0, None), (-1, None), (True, None), ("soon", None), (None, None)]
)
def test_the_wrapper_reads_the_budget_it_is_handed(monkeypatch, value, budget):
    _, wrapper_simulate = _wrappers(monkeypatch)
    assert wrapper_simulate.budget_of({"timeout": value}) == budget
    assert wrapper_simulate.budget_of(None) is None


def test_the_wrapper_answers_once_whoever_answers_first(monkeypatch):
    _, wrapper_simulate = _wrappers(monkeypatch)
    written = []
    monkeypatch.setattr(wrapper_simulate.wrapper_common, "handle_output", written.append)
    answer = wrapper_simulate.Answer()

    assert answer.give({"success": True}) is True
    assert answer.give({"success": False}) is False
    assert written == [{"success": True}]


def test_the_watchdog_answers_for_a_run_whose_budget_is_spent_and_stops_it(monkeypatch):
    process_tree, wrapper_simulate = _wrappers(monkeypatch)
    written, stopped = [], []
    monkeypatch.setattr(wrapper_simulate.wrapper_common, "handle_output", written.append)
    monkeypatch.setattr(process_tree, "stop_everything", stopped.append)

    timer = wrapper_simulate.watch(0.05, wrapper_simulate.Answer())
    timer.join(5)

    (said,) = written
    assert said["success"] is False and said["timed_out"] == 0.05
    assert stopped == [wrapper_simulate.TIMED_OUT_EXIT] == [124]


@pytest.mark.parametrize("scripted", [True, False])
def test_the_wrapper_runs_the_request_it_is_handed_and_cleans_up_after_it(monkeypatch, tmp_path, scripted):
    process_tree, wrapper_simulate = _wrappers(monkeypatch)
    script = tmp_path / "plugin.py"
    script.write_text(STUB, encoding="utf-8")
    request = {"how": "answer", "timeout": 60, "scene_file": str(tmp_path / "scene.txt")}
    # On the command line, after the two arguments 'handle_input' reads: a
    # sandbox that sends files rewrites an argument, and not the request.
    argv = ["wrapper_simulate.py", str(tmp_path), str(tmp_path)] + ([str(script)] if scripted else [])
    monkeypatch.setattr(sys, "argv", argv)
    written, done = [], []
    monkeypatch.setattr(wrapper_simulate.wrapper_common, "handle_input", lambda decode: (str(tmp_path), request))
    monkeypatch.setattr(wrapper_simulate.wrapper_common, "handle_output", written.append)
    monkeypatch.setattr(process_tree, "lead_a_group", lambda: done.append("led"))
    monkeypatch.setattr(process_tree, "stop_started", lambda: done.append("stopped"))

    wrapper_simulate.main()

    (said,) = written
    assert said["success"] is scripted
    assert done == ["led", "stopped"]


def test_a_tree_with_no_process_or_none_left_is_nothing_to_kill():
    pc_runtime.kill_process_tree(types.SimpleNamespace())
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait(10)
    pc_runtime.kill_process_tree(gone)
    assert pc_runtime.process_owner(types.SimpleNamespace()) is None
    assert pc_runtime.process_owner(gone) is None
    assert pc_runtime.process_owner(types.SimpleNamespace(pid=gone.pid, returncode=None)) is None
    # Running, but somebody else's: what a reused pid would be.
    assert pc_runtime.process_owner(types.SimpleNamespace(pid=os.getppid(), returncode=None)) is None
    alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    try:
        assert pc_runtime.process_owner(alive).pid == alive.pid
    finally:
        alive.kill()
        alive.wait(10)


def test_only_the_end_of_a_long_stderr_is_carried():
    assert simulation.stderr_tail("") == ""
    tail = simulation.stderr_tail("x" * (simulation.STDERR_TAIL_CHARACTERS * 2))
    assert tail.startswith("...\n") and len(tail) == simulation.STDERR_TAIL_CHARACTERS + 4


def test_a_plugin_that_failed_writing_something_else_fails_on_how_it_ended(package, monkeypatch):
    async def run_async(command, stdin="", cwd=None, session=None, timeout=None):
        return 1, "Traceback (most recent call last):", "the wrapper could not write its answer"

    monkeypatch.setattr(HostRuntime, "run_async", staticmethod(run_async))
    result, _ = _run(package, "answer")

    assert isinstance(result.exception, simulation.SimulationCrash)
    assert "exit code 1" in result.error
    assert "could not write its answer" in result.error
