#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the `sim` check: `pc test` holds an object to its `simulate:`.

The simulator is a **stub plugin** -- a package of the test's own whose
`simulation:` script reports a fixed `before` and `after` -- and it is run for
real, through PartCAD's own `wrapper_simulate.py`, by the interpreter running
these tests. What is left out is only what would make each test a sandbox build:
the sandbox itself (a runtime that runs the wrapper with this interpreter stands
in for it) and the export of the scene (which would build the subject in a CAD
sandbox; the stub plugin never reads the scene it is handed). So no MuJoCo, no
CAD kernel run and no network, and everything the check decides is decided on
what a plugin really returned.
"""

import asyncio
import logging
import os
import sys
import types

import pytest

import partcad as pc
from partcad import runtime as pc_runtime
from partcad import shape as pc_shape
from partcad import simulation
from partcad.cache import Cache
from partcad.test.all import tests as all_tests
from partcad.test.sim import SimTest
from partcad.test.test import Test

# The stub simulator. Fixed numbers, as a real plugin would report them: where
# every body was before the world was switched on and where it was after. What
# it is asked to do differently comes in as a parameter of the run, the way a
# declaration's 'params:' reaches a real one.
STUB_SIMULATOR = """
def process(path, request):
    if request.get("explode"):
        raise RuntimeError("the stub simulator would not start: no physics here")
    return {
        "success": True,
        "before": {"bodies": {"block": {"pos": [0.0, 0.0, 10.0]}}},
        "after": {"bodies": {"block": {"pos": [0.0, 0.0, 9.9]}}},
        "simulator": "stub",
    }
"""

PACKAGE = """
name: //sim

# The plugin, declared exactly as 'partcad-sim-mujoco' declares MuJoCo: a script,
# and the format the scene is handed to it in, which this package writes too.
# 'boxed' is the same script declared the way 'partcad-sim-gazebo' declares
# Gazebo, naming the image that carries what pip cannot install.
simulation:
  stub:
    path: stub_sim.py
    format: stubfmt
  boxed:
    path: stub_sim.py
    format: stubfmt
    dockerImage: ghcr.io/example/simulator:1
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
        desc: Nothing moves
        simulation: :stub
        validation: after["bodies"]["block"]["pos"][2] > 5.0
  bolt:
    # Declares nothing, which is the ordinary case: the check passes it over.
    type: step
    path: cube.step
"""

HOLDS = 'after["bodies"]["block"]["pos"][2] > 5.0'
DOES_NOT_HOLD = 'after["bodies"]["block"]["pos"][2] > 50.0'


def write_package(root, text=PACKAGE):
    root.mkdir(parents=True, exist_ok=True)
    (root / "cube.step").write_text("ISO-10303-21; cube", encoding="utf-8")
    (root / "stub_sim.py").write_text(STUB_SIMULATOR, encoding="utf-8")
    (root / "write_scene.py").write_text("output = {'success': True}\n", encoding="utf-8")
    (root / "partcad.yaml").write_text(text, encoding="utf-8")


class HostRuntime:
    """A sandbox that is this interpreter: the wrapper runs, nothing is installed."""

    async def prepare_for_package(self, project, session=None):
        return None

    async def ensure_async(self, requirement, session=None):
        return None

    async def run_async(self, command, stdin="", cwd=None, session=None, timeout=None):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await process.communicate(stdin.encode("utf-8"))
        return process.returncode, out.decode("utf-8"), err.decode("utf-8")


def _cache(tmp_path, name):
    """A files-only cache of the test's own, so no test reads what another wrote."""
    return Cache(
        name,
        types.SimpleNamespace(
            cache=True,
            internal_state_dir=str(tmp_path / "state"),
            cache_min_entry_size=100,
            cache_max_entry_size=10 * 1024 * 1024,
        ),
    )


def _equip(ctx, tmp_path, monkeypatch):
    """Give a context the stub's arrangements: a host 'sandbox', caches and run directories of its own."""
    monkeypatch.setattr(ctx, "get_python_runtime", lambda *args, **kwargs: HostRuntime())
    ctx.cache_artifacts = _cache(tmp_path, "artifacts")
    ctx.cache_tests = _cache(tmp_path, "tests")

    async def export(_ctx, _scene, impl, directory):
        # Where the scene would be written, and nothing more: the stub reads none.
        path = os.path.join(directory, "scene.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("scene for %s" % impl.format_name)
        return path

    monkeypatch.setattr(simulation, "_export_scene_async", export)
    runs = tmp_path / "runs"
    monkeypatch.setattr(
        simulation,
        "run_directory",
        lambda _ctx, obj, name: str(runs / ("%s-%s" % (obj, name)).replace("/", "_").replace(":", "_")),
    )


@pytest.fixture(autouse=True)
def a_container_runtime(monkeypatch):
    """Every check below runs as if this machine had one, unless it says not to.

    The one excuse the check has turns on the absence of a container runtime
    (see `ImplementationTest._verdict`). Left to the real answer, these tests
    would assert the strict contract on a machine with Docker and the lenient
    one on a machine without -- the same reason `test_cae_output.py` pins it.
    """
    monkeypatch.setattr(pc_runtime, "docker_available", lambda: True)


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    write_package(root)
    ctx = pc.Context(str(root))
    _equip(ctx, tmp_path, monkeypatch)
    return ctx


@pytest.fixture
def plugin_runs(monkeypatch):
    """How many times the simulator itself was started."""
    runs = []
    real = simulation._run_plugin_async

    async def counting(*args, **kwargs):
        runs.append(1)
        return await real(*args, **kwargs)

    monkeypatch.setattr(simulation, "_run_plugin_async", counting)
    return runs


def _part(ctx, name="block"):
    return ctx.get_project("//sim").get_part(name)


def _declare(ctx, monkeypatch, part, **simulate):
    """Replace what the part declares, as an edit to its 'partcad.yaml' would."""
    config = dict(part.config)
    config["simulate"] = simulate
    monkeypatch.setattr(part, "config", config)
    return part


def _check(ctx, part, test_ctx=None):
    return asyncio.run(SimTest().test([], ctx, part, {} if test_ctx is None else test_ctx))


def _cached_check(ctx, part, test_ctx=None):
    """The check as `pc test` runs it: through the verdict cache."""
    return asyncio.run(SimTest().test_cached([], ctx, part, {} if test_ctx is None else test_ctx))


def _errors(caplog):
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


def _no_container_runtime(ctx, monkeypatch, sandbox="venv"):
    monkeypatch.setattr(pc_runtime, "docker_available", lambda: False)
    monkeypatch.setattr(ctx.user_config, "python_sandbox", sandbox)


# --------------------------------------------------------------------------- #
# Which objects it applies to                                                 #
# --------------------------------------------------------------------------- #


def test_pc_test_runs_it_as_sim():
    """`pc test -f sim` selects it -- and, `-f` being a prefix, only it."""
    names = [test.name for test in all_tests(4)]
    assert "sim" in names
    assert [name for name in names if name.startswith("sim")] == ["sim"]


def test_an_object_that_declares_nothing_is_passed_over_without_running_anything(package, monkeypatch):
    """A package of bolts pays nothing: no plugin is resolved, no scene is built."""

    async def no(*_args, **_kwargs):
        raise AssertionError("an object with no 'simulate:' must not be simulated")

    monkeypatch.setattr(simulation, "run_async", no)
    assert _check(package, _part(package, "bolt")) is Test.TEST_PASSED


def test_a_scene_is_not_a_subject():
    """A scene is an assembly to the class hierarchy, and the world a subject goes in to everything else."""
    assert simulation.subject_kind(types.SimpleNamespace(kind="scene")) is None
    assert simulation.subject_kind(types.SimpleNamespace(kind="sketch")) is None
    assert simulation.subject_kind(types.SimpleNamespace(kind="part")) == "part"
    assert simulation.subject_kind(types.SimpleNamespace(kind="assembly")) == "assembly"


# --------------------------------------------------------------------------- #
# The verdicts                                                                #
# --------------------------------------------------------------------------- #


def test_a_simulation_whose_validation_holds_passes(package, caplog):
    """The stub really ran: its 'after' is what the validation was evaluated over."""
    test_ctx = {}
    with caplog.at_level(logging.DEBUG):
        assert _check(package, _part(package), test_ctx) is Test.TEST_PASSED
    assert not _errors(caplog)
    # A verdict on a run that came back, with a key: remembered.
    assert Test.NOT_CACHEABLE not in test_ctx


def test_a_validation_that_does_not_hold_fails_naming_the_object_the_simulation_and_the_claim(
    package, monkeypatch, caplog
):
    part = _declare(package, monkeypatch, _part(package), floats={"simulation": ":stub", "validation": DOES_NOT_HOLD})
    test_ctx = {}
    with caplog.at_level(logging.ERROR):
        assert _check(package, part, test_ctx) is Test.TEST_FAILED

    (record,) = _errors(caplog)
    message = record.getMessage()
    assert "//sim:block" in message
    assert "'floats'" in message
    assert "does not hold" in message
    assert '["pos"][2] > 50.0' in message
    assert "pc sim --json" in message
    # A fact about the run, which is in the key: remembered too.
    assert Test.NOT_CACHEABLE not in test_ctx


def test_a_validation_that_raises_fails_with_what_it_raised(package, monkeypatch, caplog):
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        typo={"simulation": ":stub", "validation": 'after["bodies"]["nope"]["pos"][2] > 5.0'},
    )
    with caplog.at_level(logging.ERROR):
        assert _check(package, part) is Test.TEST_FAILED
    (record,) = _errors(caplog)
    assert "could not be evaluated: KeyError" in record.getMessage()


def test_a_plugin_that_does_not_deliver_fails_with_what_it_said(package, monkeypatch, caplog):
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        stays={"simulation": ":stub", "validation": "True", "params": {"explode": True}},
    )
    test_ctx = {}
    with caplog.at_level(logging.ERROR):
        assert _check(package, part, test_ctx) is Test.TEST_FAILED

    (record,) = _errors(caplog)
    message = record.getMessage()
    # The plugin's own sentence, which plugin was asked, and on what machine.
    assert "no physics here" in message
    assert "could not be run by //sim:stub" in message
    assert "platform:" in message
    # Possibly the machine's doing, which no key describes.
    assert test_ctx.get(Test.NOT_CACHEABLE) is True


def test_a_plugin_that_is_not_there_fails(package, monkeypatch, caplog):
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":nosuch", "validation": "True"})
    with caplog.at_level(logging.ERROR):
        assert _check(package, part) is Test.TEST_FAILED
    assert "declares no simulation 'nosuch'" in caplog.text


def test_a_declaration_that_names_no_plugin_fails_and_says_where_to_get_one(package, monkeypatch, caplog):
    part = _declare(package, monkeypatch, _part(package), stays={"validation": "True"})
    with caplog.at_level(logging.ERROR):
        assert _check(package, part) is Test.TEST_FAILED
    assert simulation.KNOWN_SIMULATION in caplog.text


def test_every_simulation_is_run_and_every_failure_reported(package, monkeypatch, caplog):
    """One broken claim does not hide the next: each is its own line."""
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        first={"simulation": ":stub", "validation": "False"},
        second={"simulation": ":stub", "validation": "True"},
        third={"simulation": ":nosuch", "validation": "True"},
    )
    with caplog.at_level(logging.ERROR):
        assert _check(package, part) is Test.TEST_FAILED
    messages = [record.getMessage() for record in _errors(caplog)]
    assert len(messages) == 2
    assert any("'first'" in message for message in messages)
    assert any("'third'" in message for message in messages)


# --------------------------------------------------------------------------- #
# A claim with no condition                                                   #
# --------------------------------------------------------------------------- #


def test_no_validation_is_a_skip_when_a_package_is_tested(package, monkeypatch, plugin_runs, caplog):
    """The rest of the package deserves its verdict; this one is said out loud and not run."""
    part = _declare(package, monkeypatch, _part(package), runs={"simulation": ":stub"})
    test_ctx = {}
    with caplog.at_level(logging.DEBUG):
        assert _check(package, part, test_ctx) is Test.TEST_PASSED

    assert "Test skipped" in caplog.text
    assert "states no 'validation'" in caplog.text
    # 'pc' exits non-zero on any ERROR, so a skip must not have logged one.
    assert not _errors(caplog)
    # Nothing to judge a run by, so nothing was run.
    assert plugin_runs == []
    # Its verdict turns on who asked, which the key does not carry.
    assert test_ctx.get(Test.NOT_CACHEABLE) is True


def test_no_validation_is_a_failure_when_the_object_is_tested_by_name(package, monkeypatch, plugin_runs, caplog):
    """`pc test <object>` asks whether it does what it says, and it says nothing."""
    part = _declare(package, monkeypatch, _part(package), runs={"simulation": ":stub"})
    test_ctx = {Test.NAMED: True}
    with caplog.at_level(logging.ERROR):
        assert _check(package, part, test_ctx) is Test.TEST_FAILED

    (record,) = _errors(caplog)
    assert "'runs' states no 'validation'" in record.getMessage()
    assert plugin_runs == []
    assert test_ctx.get(Test.NOT_CACHEABLE) is True


def test_a_claim_with_no_condition_does_not_hide_the_others(package, monkeypatch, caplog):
    """In a walk the skip is one line, and the claims that do state a condition are judged."""
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        unfinished={"simulation": ":stub"},
        stays={"simulation": ":stub", "validation": DOES_NOT_HOLD},
    )
    with caplog.at_level(logging.WARNING):
        assert _check(package, part) is Test.TEST_FAILED
    assert "Test skipped" in caplog.text
    assert "does not hold" in caplog.text


# --------------------------------------------------------------------------- #
# The one excuse                                                              #
# --------------------------------------------------------------------------- #


def test_no_container_runtime_is_a_skip_for_a_plugin_that_names_an_image(package, monkeypatch, caplog):
    """The rule the `fea` and `cfd` checks follow, from the same code."""
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        stays={"simulation": ":boxed", "validation": "True", "params": {"explode": True}},
    )
    _no_container_runtime(package, monkeypatch)

    test_ctx = {}
    with caplog.at_level(logging.DEBUG):
        assert _check(package, part, test_ctx) is Test.TEST_PASSED

    assert "Test skipped" in caplog.text
    assert "no physics here" in caplog.text
    assert "no container runtime on this machine" in caplog.text
    assert "ghcr.io/example/simulator:1" in caplog.text
    # 'pc' exits non-zero on any ERROR, so a skip must not have logged one --
    # including the one 'run_async' writes when it reports for itself.
    assert not _errors(caplog)
    assert test_ctx.get(Test.NOT_CACHEABLE) is True


def test_no_container_runtime_is_no_excuse_for_a_plugin_that_names_none(package, monkeypatch, caplog):
    """MuJoCo is a wheel. A plugin that said it runs in an ordinary sandbox and did not has failed."""
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        stays={"simulation": ":stub", "validation": "True", "params": {"explode": True}},
    )
    _no_container_runtime(package, monkeypatch)
    with caplog.at_level(logging.WARNING):
        assert _check(package, part) is Test.TEST_FAILED
    assert "Test skipped" not in caplog.text
    assert "no physics here" in caplog.text


def test_a_container_runtime_that_is_here_leaves_no_excuse(package, monkeypatch):
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        stays={"simulation": ":boxed", "validation": "True", "params": {"explode": True}},
    )
    assert _check(package, part) is Test.TEST_FAILED


def test_a_remote_sandbox_is_a_container_runtime(package, monkeypatch):
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        stays={"simulation": ":boxed", "validation": "True", "params": {"explode": True}},
    )
    _no_container_runtime(package, monkeypatch, sandbox="remote")
    assert _check(package, part) is Test.TEST_FAILED


def test_a_plugin_that_is_not_there_is_not_excused(package, monkeypatch, caplog):
    """A misspelt plugin is wrong on every machine; no runtime would have mended it."""
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":nosuch", "validation": "True"})
    _no_container_runtime(package, monkeypatch)
    with caplog.at_level(logging.ERROR):
        assert _check(package, part) is Test.TEST_FAILED


def test_a_validation_that_does_not_hold_is_not_excused(package, monkeypatch):
    """The run happened; what failed is the claim, which no machine changes."""
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":boxed", "validation": "False"})
    _no_container_runtime(package, monkeypatch)
    assert _check(package, part) is Test.TEST_FAILED


# --------------------------------------------------------------------------- #
# Where it is run from                                                        #
# --------------------------------------------------------------------------- #


def test_relative_names_resolve_from_the_package_that_declares_them(tmp_path, monkeypatch):
    """`pc test -P //...` runs with the tree's root current; the part is a package down.

    ':stub' in '//sub' is '//sub:stub'. Resolved against the current package it
    would be '//:stub', which the root does not declare.
    """
    root = tmp_path / "workspace"
    write_package(root / "sub", PACKAGE.replace("name: //sim\n", ""))
    (root / "partcad.yaml").write_text("dependencies:\n  sub:\n    path: sub\n", encoding="utf-8")
    ctx = pc.Context(str(root))
    _equip(ctx, tmp_path, monkeypatch)

    part = ctx.get_project("//sub").get_part("block")
    assert _check(ctx, part) is Test.TEST_PASSED


def test_an_object_reached_through_what_it_is_made_into_is_not_simulated_again(package, monkeypatch):
    """The manufacturability walk tests a part as something an assembly is procured from.

    Its own claims are checked where it is tested in its own right; run here
    too, each would run once per assembly using it, concurrently with its own
    run, in the one run directory a simulation of it has.
    """

    async def no(*_args, **_kwargs):
        raise AssertionError("a procured part is not simulated by the walk")

    monkeypatch.setattr(simulation, "run_async", no)
    test_ctx = {"force_manufacturing": True, "action_prefix": "//sim:stack"}
    assert _check(package, _part(package), test_ctx) is Test.TEST_PASSED
    assert test_ctx.get(Test.NOT_CACHEABLE) is True


def test_the_walk_is_kept_away_from_the_verdict_cache(package, monkeypatch):
    """Its key does not carry the flag, so the walk must neither read nor write it.

    Read, it would hand the walk the object's own verdict -- an assembly made
    unmanufacturable by a part that does not stand up. Written, its "nothing to
    say" would become the object's own pass.
    """
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":stub", "validation": "False"})
    assert _cached_check(package, part) is Test.TEST_FAILED

    walk = {"force_manufacturing": True, "action_prefix": "//sim:stack"}
    assert _cached_check(package, part, walk) is Test.TEST_PASSED
    # And the object's own verdict is still its own.
    assert _cached_check(package, part) is Test.TEST_FAILED


# --------------------------------------------------------------------------- #
# What is remembered                                                          #
# --------------------------------------------------------------------------- #


def test_a_remembered_failure_quotes_the_claim_that_failed(package, monkeypatch, caplog):
    """Read back from the cache, a failed validation still says which, and why."""
    part = _declare(package, monkeypatch, _part(package), floats={"simulation": ":stub", "validation": DOES_NOT_HOLD})
    assert _cached_check(package, part) is Test.TEST_FAILED

    async def no(*_args, **_kwargs):
        raise AssertionError("a remembered verdict is not worked out again")

    monkeypatch.setattr(simulation, "run_async", no)
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        assert _cached_check(package, part) is Test.TEST_FAILED
    (record,) = _errors(caplog)
    message = record.getMessage()
    assert "'floats' ran, and its 'validation' does not hold" in message
    assert '["pos"][2] > 50.0' in message
    assert "remembered from an earlier run" in message


def test_a_verdict_is_remembered(package, monkeypatch):
    """The second `pc test` asks the verdict cache and runs nothing at all."""
    part = _part(package)
    assert _cached_check(package, part) is Test.TEST_PASSED

    async def no(*_args, **_kwargs):
        raise AssertionError("a remembered verdict is not worked out again")

    monkeypatch.setattr(simulation, "run_async", no)
    assert _cached_check(package, part) is Test.TEST_PASSED


def test_editing_a_validation_re_judges_from_the_cached_run(package, monkeypatch, plugin_runs):
    """The claim is in the verdict's key and not in the run's: a new verdict, the same run."""
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":stub", "validation": HOLDS})
    assert _cached_check(package, part) is Test.TEST_PASSED

    _declare(package, monkeypatch, part, stays={"simulation": ":stub", "validation": DOES_NOT_HOLD})
    assert _cached_check(package, part) is Test.TEST_FAILED

    _declare(package, monkeypatch, part, stays={"simulation": ":stub", "validation": HOLDS})
    assert _cached_check(package, part) is Test.TEST_PASSED
    assert len(plugin_runs) == 1


def test_a_change_to_what_the_run_depends_on_is_a_new_verdict(package, monkeypatch, plugin_runs):
    """The plugin's script is outside the shape and the declaration, and inside the run's key."""
    part = _part(package)
    assert _cached_check(package, part) is Test.TEST_PASSED

    script = os.path.join(package.get_project("//sim").config_dir, "stub_sim.py")
    with open(script, "a", encoding="utf-8") as f:
        f.write("\n# A new release of the simulator.\n")
    assert _cached_check(package, part) is Test.TEST_PASSED
    assert len(plugin_runs) == 2


def test_what_was_not_judged_on_a_keyed_run_is_worked_out_again(package, monkeypatch, plugin_runs):
    """A plugin that did not deliver may have been the machine; it is asked again."""
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        stays={"simulation": ":stub", "validation": "True", "params": {"explode": True}},
    )
    assert _cached_check(package, part) is Test.TEST_FAILED
    assert _cached_check(package, part) is Test.TEST_FAILED
    assert len(plugin_runs) == 2


def test_a_skip_is_said_every_time(package, monkeypatch, caplog):
    """A remembered skip would come back as a silent pass."""
    part = _declare(package, monkeypatch, _part(package), runs={"simulation": ":stub"})
    _cached_check(package, part)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert _cached_check(package, part) is Test.TEST_PASSED
    assert "Test skipped" in caplog.text


def test_a_run_with_no_key_is_never_looked_up(package, monkeypatch):
    """Nothing is stored for it, and its key is one nothing could be found under."""

    async def unkeyed(*_args, **_kwargs):
        return None

    monkeypatch.setattr(simulation, "question_key_async", unkeyed)
    part = _part(package)
    first = asyncio.run(SimTest().cache_key_suffix(package, part))
    assert first != asyncio.run(SimTest().cache_key_suffix(package, part))


def test_the_verdict_key_follows_the_declarations(package, monkeypatch):
    bolt = _part(package, "bolt")
    assert asyncio.run(SimTest().cache_key_suffix(package, bolt)) == ""

    _declare(package, monkeypatch, bolt, holds={"simulation": ":stub", "validation": "True"})
    declared = asyncio.run(SimTest().cache_key_suffix(package, bolt))
    assert declared.startswith(".sim=")
    assert asyncio.run(SimTest().cache_key_suffix(package, bolt)) == declared

    _declare(package, monkeypatch, bolt, holds={"simulation": ":stub", "validation": "False"})
    assert asyncio.run(SimTest().cache_key_suffix(package, bolt)) != declared


def test_the_verdict_key_carries_the_run_the_artifact_cache_is_asked_with(package, plugin_runs):
    """One key for the run, worked out in one place, so the two cannot disagree."""
    part = _part(package)
    (declaration,) = simulation.of_shape(part)
    result = asyncio.run(simulation.run_async(package, part, "part", declaration, report=False))
    assert result.artifact_key is not None
    assert asyncio.run(simulation.question_key_async(package, part, "part", declaration)) == result.artifact_key


def test_editing_a_claim_does_not_move_the_objects_own_key():
    """`simulate:` says nothing about the geometry, so editing it rebuilds nothing.

    Otherwise every edit to a 'validation:' rebuilt the part, moved the key of
    the scene it is placed in, and ran the simulator again -- the one edit
    somebody writing the claim first makes over and over.
    """
    assert "simulate" in pc_shape._NON_GEOMETRIC_CONFIG_KEYS


def test_a_rerun_is_read_back_rather_than_simulated(package, plugin_runs):
    """Worked out again, a verdict is still judged on the cached run."""
    part = _part(package)
    assert _check(package, part) is Test.TEST_PASSED
    assert _check(package, part) is Test.TEST_PASSED
    assert len(plugin_runs) == 1


# --------------------------------------------------------------------------- #
# `pc sim` is unchanged                                                       #
# --------------------------------------------------------------------------- #


def test_pc_sim_still_reports_for_itself(package, monkeypatch, caplog):
    """What `pc sim` prints is its verdict, and is what it always printed."""
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":stub", "validation": "False"})
    (declaration,) = simulation.of_shape(part)
    with caplog.at_level(logging.INFO):
        result = asyncio.run(simulation.run_async(package, part, "part", declaration))
    assert result.failed
    assert "the simulation 'stays' did not validate" in caplog.text
    assert _errors(caplog)
    # And nothing new in what '--json' prints.
    assert set(result.to_dict()) == {
        "object",
        "simulation",
        "scene",
        "plugin",
        "validation",
        "passed",
        "error",
        "result",
    }


def test_pc_sim_still_runs_a_declaration_with_no_validation(package, monkeypatch, plugin_runs):
    """There it is how somebody looks at what a plugin reports before writing the condition."""
    part = _declare(package, monkeypatch, _part(package), runs={"simulation": ":stub"})
    (declaration,) = simulation.of_shape(part)
    result = asyncio.run(simulation.run_async(package, part, "part", declaration))
    assert result.passed is None
    assert not result.failed
    assert result.result["simulator"] == "stub"
    assert len(plugin_runs) == 1


def test_the_check_leaves_the_saying_to_itself(package, monkeypatch, caplog):
    """Unreported, a run logs nothing above DEBUG: the check writes the one line."""
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":stub", "validation": "False"})
    (declaration,) = simulation.of_shape(part)
    with caplog.at_level(logging.INFO):
        result = asyncio.run(simulation.run_async(package, part, "part", declaration, report=False))
    assert result.passed is False
    assert not [record for record in caplog.records if record.levelno >= logging.INFO]
