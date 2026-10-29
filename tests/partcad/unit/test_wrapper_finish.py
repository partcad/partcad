#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every wrapper that builds a part hands it out finished, run as the sandbox runs it.

A part factory asks the wrapper building a part to validate it and move it
before it answers ('Shape.finish_request', 'wrapper_common.finished'), and
whether a wrapper does is a matter of one call on its way out - one per wrapper,
and easy to lose in an edit. So each one is run here the way a sandbox runs it:
the script itself, as '__main__', reading its request from standard input and
writing its answer to standard output through 'wrapper_common', only in this
process rather than a fresh interpreter, so that what it does is measured. The
request is the frame the core sends a Python wrapper ('shape_envelope.serialize'),
and so is the answer, which is read back with the core's own codec and has to
carry the claim and the geometry the claim describes.

The script wrappers (build123d, cadquery) and the SDF one need packages this
environment does not install; they are run in a sandbox by
'test_part_finish.py' and 'test_part_shell.py'.
"""

import io
import locale
import os
import runpy
import sys

import pytest
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepTools import BRepTools
from OCP.gp import gp_Pnt
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.StlAPI import StlAPI_Writer

import partcad as pc
from partcad import shape_envelope
from partcad_utils import framing

WRAPPERS = os.path.join(os.path.dirname(pc.__file__), "wrappers")
sys.path.append(WRAPPERS)
import ocp_serialize  # noqa: E402
import wrapper_common  # noqa: E402

OFFSET = [[10, 0, 0], [0, 0, 1], 0]


def _finish(solidify=True):
    return {"validate": {"solidify": solidify}, "offset": OFFSET, "scale": 2}


@pytest.fixture
def run(monkeypatch, capsysbinary):
    """Run 'wrapper_<name>.py' on 'argument' with 'request' on its stdin; its answer, as the core reads it.

    Asked as the core asks a Python wrapper, in a frame, unless 'form' is
    "json", which is how a wrapper a container runs is asked; either way the
    answer has to come back in the form it was asked in ('wrapper_common
    .handle_output'). Standard input and output are bytes, as a pipe is: a
    frame's payloads are raw.

    Everything a wrapper changes about the process it runs in is put back: the
    module state 'wrapper_common' keeps for the response, the search path each
    script appends to, and the locale 'handle_input' sets. The response channel
    is left where it is - standard output, which is captured - rather than
    moved off file descriptor 1, which would take pytest's own output with it.
    """
    for name in ("_request_finish", "_request_name", "_request_label"):
        monkeypatch.setattr(wrapper_common, name, None)
    monkeypatch.setattr(wrapper_common, "_answer_framed", False)
    monkeypatch.setattr(wrapper_common, "_response_fd", None)
    monkeypatch.setattr(wrapper_common, "protect_response_channel", lambda: None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    saved_locale = locale.setlocale(locale.LC_ALL)

    def answer(name, argument, request, form="frame"):
        script = os.path.join(WRAPPERS, "wrapper_%s.py" % name)
        monkeypatch.setattr(sys, "argv", [script, str(argument)])
        if form == "frame":
            data = ocp_serialize.serialize(request)
        else:
            data = ocp_serialize.dumps(request).encode("utf-8")
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))
        capsysbinary.readouterr()
        runpy.run_path(script, run_name="__main__")
        out = capsysbinary.readouterr().out
        assert (framing.find_message(out) is not None) is (form == "frame"), out[:200]
        return shape_envelope.deserialize(out)

    yield answer
    locale.setlocale(locale.LC_ALL, saved_locale)


def _request(finish, **fields):
    return {"name": "//test:thing", "label": "thing", ocp_serialize.KEY_FINISH: finish, **fields}


def _finished(answer, key="shape"):
    """The shape in 'answer', the claim taken off it, and what it measured."""
    assert answer["success"], answer.get("exception")
    shape = answer[key][0] if key == "shapes" else answer[key]
    shape, claim = shape_envelope.take_finished(shape)
    assert shape["name"] == "//test:thing"
    return claim, shape_envelope.metadata_of(shape)[shape_envelope.METADATA_MEASUREMENTS]


def _box():
    return BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()


def _square():
    polygon = BRepBuilderAPI_MakePolygon()
    for x, y in ((0, 0), (10, 0), (10, 10), (0, 10)):
        polygon.Add(gp_Pnt(x, y, 0))
    polygon.Close()
    return BRepBuilderAPI_MakeFace(polygon.Wire()).Face()


# The box above, moved 10 in X and scaled about the origin by two.
MOVED_BOX = [20.0, 0.0, 0.0, 40.0, 40.0, 60.0]


@pytest.fixture
def step(tmp_path):
    path = tmp_path / "box.step"
    writer = STEPControl_Writer()
    writer.Transfer(_box(), STEPControl_AsIs)
    assert writer.Write(str(path))
    return path


@pytest.fixture
def stl(tmp_path):
    path = tmp_path / "box.stl"
    box = _box()
    BRepMesh_IncrementalMesh(box, 0.1)
    writer = StlAPI_Writer()
    assert writer.Write(box, str(path))
    return path


def test_a_step_part_is_judged_not_converted_and_moved(run, step):
    claim, measured = _finished(run("step", step, _request(_finish(solidify=False))))
    assert claim == {"validated": {"solidify": False, "problems": []}, "offset": OFFSET, "scale": 2}
    assert measured["bbox"] == pytest.approx(MOVED_BOX, abs=1e-6)


@pytest.mark.parametrize("form", ["frame", "json"])
def test_a_brep_part_is_finished(run, tmp_path, form):
    """Asked in JSON too, as a wrapper a container runs is, and answered with the same claim in JSON."""
    path = tmp_path / "box.brep"
    BRepTools.Write_s(_box(), str(path))
    claim, measured = _finished(run("brep", path, _request(_finish(solidify=False)), form=form))
    assert list(claim) == ["validated", "offset", "scale"]
    assert measured["volume"] == pytest.approx(6000.0 * 8)


def test_an_stl_part_is_finished(run, stl):
    claim, measured = _finished(run("stl", stl, _request(_finish())))
    # Judged: whatever OCCT makes of a solid of triangles is reported, not hidden.
    assert claim["validated"]["solidify"] is True
    assert isinstance(claim["validated"]["problems"], list)
    # Moved by the very functions the core's own sandbox moves a part with;
    # where those leave a mesh is theirs to answer for, the same either way.
    assert claim["offset"] == OFFSET and claim["scale"] == 2
    assert measured["solids"] == 1


def test_a_mesh_import_is_finished(run, stl):
    claim, measured = _finished(run("import_mesh", stl, _request(_finish(), fallback_import_stl=True)))
    assert list(claim) == ["validated", "offset", "scale"]
    assert measured["bbox"] is not None


def test_an_obj_part_is_finished_and_said_to_be_a_skin(run, tmp_path):
    path = tmp_path / "square.obj"
    path.write_text("v 0 0 0\nv 10 0 0\nv 10 10 0\nv 0 10 0\nf 1 2 3 4\n")
    claim, measured = _finished(run("obj", path, _request(_finish())))
    assert "it holds no solid" in claim["validated"]["problems"]
    assert measured["bbox"] == pytest.approx([20.0, 0.0, 0.0, 40.0, 20.0, 0.0], abs=1e-6)


def test_an_extrusion_is_finished(run, tmp_path):
    claim, measured = _finished(run("extrude", tmp_path / "unused", _request(_finish(), sketch=_square(), depth=5.0)))
    assert claim["validated"]["problems"] == []
    assert measured["bbox"] == pytest.approx([20.0, 0.0, 0.0, 40.0, 20.0, 10.0], abs=1e-6)


def test_a_sweep_is_finished(run, tmp_path):
    request = _request(_finish(), sketch=_square(), axis=[[0, 0, 10]], ratio=None, accumulate=False)
    claim, measured = _finished(run("sweep", tmp_path / "unused", request))
    assert list(claim) == ["validated", "offset", "scale"]
    assert measured["bbox"][5] == pytest.approx(20.0, abs=1e-6)


def test_a_part_type_s_shapes_leave_as_one_finished_part(run, tmp_path):
    script = tmp_path / "many.py"
    script.write_text(
        "from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox\n"
        "from OCP.gp import gp_Pnt\n"
        "output = {'shapes': [BRepPrimAPI_MakeBox(gp_Pnt(20.0 * i, 0, 0), 10, 10, 10).Shape() for i in range(3)]}\n"
    )
    answer = run("part_type", script, _request(_finish(), parameters={}))
    assert len(answer["shapes"]) == 1
    claim, measured = _finished(answer, key="shapes")
    assert claim["scale"] == 2
    assert measured["solids"] == 3
    assert measured["bbox"] == pytest.approx([20.0, 0.0, 0.0, 120.0, 20.0, 20.0], abs=1e-6)


def test_a_wrapper_asked_for_nothing_answers_as_it_always_did(run, tmp_path):
    """The same wrappers build what is not a part, and are then asked for none of it."""
    path = tmp_path / "box.brep"
    BRepTools.Write_s(_box(), str(path))
    answer = run("brep", path, {"name": "//test:thing", "label": "thing"})
    shape, claim = shape_envelope.take_finished(answer["shape"])
    assert claim == {}
    assert shape_envelope.metadata_of(shape)["measurements"]["bbox"] == pytest.approx([0, 0, 0, 10, 20, 30], abs=1e-6)
