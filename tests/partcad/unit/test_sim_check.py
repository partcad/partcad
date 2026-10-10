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
simulation:
  stub:
    path: stub_sim.py
    format: stubfmt
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


def _equip(ctx, tmp_path, monkeypatch):
    """Give a context the stub's arrangements: a host 'sandbox', a cache and run directories of its own."""
    monkeypatch.setattr(ctx, "get_python_runtime", lambda *args, **kwargs: HostRuntime())
    ctx.cache_artifacts = Cache(
        "artifacts",
        types.SimpleNamespace(
            cache=True,
            internal_state_dir=str(tmp_path / "state"),
            cache_min_entry_size=100,
            cache_max_entry_size=10 * 1024 * 1024,
        ),
    )

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

    The one excuse the check has is the absence of a container runtime (see
    `ImplementationTest._verdict`). Left to the real answer, these tests would
    assert the strict contract on a machine with Docker and the lenient one on a
    machine without -- the same reason `test_cae_output.py` pins it.
    """
    monkeypatch.setattr(pc_runtime, "docker_available", lambda: True)


@pytest.fixture
def package(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    write_package(root)
    ctx = pc.Context(str(root))
    _equip(ctx, tmp_path, monkeypatch)
    return ctx


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


def _errors(caplog):
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


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
    # The verdict is the run's to remember, where the whole question is the key.
    assert test_ctx.get(Test.NOT_CACHEABLE) is True


def test_a_validation_that_does_not_hold_fails_naming_the_object_the_simulation_and_the_claim(
    package, monkeypatch, caplog
):
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        floats={"simulation": ":stub", "validation": 'after["bodies"]["block"]["pos"][2] > 50.0'},
    )
    with caplog.at_level(logging.ERROR):
        assert _check(package, part) is Test.TEST_FAILED

    (record,) = _errors(caplog)
    message = record.getMessage()
    assert "//sim:block" in message
    assert "'floats'" in message
    assert "does not hold" in message
    assert '["pos"][2] > 50.0' in message
    assert "pc sim --json" in message


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


def test_a_declaration_with_no_validation_passes_once_it_has_run_and_says_so(package, monkeypatch, caplog):
    """It states no condition, so running is the whole of what it asked."""
    part = _declare(package, monkeypatch, _part(package), runs={"simulation": ":stub"})
    with caplog.at_level(logging.INFO):
        assert _check(package, part) is Test.TEST_PASSED
    assert "running is all it was checked for" in caplog.text
    assert not _errors(caplog)


def test_a_plugin_that_does_not_deliver_fails_with_what_it_said(package, monkeypatch, caplog):
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        stays={"simulation": ":stub", "validation": "True", "params": {"explode": True}},
    )
    with caplog.at_level(logging.ERROR):
        assert _check(package, part) is Test.TEST_FAILED

    (record,) = _errors(caplog)
    message = record.getMessage()
    # The plugin's own sentence, which plugin was asked, and on what machine.
    assert "no physics here" in message
    assert "could not be run by //sim:stub" in message
    assert "platform:" in message


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
        third={"simulation": ":nosuch"},
    )
    with caplog.at_level(logging.ERROR):
        assert _check(package, part) is Test.TEST_FAILED
    messages = [record.getMessage() for record in _errors(caplog)]
    assert len(messages) == 2
    assert any("'first'" in message for message in messages)
    assert any("'third'" in message for message in messages)


# --------------------------------------------------------------------------- #
# The one excuse                                                              #
# --------------------------------------------------------------------------- #


def _no_container_runtime(ctx, monkeypatch):
    monkeypatch.setattr(pc_runtime, "docker_available", lambda: False)
    monkeypatch.setattr(ctx.user_config, "python_sandbox", "venv")


def test_no_container_runtime_is_a_skip_that_carries_the_report(package, monkeypatch, caplog):
    """The rule the `fea` and `cfd` checks follow, from the same code."""
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        stays={"simulation": ":stub", "validation": "True", "params": {"explode": True}},
    )
    _no_container_runtime(package, monkeypatch)

    test_ctx = {}
    with caplog.at_level(logging.DEBUG):
        assert _check(package, part, test_ctx) is Test.TEST_PASSED

    assert "Test skipped" in caplog.text
    assert "no physics here" in caplog.text
    assert "no container runtime on this machine" in caplog.text
    # 'pc' exits non-zero on any ERROR, so a skip must not have logged one --
    # including the one 'run_async' writes when it reports for itself.
    assert not _errors(caplog)
    assert test_ctx.get(Test.NOT_CACHEABLE) is True


def test_a_plugin_that_is_not_there_is_not_excused(package, monkeypatch, caplog):
    """A misspelt plugin is wrong on every machine; no runtime would have mended it."""
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":nosuch", "validation": "True"})
    _no_container_runtime(package, monkeypatch)
    with caplog.at_level(logging.ERROR):
        assert _check(package, part) is Test.TEST_FAILED


def test_a_validation_that_does_not_hold_is_not_excused(package, monkeypatch):
    """The run happened; what failed is the claim, which no machine changes."""
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":stub", "validation": "False"})
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


# --------------------------------------------------------------------------- #
# What is remembered                                                          #
# --------------------------------------------------------------------------- #


def test_declaring_a_simulation_is_a_new_question_for_the_verdict_cache(package, monkeypatch):
    """The "not applicable" pass is cached, and must not answer for a declared simulation."""
    bolt = _part(package, "bolt")
    before = asyncio.run(SimTest().cache_key_suffix(package, bolt))
    assert before == ""

    _declare(package, monkeypatch, bolt, holds={"simulation": ":stub", "validation": "True"})
    declared = asyncio.run(SimTest().cache_key_suffix(package, bolt))
    assert declared.startswith(".sim=")

    _declare(package, monkeypatch, bolt, holds={"simulation": ":stub", "validation": "False"})
    assert asyncio.run(SimTest().cache_key_suffix(package, bolt)) != declared


def test_editing_a_claim_does_not_move_the_objects_own_key():
    """`simulate:` says nothing about the geometry, so editing it rebuilds nothing.

    Otherwise every edit to a 'validation:' rebuilt the part, moved the key of
    the scene it is placed in, and ran the simulator again -- the one edit
    somebody writing the claim first makes over and over.
    """
    assert "simulate" in pc_shape._NON_GEOMETRIC_CONFIG_KEYS


def test_a_rerun_is_read_back_rather_than_simulated(package, monkeypatch):
    """`pc test` twice runs the simulator once: the run's own cache answers the second."""
    runs = []
    real = simulation._run_plugin_async

    async def counting(*args, **kwargs):
        runs.append(1)
        return await real(*args, **kwargs)

    monkeypatch.setattr(simulation, "_run_plugin_async", counting)
    part = _part(package)
    assert _check(package, part) is Test.TEST_PASSED
    assert _check(package, part) is Test.TEST_PASSED
    assert len(runs) == 1


# --------------------------------------------------------------------------- #
# `pc sim` is unchanged                                                       #
# --------------------------------------------------------------------------- #


def test_pc_sim_still_reports_for_itself(package, monkeypatch, caplog):
    """What `pc sim` prints is its verdict, and is what it always printed."""
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":stub", "validation": "False"})
    with caplog.at_level(logging.INFO):
        (result,) = asyncio.run(simulation.run_declared_async(package, part, "part"))
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


def test_the_check_leaves_the_saying_to_itself(package, monkeypatch, caplog):
    """Unreported, a run logs nothing above DEBUG: the check writes the one line."""
    part = _declare(package, monkeypatch, _part(package), stays={"simulation": ":stub", "validation": "False"})
    with caplog.at_level(logging.INFO):
        (result,) = asyncio.run(simulation.run_declared_async(package, part, "part", report=False))
    assert result.passed is False
    assert not [record for record in caplog.records if record.levelno >= logging.INFO]


def test_one_simulation_is_selected_by_name(package, monkeypatch):
    """`pc sim -f NAME`, through the loop the check shares."""
    part = _declare(
        package,
        monkeypatch,
        _part(package),
        first={"simulation": ":stub", "validation": "True"},
        second={"simulation": ":stub", "validation": "True"},
    )
    results = asyncio.run(simulation.run_declared_async(package, part, "part", "second"))
    assert [result.name for result in results] == ["second"]
