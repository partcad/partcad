#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The shared machinery of partTypes and sketchTypes, without the sandbox.

'partcad.type_wrapper' resolves a type, finds its script, runs it and reads
the answer, for parts and sketches alike; 'wrapper_common.sketch_answer' is
what the wrapper makes of a sketchType script's shapes. The sandbox runs are
in 'test_sketch_type.py'; these are the paths a run should never reach -- a
type that is not there, a script that is not, an answer that is not one --
checked in this process, with the runtime stood in for.
"""

import asyncio
import base64
import os
import sys
import textwrap

import pytest

import partcad as pc
from partcad import shape_envelope
from partcad.cache_hash import CacheHash
from partcad.type_wrapper import TypeWrapperFactory

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_common  # noqa: E402


def _package(path, text):
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "partcad.yaml"), "w") as f:
        f.write(textwrap.dedent(text))


def _factory(sketch):
    """The factory that built 'sketch': the one its 'instantiate' closes over."""
    return sketch.instantiate.__closure__[0].cell_contents


class _Runtime:
    """A sandbox that answers 'answer' to whatever it is asked to run."""

    version = "3.12"
    path = "/nowhere"

    def __init__(self, answer, exitcode=0, errors=""):
        self.answer, self.exitcode, self.errors = answer, exitcode, errors
        self.commands = []

    async def prepare_for_package(self, *args, **kwargs):
        pass

    async def prepare_for_shape(self, *args, **kwargs):
        pass

    async def ensure_async(self, *args, **kwargs):
        pass

    async def run_async(self, command, request, session=None):
        self.commands.append((command, request))
        return self.exitcode, self.answer, self.errors


def _sketch(tmp_path, sketch_types, script="outline.py", type_ref=":outline"):
    _package(
        tmp_path,
        """
        sketchTypes:
        %s
        sketches:
          s:
            type: "%s"
        """ % (textwrap.indent(textwrap.dedent(sketch_types), "  "), type_ref),
    )
    if script:
        (tmp_path / script).write_text("CACHE_VERSION = 1\n")
    ctx = pc.Context(str(tmp_path))
    return ctx, ctx.get_sketch(":s")


def _instantiate(sketch):
    return asyncio.run(_factory(sketch).instantiate(sketch))


# --------------------------------------------------------------------------- #
# What a subclass has to say                                                  #
# --------------------------------------------------------------------------- #


def test_the_base_class_says_nothing_of_its_own():
    base = TypeWrapperFactory()
    with pytest.raises(NotImplementedError):
        base._type_config(None, "x")
    with pytest.raises(NotImplementedError):
        base.shape_object()
    assert base._builtin_type_package(None, "x") is None


# --------------------------------------------------------------------------- #
# A type that cannot be used                                                  #
# --------------------------------------------------------------------------- #


def test_a_type_of_a_package_that_is_not_there_fails_the_sketch(tmp_path):
    ctx, sketch = _sketch(tmp_path, "outline: {path: outline.py}", type_ref="nowhere:outline")
    assert _factory(sketch)._type_versions() is None
    assert _instantiate(sketch) is None
    assert any("package not found" in str(e) for e in sketch.errors), sketch.errors


def test_a_type_its_package_does_not_declare_fails_the_sketch(tmp_path):
    ctx, sketch = _sketch(tmp_path, "outline: {path: outline.py}", type_ref=":nope")
    assert _factory(sketch)._type_versions() is None
    assert _instantiate(sketch) is None
    assert any("sketchType 'nope' not found" in str(e) for e in sketch.errors), sketch.errors


def test_a_kind_other_than_wrapper_fails_the_sketch(tmp_path):
    ctx, sketch = _sketch(tmp_path, "outline: {path: outline.py, kind: native}")
    assert _instantiate(sketch) is None
    assert any("Unsupported sketchType kind 'native'" in str(e) for e in sketch.errors), sketch.errors


def test_a_file_backed_sketch_whose_file_is_not_there_fails(tmp_path):
    ctx, sketch = _sketch(tmp_path, "outline: {path: outline.py, extension: outline}")
    assert _instantiate(sketch) is None
    assert any("file is not found" in str(e) for e in sketch.errors), sketch.errors


def test_a_script_that_is_not_there_fails_the_sketch(tmp_path):
    ctx, sketch = _sketch(tmp_path, "outline: {path: outline.py}", script=None)
    assert _instantiate(sketch) is None
    assert any("wrapper script not found" in str(e) for e in sketch.errors), sketch.errors


# --------------------------------------------------------------------------- #
# A script a repository plugin serves                                         #
# --------------------------------------------------------------------------- #


class _Served:
    """A plugin-backed package: its files come from 'get_data_async'."""

    def __init__(self, config_dir, served):
        self.config_dir = str(config_dir)
        self.served = served

    async def get_data_async(self, key):
        return self.served.get(key)


def test_a_served_script_is_written_into_the_package_and_found_there_next_time(tmp_path):
    factory = TypeWrapperFactory()
    factory.TYPE_KIND = "sketchType"
    package = _Served(tmp_path, {"files/types/outline.py": base64.b64encode(b"CACHE_VERSION = 2\n").decode()})
    written = asyncio.run(factory._materialize_wrapper_script(package, "types/outline.py"))
    assert written == str(tmp_path / "types" / "outline.py")
    assert (tmp_path / "types" / "outline.py").read_bytes() == b"CACHE_VERSION = 2\n"
    # Nothing half-written is left beside it.
    assert os.listdir(tmp_path / "types") == ["outline.py"]
    package.served = {}
    assert asyncio.run(factory._materialize_wrapper_script(package, "types/outline.py")) == written


def test_a_script_the_repository_does_not_serve_is_an_error(tmp_path):
    factory = TypeWrapperFactory()
    factory.TYPE_KIND = "sketchType"
    with pytest.raises(Exception, match="did not provide the sketchType wrapper"):
        asyncio.run(factory._materialize_wrapper_script(_Served(tmp_path, {}), "outline.py"))


# --------------------------------------------------------------------------- #
# What the wrapper answers                                                    #
# --------------------------------------------------------------------------- #


def _answering(tmp_path, answer, exitcode=0, errors=""):
    ctx, sketch = _sketch(tmp_path, "outline: {path: outline.py}")
    runtime = _Runtime(answer, exitcode, errors)
    _factory(sketch).runtime = runtime
    return sketch, runtime


def test_an_answer_that_is_not_one_fails_the_sketch(tmp_path):
    sketch, runtime = _answering(tmp_path, b"", exitcode=3)
    assert _instantiate(sketch) is None
    assert any("Deserialization error" in str(e) for e in sketch.errors), sketch.errors
    # The script ran under the one wrapper, told it is building a sketch.
    command, request = runtime.commands[0]
    assert os.path.basename(command[0]) == "wrapper_part_type.py"
    assert shape_envelope.deserialize(request)["kind"] == "sketch"


def test_a_failure_the_script_reports_fails_the_sketch(tmp_path):
    sketch, _ = _answering(tmp_path, shape_envelope.serialize({"success": False, "exception": "a bad outline"}))
    assert _instantiate(sketch) is None
    assert any("a bad outline" in str(e) for e in sketch.errors), sketch.errors


def test_an_answer_with_no_component_fails_the_sketch(tmp_path):
    answer = shape_envelope.serialize({"success": True, "shape": None, "components": [[]]})
    sketch, _ = _answering(tmp_path, answer, errors="a line the script printed")
    assert _instantiate(sketch) is None
    assert any("no edge, wire or face" in str(e) for e in sketch.errors), sketch.errors


def test_the_sketch_says_which_sandbox_built_it(tmp_path):
    sketch, runtime = _answering(tmp_path, b"")
    info = _factory(sketch).info(sketch)
    assert info["sandbox_version"] == runtime.version
    assert info["sandbox_path"] == runtime.path


def test_a_script_that_cannot_tell_what_it_read_leaves_the_sketch_uncached(tmp_path):
    ctx, sketch = _sketch(tmp_path, "outline: {path: outline.py}")
    factory = _factory(sketch)
    asyncio.run(factory.record_reported_async(sketch, {"dependencies": None}))  # not keyed on any: nothing
    factory._declared_key = sketch.hash.snapshot()
    before = sketch.hash
    asyncio.run(factory.record_reported_async(sketch, {"dependencies": None}))
    assert sketch.hash is not before
    assert isinstance(sketch.hash, CacheHash) and sketch.hash.get() is None


# --------------------------------------------------------------------------- #
# The wrapper's side: 'wrapper_common.sketch_answer'                          #
# --------------------------------------------------------------------------- #


def _face_with_hole():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

    outer = BRepBuilderAPI_MakeWire()
    points = [(0, 0), (10, 0), (10, 10), (0, 10)]
    for a, b in zip(points, points[1:] + points[:1]):
        outer.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(*a, 0), gp_Pnt(*b, 0)).Edge())
    face = BRepBuilderAPI_MakeFace(outer.Wire(), True)
    circle = gp_Circ(gp_Ax2(gp_Pnt(5, 5, 0), gp_Dir(0, 0, -1)), 2)
    face.Add(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire())
    return face.Face()


def _open_wire():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Pnt

    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 12, 0), gp_Pnt(10, 12, 0)).Edge()).Wire()


class _Wrapping:
    """What a build123d object is to the wrapper: something holding a shape in 'wrapped'."""

    def __init__(self, wrapped):
        self.wrapped = wrapped


def test_build123d_objects_are_unwrapped_however_deep():
    face, wire = _face_with_hole(), _open_wire()
    assert wrapper_common.unwrapped([_Wrapping(face), [_Wrapping(wire), None]]) == [face, [wire, None]]
    assert list(wrapper_common.flattened([face, [wire, [None]]])) == [face, wire, None]


def test_a_face_with_a_hole_and_an_open_wire_are_a_sketch_of_two_components():
    answer = wrapper_common.sketch_answer([_face_with_hole(), _open_wire()])
    assert answer["success"], answer
    assert len(answer["components"]) == 2
    assert answer["shape"] is not None


@pytest.mark.parametrize("shapes", [[], [[]], [[None]]])
def test_no_edge_wire_or_face_is_no_sketch(shapes):
    answer = wrapper_common.sketch_answer(shapes)
    assert not answer["success"]
    assert "no edge, wire or face" in answer["exception"]


def test_a_solid_is_no_sketch():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    answer = wrapper_common.sketch_answer([_face_with_hole(), BRepPrimAPI_MakeBox(1, 1, 1).Shape()])
    assert not answer["success"]
    assert "solid" in answer["exception"]


@pytest.mark.parametrize(
    "output, carried",
    [
        ({}, None),
        ({"dependencies": None}, {"dependencies": None}),
        ({"dependencies": ["a.dat", 3, "b.dat"]}, {"dependencies": ["a.dat", "b.dat"]}),
        ({"dependencies": "a.dat"}, {}),
    ],
)
def test_what_a_script_read_is_carried_as_it_said_it(output, carried):
    answer = {}
    wrapper_common.carry_dependencies(output, answer)
    assert answer == (carried or {})


def test_a_sketch_is_what_the_wrapper_answers(tmp_path):
    """The success path, with the wrapper's own answer for a face with a hole and an open wire."""
    answer = wrapper_common.sketch_answer([_face_with_hole(), _open_wire()])
    sketch, _ = _answering(tmp_path, shape_envelope.serialize(answer))
    assert _instantiate(sketch) is not None, sketch.errors
    assert len(sketch.components) == 2


def test_a_script_on_another_drive_is_outside_its_package(tmp_path, monkeypatch):
    """'commonpath' raises for paths on two Windows drives: that is outside, not an error of its own."""
    factory = TypeWrapperFactory()
    factory.TYPE_KIND = "sketchType"

    def other_drive(paths):
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr(os.path, "commonpath", other_drive)
    with pytest.raises(ValueError, match="outside its package"):
        factory._script_path(_Served(tmp_path, {}), "outline.py")
