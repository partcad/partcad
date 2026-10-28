#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'wrapper_export.py' writing several files of one object, run in this process.

In a sandbox the wrapper is an interpreter of its own: nothing measures it, and
whatever it changes is gone when it exits. Here it is loaded into the test's own
interpreter, and its '__main__' is run as a sandbox runs it - the files to write
as arguments, the document on standard input, the answers on standard output -
so that what it does is measured. Everything a sandbox process is free to
change for good is then this worker's, and is put back: the working directory
each file is written from, the 'sys.path' an implementation appends to, the
modules it imports from beside it, the locale 'handle_input' sets, the collector
'run_together' freezes, and the descriptor 'protect_response_channel' would take
away from pytest's capture.

`test_output_batch.py` runs the same wrapper as a subprocess, under a render.
The tests that hand it geometry need OCP in this interpreter, as PartCAD's own
tests do, and skip without it.
"""

import gc
import importlib.util
import io
import json
import locale
import os
import runpy
import sys
import textwrap
import types

import pytest

import partcad as pc
from partcad import wrapper as pc_wrapper

WRAPPERS = os.path.dirname(os.path.abspath(pc_wrapper.get("export.py")))
WRAPPER = os.path.join(WRAPPERS, "wrapper_export.py")
EXPORTERS = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "builtin", "export")


@pytest.fixture
def wrapper_export(tmp_path, monkeypatch):
    """The wrapper as a module of this process, loaded afresh, and what running it changes put back afterwards.

    Afresh because it remembers what each script declared for as long as it is
    loaded, which in a sandbox is one call.
    """
    modules = set(sys.modules)
    locale_before = locale.setlocale(locale.LC_ALL)
    monkeypatch.syspath_prepend(WRAPPERS)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [WRAPPER])
    # Frozen for good in a sandbox, which ends; here the worker would carry a
    # frozen heap into every test after this one.
    frozen = []
    monkeypatch.setattr(gc, "freeze", lambda: frozen.append(True))
    spec = importlib.util.spec_from_file_location("partcad_test_batch_wrapper_export", WRAPPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    common = module.wrapper_common
    monkeypatch.setattr(common, "_response_fd", None)
    monkeypatch.setattr(common, "_request_name", None)
    monkeypatch.setattr(common, "_request_label", None)
    monkeypatch.setattr(common, "_request_finish", None)
    monkeypatch.setattr(common, "_answer_framed", False)
    monkeypatch.setattr(common, "protect_response_channel", lambda: None)
    module.frozen = frozen
    try:
        yield module
    finally:
        locale.setlocale(locale.LC_ALL, locale_before)
        for name in set(sys.modules) - modules:
            path = getattr(sys.modules[name], "__file__", None)
            if path and os.path.abspath(path).startswith((WRAPPERS, EXPORTERS)):
                del sys.modules[name]


@pytest.fixture
def wrapper_call(wrapper_export, monkeypatch, capsysbinary):
    """Run the wrapper's '__main__' for these files and this document, and read back what it answered.

    Handed the document as the core hands it, a frame ('shape_envelope.serialize'),
    and read back as the core reads it: several files are answered a frame each,
    by place ('wrapper_export.OUTPUT_KEY', 'Shape._together_answers'); one is
    answered as one always was, with its result alone.
    """
    from partcad import process_output
    from partcad import shape as pc_shape
    from partcad import shape_envelope

    def call(outputs, document):
        argv = [WRAPPER]
        for path, directory, script in outputs:
            argv += [path, directory, script]
        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(shape_envelope.serialize(document))))
        capsysbinary.readouterr()
        runpy.run_path(WRAPPER, run_name="__main__")
        said = process_output.answer(capsysbinary.readouterr().out)
        assert isinstance(said, bytes), "answered in the frame it was asked in: %r" % said[:200]
        if len(outputs) == 1:
            return shape_envelope.deserialize(said)
        return pc_shape._together_answers(said, len(outputs))

    return call


def _script(directory, name, text):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text)
    return str(path)


# Says what it was asked to say, which object it was handed, where it ran, and
# whether what an earlier file put in 'sys.path' was still there.
WRITE = textwrap.dedent("""
    import os
    import sys


    def process(path, request):
        if request.get("fail"):
            return {"success": False, "exception": "%s cannot be written" % request.get("say")}
        leaked = request.get("leak") in sys.path
        if request.get("leak"):
            sys.path.append(request["leak"])
        with open(path, "w") as f:
            f.write(
                "%s of %s in %s, leaked %s"
                % (request.get("say"), (request.get("wrapped") or {}).get("name"), os.path.basename(os.getcwd()), leaked)
            )
        return {"success": True, "files": []}
    """)


def test_the_wrapper_answers_each_file_and_leaves_unanswered_what_it_could_not_start(wrapper_call, tmp_path):
    """Each file is written as it would be on its own, and one it cannot even start is left for a call of its own."""
    script = _script(tmp_path / "package", "write.py", WRITE)
    outputs = [
        (str(tmp_path / "a.txt"), str(tmp_path / "package"), script),
        (str(tmp_path / "b.txt"), str(tmp_path / "gone"), script),
        (str(tmp_path / "c.txt"), str(tmp_path / "package"), script),
    ]
    document = {
        "outputs": [{"request": {"say": name, "leak": "/nowhere"}, "subject": 0} for name in ("a", "b", "c")],
        "subjects": [{"name": "bracket", "label": None}],
    }

    answers = wrapper_call(outputs, document)

    assert sorted(answers) == [0, 2]
    assert answers[0] == {"success": True, "exception": None, "files": []}
    # In its own working directory, handed the object, and with nothing the
    # first file put in 'sys.path'.
    assert (tmp_path / "c.txt").read_text() == "c of bracket in package, leaked False"
    assert not (tmp_path / "b.txt").exists()


def test_a_call_writing_one_file_is_answered_as_one_always_was(wrapper_call, tmp_path):
    """The request itself on standard input, and its result alone on standard output: no place, no line of its own."""
    script = _script(tmp_path / "package", "write.py", WRITE)
    request = {"say": "alone", "wrapped": {"name": "bracket", "label": None}}

    answer = wrapper_call([(str(tmp_path / "alone.txt"), str(tmp_path / "package"), script)], request)

    assert answer == {"success": True, "exception": None, "files": []}
    assert (tmp_path / "alone.txt").read_text() == "alone of bracket in package, leaked False"


def test_a_failed_file_is_answered_and_the_others_are_still_written(wrapper_call, tmp_path):
    """An implementation's own failure is an answer like any other; only the wrapper's own is left unanswered."""
    script = _script(tmp_path / "package", "write.py", WRITE)
    outputs = [(str(tmp_path / name), str(tmp_path / "package"), script) for name in ("a.txt", "b.txt")]
    document = {"outputs": [{"request": {"say": "a", "fail": True}}, {"request": {"say": "b"}}], "subjects": []}

    answers = wrapper_call(outputs, document)

    assert answers == {
        0: {"success": False, "exception": "a cannot be written"},
        1: {"success": True, "exception": None, "files": []},
    }
    assert (tmp_path / "b.txt").read_text() == "b of None in package, leaked False"


def test_a_call_asked_in_json_answers_a_line_per_file(wrapper_export, monkeypatch, capsysbinary, tmp_path):
    """In the form it was asked in (see 'wrapper_common.handle_output'): JSON, a line each, which the core reads too."""
    from partcad import process_output
    from partcad import shape as pc_shape

    script = _script(tmp_path / "package", "write.py", WRITE)
    outputs = [(str(tmp_path / name), str(tmp_path / "package"), script) for name in ("a.txt", "b.txt")]
    document = {"outputs": [{"request": {"say": "a"}}, {"request": {"say": "b"}}], "subjects": []}
    monkeypatch.setattr(sys, "argv", [WRAPPER] + [part for output_ in outputs for part in output_])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(document).encode("utf-8"))))
    capsysbinary.readouterr()

    runpy.run_path(WRAPPER, run_name="__main__")

    said = process_output.answer(capsysbinary.readouterr().out)
    assert isinstance(said, str)
    assert [json.loads(line)[wrapper_export.OUTPUT_KEY] for line in said.splitlines()] == [0, 1]
    assert pc_shape._together_answers(said, 2) == {
        0: {"success": True, "exception": None, "files": []},
        1: {"success": True, "exception": None, "files": []},
    }


def test_the_collector_is_frozen_once_however_many_decodings_are_let_go(wrapper_export, wrapper_call, tmp_path):
    """The first collection pays for the CAD stack; what survives it is frozen, so every later one looks only at what is new."""
    script = _script(tmp_path / "package", "write.py", WRITE)
    outputs = [(str(tmp_path / name), str(tmp_path / "package"), script) for name in ("a.txt", "b.txt", "c.txt")]
    document = {"outputs": [{"request": {"say": name}} for name in ("a", "b", "c")], "subjects": []}

    assert len(wrapper_call(outputs, document)) == 3
    # Three decodings of their own, each let go after its file.
    assert wrapper_export.frozen == [True]


@pytest.mark.parametrize(
    "document, handed",
    [
        ({"outputs": [{"request": {}}], "subjects": []}, "1 requests"),
        ({"subjects": []}, "none"),
        ([{"request": {}}, {"request": {}}], "none"),
    ],
    ids=["too-few", "no-requests", "not-a-document"],
)
def test_a_document_that_does_not_match_the_files_named_is_refused_before_anything_is_written(
    wrapper_export, tmp_path, document, handed
):
    """Every file it names is then left unanswered, and so written again by a call of its own."""
    script = _script(tmp_path / "package", "write.py", WRITE)
    outputs = [(str(tmp_path / name), str(tmp_path / "package"), script) for name in ("a.txt", "b.txt")]

    with pytest.raises(ValueError, match="Asked to write 2 files and handed %s" % handed):
        wrapper_export.run_together(outputs, document)
    assert not (tmp_path / "a.txt").exists()


# --------------------------------------------------------------------------- #
# Which files share a decoding of the object                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body, declared",
    [
        (
            'TESSELLATION = ("relative", "tolerance", "angularTolerance")\n',
            ("relative", "tolerance", "angularTolerance"),
        ),
        ('TESSELLATION: tuple = ("relative", "tolerance")\n', ("relative", "tolerance")),
        ('TESSELLATION = ["absolute"]\n', ("absolute",)),
        ('MESH = TESSELLATION = ("relative",)\n', ("relative",)),
        # Read, never run: what the script would fail at is no concern of this.
        ('import a_module_nobody_has\nTESSELLATION = ("relative",)\n', ("relative",)),
        # Anything but a literal tuple or list of names is saying nothing.
        ('TESSELLATION = tuple(["relative"])\n', None),
        ("TESSELLATION = ()\n", None),
        ('TESSELLATION = ("relative", 0.1)\n', None),
        ('TESSELLATION = "relative"\n', None),
        ("TESSELLATION: tuple\n", None),
        ('MESH = ("relative",)\n\n\ndef process(path, request):\n    return {}\n', None),
        ('TESSELLATION = ("relative",\n', None),
    ],
    ids=[
        "tuple",
        "annotated",
        "list",
        "one-of-several-targets",
        "never-run",
        "not-a-literal",
        "empty",
        "not-names",
        "a-string",
        "annotation-only",
        "undeclared",
        "not-python",
    ],
)
def test_what_an_implementation_declares_of_its_mesh_is_read_from_its_source(wrapper_export, tmp_path, body, declared):
    assert wrapper_export.declared_tessellation(_script(tmp_path, "impl.py", body)) == declared


def test_a_script_that_cannot_be_read_declares_nothing_and_each_is_read_once(wrapper_export, tmp_path):
    """Once per call: what a script declared is what it declared when the call began."""
    assert wrapper_export.declared_tessellation(str(tmp_path / "missing.py")) is None
    script = _script(tmp_path, "impl.py", 'TESSELLATION = ("relative", "tolerance")\n')
    assert wrapper_export.declared_tessellation(script) == ("relative", "tolerance")
    os.remove(script)
    assert wrapper_export.declared_tessellation(script) == ("relative", "tolerance")


def test_only_files_of_one_object_meshed_alike_with_the_same_values_may_share_a_decoding(wrapper_export, tmp_path):
    declared = _script(tmp_path, "declared.py", 'TESSELLATION = ("relative", "tolerance", "ports")\n')
    other = _script(tmp_path, "other.py", 'TESSELLATION = ("absolute", "tolerance", "ports")\n')
    silent = _script(tmp_path, "silent.py", "def process(path, request):\n    return {}\n")
    key = wrapper_export.sharing_key
    entry = {"subject": 0, "request": {"tolerance": 0.1, "ports": [{"name": "a", "sketch": {"brep": "..."}}]}}

    def changed(**request):
        return dict(entry, request=dict(entry["request"], **request))

    # What it does not mesh with is not asked about ...
    assert key(declared, changed(say="something else")) == key(declared, entry) is not None
    # ... and every value it meshes with is, sketches and all.
    assert key(declared, changed(tolerance=0.5)) != key(declared, entry)
    assert key(declared, changed(ports=[{"name": "b"}])) != key(declared, entry)
    # Another object, another way of meshing: another decoding.
    assert key(declared, dict(entry, subject=1)) != key(declared, entry)
    assert key(other, entry) != key(declared, entry)
    # And none at all for a script that says nothing, or a file of no object.
    assert key(silent, entry) is None
    assert key(None, entry) is None
    assert key(declared, dict(entry, subject=None)) is None
    assert key(declared, dict(entry, subject=True)) is None


def test_files_that_share_a_decoding_are_written_one_after_another(wrapper_export):
    """Each group where its first file was asked for; and nothing moved when two files are one path."""
    outputs = [("/out/%d" % index, "/pkg", "impl.py") for index in range(6)]
    keys = ["mesh", None, "coarser", "mesh", None, "coarser"]
    assert wrapper_export.plan(outputs, keys) == [0, 3, 1, 2, 5, 4]

    # Which of two at one path is left there is whichever is written last.
    outputs[4] = outputs[0]
    assert wrapper_export.plan(outputs, keys) == [0, 1, 2, 3, 4, 5]


def test_each_request_is_handed_the_object_it_names_and_only_that(wrapper_export):
    subjects = [{"name": "bracket"}, {"name": "bracket", "assembly": []}]
    entry = {"request": {"say": "a"}, "subject": 1}

    assert wrapper_export.request_of(entry, subjects) == {"say": "a", "wrapped": subjects[1]}
    assert entry == {"request": {"say": "a"}, "subject": 1}, "the document is left as it was"
    for subject in (None, 2, -1, True):
        assert wrapper_export.request_of({"request": {"say": "a"}, "subject": subject}, subjects) == {"say": "a"}
    assert wrapper_export.request_of({}, subjects) == {}


# --------------------------------------------------------------------------- #
# Sharing one decoding, with geometry                                         #
# --------------------------------------------------------------------------- #


def _envelope(wrapper_export, shape, name):
    return {"name": name, "label": None, "brep": wrapper_export.ocp_serialize.compressed_brep(shape)}


@pytest.fixture
def box(wrapper_export):
    """A shape envelope holding a box, and the same box carrying a mesh."""
    pytest.importorskip("OCP")
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    plain = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    meshed = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    BRepMesh_IncrementalMesh(meshed, 0.5)
    return _envelope(wrapper_export, plain, "box"), _envelope(wrapper_export, meshed, "box")


@pytest.fixture
def probe(monkeypatch):
    """Where the PROBE implementation remembers the last shape it was handed, in this process."""
    module = types.ModuleType("partcad_test_batch_probe")
    module.last = None
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


# Says whether the shape it is handed shares its geometry with the last one it
# was handed, in this process.
PROBE = textwrap.dedent("""
    import partcad_test_batch_probe as probe

    {declaration}


    def process(path, request):
        if request.get("fail"):
            return {{"success": False, "exception": "refused"}}
        shape = request["wrapped"]
        last, probe.last = probe.last, shape
        with open(path, "w") as f:
            f.write("shared" if last is not None and last.IsPartner(shape) else "own")
        return {{"success": True, "files": []}}
    """)


def test_files_that_mesh_alike_share_one_decoding_of_the_object(wrapper_call, tmp_path, box, probe):
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

    answers = wrapper_call(outputs, document)

    assert len(answers) == 5
    written = {name: (tmp_path / name).read_text() for name in names}
    # The three alike are written one after another from one decoding; the one
    # meshed coarser, and the one that says nothing, each from one of its own.
    assert written == {"first": "own", "second": "shared", "third": "shared", "coarser": "own", "silent": "own"}


def test_an_object_that_arrived_with_a_mesh_on_it_is_decoded_for_each_file(wrapper_call, tmp_path, box, probe):
    _plain, meshed = box
    declared = _script(tmp_path / "pkg", "declared.py", PROBE.format(declaration='TESSELLATION = ("m", "tolerance")'))
    names = ["first", "second"]
    outputs = [(str(tmp_path / name), str(tmp_path / "pkg"), declared) for name in names]
    document = {"outputs": [{"request": {"tolerance": 0.1}, "subject": 0}] * 2, "subjects": [meshed]}

    answers = wrapper_call(outputs, document)

    assert len(answers) == 2
    assert [(tmp_path / name).read_text() for name in names] == ["own", "own"]


def test_a_file_that_failed_lets_its_decoding_go(wrapper_call, tmp_path, box, probe):
    """It may have left the shapes half done, so the next file of its group starts from a decoding of its own."""
    plain, _meshed = box
    declared = _script(tmp_path / "pkg", "declared.py", PROBE.format(declaration='TESSELLATION = ("m", "tolerance")'))
    names = ["first", "failed", "after", "last"]
    outputs = [(str(tmp_path / name), str(tmp_path / "pkg"), declared) for name in names]
    requests = [{"tolerance": 0.1}, {"tolerance": 0.1, "fail": True}, {"tolerance": 0.1}, {"tolerance": 0.1}]
    document = {"outputs": [{"request": request, "subject": 0} for request in requests], "subjects": [plain]}

    answers = wrapper_call(outputs, document)

    assert answers[1] == {"success": False, "exception": "refused"}
    assert [(tmp_path / name).read_text() for name in ("first", "after", "last")] == ["own", "own", "shared"]


def test_a_mesh_on_a_face_or_on_an_edge_is_a_mesh_the_object_arrived_with(wrapper_export):
    """A sketch has no faces, and its mesh is the polygons on its edges."""
    pytest.importorskip("OCP")
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

    box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
    circle = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 5.0)).Edge()
    assert not wrapper_export.carries_mesh([box, circle])

    BRepMesh_IncrementalMesh(circle, 0.1)
    assert wrapper_export.carries_mesh([box, circle])
    BRepMesh_IncrementalMesh(box, 0.5)
    assert wrapper_export.carries_mesh([box])


# --------------------------------------------------------------------------- #
# The built-in exporters, in this process                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def cylinder(wrapper_export):
    """A shape whose mesh depends on both tolerances: curved, so both the chord and the angle decide it."""
    pytest.importorskip("OCP")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    return _envelope(wrapper_export, BRepPrimAPI_MakeCylinder(5.0, 10.0).Shape(), "cylinder")


def test_built_in_exporters_written_together_write_what_they_write_alone(
    wrapper_call, wrapper_export, tmp_path, cylinder
):
    """Byte for byte, OBJ and three.js meshed once between them, and STL - which meshes otherwise - on its own.

    'test_output_batch.py' asks the same of every built-in file type in a real
    sandbox; this is the half of it that needs nothing but OCP.
    """
    names = {"stl": "export_stl.py", "obj": "export_obj.py", "three.json": "export_threejs.py"}
    request = {"tolerance": 0.1, "angularTolerance": 0.1, "reproducible": True}
    together = [
        (str(tmp_path / ("together." + ext)), str(tmp_path), os.path.join(EXPORTERS, script))
        for ext, script in names.items()
    ]
    entries = [{"request": dict(request), "subject": 0} for _ in names]
    keys = [wrapper_export.sharing_key(script, entry) for (_path, _directory, script), entry in zip(together, entries)]
    assert keys[0] != keys[1] == keys[2]

    answers = wrapper_call(together, {"outputs": entries, "subjects": [cylinder]})
    assert [answer["success"] for _index, answer in sorted(answers.items())] == [True] * 3

    for (path, directory, script), ext in zip(together, names):
        alone = str(tmp_path / ("alone." + ext))
        assert wrapper_call([(alone, directory, script)], dict(request, wrapped=cylinder))["success"] is True
        with open(path, "rb") as written, open(alone, "rb") as expected:
            assert written.read() == expected.read(), ext


def _cadquery(monkeypatch):
    """CadQuery as far as the 3MF exporter reaches it, which writes what it was asked to mesh with.

    CadQuery is not installed beside PartCAD (it runs in a layer of the sandbox
    of its own), and how it meshes with what it is handed is its business: what
    is PartCAD's is that the exporter hands it what it declares.
    """
    cadquery = types.ModuleType("cadquery")

    def export(_shape, path, **parameters):
        with open(path, "w") as f:
            f.write(json.dumps(parameters, sort_keys=True))

    cadquery.Solid = types.SimpleNamespace(makeBox=lambda *_size: types.SimpleNamespace(wrapped=None))
    cadquery.exporters = types.SimpleNamespace(export=export)
    monkeypatch.setitem(sys.modules, "cadquery", cadquery)


@pytest.mark.parametrize("script", ["export_stl.py", "export_obj.py", "export_threejs.py", "export_3mf.py"])
def test_a_built_in_exporter_meshes_with_every_parameter_it_declares(
    wrapper_export, tmp_path, cylinder, monkeypatch, script
):
    """What 'TESSELLATION' names is what two files' sharing is decided on, so each name has to change the mesh.

    A name the exporter does not mesh with - misspelt, say - leaves the one it
    does mesh with out of the key, and two files asking for different meshes
    would both be written from the first one's.
    """
    if script == "export_3mf.py":
        _cadquery(monkeypatch)
    path = os.path.join(EXPORTERS, script)
    declared = wrapper_export.declared_tessellation(path)
    assert declared is not None and declared[1:] == ("tolerance", "angularTolerance")
    fine = {"tolerance": 0.01, "angularTolerance": 1.0}
    coarse = {"tolerance": 1.0, "angularTolerance": 0.1}

    def written(name, **parameters):
        target = str(tmp_path / name)
        result = wrapper_export.run(path, target, dict(fine, wrapped=cylinder, **parameters))
        assert result["success"] is True, result
        with open(target, "rb") as f:
            return f.read()

    assert written("again") == written("base")
    for parameter in declared[1:]:
        assert written(parameter, **{parameter: coarse[parameter]}) != written("base"), parameter
