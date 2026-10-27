#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for caching what an analysis, a simulation or an output file produced.

`partcad.cache_artifacts` on its own first - what goes into an entry, what comes
back out, and what is refused - and then the places that use it: a second
`pc cae`, `pc cam`, `pc sim`, `pc export` or `pc render` of an unchanged object
must be a read, with the files back where the caller expects them, and anything
that changes the question must be a run. And the same for PartCAD's own
wrappers: the IDE's tessellation, an instruction book's PDF, a measurement.

No solver, no simulator and no sandbox: the implementation is stubbed where it
would be started, and counted.
"""

import asyncio
import gzip
import hashlib
import io
import os
import pathlib
import tarfile
import textwrap
import types

import pytest

import partcad as pc
from partcad import cache_artifacts, cae
from partcad import document as pc_document
from partcad import document_pdf, measure, runtime, shape_envelope, shape_gltf, simulation
from partcad.cache import Cache
from partcad.cache_backend import ARTIFACT_KEY
from partcad.cache_hash import CacheHash
from partcad.geom import Location

try:
    from compression.zstd import compress as _zstd_compress
    from compression.zstd import decompress as _zstd_decompress
except ImportError:  # pragma: no cover - exercised on the other interpreter
    from backports.zstd import compress as _zstd_compress
    from backports.zstd import decompress as _zstd_decompress


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


def test_the_key_follows_the_version_the_scripts_report(tmp_path, monkeypatch):
    """The 'CACHE_VERSION' a script states is in the key on its own, beside its content."""
    from partcad import code_version

    script = tmp_path / "solve.py"
    script.write_text("CACHE_VERSION = 1\n")
    first = cache_artifacts.question_hash("x", "s", {"load": 5}, [str(script)]).get()
    monkeypatch.setattr(code_version, "declared", lambda path: 2)
    assert cache_artifacts.question_hash("x", "s", {"load": 5}, [str(script)]).get() != first


def test_a_script_that_states_no_version_keys_as_before_there_were_versions(tmp_path):
    """Adopting 'CACHE_VERSION' costs nothing until a script first raises it."""
    script = tmp_path / "solve.py"
    script.write_text("v = 1\n")
    expected = CacheHash("x", cache=True)
    expected.add_string("artifact-v%d" % cache_artifacts.VERSION)
    expected.add_string("s")
    expected.add_dict({"load": 5})
    expected.add_filename(str(script))
    assert cache_artifacts.question_hash("x", "s", {"load": 5}, [str(script)]).get() == expected.get()


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


def _entry(members: dict, compression: str = "zstd") -> bytes:
    """An entry as something other than this release may have written it.

    "zstd" is the format '_pack' writes, "gzip" the one releases before it did,
    which shared tiers can still hold.
    """
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    if compression == "gzip":
        return gzip.compress(tar_bytes.getvalue(), compresslevel=9)
    return _zstd_compress(tar_bytes.getvalue())


def test_an_entry_is_an_uncompressed_tar_in_one_zstd_frame(tmp_path):
    model = tmp_path / "model.vtu"
    model.write_bytes(b"<VTKFile/>" * 50)

    data = cache_artifacts._pack({"success": True}, {"model": str(model)}, None, 0)

    assert data[:4] == shape_envelope.ZSTD_MAGIC
    with tarfile.open(fileobj=io.BytesIO(_zstd_decompress(data)), mode="r:") as tar:
        # The result first: it says where everything after it goes.
        assert tar.getnames() == ["result.json", "files/model"]


def test_an_entry_an_earlier_release_gzipped_is_still_read(tmp_path):
    """Nothing in the key says which release wrote an entry, so the reader sniffs."""
    cache = _cache(tmp_path)
    stored = {
        "result.json": b'{"success": true, "trajectory": "@@partcad-artifact-directory@@/t.csv"}',
        "files/model": b"<VTKFile/>" * 50,
        "directory/t.csv": b"t,z\n0,10\n",
        "directory/meshes/block.stl": b"solid\n" * 40,
    }
    data = _entry(stored, compression="gzip")
    assert data[:2] == b"\x1f\x8b"
    assert _run(cache.write_data_async(_hash(), {ARTIFACT_KEY: data}))[ARTIFACT_KEY]

    run = tmp_path / "run"
    run.mkdir()
    restored = _run(
        cache_artifacts.restore_async(cache, _hash(), files={"model": str(run / "m.vtu")}, directory=str(run))
    )
    assert restored == {"success": True, "trajectory": str(run / "t.csv")}
    assert (run / "m.vtu").read_bytes() == b"<VTKFile/>" * 50
    assert (run / "t.csv").read_bytes() == b"t,z\n0,10\n"
    assert (run / "meshes" / "block.stl").read_bytes() == b"solid\n" * 40


def test_many_files_come_back_from_one_pass_over_the_entry(tmp_path):
    cache = _cache(tmp_path, max_size=64 * 1024 * 1024)
    first = tmp_path / "run-a"
    first.mkdir()
    for i in range(40):
        (first / ("frame%02d.bin" % i)).write_bytes(bytes([i]) * (64 * 1024 + i))
    assert _run(cache_artifacts.store_async(cache, _hash(), {"frames": 40}, directory=str(first)))

    second = tmp_path / "run-b"
    second.mkdir()
    assert _run(cache_artifacts.restore_async(cache, _hash(), directory=str(second))) == {"frames": 40}
    for i in range(40):
        assert (second / ("frame%02d.bin" % i)).read_bytes() == bytes([i]) * (64 * 1024 + i)


def test_an_entry_that_expands_past_what_gzip_could_is_a_miss(tmp_path, monkeypatch):
    """A few bytes of zstd can stand for gigabytes; one from a shared tier may not."""
    cache = _cache(tmp_path)
    # Scaled down, so the test does not have to build the entry it is about.
    monkeypatch.setattr(cache_artifacts, "_MAX_EXPANSION_FLOOR", 1 << 20)
    data = _entry({"result.json": b"{}", "files/model": bytes(4 << 20)})
    assert len(data) * cache_artifacts._MAX_EXPANSION < 4 << 20
    assert _run(cache.write_data_async(_hash(), {ARTIFACT_KEY: data}))[ARTIFACT_KEY]

    target = tmp_path / "model.bin"
    assert _run(cache_artifacts.restore_async(cache, _hash(), files={"model": str(target)})) is None
    assert not target.exists()


@pytest.mark.parametrize("compression", ["zstd", "gzip"])
@pytest.mark.parametrize("name", ["directory/../escaped.txt", "directory//etc/escaped.txt"])
def test_an_entry_that_would_write_outside_the_directory_is_refused(tmp_path, name, compression):
    """Shared tiers are written by other people: nothing lands outside the run."""
    cache = _cache(tmp_path)
    data = _entry({"result.json": b"{}", name: b"gotcha"}, compression)
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


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="needs POSIX symbolic links")
def test_a_refused_restore_creates_nothing_where_a_link_points(tmp_path):
    """The check comes before any directory is made, not only before the file."""
    cache = _cache(tmp_path)
    first = tmp_path / "run-a"
    (first / "meshes" / "deep").mkdir(parents=True)
    (first / "meshes" / "deep" / "inner.stl").write_bytes(b"solid\n" * 40)
    assert _run(cache_artifacts.store_async(cache, _hash(), {"before": {}}, directory=str(first)))

    outside = tmp_path / "outside"
    outside.mkdir()
    second = tmp_path / "run-b"
    second.mkdir()
    os.symlink(outside, second / "meshes")

    assert _run(cache_artifacts.restore_async(cache, _hash(), directory=str(second))) is None
    assert os.listdir(outside) == []


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
# `pc sim`                                                                    #
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

    async def run(_ctx, _impl, directory, _scene_file, _declaration, _subject, _kind, snapshot=None):
        runs.append(directory)
        trajectory = os.path.join(directory, "trajectory.csv")
        with open(trajectory, "w") as f:
            f.write("run %d" % len(runs))
        result = {"success": True, "before": {"z": 10.0}, "after": {"z": 9.9}, "trajectory": trajectory}
        if snapshot:
            # A plugin that draws: the picture of how it ended, as asked.
            name = snapshot["files"]["after"]
            with open(os.path.join(directory, name), "w") as f:
                f.write("picture of run %d" % len(runs))
            result["snapshots"] = {"after": name}
        return result

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


def test_the_pictures_come_back_with_a_cached_run(simulated):
    """They are files in the run directory, which is what the cache keeps."""
    ctx, part, runs = simulated
    (entry,) = simulation.of_shape(part)

    _run(simulation.run_async(ctx, part, "part", entry))
    second = _run(simulation.run_async(ctx, part, "part", entry))

    assert len(runs) == 1
    with open(second.snapshots["after"]) as f:
        assert f.read() == "picture of run 1"


def test_a_scene_looked_at_from_elsewhere_is_another_run(simulated, monkeypatch):
    """The pictures are part of the answer, so where they are taken from is part
    of the question: the old ones are not this viewpoint's."""
    ctx, part, runs = simulated
    (entry,) = simulation.of_shape(part)
    _run(simulation.run_async(ctx, part, "part", entry))

    asked = simulation.snapshot_request

    def from_the_front(ctx, scene):
        return dict(asked(ctx, scene), viewport_origin=[0.0, -100.0, 0.0])

    monkeypatch.setattr(simulation, "snapshot_request", from_the_front)
    _run(simulation.run_async(ctx, part, "part", entry))
    assert len(runs) == 2


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


# --------------------------------------------------------------------------- #
# What the implementation imports is part of the question                     #
# --------------------------------------------------------------------------- #
#
# A plugin is rarely one file. 'partcad-sim-mujoco' keeps what its exporter,
# its reader and its simulator share in 'mujoco_common.py', and the Gazebo one
# its picture-drawing in 'snapshot_raster.py'. A key made of the script alone
# answered a plugin update that changed only such a module with the result
# the old module produced, until '--cache-bypass'.

HELPER_V1 = "SCALE = 1.0\n"
HELPER_V2 = "SCALE = 2.0  # a new release of the helper\n"


def _imports_a_helper(directory, script, helper):
    """'script' reads its helper the way the MuJoCo plugin reads 'mujoco_common'."""
    (directory / helper).write_text(HELPER_V1)
    module = helper[: -len(".py")]
    (directory / script).write_text(
        "import os, sys\n"
        "sys.path.append(os.path.dirname(os.path.abspath(__file__)))\n"
        "import %s\n"
        "def process(path, request):\n"
        "    return {'success': True, 'scale': %s.SCALE}\n" % (module, module)
    )


def test_a_simulation_plugin_whose_helper_changed_is_run_again(simulated):
    ctx, part, runs = simulated
    root = ctx.get_project("//sim").config_dir
    _imports_a_helper(pathlib.Path(root), "run_it.py", "sim_common.py")
    (entry,) = simulation.of_shape(part)

    _run(simulation.run_async(ctx, part, "part", entry))
    _run(simulation.run_async(ctx, part, "part", entry))
    assert len(runs) == 1

    (pathlib.Path(root) / "sim_common.py").write_text(HELPER_V2)
    _run(simulation.run_async(ctx, part, "part", entry))
    assert len(runs) == 2


def test_an_analysis_whose_solver_helper_changed_is_run_again(analysed):
    ctx, part, runs, root = analysed
    _imports_a_helper(root, "solve.py", "solver_common.py")

    _run(part.analyze_async(ctx, cae.FEA))
    _run(part.analyze_async(ctx, cae.FEA))
    assert len(runs) == 1

    (root / "solver_common.py").write_text(HELPER_V2)
    _run(part.analyze_async(ctx, cae.FEA))
    assert len(runs) == 2


def test_a_route_whose_post_processor_helper_changed_is_produced_again(routed):
    ctx, runs, root = routed
    _imports_a_helper(root, "route.py", "post_common.py")
    part = ctx.get_part("//cam-cache:panel")

    _run(part.route_async(ctx))
    _run(part.route_async(ctx))
    assert len(runs) == 1

    (root / "post_common.py").write_text(HELPER_V2)
    _run(part.route_async(ctx))
    assert len(runs) == 2


def test_what_a_run_writes_into_its_package_is_not_part_of_the_question(analysed):
    """An analysis keeps its model beside the package, and a render its pictures.

    Were every file of the implementing package in the key, the run would move
    its own key by writing its answer, and nothing would ever be found.
    """
    ctx, part, runs, root = analysed
    _run(part.analyze_async(ctx, cae.FEA))
    (root / "bracket.svg").write_text("<svg/>")
    (root / "README.md").write_text("# rendered\n")
    (root / "notes.txt").write_text("measured 0.1655 mm\n")
    _run(part.analyze_async(ctx, cae.FEA))
    assert len(runs) == 1


# --------------------------------------------------------------------------- #
# `pc export` and `pc render`                                                 #
# --------------------------------------------------------------------------- #

EXPORT_PACKAGE = textwrap.dedent("""
    name: //export-cache
    parts:
      bracket:
        type: step
        path: bracket.step
    export:
      toy:
        path: write.py
        extension: toy
    """)


@pytest.fixture
def exported(tmp_path, monkeypatch):
    """A part whose file type is a counter: the file says which run wrote it.

    What the stub is asked decides what it does, so each test can be the
    implementation it needs: 'beside' lists what it writes next to the file,
    named the way an exporter names them - after the file, as a suffix of its
    stem ('_meshes/body.stl' beside 'bracket.toy' is 'bracket_meshes/body.stl')
    - and says it wrote; 'link' has the file name those, the way a URDF names
    its meshes; 'undeclared' keeps it from saying what it wrote at all, 'silent'
    has it report success without writing anything, and 'fail' has it fail.
    """
    root = tmp_path / "package"
    root.mkdir()
    (root / "partcad.yaml").write_text(EXPORT_PACKAGE)
    (root / "write.py").write_text("def process(path, request):\n    return {'success': True, 'files': []}\n")
    (root / "bracket.step").write_text("ISO-10303-21; bracket")
    ctx = pc.Context(str(root))
    ctx.cache_artifacts = _cache(tmp_path)
    runs = []

    async def get_wrapped(self, _ctx):
        return {"brep": b"geometry"}

    async def run(self, _ctx, _impl, _script, request, final_filepath):
        runs.append(request)
        if request.get("fail"):
            return {"success": False, "exception": "exporter crashed"}
        directory = os.path.dirname(final_filepath)
        stem = os.path.splitext(os.path.basename(final_filepath))[0]
        beside = [name if name.startswith("..") else stem + name for name in request.get("beside") or []]
        if not request.get("silent"):
            with open(final_filepath, "w") as f:
                f.write("run %d" % len(runs))
                if request.get("link"):
                    f.write(" using %s" % ", ".join(beside))
        for name in beside:
            path = os.path.join(directory, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("%s of run %d" % (name, len(runs)))
        result = {"success": True, "warnings": ["coarse tessellation"]}
        if not request.get("undeclared"):
            result["files"] = beside
        return result

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", get_wrapped)
    monkeypatch.setattr(pc.shape.Shape, "_run_implementation_async", run)
    return ctx, ctx.get_part("//export-cache:bracket"), runs, root


def _export(ctx, part, directory, name="bracket.toy", **kwargs):
    path = os.path.join(str(directory), name)
    _run(part.render_async(ctx, "toy", filepath=path, **kwargs))
    return path


def test_the_same_file_twice_runs_the_exporter_once(exported, tmp_path):
    ctx, part, runs, _root = exported

    first = _export(ctx, part, tmp_path / "out")
    os.remove(first)
    second = _export(ctx, part, tmp_path / "elsewhere")

    assert len(runs) == 1
    # Back where *this* call asked for it, and the file the run wrote.
    with open(second) as f:
        assert f.read() == "run 1"


def test_a_cached_file_says_what_the_run_said(exported, tmp_path, caplog):
    ctx, part, runs, _root = exported

    _export(ctx, part, tmp_path / "out")
    caplog.clear()
    _export(ctx, part, tmp_path / "out")

    assert len(runs) == 1
    assert "coarse tessellation" in caplog.text


def test_another_question_is_another_file(exported, tmp_path):
    ctx, part, runs, root = exported

    _export(ctx, part, tmp_path / "out")
    _export(ctx, part, tmp_path / "out", tolerance=0.5)
    assert len(runs) == 2

    # The implementation changed: the question is asked again.
    (root / "write.py").write_text("def process(path, request):\n    return {'success': True, 'files': ['v2']}\n")
    _export(ctx, part, tmp_path / "out")
    assert len(runs) == 3


def test_a_file_asked_for_by_another_name_is_put_back_under_it(exported, tmp_path):
    """The name is not part of the question: where the file goes is."""
    ctx, part, runs, _root = exported

    _export(ctx, part, tmp_path / "out", name="bracket.toy")
    renamed = _export(ctx, part, tmp_path / "elsewhere", name="renamed.toy")

    assert len(runs) == 1
    with open(renamed) as f:
        assert f.read() == "run 1"


def test_what_was_written_beside_the_file_is_named_after_the_next_one(exported, tmp_path):
    ctx, part, runs, _root = exported
    beside = ["_meshes/body.stl", ".bin"]

    _export(ctx, part, tmp_path / "out", beside=beside)
    second = _export(ctx, part, tmp_path / "elsewhere", name="renamed.toy", beside=beside)

    assert len(runs) == 1
    with open(second) as f:
        assert f.read() == "run 1"
    # Named after the file asked for, holding what the run wrote.
    with open(tmp_path / "elsewhere" / "renamed_meshes" / "body.stl") as f:
        assert f.read() == "bracket_meshes/body.stl of run 1"
    with open(tmp_path / "elsewhere" / "renamed.bin") as f:
        assert f.read() == "bracket.bin of run 1"


def test_a_name_ending_in_another_suffix_is_produced_again(exported, tmp_path):
    """Nothing says what 'x.toyz' calls the other file: the hit is dismissed and the run happens."""
    ctx, part, runs, _root = exported

    _export(ctx, part, tmp_path / "out", beside=[".colors.txt"])
    # The suffix in another case is the same suffix.
    _export(ctx, part, tmp_path / "out", name="X.TOY", beside=[".colors.txt"])
    assert len(runs) == 1
    assert (tmp_path / "out" / "X.colors.txt").read_text() == "bracket.colors.txt of run 1"

    _export(ctx, part, tmp_path / "out", name="x.toyz", beside=[".colors.txt"])
    assert len(runs) == 2


def test_files_that_name_each_other_are_produced_again_under_another_name(exported, tmp_path):
    """Renamed, the file would name meshes that are not there; moved, it names them still."""
    ctx, part, runs, _root = exported
    beside = ["_meshes/body.stl"]

    _export(ctx, part, tmp_path / "out", beside=beside, link=True)
    moved = _export(ctx, part, tmp_path / "elsewhere", beside=beside, link=True)
    assert len(runs) == 1
    with open(moved) as f:
        assert f.read() == "run 1 using bracket_meshes/body.stl"

    _export(ctx, part, tmp_path / "out", name="renamed.toy", beside=beside, link=True)
    assert len(runs) == 2


def test_an_exporter_that_does_not_say_what_it_wrote_is_run_every_time(exported, tmp_path):
    """Its meshes could be anywhere beside the file, and a file without them is worse than a run."""
    ctx, part, runs, _root = exported

    _export(ctx, part, tmp_path / "out", undeclared=True)
    _export(ctx, part, tmp_path / "out", undeclared=True)
    assert len(runs) == 2


def test_a_file_written_outside_the_directory_is_not_remembered(exported, tmp_path):
    """It could not be put back where it was, relative to the file, wherever that is next."""
    ctx, part, runs, _root = exported

    _export(ctx, part, tmp_path / "out" / "deep", beside=["../outside.bin"])
    _export(ctx, part, tmp_path / "out" / "deep", beside=["../outside.bin"])
    assert len(runs) == 2


def test_a_file_the_run_did_not_write_is_not_remembered(exported, tmp_path):
    """Nothing clears the path first, so a file there afterwards proves nothing by itself."""
    ctx, part, runs, _root = exported
    stale = tmp_path / "out" / "bracket.toy"
    stale.parent.mkdir(parents=True)
    stale.write_text("last week's")

    _export(ctx, part, tmp_path / "out", silent=True)
    _export(ctx, part, tmp_path / "out", silent=True)
    assert len(runs) == 2


def test_a_failed_export_is_not_remembered(exported, tmp_path):
    ctx, part, runs, _root = exported

    _export(ctx, part, tmp_path / "out", fail=True)
    _export(ctx, part, tmp_path / "out", fail=True)
    assert len(runs) == 2


def test_a_part_that_is_not_cached_is_exported_every_time(exported, tmp_path, monkeypatch):
    ctx, part, runs, _root = exported
    monkeypatch.setattr(part, "cacheable", False)

    _export(ctx, part, tmp_path / "out")
    _export(ctx, part, tmp_path / "out")
    assert len(runs) == 2


def test_a_file_cached_in_one_sandbox_is_found_from_another(exported, tmp_path, monkeypatch):
    ctx, part, runs, _root = exported
    _export(ctx, part, tmp_path / "out")

    monkeypatch.setattr(ctx.user_config, "python_sandbox", "remote")
    monkeypatch.setattr(ctx, "get_python_runtime", _no_runtime)
    monkeypatch.setattr(ctx, "get_container_runtime", _no_runtime)
    _export(ctx, part, tmp_path / "out")

    assert len(runs) == 1


def test_a_view_is_keyed_as_the_links_it_keeps(exported, tmp_path):
    """A filtered view has no key of its own: the object's and the filter are what it is."""
    ctx, part, runs, _root = exported
    project = ctx.get_project("//export-cache")
    impl, path = part.output_getopts(ctx, "toy", project, filepath=str(tmp_path / "out" / "bracket.toy"))
    os.makedirs(os.path.dirname(path), exist_ok=True)

    async def once(view):
        script = await part._materialize_output_script(ctx, impl)
        request = {"wrapped": {"brep": b"view"}, "shape_name": part.name}
        return await part._output_run_async(ctx, impl, script, request, path, view=view)

    def view(key):
        return types.SimpleNamespace(key=lambda: key)

    _run(once(view("{arm:*}")))
    _run(once(view("{arm:*}")))
    _run(once(view("{base:*}")))
    _run(once(None))
    assert len(runs) == 3


def test_a_part_painted_another_colour_is_drawn_again(exported, tmp_path, monkeypatch):
    """'properties:' is no part of a shape's key - a part that gains a colour is the same solid.

    But a renderer paints it, from the tree it is handed, and the picture of it
    in red was handed back for it in blue. The tree reaches the renderer the way
    'get_wrapped' builds it: the payload, with the shape's own outer layer
    stamped on - its properties among it.
    """
    ctx, part, runs, _root = exported

    async def get_wrapped(self, _ctx):
        return shape_envelope.apply_metadata({"brep": b"geometry"}, self.get_cache_metadata())

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", get_wrapped)

    part.config["properties"] = {"color": "red"}
    _export(ctx, part, tmp_path / "out")
    _export(ctx, part, tmp_path / "out")
    assert len(runs) == 1

    part.config["properties"] = {"color": "blue"}
    _export(ctx, part, tmp_path / "out")
    assert len(runs) == 2
    assert runs[-1]["wrapped"]["properties"] == {"color": "blue"}


def test_a_tree_is_described_without_its_geometry():
    """What decides a file beside the shape's key: everything the tree says, nothing it carries.

    Without its payloads, so a large assembly's key is not a hash of every
    brick; with everything else, at every depth.
    """
    brick = {"brep": b"a brick", "metadata": {"measurements": {"volume": 1.0}}, "name": "brick"}
    tree = {
        "assembly": [
            dict(brick, label="left", location=[1, 0, 0], properties={"color": "red"}),
            dict(brick, label="right", location=[2, 0, 0], properties={"color": "blue"}),
        ],
        "name": "wall",
        "gltf": "...",
        "geometry": {"digest": "..."},
        "extra": b"opaque",
    }
    described = shape_envelope.description(tree)

    assert described == {
        "assembly": [
            {"name": "brick", "label": "left", "location": [1, 0, 0], "properties": {"color": "red"}},
            {"name": "brick", "label": "right", "location": [2, 0, 0], "properties": {"color": "blue"}},
        ],
        "name": "wall",
        "extra": shape_envelope.description(b"opaque"),
    }
    assert described["extra"] != shape_envelope.description(b"something else")


def test_what_a_node_s_properties_say_is_described_whole():
    """The user's names are the user's: a 'physics' block saying 'geometry' is a property, not a payload."""
    node = {"brep": b"a brick", "properties": {"physics": {"geometry": "box", "metadata": {"source": "urdf"}}}}
    other = {"brep": b"a brick", "properties": {"physics": {"geometry": "cylinder", "metadata": {"source": "urdf"}}}}

    assert shape_envelope.description(node) == {"properties": node["properties"]}
    assert shape_envelope.description(node) != shape_envelope.description(other)


def test_bytes_are_not_described_as_the_string_that_spells_their_digest():
    digest = hashlib.sha256(b"opaque").hexdigest()

    assert shape_envelope.description({"extra": b"opaque"}) != shape_envelope.description({"extra": digest})


def test_only_nodes_lose_their_geometry():
    """A child at any depth and a sketch in the root's table are nodes; a joint is data, whatever it names."""
    joint = {"name": "hinge", "metadata": {"limit": 90}, "geometry": "revolute"}
    tree = {
        "assembly": [{"assembly": [{"brep": b"a pin", "metadata": {"volume": 1.0}, "joint": joint}]}],
        "sketches": {"//pkg:circle": {"brep": b"a circle", "name": "circle"}},
    }

    assert shape_envelope.description(tree) == {
        "assembly": [{"assembly": [{"joint": joint}]}],
        "sketches": {"//pkg:circle": {"name": "circle"}},
    }


# --------------------------------------------------------------------------- #
# Naming the files of an answer after the next path asked for                 #
# --------------------------------------------------------------------------- #


def _written(directory, *names, content=None):
    for name in names:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.get(name, name) if content else name)
    return [str(directory / name) for name in names]


def test_a_layout_is_the_suffixes_of_a_shared_prefix(tmp_path):
    _written(tmp_path, "logo.urdf", "logo_meshes/bolt.stl", "logo_meshes/bone.stl")

    layout = cache_artifacts.files_layout(
        str(tmp_path / "logo.urdf"), ["logo_meshes/bolt.stl", str(tmp_path / "logo_meshes" / "bone.stl")]
    )

    assert layout["suffix"] == ".urdf"
    assert layout["others"] == ["_meshes/bolt.stl", "_meshes/bone.stl"]
    assert layout["stem"] == "logo"
    assert cache_artifacts.placed_files(layout, str(tmp_path / "next" / "xyz.urdf")) == [
        str(tmp_path / "next" / "xyz.urdf"),
        str(tmp_path / "next" / "xyz_meshes" / "bolt.stl"),
        str(tmp_path / "next" / "xyz_meshes" / "bone.stl"),
    ]


def test_a_suffix_is_matched_in_any_case_and_in_no_other_spelling(tmp_path):
    """'abc.jpg' with 'abc.colors.txt' says what 'xyz.JPG' writes, and nothing about 'xyz.JPEG'."""
    _written(tmp_path, "abc.jpg", "abc.colors.txt")
    layout = cache_artifacts.files_layout(str(tmp_path / "abc.jpg"), ["abc.colors.txt"])

    assert cache_artifacts.placed_files(layout, str(tmp_path / "xyz.JPG")) == [
        str(tmp_path / "xyz.JPG"),
        str(tmp_path / "xyz.colors.txt"),
    ]
    assert cache_artifacts.placed_files(layout, str(tmp_path / "xyz.JPEG")) is None


def test_a_prefix_is_never_cut_inside_a_word(tmp_path):
    _written(tmp_path, "abc.jpg", "abc.jpeg")
    layout = cache_artifacts.files_layout(str(tmp_path / "abc.jpg"), ["abc.jpeg"])

    assert (layout["suffix"], layout["others"]) == (".jpg", [".jpeg"])


def test_one_file_goes_wherever_it_is_asked_for(tmp_path):
    _written(tmp_path, "bracket.svg")
    layout = cache_artifacts.files_layout(str(tmp_path / "bracket.svg"), [])

    assert layout["suffix"] == "" and layout["others"] == []
    assert cache_artifacts.placed_files(layout, str(tmp_path / "x" / "Other.SVG")) == [
        str(tmp_path / "x" / "Other.SVG")
    ]


def test_files_named_otherwise_come_back_only_under_the_same_name(tmp_path):
    """Sharing nothing but the directory, the names are the names: moved, not renamed."""
    _written(tmp_path, "robot.urdf", "meshes/body.stl")
    layout = cache_artifacts.files_layout(str(tmp_path / "robot.urdf"), ["meshes/body.stl"])

    assert (layout["suffix"], layout["others"], layout["stem"]) == ("robot.urdf", ["meshes/body.stl"], "")
    assert cache_artifacts.placed_files(layout, str(tmp_path / "next" / "robot.urdf"))[1] == str(
        tmp_path / "next" / "meshes" / "body.stl"
    )
    assert cache_artifacts.placed_files(layout, str(tmp_path / "next" / "other.urdf")) is None


def test_files_that_name_each_other_can_move_but_not_be_renamed(tmp_path):
    _written(tmp_path, "cube.gltf", "cube.bin", content={"cube.gltf": '{"uri": "cube.bin"}', "cube.bin": "\0"})
    layout = cache_artifacts.files_layout(str(tmp_path / "cube.gltf"), ["cube.bin"])

    assert layout["linked"] is True
    assert cache_artifacts.placed_files(layout, str(tmp_path / "moved" / "cube.gltf")) is not None
    assert cache_artifacts.placed_files(layout, str(tmp_path / "moved" / "xyz.gltf")) is None


def test_files_that_name_their_directory_cannot_move(tmp_path):
    _written(
        tmp_path,
        "cube.gltf",
        "cube.bin",
        content={"cube.gltf": '{"uri": "%s"}' % (tmp_path / "cube.bin"), "cube.bin": "\0"},
    )
    layout = cache_artifacts.files_layout(str(tmp_path / "cube.gltf"), ["cube.bin"])

    assert cache_artifacts.placed_files(layout, str(tmp_path / "cube.gltf")) is not None
    assert cache_artifacts.placed_files(layout, str(tmp_path / "moved" / "cube.gltf")) is None


@pytest.mark.parametrize("other", ["../escape.bin", "/elsewhere/escape.bin"])
def test_a_file_outside_the_directory_cannot_be_laid_out(tmp_path, other):
    (tmp_path / "out").mkdir()
    _written(tmp_path / "out", "cube.gltf")
    assert cache_artifacts.files_layout(str(tmp_path / "out" / "cube.gltf"), [other]) is None


@pytest.mark.parametrize("other", ["/../../escape", "_x/../../../escape", "a\\b"])
def test_a_layout_read_from_a_tier_cannot_write_outside_the_directory(tmp_path, other):
    """An entry is read from tiers others may write to, so its names are not trusted."""
    layout = {"suffix": ".gltf", "others": [other], "stem": "cube", "linked": False}
    assert cache_artifacts.placed_files(layout, str(tmp_path / "cube.gltf")) is None


# --------------------------------------------------------------------------- #
# What an implementation says it wrote                                        #
# --------------------------------------------------------------------------- #


def _wrapper_export():
    import sys

    sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
    import wrapper_export

    return wrapper_export


@pytest.mark.parametrize(
    "said, passed_on",
    [
        ("[]", []),
        ("['meshes/a.stl']", ["meshes/a.stl"]),
        (None, None),
        ("'meshes/a.stl'", None),
    ],
)
def test_what_an_implementation_wrote_reaches_the_core(tmp_path, said, passed_on):
    """An empty list is passed on: it is a statement, and saying nothing is not."""
    script = tmp_path / "write.py"
    files = "" if said is None else ", 'files': %s" % said
    script.write_text("def process(path, request):\n    return {'success': True%s}\n" % files)

    result = _wrapper_export().process(str(script), str(tmp_path / "out.toy"), {})

    assert result["success"] is True
    assert result.get("files") == passed_on


def test_every_built_in_implementation_says_what_it_wrote():
    """Or the files PartCAD writes itself would never be cached.

    Read rather than run, since running them takes a CAD sandbox: every dict
    an export or a render implementation returns for a success has to say what
    else it wrote, if only that it wrote nothing.
    """
    import ast

    builtin = os.path.join(os.path.dirname(pc.__file__), "builtin")
    checked = 0
    for section in ("export", "render"):
        directory = os.path.join(builtin, section)
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(directory, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                keys = {key.value: value for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant)}
                success = keys.get("success")
                if isinstance(success, ast.Constant) and success.value is True:
                    checked += 1
                    assert "files" in keys, "%s/%s returns a success without 'files'" % (section, name)
    assert checked >= 10


# --------------------------------------------------------------------------- #
# PartCAD's own wrappers: the IDE's tessellation, a PDF, a measurement        #
# --------------------------------------------------------------------------- #


class _Sandbox:
    """A runtime that answers with 'answer(request, run)' and counts how often it was asked."""

    def __init__(self, answer):
        self.answer = answer
        self.runs = []

    def get_session(self, _name):
        return None

    async def ensure_async(self, *_args, **_kwargs):
        return None

    async def run_async(self, command, request_serialized, **_kwargs):
        # Resolved the way a real runtime resolves it, at the spawn: the request
        # may be the callable that serializes it (see 'runtime.stdin_bytes').
        request = shape_envelope.deserialize(runtime.stdin_bytes(request_serialized))
        self.runs.append(request)
        return 0, shape_envelope.serialize(self.answer(command, request, len(self.runs))), ""


def _context(tmp_path, sandbox):
    return types.SimpleNamespace(cache_artifacts=_cache(tmp_path), get_python_runtime=lambda **_kwargs: sandbox)


def _tessellated(_command, request, run):
    if request["tree"].get("fail"):
        return {"success": False, "exception": "no OCP"}
    return {"success": True, "tree": {"name": request["tree"]["name"], shape_envelope.KEY_GLTF: b"glb of run %d" % run}}


def test_a_tessellation_is_tessellated_once(tmp_path):
    sandbox = _Sandbox(_tessellated)
    ctx = _context(tmp_path, sandbox)
    tree = {"name": "cube", "brep": b"geometry"}

    first = _run(shape_gltf.convert_async(ctx, tree))
    # The next process asks without a sandbox to hand: it needs none.
    ctx.get_python_runtime = _no_runtime
    second = _run(shape_gltf.convert_async(ctx, dict(tree)))

    assert len(sandbox.runs) == 1
    assert second == first
    assert second[shape_envelope.KEY_GLTF] == b"glb of run 1"


def test_another_tree_is_another_tessellation(tmp_path):
    """Keyed on what the sandbox is handed, the sketches of the ports included."""
    sandbox = _Sandbox(_tessellated)
    ctx = _context(tmp_path, sandbox)

    _run(shape_gltf.convert_async(ctx, {"name": "cube", "brep": b"geometry"}))
    _run(shape_gltf.convert_async(ctx, {"name": "cube", "brep": b"other geometry"}))
    _run(shape_gltf.convert_async(ctx, {"name": "cube", "brep": b"geometry"}, tolerance=0.01))
    assert len(sandbox.runs) == 3


def test_a_tessellation_of_what_is_not_cached_is_not_remembered(tmp_path):
    sandbox = _Sandbox(_tessellated)
    ctx = _context(tmp_path, sandbox)
    tree = {"name": "cube", "brep": b"geometry"}

    _run(shape_gltf.convert_async(ctx, tree, cacheable=False))
    _run(shape_gltf.convert_async(ctx, tree, cacheable=False))
    assert len(sandbox.runs) == 2


def test_a_failed_tessellation_is_not_remembered(tmp_path):
    sandbox = _Sandbox(_tessellated)
    ctx = _context(tmp_path, sandbox)
    tree = {"name": "cube", "brep": b"geometry", "fail": True}

    for _ in range(2):
        with pytest.raises(Exception, match="no OCP"):
            _run(shape_gltf.convert_async(ctx, tree))
    assert len(sandbox.runs) == 2


def _composed(command, _request, run):
    with open(command[1], "w") as f:
        f.write("pdf of run %d" % run)
    return {"success": True}


def _book(picture):
    image = pc_document.Image(file=str(picture), alt="the widget")
    return pc_document.Document(
        title="widget",
        pages=[pc_document.Page(blocks=[pc_document.Paragraph("A widget."), pc_document.ImageRow(images=[image])])],
    )


def test_a_book_is_composed_once(tmp_path):
    """Its pictures are drawn into a new temporary directory every time, so they key by content."""
    sandbox = _Sandbox(_composed)
    ctx = _context(tmp_path, sandbox)
    for directory in ("first", "second"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "widget.svg").write_text("<svg/>")

    _run(document_pdf.render_pdf_async(ctx, _book(tmp_path / "first" / "widget.svg"), str(tmp_path / "a.pdf")))
    _run(document_pdf.render_pdf_async(ctx, _book(tmp_path / "second" / "widget.svg"), str(tmp_path / "b.pdf")))

    assert len(sandbox.runs) == 1
    assert (tmp_path / "b.pdf").read_text() == "pdf of run 1"


def test_a_book_whose_picture_changed_is_composed_again(tmp_path):
    sandbox = _Sandbox(_composed)
    ctx = _context(tmp_path, sandbox)
    picture = tmp_path / "widget.svg"

    picture.write_text("<svg/>")
    _run(document_pdf.render_pdf_async(ctx, _book(picture), str(tmp_path / "a.pdf")))
    picture.write_text("<svg><path/></svg>")
    _run(document_pdf.render_pdf_async(ctx, _book(picture), str(tmp_path / "a.pdf")))
    _run(document_pdf.render_pdf_async(ctx, _book(picture), str(tmp_path / "a.pdf"), reproducible=True))
    _run(document_pdf.render_pdf_async(ctx, _book(picture), str(tmp_path / "a.pdf"), cacheable=False))

    assert len(sandbox.runs) == 4


def _measured(_command, _request, _count):
    return {"success": True, "result": [0.0, 0.0, 0.0, 1.0, 2.0, 3.0]}


def test_a_measurement_is_measured_once(tmp_path):
    sandbox = _Sandbox(_measured)
    ctx = _context(tmp_path, sandbox)
    shape = {"brep": b"geometry"}

    assert _run(measure.extent_z(ctx, shape)) == 3.0
    assert _run(measure.extent_z(ctx, shape)) == 3.0
    assert len(sandbox.runs) == 1

    # Measured from somewhere else, it is another measurement.
    _run(measure.extent_z(ctx, shape, Location([[0, 0, 5], [0, 0, 1], 0])))
    assert len(sandbox.runs) == 2

    _run(measure.extent_z(ctx, shape, cacheable=False))
    assert len(sandbox.runs) == 3
