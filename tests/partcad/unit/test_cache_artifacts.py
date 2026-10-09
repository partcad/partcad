#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for caching what an analysis or a simulation produced.

`partcad.cache_artifacts` on its own first - what goes into an entry, what comes
back out, and what is refused - and then the two places that use it: a second
`pc cae` of an unchanged part and a second `pc simulate` of an unchanged object
must be reads, with the files back where the caller expects them, and anything
that changes the question must be a run.

No solver, no simulator and no sandbox: the implementation is stubbed where it
would be started, and counted.
"""

import asyncio
import io
import os
import tarfile
import textwrap
import types

import pytest

import partcad as pc
from partcad import cache_artifacts, cae, simulation
from partcad.cache import Cache
from partcad.cache_backend import ARTIFACT_KEY
from partcad.cache_hash import CacheHash


def _cache(tmp_path, max_size=10 * 1024 * 1024, min_size=100) -> Cache:
    """A files-only cache of its own, so no test reads what another one wrote."""
    config = types.SimpleNamespace(
        cache=True,
        internal_state_dir=str(tmp_path / "state"),
        cache_min_entry_size=min_size,
        cache_max_entry_size=max_size,
    )
    return Cache("artifacts", config)


def _hash(text="question") -> CacheHash:
    return cache_artifacts.question_hash("//pkg:obj#fea", "subject-key", {"question": text})


def _run(coroutine):
    return asyncio.run(coroutine)


# --------------------------------------------------------------------------- #
# The key                                                                     #
# --------------------------------------------------------------------------- #


def test_a_subject_with_no_key_has_no_question():
    """`cache: false` on an object means nothing derived from it is cached."""
    assert cache_artifacts.question_hash("x", None, {"a": 1}) is None
    assert cache_artifacts.question_hash("x", "", {"a": 1}) is None


def test_the_key_follows_the_subject_the_question_and_the_scripts(tmp_path):
    script = tmp_path / "solve.py"
    script.write_text("v = 1\n")

    def key(subject="s", question=None, files=(str(script),)):
        return cache_artifacts.question_hash("x", subject, question or {"load": 5}, files).get()

    first = key()
    assert key() == first
    assert key(subject="t") != first
    assert key(question={"load": 6}) != first
    script.write_text("v = 2\n")
    assert key() != first


# --------------------------------------------------------------------------- #
# What is stored and what comes back                                          #
# --------------------------------------------------------------------------- #


def test_a_file_comes_back_by_role_wherever_it_is_asked_for(tmp_path):
    cache = _cache(tmp_path)
    model = tmp_path / "first" / "bracket.fea.vtu"
    model.parent.mkdir()
    model.write_bytes(b"<VTKFile/>" * 50)
    result = {"success": True, "findings": [{"message": "too thin"}]}

    assert _run(cache_artifacts.store_async(cache, _hash(), result, files={"model": str(model)}))

    elsewhere = tmp_path / "second" / "out.vtu"
    restored = _run(cache_artifacts.restore_async(cache, _hash(), files={"model": str(elsewhere)}))
    assert restored == result
    assert elsewhere.read_bytes() == model.read_bytes()


def test_a_directory_comes_back_with_the_result_pointing_into_it(tmp_path):
    """Read on another machine through a shared tier, the paths must be that machine's."""
    cache = _cache(tmp_path)
    first = tmp_path / "run-a"
    (first / "meshes").mkdir(parents=True)
    (first / "scene.xml").write_text("<mujoco/>")
    (first / "meshes" / "block.stl").write_bytes(b"solid\n" * 40)
    result = {"before": {}, "after": {}, "trajectory": str(first / "trajectory.csv")}
    (first / "trajectory.csv").write_text("t,z\n0,10\n")

    assert _run(cache_artifacts.store_async(cache, _hash(), result, directory=str(first)))

    second = tmp_path / "run-b"
    second.mkdir()
    restored = _run(cache_artifacts.restore_async(cache, _hash(), directory=str(second)))
    assert restored["trajectory"] == str(second / "trajectory.csv")
    assert (second / "scene.xml").read_text() == "<mujoco/>"
    assert (second / "meshes" / "block.stl").read_bytes() == b"solid\n" * 40
    assert (second / "trajectory.csv").read_text() == "t,z\n0,10\n"


def test_a_miss_is_none(tmp_path):
    assert _run(cache_artifacts.restore_async(_cache(tmp_path), _hash(), files={"model": "x"})) is None


def test_no_key_and_no_cache_are_both_a_quiet_no(tmp_path):
    cache = _cache(tmp_path)
    assert not _run(cache_artifacts.store_async(cache, None, {}))
    assert _run(cache_artifacts.restore_async(cache, None)) is None
    assert not _run(cache_artifacts.store_async(None, _hash(), {}))
    assert _run(cache_artifacts.restore_async(None, _hash())) is None


def test_an_entry_missing_a_file_the_caller_needs_is_a_miss(tmp_path):
    """A result whose model went missing is worse than running again."""
    cache = _cache(tmp_path)
    assert _run(cache_artifacts.store_async(cache, _hash(), {"success": True}))

    target = tmp_path / "model.vtu"
    assert _run(cache_artifacts.restore_async(cache, _hash(), files={"model": str(target)})) is None
    assert not target.exists()


def _entry(members: dict) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@pytest.mark.parametrize("name", ["directory/../escaped.txt", "directory//etc/escaped.txt"])
def test_an_entry_that_would_write_outside_the_directory_is_refused(tmp_path, name):
    """Shared tiers are written by other people: nothing lands outside the run."""
    cache = _cache(tmp_path)
    data = _entry({"result.json": b"{}", name: b"gotcha"})
    assert _run(cache.write_data_async(_hash(), {ARTIFACT_KEY: data}))[ARTIFACT_KEY]

    directory = tmp_path / "run"
    directory.mkdir()
    assert _run(cache_artifacts.restore_async(cache, _hash(), directory=str(directory))) is None
    assert not (tmp_path / "escaped.txt").exists()
    assert os.listdir(directory) == []


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="needs POSIX symbolic links")
@pytest.mark.parametrize("link", ["meshes", "meshes/block.stl"])
def test_a_link_already_in_the_directory_does_not_carry_a_write_out_of_it(tmp_path, link):
    """The member name is checked as a name; what is on disk is checked as well."""
    cache = _cache(tmp_path)
    first = tmp_path / "run-a"
    (first / "meshes").mkdir(parents=True)
    (first / "meshes" / "block.stl").write_bytes(b"solid\n" * 40)
    assert _run(cache_artifacts.store_async(cache, _hash(), {"before": {}}, directory=str(first)))

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "block.stl").write_text("keep me")
    second = tmp_path / "run-b"
    # The link is either the directory the file goes in or the file itself.
    (second / link).parent.mkdir(parents=True)
    os.symlink(outside / os.path.relpath(link, "meshes") if link != "meshes" else outside, second / link)

    assert _run(cache_artifacts.restore_async(cache, _hash(), directory=str(second))) is None
    assert (outside / "block.stl").read_text() == "keep me"


def test_garbage_under_the_key_is_a_miss(tmp_path):
    cache = _cache(tmp_path)
    _run(cache.write_data_async(_hash(), {ARTIFACT_KEY: b"not a tarball at all" * 10}))
    assert _run(cache_artifacts.restore_async(cache, _hash())) is None


# --------------------------------------------------------------------------- #
# Size windows                                                                #
# --------------------------------------------------------------------------- #


def test_no_answer_is_too_small_to_keep(tmp_path):
    """The minimum keeps trivial geometry out; a solver's answer is never trivial."""
    cache = _cache(tmp_path, min_size=1024 * 1024)
    assert _run(cache_artifacts.store_async(cache, _hash(), {"success": True, "findings": []}))
    assert _run(cache_artifacts.restore_async(cache, _hash())) == {"success": True, "findings": []}


def test_an_answer_too_big_for_every_tier_is_not_stored(tmp_path):
    cache = _cache(tmp_path, max_size=1024)
    model = tmp_path / "model.vtu"
    model.write_bytes(os.urandom(64 * 1024))

    assert not _run(cache_artifacts.store_async(cache, _hash(), {}, files={"model": str(model)}))
    assert _run(cache_artifacts.restore_async(cache, _hash(), files={"model": str(model)})) is None


# --------------------------------------------------------------------------- #
# `pc cae`                                                                    #
# --------------------------------------------------------------------------- #

PACKAGE = textwrap.dedent("""
    name: //cae-cache
    parts:
      bracket:
        type: step
        path: bracket.step
        fea:
          fix:
            - m3-screw
          load:
            hook: 5 kg
    cae:
      fea:
        path: solve.py
        extension: vtu
    """)


@pytest.fixture
def analysed(tmp_path, monkeypatch):
    """A part whose analysis is a counter: the model it writes says which run it was."""
    root = tmp_path / "package"
    root.mkdir()
    (root / "partcad.yaml").write_text(PACKAGE)
    (root / "solve.py").write_text("def process(path, request):\n    return {'success': True}\n")
    (root / "bracket.step").write_text("ISO-10303-21; bracket")
    ctx = pc.Context(str(root))
    monkeypatch.setattr(ctx.user_config, "cae_fea_implementation", "//cae-cache:fea")
    ctx.cache_artifacts = _cache(tmp_path)

    part = ctx.get_part("//cae-cache:bracket")
    runs = []

    async def get_wrapped(_ctx):
        return {"brep": b"geometry"}

    async def boundary(_ctx, _config):
        return [{"interface": "m3-screw", "role": "fix", "location": [[0, 0, 0], [0, 0, 1], 0]}]

    async def run(_ctx, _impl, _script, request, final_filepath):
        runs.append(request)
        with open(final_filepath, "w") as f:
            f.write("run %d" % len(runs))
        if request.get("fail"):
            return {"success": False, "exception": "ccx: not found"}
        return {"success": True, "findings": [{"message": "yield exceeded"}], "warnings": ["coarse mesh"]}

    monkeypatch.setattr(part, "get_wrapped", get_wrapped)
    monkeypatch.setattr(part, "_analysis_boundary_async", boundary)
    monkeypatch.setattr(part, "_run_implementation_async", run)
    return ctx, part, runs, root


def test_the_same_analysis_twice_runs_the_solver_once(analysed, tmp_path):
    ctx, part, runs, _root = analysed

    first = _run(part.analyze_async(ctx, cae.FEA))
    os.remove(first["filepath"])
    second = _run(part.analyze_async(ctx, cae.FEA, output_dir=str(tmp_path / "elsewhere")))

    assert len(runs) == 1
    assert second["findings"] == first["findings"]
    # Back where *this* call asked for it, and the model the run wrote.
    assert second["filepath"] != first["filepath"]
    with open(second["filepath"]) as f:
        assert f.read() == "run 1"


def test_another_question_is_another_run(analysed):
    ctx, part, runs, root = analysed

    _run(part.analyze_async(ctx, cae.FEA))
    _run(part.analyze_async(ctx, cae.FEA, mesh_size=2.0))
    assert len(runs) == 2

    # The solver changed: the question is asked again.
    (root / "solve.py").write_text("def process(path, request):\n    return {'success': True, 'v': 2}\n")
    _run(part.analyze_async(ctx, cae.FEA))
    assert len(runs) == 3


def test_a_failed_analysis_is_not_remembered(analysed):
    """Installing the solver changes no key, so a remembered failure would outlive its reason."""
    ctx, part, runs, _root = analysed

    for _ in range(2):
        with pytest.raises(cae.CaeFailed):
            _run(part.analyze_async(ctx, cae.FEA, fail=True))
    assert len(runs) == 2


def test_a_part_that_is_not_cached_is_analysed_every_time(analysed, monkeypatch):
    ctx, part, runs, _root = analysed
    monkeypatch.setattr(part, "cacheable", False)

    _run(part.analyze_async(ctx, cae.FEA))
    _run(part.analyze_async(ctx, cae.FEA))
    assert len(runs) == 2


# --------------------------------------------------------------------------- #
# `pc simulate`                                                               #
# --------------------------------------------------------------------------- #


@pytest.fixture
def simulated(tmp_path, monkeypatch):
    """An object with one simulation, whose plugin is a counter that writes an artifact."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "cube.step").write_text("ISO-10303-21; cube", encoding="utf-8")
    (root / "run_it.py").write_text("output = {'success': True}\n", encoding="utf-8")
    (root / "write_it.py").write_text("output = {'success': True}\n", encoding="utf-8")
    (root / "partcad.yaml").write_text(
        "name: //sim\n"
        "simulation:\n  toy:\n    path: run_it.py\n    format: toyfmt\n"
        "export:\n  toyfmt:\n    path: write_it.py\n    extension: tf\n"
        "parts:\n"
        "  block:\n"
        "    type: step\n"
        "    path: cube.step\n"
        "    simulate:\n"
        "      stands:\n"
        "        simulation: //sim:toy\n"
        "        validation: after['z'] > 5.0\n",
        encoding="utf-8",
    )
    ctx = pc.Context(str(root))
    ctx.cache_artifacts = _cache(tmp_path)
    runs = []

    async def export(_ctx, _scene, _impl, directory):
        path = os.path.join(directory, "scene.tf")
        with open(path, "w") as f:
            f.write("scene")
        return path

    async def run(_ctx, _impl, directory, _scene_file, _declaration, _subject, _kind):
        runs.append(directory)
        trajectory = os.path.join(directory, "trajectory.csv")
        with open(trajectory, "w") as f:
            f.write("run %d" % len(runs))
        return {"success": True, "before": {"z": 10.0}, "after": {"z": 9.9}, "trajectory": trajectory}

    monkeypatch.setattr(simulation, "_export_scene_async", export)
    monkeypatch.setattr(simulation, "_run_plugin_async", run)
    return ctx, ctx.get_project("//sim").get_part("block"), runs


def test_the_same_simulation_twice_runs_the_simulator_once(simulated):
    ctx, part, runs = simulated
    (entry,) = simulation.of_shape(part)

    first = _run(simulation.run_async(ctx, part, "part", entry))
    second = _run(simulation.run_async(ctx, part, "part", entry))

    assert first.error is None and second.error is None
    assert len(runs) == 1
    assert second.passed is True
    assert second.result["after"] == {"z": 9.9}
    # The directory is back as the run left it, scene and artifacts both.
    with open(second.result["trajectory"]) as f:
        assert f.read() == "run 1"
    assert os.path.isfile(os.path.join(os.path.dirname(second.result["trajectory"]), "scene.tf"))


def test_the_validation_is_judged_again_rather_than_remembered(simulated):
    """Editing what the run is held to re-judges it; it does not repeat it."""
    ctx, part, runs = simulated
    (entry,) = simulation.of_shape(part)
    assert _run(simulation.run_async(ctx, part, "part", entry)).passed is True

    stricter = simulation.SimulationDeclaration(
        "stands", {"simulation": "//sim:toy", "validation": "after['z'] > 9.95"}
    )
    assert _run(simulation.run_async(ctx, part, "part", stricter)).passed is False
    assert len(runs) == 1


def test_another_simulation_question_is_another_run(simulated):
    ctx, part, runs = simulated
    (entry,) = simulation.of_shape(part)
    _run(simulation.run_async(ctx, part, "part", entry))

    longer = simulation.SimulationDeclaration(
        "stands", {"simulation": "//sim:toy", "validation": "True", "params": {"duration": 20.0}}
    )
    _run(simulation.run_async(ctx, part, "part", longer))
    assert len(runs) == 2


def test_a_rerun_leaves_nothing_of_the_previous_one_behind(simulated, monkeypatch):
    ctx, part, runs = simulated
    (entry,) = simulation.of_shape(part)
    first = _run(simulation.run_async(ctx, part, "part", entry))
    directory = os.path.dirname(first.result["trajectory"])
    with open(os.path.join(directory, "stale.log"), "w") as f:
        f.write("from somewhere else")

    monkeypatch.setattr(ctx.cache_artifacts, "backends", [])
    _run(simulation.run_async(ctx, part, "part", entry))
    assert len(runs) == 2
    assert not os.path.exists(os.path.join(directory, "stale.log"))


# --------------------------------------------------------------------------- #
# `pc cam`                                                                    #
# --------------------------------------------------------------------------- #

CAM_PACKAGE = textwrap.dedent("""
    name: //cam-cache
    parts:
      stock:
        type: step
        path: panel.step
      panel:
        type: step
        path: panel.step
        manufacturing:
          method: subtractive
          source: stock
          diameter: 6 mm
          depth: 18 mm
      two_machines:
        type: step
        path: panel.step
        manufacturing:
          method: subtractive
          source: stock
          diameter: 6 mm
          depth: 18 mm
          laser:
            kerf: 0.15
          drill:
            peck: 3
    cam:
      router:
        path: route.py
        extension: tap
    """)


@pytest.fixture
def routed(tmp_path, monkeypatch):
    """Parts whose route implementation is a counter: the program says which run wrote it."""
    root = tmp_path / "package"
    root.mkdir()
    (root / "partcad.yaml").write_text(CAM_PACKAGE)
    (root / "route.py").write_text("def process(path, request):\n    return {'success': True}\n")
    (root / "panel.step").write_text("ISO-10303-21; panel")
    ctx = pc.Context(str(root))
    monkeypatch.setattr(ctx.user_config, "cam_implementation", "//cam-cache:router")
    ctx.cache_artifacts = _cache(tmp_path)
    runs = []

    async def get_wrapped(self, _ctx):
        return {"brep": b"geometry"}

    async def run(self, _ctx, _impl, _script, request, final_filepath):
        runs.append(request)
        with open(final_filepath, "w") as f:
            f.write("run %d for %s" % (len(runs), request.get("machine")))
        if request.get("fail"):
            return {"success": False, "exception": "post-processor crashed"}
        return {"success": True, "stats": {"moves": 42}, "warnings": ["slow feed"]}

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", get_wrapped)
    monkeypatch.setattr(pc.shape.Shape, "_run_implementation_async", run)
    return ctx, runs, root


def test_the_same_route_twice_runs_the_post_processor_once(routed, tmp_path):
    ctx, runs, _root = routed
    part = ctx.get_part("//cam-cache:panel")

    first = _run(part.route_async(ctx))
    os.remove(first["filepath"])
    second = _run(part.route_async(ctx, output_dir=str(tmp_path / "elsewhere")))

    assert len(runs) == 1
    assert second["stats"] == {"moves": 42}
    assert second["warnings"] == ["slow feed"]
    assert second["filepath"] != first["filepath"]
    with open(second["filepath"]) as f:
        assert f.read() == "run 1 for cnc"


def test_each_machine_is_its_own_route(routed):
    """'manufacturing:' is outside the shape's key, so the request has to tell them apart."""
    ctx, runs, _root = routed
    part = ctx.get_part("//cam-cache:two_machines")

    laser = _run(part.route_async(ctx, machine="laser"))
    drill = _run(part.route_async(ctx, machine="drill"))
    again = _run(part.route_async(ctx, machine="laser"))

    assert len(runs) == 2
    with open(laser["filepath"]) as f:
        assert f.read() == "run 1 for laser"
    with open(drill["filepath"]) as f:
        assert f.read() == "run 2 for drill"
    assert again["filepath"] == laser["filepath"]


def test_another_job_is_another_route(routed):
    ctx, runs, root = routed
    part = ctx.get_part("//cam-cache:panel")

    _run(part.route_async(ctx))
    _run(part.route_async(ctx, feed=900))
    assert len(runs) == 2

    (root / "route.py").write_text("def process(path, request):\n    return {'success': True, 'v': 2}\n")
    _run(part.route_async(ctx))
    assert len(runs) == 3


def test_a_failed_route_is_not_remembered(routed):
    ctx, runs, _root = routed
    part = ctx.get_part("//cam-cache:panel")

    for _ in range(2):
        with pytest.raises(pc.cam.CamFailed):
            _run(part.route_async(ctx, fail=True))
    assert len(runs) == 2


# --------------------------------------------------------------------------- #
# Every sandbox type finds the same entries                                   #
# --------------------------------------------------------------------------- #


def _no_runtime(*_args, **_kwargs):
    raise AssertionError("an artifact key asked which sandbox would run it")


@pytest.mark.parametrize("sandbox", ["conda", "venv", "docker", "remote"])
def test_an_analysis_cached_in_one_sandbox_is_found_from_another(analysed, monkeypatch, sandbox):
    """Sandboxes are equivalent, so the key is made of declarations and nothing else.

    Asked with every way of finding out about a sandbox made to fail: the key
    must be worked out without a runtime, which is what keeps it the same
    whichever one would have run the analysis.
    """
    ctx, part, runs, _root = analysed
    monkeypatch.setattr(ctx.user_config, "python_sandbox", "conda")
    _run(part.analyze_async(ctx, cae.FEA))

    monkeypatch.setattr(ctx.user_config, "python_sandbox", sandbox)
    monkeypatch.setattr(ctx, "get_python_runtime", _no_runtime)
    monkeypatch.setattr(ctx, "get_container_runtime", _no_runtime)
    _run(part.analyze_async(ctx, cae.FEA))

    assert len(runs) == 1


def test_a_route_cached_in_one_sandbox_is_found_from_another(routed, monkeypatch):
    ctx, runs, _root = routed
    part = ctx.get_part("//cam-cache:panel")
    _run(part.route_async(ctx))

    monkeypatch.setattr(ctx.user_config, "python_sandbox", "remote")
    monkeypatch.setattr(ctx, "get_python_runtime", _no_runtime)
    _run(part.route_async(ctx))

    assert len(runs) == 1


def test_a_simulation_cached_in_one_sandbox_is_found_from_another(simulated, monkeypatch):
    ctx, part, runs = simulated
    (entry,) = simulation.of_shape(part)
    _run(simulation.run_async(ctx, part, "part", entry))

    monkeypatch.setattr(ctx.user_config, "python_sandbox", "docker")
    monkeypatch.setattr(ctx, "get_python_runtime", _no_runtime)
    second = _run(simulation.run_async(ctx, part, "part", entry))

    assert second.error is None
    assert len(runs) == 1


def test_what_the_implementing_package_installs_is_part_of_the_question(analysed, monkeypatch):
    """Its own 'pythonRequirements' are installed beside the script, so they key it."""
    ctx, part, runs, root = analysed
    _run(part.analyze_async(ctx, cae.FEA))

    (root / "partcad.yaml").write_text("pythonRequirements:\n  - numpy==2.1.0\n" + PACKAGE)
    reloaded_ctx = pc.Context(str(root))
    monkeypatch.setattr(reloaded_ctx.user_config, "cae_fea_implementation", "//cae-cache:fea")
    reloaded_ctx.cache_artifacts = ctx.cache_artifacts
    reloaded = reloaded_ctx.get_part("//cae-cache:bracket")
    for name in ("get_wrapped", "_analysis_boundary_async", "_run_implementation_async"):
        monkeypatch.setattr(reloaded, name, getattr(part, name))
    _run(reloaded.analyze_async(reloaded_ctx, cae.FEA))

    assert len(runs) == 2


def test_an_implementation_s_environment_is_its_declaration(analysed):
    ctx, part, _runs, _root = analysed
    impl, _ = part.analysis_getopts(
        ctx, cae.FEA, "fea", ctx.get_project("//cae-cache"), None, ctx.get_project("//cae-cache"), None
    )

    key = impl.environment_cache_key()
    assert key.startswith("python==%s;" % impl.python_version())
    assert "image=" not in key
