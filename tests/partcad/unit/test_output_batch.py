#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The file types of one object, written by one sandbox call.

`pc render` of a package asks for every file type of a shape at once, and those
the cache does not hold are written by one interpreter per sandbox environment
rather than one per file: the CAD stack is imported once and the shape decoded
once (see `Shape._run_together_locked` and `wrapper_export.run_together`). Each
file is still worked out, cached, logged and reported on its own, and one that
fails costs the others nothing.

The wrapper is the real one, run as a subprocess by this interpreter; only the
runtime around it is a stand-in, which counts the calls. The implementations are
scripts of the test's own and the shape carries no geometry, so none of it needs
a CAD sandbox - except the one test that is about sharing geometry, which needs
OCP in this interpreter and skips without it.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import textwrap
import types

import pytest

import partcad as pc
from partcad import output, sandbox_versions
from partcad import shape as pc_shape
from partcad import wrapper as pc_wrapper
from partcad.cache import Cache

WRAPPERS = os.path.dirname(pc_wrapper.get("export.py"))
WRAPPER = os.path.join(WRAPPERS, "wrapper_export.py")

# Says which file type it is, where it ran, and with what in 'sys.path' and
# 'sys.argv' -- which is what it would have found running on its own. 'crash'
# ends the whole process the first time it is asked, the way a native fault
# would, and 'always_crash' every time; 'fail' is an implementation reporting a
# failure of its own.
WRITE = textwrap.dedent("""
    import os
    import sys


    def process(path, request):
        if request.get("always_crash"):
            os._exit(3)
        marker = request.get("crash")
        if marker and not os.path.exists(marker):
            open(marker, "w").close()
            os._exit(3)
        if request.get("fail"):
            return {"success": False, "exception": "%s cannot be written" % request.get("say")}
        leaked = request.get("leak") in sys.path
        if request.get("leak"):
            sys.path.append(request["leak"])
        with open(path, "w") as f:
            f.write(
                "%s in %s, argv %s, leaked %s"
                % (request.get("say"), os.path.basename(os.getcwd()), sys.argv[1] == path, leaked)
            )
        return {"success": True, "files": []}
    """)


def _cache(tmp_path) -> Cache:
    """A files-only cache of the test's own."""
    config = types.SimpleNamespace(
        cache=True,
        internal_state_dir=str(tmp_path / "state"),
        cache_min_entry_size=1,
        cache_max_entry_size=10 * 1024 * 1024,
    )
    return Cache("artifacts", config)


class _Sandbox:
    """A Python runtime that runs what it is asked with this interpreter, and keeps count.

    Its own environment holds everything but what is named 'layer-...': a file
    type asking for one of those runs in the layer named after them, as
    'PythonRuntime.get_session' has it.
    """

    EXCHANGES_FILES = False

    def __init__(self):
        self.calls = []
        self.sessions = []

    def get_session(self, name):
        return {"name": name, "path": None, "dirty": False, "deps": [], "missing": []}

    def _ask(self, session, python_package):
        if session is None:
            return
        session["deps"].append(python_package)
        if python_package.startswith("layer-") and python_package not in session["missing"]:
            session["missing"].append(python_package)
            session["dirty"] = True
            session["path"] = "layer:" + ",".join(sorted(session["missing"]))

    async def prepare_for_package(self, project, session=None):
        for python_package in project.config_obj.get("pythonRequirements") or []:
            self._ask(session, python_package)

    async def ensure_async(self, python_package, session=None, path=None, force=False):
        self._ask(session, python_package)

    async def run_async(self, cmd, stdin="", session=None, **_kwargs):
        data = stdin() if callable(stdin) else stdin
        cmd = [part for part in cmd if part != "python"]
        self.calls.append(cmd)
        self.sessions.append(session)
        finished = await asyncio.to_thread(
            subprocess.run, [sys.executable, *cmd], input=data, capture_output=True, text=True
        )
        # What 'PythonRuntime' does with what a run printed: a warning when it
        # succeeded, the error when it did not.
        return finished.returncode, finished.stdout, finished.stderr if finished.returncode else ""

    def files_per_call(self):
        return [(len(call) - 1) // 3 for call in self.calls]


def _package(root, file_types: str):
    root.mkdir(parents=True, exist_ok=True)
    (root / "partcad.yaml").write_text(
        "name: //batch\nparts:\n  bracket:\n    type: step\n    path: bracket.step\nexport:\n"
        + textwrap.indent(textwrap.dedent(file_types), "  ")
    )
    (root / "write.py").write_text(WRITE)
    (root / "bracket.step").write_text("ISO-10303-21; bracket")


@pytest.fixture
def batch(tmp_path, monkeypatch):
    """A part of a package whose file types are written by 'write.py', and the sandbox that writes them."""
    sandbox = _Sandbox()

    def make(file_types):
        root = tmp_path / "package"
        _package(root, file_types)
        ctx = pc.Context(str(root))
        ctx.cache_artifacts = _cache(tmp_path)
        monkeypatch.setattr(ctx, "get_python_runtime", lambda version=None, image=None: sandbox)

        async def get_container_runtime(_container):
            return sandbox

        monkeypatch.setattr(ctx, "get_container_runtime", get_container_runtime)
        return ctx

    async def get_wrapped(self, _ctx):
        # A tree with no geometry in it: the wrapper decodes nothing.
        return {"name": self.name, "label": None}

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", get_wrapped)
    return make, sandbox, tmp_path / "out"


THREE = """
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """


def _render(ctx, out):
    asyncio.run(ctx.get_project("//").render_async(output_dir=str(out)))


def _read(out, name):
    with open(os.path.join(str(out), name)) as f:
        return f.read()


def test_the_file_types_of_a_shape_are_written_by_one_call(batch):
    make, sandbox, out = batch
    ctx = make(THREE)

    _render(ctx, out)

    assert sandbox.files_per_call() == [3]
    # Each as it would have been written on its own: in its package, with its
    # own path in 'sys.argv', and nothing another file type put in 'sys.path'.
    for name in ("alpha", "beta", "gamma"):
        assert _read(out, "bracket." + name) == "%s in package, argv True, leaked False" % name


def test_a_file_type_the_cache_holds_is_not_drawn_again(batch):
    make, sandbox, out = batch
    ctx = make(THREE)

    asyncio.run(ctx.get_part("//:bracket").render_async(ctx, "alpha", output_dir=str(out)))
    _render(ctx, out)
    assert sandbox.files_per_call() == [1, 2]
    assert "alpha" not in " ".join(sandbox.calls[1])

    for name in ("alpha", "beta", "gamma"):
        os.remove(os.path.join(str(out), "bracket." + name))
    _render(ctx, out)
    # Every one of them from the cache, under its own key.
    assert sandbox.files_per_call() == [1, 2]
    assert _read(out, "bracket.gamma").startswith("gamma in package")


def test_what_one_sandbox_path_leaves_behind_is_not_seen_by_the_next(batch):
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha, leak: /nowhere}
    beta: {path: write.py, extension: beta, say: beta, leak: /nowhere}
    """)

    _render(ctx, out)
    assert sandbox.files_per_call() == [2]
    assert _read(out, "bracket.beta").endswith("leaked False")


def test_a_file_type_that_fails_does_not_stop_the_others(batch, caplog):
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, fail: true}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """)

    _render(ctx, out)

    assert sandbox.files_per_call() == [3]
    assert _read(out, "bracket.gamma").startswith("gamma")
    assert not os.path.exists(os.path.join(str(out), "bracket.beta"))
    # The message a failed file type has always had.
    assert "Render BETA failed for //batch:bracket: beta cannot be written" in caplog.text


def test_a_file_the_call_did_not_finish_is_written_by_a_call_of_its_own(batch, caplog, tmp_path):
    """The process dies writing the second file: the first is answered, and the other two are written alone."""
    make, sandbox, out = batch
    marker = str(tmp_path / "crashed").replace("\\", "/")
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, crash: "%s"}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """ % marker)

    with caplog.at_level(logging.WARNING):
        _render(ctx, out)

    assert sandbox.files_per_call() == [3, 1, 1]
    for name in ("alpha", "beta", "gamma"):
        assert _read(out, "bracket." + name).startswith(name)
    assert "stopped before it wrote beta, gamma" in caplog.text


def test_a_file_that_crashes_on_its_own_too_fails_as_it_always_did(batch):
    """Written alone it crashes again, and that is raised - as it was before any of this."""
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, always_crash: true}
    """)

    with pytest.raises(Exception, match="Failed to execute command") as raised:
        _render(ctx, out)
    # The call of its own, which names that file and no other.
    assert "bracket.beta" in str(raised.value) and "bracket.alpha" not in str(raised.value)
    assert sandbox.files_per_call() == [2, 1]
    assert _read(out, "bracket.alpha").startswith("alpha")


def test_two_file_types_that_write_one_path_are_not_written_by_one_call(batch):
    """The one left there is the one asked for last, and neither run is remembered as the other's file."""
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: toy, say: alpha}
    beta: {path: write.py, extension: toy, say: beta}
    gamma: {path: write.py, extension: gamma, say: gamma}
    """)

    _render(ctx, out)
    assert sandbox.files_per_call() == [2, 1]
    assert _read(out, "bracket.toy").startswith("beta")


def test_file_types_of_another_environment_are_written_by_a_call_of_their_own(batch):
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, pythonVersion: "3.12"}
    gamma: {path: write.py, extension: gamma, say: gamma}
    delta: {path: write.py, extension: delta, say: delta, container: {image: example/solver:1}}
    """)

    _render(ctx, out)
    assert sorted(sandbox.files_per_call()) == [1, 1, 2]
    for name in ("alpha", "beta", "gamma", "delta"):
        assert _read(out, "bracket." + name).startswith(name)


def test_the_requirements_of_several_file_types_are_asked_for_in_an_order_that_keeps_them(batch):
    """glTF's list after STEP's, each package once where it first appears, would end in build123d.

    Which a sandbox keeping one environment, installing in the order asked,
    would leave with OCP's build without VTK.
    """
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha, pythonRequirements: ["%s"]}
    beta: {path: write.py, extension: beta, say: beta, pythonRequirements: ["%s", "%s"]}
    """ % (sandbox_versions.CADQUERY_OCP, sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP))

    _render(ctx, out)
    assert sandbox.files_per_call() == [2]
    assert sandbox.sessions[0]["deps"] == [sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP]


def test_file_types_are_written_together_with_those_of_their_own_layer(batch):
    """Each runs where it would have run alone: the base, or the layer its requirements make."""
    make, sandbox, out = batch
    ctx = make("""
    alpha: {path: write.py, extension: alpha, say: alpha}
    beta: {path: write.py, extension: beta, say: beta, pythonRequirements: [layer-raster]}
    gamma: {path: write.py, extension: gamma, say: gamma}
    delta: {path: write.py, extension: delta, say: delta, pythonRequirements: [layer-raster]}
    epsilon: {path: write.py, extension: epsilon, say: epsilon, pythonRequirements: [layer-cad]}
    """)

    _render(ctx, out)

    written = {}
    for call, session in zip(sandbox.calls, sandbox.sessions):
        layer = session["path"] if session["dirty"] else "base"
        written[layer] = sorted(os.path.basename(call[index]) for index in range(1, len(call), 3))
    assert written == {
        "base": ["bracket.alpha", "bracket.gamma"],
        "layer:layer-raster": ["bracket.beta", "bracket.delta"],
        "layer:layer-cad": ["bracket.epsilon"],
    }


def test_every_file_type_is_still_an_action_of_its_own(batch, caplog):
    make, _sandbox, out = batch
    ctx = make(THREE)

    with caplog.at_level(logging.DEBUG):
        _render(ctx, out)
    for name in ("ALPHA", "BETA", "GAMMA"):
        assert "DONE: Render%s: //batch: bracket:" % name in caplog.text


def test_a_caller_holding_the_shape_writes_each_file_type_on_its_own(batch):
    """A batch's file types are worked out in tasks of their own, which could never take a lock it held."""
    make, sandbox, out = batch
    ctx = make(THREE)
    part = ctx.get_part("//:bracket")

    async def held():
        async with part.locked():
            await part.render_async(ctx, ["alpha", "beta"], output_dir=str(out))

    asyncio.run(held())
    assert sandbox.files_per_call() == [1, 1]


# --------------------------------------------------------------------------- #
# Which sandbox a file type runs in                                           #
# --------------------------------------------------------------------------- #


def _impl(name, container=None, version="3.11", image=None):
    return types.SimpleNamespace(
        container=container,
        project=types.SimpleNamespace(name=name),
        python_version=lambda: version,
        docker_image=image,
    )


def test_built_in_implementations_share_a_sandbox_and_packages_do_not():
    sandbox_of = pc_shape._sandbox_of
    assert sandbox_of(_impl("//builtin/render")) == sandbox_of(_impl("//builtin/export"))
    assert sandbox_of(_impl("//pub/plugin")) == sandbox_of(_impl("//pub/plugin"))
    assert sandbox_of(_impl("//pub/plugin")) != sandbox_of(_impl("//pub/other"))
    assert sandbox_of(_impl("//pub/plugin")) != sandbox_of(_impl("//pub/plugin", version="3.12"))
    assert sandbox_of(_impl("//pub/plugin")) != sandbox_of(_impl("//pub/plugin", image="example/sandbox:1"))
    # A container is a process of its own.
    assert sandbox_of(_impl("//pub/plugin", container={"image": "example/solver:1"})) is None


def test_rounds_keep_two_files_at_one_path_apart():
    paths = ["/out/a.json", "/out/b.stl", "/out/a.json", "/out/c.svg", "/out/a.json"]
    outputs = [pc_shape._Output(None, None, {}, path) for path in paths]
    assert pc_shape._rounds(outputs) == [[0, 1, 3], [2], [4]]


def test_the_object_travels_once_however_many_files_are_of_it():
    tree = {"name": "bracket", "brep": b"geometry"}
    view = {"name": "bracket", "assembly": []}
    outputs = [
        pc_shape._Output(None, None, {"wrapped": tree, "say": "a"}, "a"),
        pc_shape._Output(None, None, {"wrapped": view, "say": "b"}, "b"),
        pc_shape._Output(None, None, {"wrapped": tree, "say": "c"}, "c"),
        pc_shape._Output(None, None, {"say": "d"}, "d"),
    ]
    document = pc_shape._together_request(outputs)
    assert document[output.BATCH_SUBJECTS_KEY] == [tree, view]
    entries = document[output.BATCH_OUTPUTS_KEY]
    assert [entry.get(output.BATCH_SUBJECT_KEY) for entry in entries] == [0, 1, 0, None]
    assert all("wrapped" not in entry[output.BATCH_REQUEST_KEY] for entry in entries)
    # The requests themselves are left as they were.
    assert outputs[0].request["wrapped"] is tree


# --------------------------------------------------------------------------- #
# The wrapper                                                                 #
# --------------------------------------------------------------------------- #


def _wrapper_call(outputs, document):
    command = [sys.executable, WRAPPER]
    for path, directory, script in outputs:
        command += [path, directory, script]
    finished = subprocess.run(command, input=json.dumps(document), capture_output=True, text=True)
    answers = {}
    for line in finished.stdout.splitlines():
        if line.strip():
            answer = json.loads(line)
            answers[answer["output"]] = answer["result"]
    return finished, answers


def _script(directory, name, text):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text)
    return str(path)


def test_the_wrapper_answers_each_file_and_leaves_unanswered_what_it_could_not_start(tmp_path):
    script = _script(tmp_path / "package", "write.py", WRITE)
    outputs = [
        (str(tmp_path / "a.txt"), str(tmp_path / "package"), script),
        (str(tmp_path / "b.txt"), str(tmp_path / "gone"), script),
        (str(tmp_path / "c.txt"), str(tmp_path / "package"), script),
    ]
    document = {
        "outputs": [{"request": {"say": name}} for name in ("a", "b", "c")],
        "subjects": [],
    }

    finished, answers = _wrapper_call(outputs, document)

    assert finished.returncode == 0, finished.stderr
    assert sorted(answers) == [0, 2]
    assert answers[0]["success"] is True and answers[0]["files"] == []
    assert (tmp_path / "c.txt").read_text().startswith("c in package")


@pytest.fixture
def box():
    """A shape envelope holding a box, and the same box carrying a mesh."""
    pytest.importorskip("OCP")
    sys.path.insert(0, WRAPPERS)
    try:
        import ocp_serialize
    finally:
        sys.path.remove(WRAPPERS)
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    plain = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    meshed = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    BRepMesh_IncrementalMesh(meshed, 0.5)
    encode = ocp_serialize._brep_b64
    return {"name": "box", "label": None, "brep": encode(plain)}, {"name": "box", "label": None, "brep": encode(meshed)}


# Remembers the shape it was handed, in the process, and says whether the one
# it is handed now shares its geometry with the last one.
PROBE = textwrap.dedent("""
    import builtins

    {declaration}


    def process(path, request):
        shape = request["wrapped"]
        last = getattr(builtins, "_probe_last", None)
        builtins._probe_last = shape
        with open(path, "w") as f:
            f.write("shared" if last is not None and last.IsPartner(shape) else "own")
        return {{"success": True, "files": []}}
    """)


def test_files_that_mesh_alike_share_one_decoding_of_the_object(tmp_path, box):
    plain, _meshed = box
    declared = _script(tmp_path / "pkg", "declared.py", PROBE.format(declaration='TESSELLATION = ("m", "tolerance")'))
    silent = _script(tmp_path / "pkg", "silent.py", PROBE.format(declaration=""))
    directory = str(tmp_path / "pkg")
    names = ["first", "second", "coarser", "silent", "third"]
    scripts = [declared, declared, declared, silent, declared]
    tolerances = [0.1, 0.1, 0.5, 0.1, 0.1]
    outputs = [(str(tmp_path / name), directory, script) for name, script in zip(names, scripts)]
    document = {
        "outputs": [{"request": {"tolerance": tolerance}, "subject": 0} for tolerance in tolerances],
        "subjects": [plain],
    }

    finished, answers = _wrapper_call(outputs, document)

    assert finished.returncode == 0, finished.stderr
    assert len(answers) == 5
    written = {name: (tmp_path / name).read_text() for name in names}
    # The three alike are written one after another from one decoding; the one
    # meshed coarser, and the one that says nothing, each from one of its own.
    assert written == {"first": "own", "second": "shared", "third": "shared", "coarser": "own", "silent": "own"}


def test_an_object_that_arrived_with_a_mesh_on_it_is_decoded_for_each_file(tmp_path, box):
    _plain, meshed = box
    declared = _script(tmp_path / "pkg", "declared.py", PROBE.format(declaration='TESSELLATION = ("m", "tolerance")'))
    names = ["first", "second"]
    outputs = [(str(tmp_path / name), str(tmp_path / "pkg"), declared) for name in names]
    document = {"outputs": [{"request": {"tolerance": 0.1}, "subject": 0}] * 2, "subjects": [meshed]}

    finished, answers = _wrapper_call(outputs, document)

    assert finished.returncode == 0, finished.stderr
    assert len(answers) == 2
    assert [(tmp_path / name).read_text() for name in names] == ["own", "own"]


# --------------------------------------------------------------------------- #
# The built-in file types, in a real sandbox                                  #
# --------------------------------------------------------------------------- #

SCREW = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "..",
    "examples",
    "feature_interface",
    "socket-head-m3-screw-6mm.step",
)


def _contents(path):
    """A file's bytes, less what the format stamps with the clock: a 3MF's creation date."""
    import re
    import zipfile

    if path.endswith(".3mf"):
        with zipfile.ZipFile(path) as archive:
            return [(name, re.sub(rb'"CreationDate">[^<]*<', b"", archive.read(name))) for name in archive.namelist()]
    with open(path, "rb") as f:
        return f.read()


@pytest.mark.slow
def test_built_in_files_written_together_are_the_files_written_alone(tmp_path, monkeypatch):
    """Byte for byte, the file types that share a decoding and a mesh included.

    The SVG, the STL, the OBJ and the three.js file run in the sandbox's own
    environment and are written by one call, the PNG and the JPEG in the layer
    that rasterizes and by another, and the 3MF in CadQuery's, alone. PNG and
    JPEG share a decoding and a mesh ('render_svg.TESSELLATION'), and so do OBJ
    and three.js: a file written after its group's first one finds that one's
    mesh on the shape, and has to come out as though it had made it.
    """
    from partcad import runtime_python

    root = tmp_path / "package"
    root.mkdir()
    with open(SCREW, "rb") as source, open(root / "screw.step", "wb") as target:
        target.write(source.read())
    (root / "partcad.yaml").write_text(textwrap.dedent("""
        name: //together
        parts:
          screw:
            type: step
        render:
          svg:
          png:
          jpeg:
        export:
          stl:
          3mf:
          obj:
          threejs:
            extension: three.json
        """))

    calls = []
    original = runtime_python.PythonRuntime.run_async_onced

    async def counted(self, cmd, *args, **kwargs):
        if os.path.basename(str(cmd[0])) == "wrapper_export.py":
            calls.append((len(cmd) - 1) // 3)
        return await original(self, cmd, *args, **kwargs)

    monkeypatch.setattr(runtime_python.PythonRuntime, "run_async_onced", counted)

    formats = ("svg", "png", "jpeg", "stl", "3mf", "obj", "threejs")
    ctx = pc.Context(str(root))
    ctx.cache_artifacts = None
    together, alone = tmp_path / "together", tmp_path / "alone"
    asyncio.run(ctx.get_project("//").render_async(output_dir=str(together)))
    assert sorted(calls) == [1, 2, 4]

    part = ctx.get_part("//:screw")
    for format_name in formats:
        asyncio.run(part.render_async(ctx, format_name, output_dir=str(alone)))

    names = sorted(os.listdir(alone))
    assert names == sorted(os.listdir(together)) and len(names) == len(formats)
    for name in names:
        assert _contents(str(together / name)) == _contents(str(alone / name)), name
