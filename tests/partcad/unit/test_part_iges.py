#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in 'iges' part type: an IGES file's solids, read by OpenCASCADE.

The files it reads are written here, by the same OpenCASCADE writer that 'pc
export -t iges' uses, in both of the ways IGES states a solid: as one (a
manifold solid B-rep) and as the faces that bound it (OCCT's default). What the
reader makes of each is held to the definition every part is (
'wrapper_common.solid_problems'), after the wrapper has stated each closed shell
as its solid ('wrapper_common.solidify') as it does for every part type.
"""

import asyncio
import importlib
import importlib.util
import math
import os
import runpy
import sys
from collections import Counter

import pytest
import yaml
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pln, gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.IGESCAFControl import IGESCAFControl_Writer
from OCP.IGESControl import IGESControl_Controller
from OCP.Interface import Interface_Static
from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402
import wrapper_common  # noqa: E402

BUILTIN_IMPORT = os.path.join(os.path.dirname(pc.__file__), "builtin", "import")
SCRIPT = os.path.join(BUILTIN_IMPORT, "part_iges.py")
PACKAGE = "tests/partcad/unit/data/import_iges/partcad.yaml"
PLATE = os.path.join(os.path.dirname(PACKAGE), "plate.igs")
# Eight bodies, several of them touching.
AERO_ASSEMBLY = "examples/feature_import/AeroAssembly.step"

# 30 x 20 x 10 mm, with an 8 mm hole through its 10 mm.
PLATE_VOLUME = 30 * 20 * 10 - math.pi * 4**2 * 10

RED, GREEN, BLUE = "#C91A09", "#237841", "#0055BF"


def _module():
    spec = importlib.util.spec_from_file_location("part_iges_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


part_iges = _module()


def _mapped(shape, kind):
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, found)
    return found


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, 1e-7, False)
    return props.Mass()


def _as_part(path):
    """'(shape, cmf)' of the file at 'path' as the wrapper hands it on: read, and each closed shell its solid."""
    shape, cmf = part_iges.read(str(path))
    return wrapper_common.solidify(shape), cmf


def _box(x=0.0, size=10.0):
    return BRepPrimAPI_MakeBox(gp_Pnt(x, 0, 0), size, size, size).Shape()


def _rgb(hex_color):
    return Quantity_Color(*(int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)), Quantity_TOC_sRGB)


def _write(path, bodies, as_solids=False):
    """Write 'bodies' to IGES at 'path' the way OCCT writes it: as solids, or as the faces that bound them.

    Each body is '(shape, colour)' or '(shape, colour, {face number: colour})',
    a colour '#RRGGBB' or None; the face numbers count from 0 in the order
    'TopExp::MapShapes' has them.
    """
    document = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    XCAFApp_Application.GetApplication_s().NewDocument(TCollection_ExtendedString("MDTV-XCAF"), document)
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colors = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    for body in bodies:
        shape, color, face_colors = (tuple(body) + ({},))[:3]
        label = shapes.AddShape(shape, False)
        if color:
            colors.SetColor(label, _rgb(color), XCAFDoc_ColorSurf)
        faces = _mapped(shape, TopAbs_FACE)
        for number, face_color in face_colors.items():
            colors.SetColor(shapes.AddSubShape(label, faces.FindKey(number + 1)), _rgb(face_color), XCAFDoc_ColorSurf)
    # The mode is a process-wide parameter, so it is put back as it was.
    IGESControl_Controller.Init_s()
    mode = Interface_Static.IVal_s("write.iges.brep.mode")
    assert Interface_Static.SetIVal_s("write.iges.brep.mode", 1 if as_solids else 0)
    try:
        writer = IGESCAFControl_Writer()
        writer.SetColorMode(True)
        assert writer.Transfer(document)
        assert writer.Write(str(path))
    finally:
        Interface_Static.SetIVal_s("write.iges.brep.mode", mode)
    return path


def _blank(path, entity_type, nth):
    """Mark the 'nth' entity of 'entity_type' in the IGES file at 'path' blanked, as a CAD application hides one."""
    lines = path.read_text().split("\n")
    seen = 0
    for number, line in enumerate(lines):
        # A directory entry is two lines; the first, at an odd sequence
        # number, has the entity type in columns 1-8 and the status in 65-72,
        # whose first two digits are the blank status.
        if len(line) >= 80 and line[72] == "D" and int(line[73:80]) % 2 == 1 and int(line[:8]) == entity_type:
            seen += 1
            if seen == nth:
                lines[number] = line[:64] + "01" + line[66:]
                path.write_text("\n".join(lines))
                return path
    raise AssertionError("no entity %d number %d in %s" % (entity_type, nth, path))


# ---------------------------------------------------------------------------
# What is declared
# ---------------------------------------------------------------------------


def test_iges_is_a_builtin_part_type_read_by_opencascade():
    with open(os.path.join(BUILTIN_IMPORT, "partcad.yaml")) as f:
        declared = yaml.safe_load(f)["partTypes"]["iges"]
    assert declared["path"] == "part_iges.py"
    assert declared["extension"] == "iges"
    assert declared["requireSolid"] is True


# ---------------------------------------------------------------------------
# What it reads
# ---------------------------------------------------------------------------


def test_a_surface_model_is_sewn_back_into_the_solid_it_bounds():
    """OCCT's default IGES: seven trimmed surfaces with nothing to say they are one body."""
    shape, cmf = _as_part(PLATE)
    assert _mapped(shape, TopAbs_SOLID).Extent() == 1
    assert _mapped(shape, TopAbs_FACE).Extent() == 7
    assert wrapper_common.solid_problems(shape) == []
    assert _volume(shape) == pytest.approx(PLATE_VOLUME, rel=1e-6)
    assert cmf is None


@pytest.mark.parametrize("as_solids", [False, True], ids=["as faces", "as solids"])
def test_what_opencascade_writes_reads_back_as_the_solids_it_wrote(tmp_path, as_solids):
    path = _write(tmp_path / "boxes.igs", [(_box(), None), (_box(20, 5), None)], as_solids=as_solids)
    shape, _ = _as_part(path)
    assert wrapper_common.solid_problems(shape) == []
    assert sorted(round(_volume(solid), 6) for solid in _solids(shape)) == [125.0, 1000.0]


def _solids(shape):
    found = _mapped(shape, TopAbs_SOLID)
    return [found.FindKey(index) for index in range(1, found.Extent() + 1)]


def test_the_bodies_of_an_assembly_written_as_faces_come_back_one_by_one(tmp_path):
    """Each body's faces are sewn with each other only, so bodies that touch are not sewn into each other.

    The eight bodies of an assembly, written as 'pc export -t iges' writes them:
    as faces, which OCCT groups body by body. Sewn all together, at the same
    tolerance, they make three solids that are not those eight.
    """
    from OCP.IGESControl import IGESControl_Writer
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    reader.ReadFile(AERO_ASSEMBLY)
    reader.TransferRoots()
    assembly = reader.OneShape()
    writer = IGESControl_Writer()
    writer.AddShape(assembly)
    writer.ComputeModel()
    path = tmp_path / "assembly.igs"
    assert writer.Write(str(path))

    shape, _ = _as_part(path)
    assert wrapper_common.solid_problems(shape) == []
    assert len(_solids(shape)) == 8
    assert _volume(shape) == pytest.approx(_volume(assembly), rel=1e-5)

    _, reader = part_iges._open(str(path))
    faces = _mapped(reader.OneShape(), TopAbs_FACE)
    every = [faces.FindKey(index) for index in range(1, faces.Extent() + 1)]
    sewn, _ = part_iges._sewn(every)
    together = wrapper_common.solidify(ocp_serialize.compound_of(sewn))
    assert len(_solids(together)) != 8 or wrapper_common.solid_problems(together) != []


def test_faces_that_do_not_close_are_left_open_to_be_judged(tmp_path):
    """A box with a face missing is an open shell, which is not a solid: the part is failed by the common check."""
    box = _box()
    faces = _mapped(box, TopAbs_FACE)
    open_box = ocp_serialize.compound_of([faces.FindKey(index) for index in range(1, faces.Extent())])
    shape, _ = _as_part(_write(tmp_path / "open.igs", [(open_box, None)]))
    assert _mapped(shape, TopAbs_SOLID).Extent() == 0
    assert _mapped(shape, TopAbs_FACE).Extent() == 5
    assert wrapper_common.solid_problems(shape) != []


def test_a_lone_face_is_handed_over_as_it_is(tmp_path):
    face = BRepBuilderAPI_MakeFace(gp_Pln(), 0, 10, 0, 10).Face()
    shape, _ = _as_part(_write(tmp_path / "face.igs", [(face, None)]))
    assert shape.ShapeType() == TopAbs_FACE
    assert wrapper_common.solid_problems(shape) != []


def test_a_file_of_curves_holds_no_solid(tmp_path):
    edge = BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0)).Edge()
    path = _write(tmp_path / "curve.igs", [(edge, None)])
    with pytest.raises(RuntimeError, match="curve.igs holds no solid"):
        part_iges.read(str(path))


def test_a_file_opencascade_cannot_read_is_an_error(tmp_path):
    # OCCT takes anything for IGES that it can open, and finds nothing in it.
    path = tmp_path / "unreadable.igs"
    path.write_text("not an IGES file\n")
    with pytest.raises(RuntimeError, match="could not read the geometry of unreadable.igs"):
        part_iges.read(str(path))
    with pytest.raises(RuntimeError, match="could not read missing.igs"):
        part_iges.read(str(tmp_path / "missing.igs"))


@pytest.mark.parametrize(("as_solids", "entity_type"), [(False, 402), (True, 186)], ids=["as faces", "as solids"])
def test_a_body_the_file_blanks_is_not_in_the_part(tmp_path, as_solids, entity_type):
    """A body is blanked by its group (402) when written as faces, and by its own entity (186) as a solid."""
    path = _write(tmp_path / "hidden.igs", [(_box(), None), (_box(20, 5), None)], as_solids=as_solids)
    shape, _ = _as_part(_blank(path, entity_type, 2))
    assert [round(_volume(solid), 6) for solid in _solids(shape)] == [1000.0]


@pytest.mark.parametrize("as_solids", [False, True], ids=["as faces", "as solids"])
def test_the_colours_the_file_puts_on_its_bodies_and_faces_come_with_the_part(tmp_path, as_solids):
    path = _write(tmp_path / "coloured.igs", [(_box(), RED, {0: GREEN}), (_box(20, 5), BLUE)], as_solids=as_solids)
    raw, cmf = part_iges.read(str(path))
    assert cmf["convention"] == "step"
    # One entry per face of the shape handed over, in its order: what the
    # wrapper reads them against.
    assert len(cmf["faces"]) == _mapped(raw, TopAbs_FACE).Extent() == 12
    assert Counter(entry["color"] for entry in cmf["faces"]) == {RED: 5, GREEN: 1, BLUE: 6}
    assert all(entry["rgba"][3] == 1 for entry in cmf["faces"])
    if as_solids:
        # A solid the file states keeps the colour stated of it.
        assert [entry["color"] for entry in cmf["solids"]] == [RED, BLUE]
    else:
        # What sewing makes is a shell, which its faces say what it is in.
        assert "solids" not in cmf


def test_a_file_without_colours_states_none(tmp_path):
    _, cmf = part_iges.read(str(_write(tmp_path / "plain.igs", [(_box(), None)], as_solids=True)))
    assert cmf is None


# ---------------------------------------------------------------------------
# As the sandbox runs it
# ---------------------------------------------------------------------------


def test_the_script_answers_with_the_shape_or_why_there_is_none(tmp_path):
    def run(path):
        return runpy.run_path(SCRIPT, init_globals={"request": {"path": str(path)}}, run_name="__partcad_part__")[
            "output"
        ]

    said = run(_write(tmp_path / "coloured.igs", [(_box(), RED)]))
    assert _mapped(said["shape"], TopAbs_FACE).Extent() == 6
    assert {entry["color"] for entry in said["cmf"]["faces"]} == {RED}
    assert "cmf" not in run(PLATE)

    unreadable = tmp_path / "unreadable.igs"
    unreadable.write_text("not an IGES file\n")
    assert "could not read" in run(unreadable)["exception"]


def test_the_wrapper_states_the_sewn_shells_as_solids_in_the_colours_of_their_faces(tmp_path, monkeypatch):
    """'part_iges.py' run by 'wrapper_part_type' as the sandbox runs it: solids, with the file's colours on them."""
    path = _write(tmp_path / "coloured.igs", [(_box(), RED, {0: GREEN}), (_box(20, 5), BLUE)])
    written = []
    monkeypatch.setattr(wrapper_common, "handle_input", lambda *_a, **_k: (SCRIPT, {"path": str(path)}))
    monkeypatch.setattr(wrapper_common, "handle_output", written.append)
    # The wrapper is a script: importing it runs the request it is handed.
    sys.modules.pop("wrapper_part_type", None)
    try:
        importlib.import_module("wrapper_part_type")
    finally:
        sys.modules.pop("wrapper_part_type", None)

    (said,) = written
    assert said["success"], said["exception"]
    (payload,) = said["shapes"]
    shape = ocp_serialize.decode_shape(payload)
    assert sorted(round(_volume(solid), 6) for solid in _solids(shape)) == [125.0, 1000.0]
    carried = ocp_serialize.cmf_of_payload(payload[ocp_serialize.KEY_BREP])
    assert Counter(carried.face_set(index).color for index in range(len(carried.faces))) == {RED: 5, GREEN: 1, BLUE: 6}
    assert {cmf_set.origin for cmf_set in carried.sets} == {"raw:step"}


# ---------------------------------------------------------------------------
# As a part of a package
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ctx():
    return pc.Context(PACKAGE)


@pytest.mark.slow
def test_an_iges_part_is_the_solid_its_faces_bound(ctx):
    part = ctx.get_part(":plate")
    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None, part.errors
    assert _volume(ocp_serialize.decode_shape(envelope)) == pytest.approx(PLATE_VOLUME, rel=1e-6)


@pytest.mark.slow
def test_what_pc_export_writes_as_iges_reads_back(ctx, tmp_path):
    exported = tmp_path / "plate.iges"
    asyncio.run(ctx.get_part(":plate").render_async(ctx, "iges", filepath=str(exported)))
    shape, _ = _as_part(exported)
    assert wrapper_common.solid_problems(shape) == []
    assert _volume(shape) == pytest.approx(PLATE_VOLUME, rel=1e-6)


@pytest.mark.slow
def test_an_iges_file_whose_faces_bound_no_solid_is_not_a_part(tmp_path):
    box = _box()
    faces = _mapped(box, TopAbs_FACE)
    _write(tmp_path / "open.igs", [(ocp_serialize.compound_of([faces.FindKey(i) for i in range(1, 6)]), None)])
    (tmp_path / "partcad.yaml").write_text("parts:\n  open:\n    type: iges\n    path: open.igs\n")
    ctx = pc.Context(str(tmp_path))
    part = ctx.get_part(":open")
    assert asyncio.run(part.get_wrapped(ctx)) is None
    assert any("is not a solid" in error for error in part.errors), part.errors
