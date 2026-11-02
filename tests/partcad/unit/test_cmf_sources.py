#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where a part's CMF comes from besides its parameters, and how it is converted (docs/design/cmf.md, section 7).

Pinned here:

- converting: a source's names are looked up by 'ids' in scope, an unclaimed
  colour becomes display-only 'rgba', an unclaimed material stays unset, both
  reported once; a material's colour claim colours what states no colour;
  PartCAD's own convention takes references; a package declares conventions
  of its own; 'cmfConvention' never reaches what 'set_cmf' said;
- STEP: colours and materials read through XCAF, with the geometry the plain
  reader produced, and written back the same way;
- scripts: build123d's '.color', CadQuery's options and 'set_cmf', each on the
  shapes it was said of, the more specific winning;
- meshes: a 3MF's objects each in its base material's colour;
- OpenSCAD: a colour-writing release is told by its version;
- 'pc import' of a STEP assembly: the parts keep their colours, and an
  instance's own colour is said of its link;
- finishing: a section is carried where the faces are kept, and dropped,
  saying so, where they are not.
"""

import asyncio
import logging
import os
import sys
import zipfile

import pytest
import yaml

import partcad as pc
from partcad import cmf, cmf_conventions, shape_envelope

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import cmf_section  # noqa: E402
from cmf_section import NONE, CmfSet, Section  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _declare(**values):
    return {name: {"type": "string", "default": value} for name, value in values.items()}


def _package(path, name="//src", parts=None, **sections):
    path.mkdir(parents=True, exist_ok=True)
    config = {"name": name, "parts": parts or {"box": {"type": "stl", "path": "box.stl"}}, **sections}
    (path / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (path / "box.stl").write_text("")
    return path


COLORS = {
    "signal-red": {"display": "#C91A09", "ids": {"step": "#c91a09", "sw": "Signal Red"}},
    "natural": {"display": "#A8A9AD"},
    "red": {"display": "#FF0000"},
}
MATERIALS = {"al-6061": {"density": 2700, "color": ":natural", "ids": {"step": "Aluminium 6061"}}}


def _raw(convention="step", **values):
    return Section([CmfSet(origin="raw:" + convention, **values)], 0)


def _ctx(tmp_path, **parts):
    root = _package(tmp_path / "pkg", parts=parts or None, colors=COLORS, materials=MATERIALS)
    return pc.Context(str(root))


def _converted(ctx, ref="//src:box", section=None, convention=None):
    part = ctx.get_part(ref)
    return cmf_conventions.convert(ctx, part, section, convention).own()


# ---------------------------------------------------------------- converting


def test_a_source_s_colour_is_the_declaration_that_claims_it(tmp_path):
    ctx = _ctx(tmp_path)
    own = _converted(ctx, section=_raw(color="#C91A09", rgba=(201, 26, 9, 1.0)))

    assert (own.color, own.origin) == ("//src:signal-red", "source:step")
    assert own.rgba == (201, 26, 9, 1.0)


def test_a_colour_nothing_claims_is_a_picture_of_itself_and_is_reported(tmp_path, caplog):
    ctx = _ctx(tmp_path)
    with caplog.at_level(logging.WARNING):
        own = _converted(ctx, section=_raw(color="#123456", rgba=(18, 52, 86, 1.0)))

    assert own.color == "//pub/std/color:rgba;color=123456FF"
    assert "nothing in scope claims color '#123456'" in caplog.text


def test_a_material_nothing_claims_is_left_for_the_parameters(tmp_path):
    ctx = _ctx(tmp_path)
    own = _converted(ctx, section=_raw(material="Unobtainium"))

    assert own.material is None


def test_a_claimed_material_colours_what_states_no_colour(tmp_path):
    ctx = _ctx(tmp_path)
    own = _converted(ctx, section=_raw(material="aluminium 6061"))

    assert own.material == "//src:al-6061"
    assert own.color == "//src:natural"
    assert own.rgba == (168, 169, 173, 1.0)


def test_a_finish_draws_as_declared_and_as_the_source_said_where_it_says_nothing(tmp_path):
    finishes = {"gloss": {"display": {"roughness": 0.1}, "ids": {"step": "Gloss"}}}
    root = _package(tmp_path / "pkg", colors=COLORS, materials=MATERIALS, finishes=finishes)
    ctx = pc.Context(str(root))
    own = _converted(ctx, section=_raw(finish="Gloss", roughness=0.7, metallic=0.4))

    assert own.finish == "//src:gloss"
    # Its declaration's roughness, and - as it says nothing of it - the source's metallic.
    assert (own.roughness, own.metallic) == (0.1, 0.4)


def test_partcad_s_own_convention_takes_references(tmp_path):
    ctx = _ctx(tmp_path)
    own = _converted(ctx, section=_raw("partcad", color=":red"))

    assert (own.color, own.origin) == ("//src:red", "source:partcad")


def test_cmf_convention_names_how_the_source_s_tool_is_read_and_only_that(tmp_path):
    ctx = _ctx(tmp_path)
    section = Section(
        [
            CmfSet(color="Signal Red", rgba=(201, 26, 9, 1.0), origin="raw:step"),
            CmfSet(color=":red", origin="raw:partcad"),
        ],
        0,
        faces=[0, 1],
    )
    part = ctx.get_part("//src:box")

    # A package's own convention, through the 'sw' key of 'ids'...
    (tmp_path / "pkg" / "partcad.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "//src",
                "parts": {"box": {"type": "stl", "path": "box.stl"}},
                "colors": COLORS,
                "cmfConventions": {"solidworks": {"extends": "step", "ids": "sw"}},
            }
        )
    )
    ctx = pc.Context(str(tmp_path / "pkg"))
    part = ctx.get_part("//src:box")
    converted = cmf_conventions.convert(ctx, part, section, "solidworks")

    assert converted.face_set(0).color == "//src:signal-red"
    # ...and never to what was said in PartCAD's own terms.
    assert converted.face_set(1).color == "//src:red"


def test_a_convention_looks_in_its_catalogs(tmp_path):
    _package(
        tmp_path / "pkg" / "vendor",
        name="//src/vendor",
        colors={"brand": {"display": "#0055BF", "ids": {"acme": "B-1"}}},
    )
    root = _package(
        tmp_path / "pkg",
        cmfConventions={"acme": {"extends": "step", "catalogs": ["//src/vendor"]}},
        **{"import": {"vendor": {"path": "vendor"}}},
    )
    ctx = pc.Context(str(root))

    own = _converted(ctx, section=_raw(color="B-1", rgba=(0, 85, 191, 1.0)), convention="acme")

    assert own.color == "//src/vendor:brand"


def test_an_assembly_is_keyed_on_what_its_items_source_cmf_is_converted_by(tmp_path):
    """A colour table that changes changes no part file: the assembly's key is what notices."""

    def described(ids):
        root = _package(tmp_path / ids.lstrip("#"), colors={"signal-red": {"display": "#C91A09", "ids": {"step": ids}}})
        ctx = pc.Context(str(root))
        return cmf.key_of(ctx, ctx.get_part("//src:box"))

    assert described("#C91A09") != described("#C91A0A")
    # A package that declares no CMF adds nothing to the key.
    plain = pc.Context(str(_package(tmp_path / "plain")))
    assert cmf.key_of(plain, plain.get_part("//src:box")) == {}


def test_what_converts_takes_in_the_package_a_convention_names_and_its_catalogs(tmp_path):
    _package(tmp_path / "pkg" / "vendor", name="//src/vendor", colors={"brand": {"ids": {"acme": "B-1"}}})
    _package(
        tmp_path / "pkg" / "acme",
        name="//src/acme",
        cmfConventions={"acme": {"extends": "step", "catalogs": ["//src/vendor"]}},
    )
    root = _package(
        tmp_path / "pkg",
        parts={"box": {"type": "stl", "path": "box.stl", "cmfConvention": "//src/acme:acme"}},
        **{"import": {"vendor": {"path": "vendor"}, "acme": {"path": "acme"}}},
    )
    ctx = pc.Context(str(root))

    # '//src' declares nothing; the convention's package and its catalog do.
    assert set(cmf.conversion_scope(ctx, ctx.get_part("//src:box"))) == {"//src/acme", "//src/vendor"}


def test_an_unknown_convention_is_reported_and_the_source_s_own_used(tmp_path, caplog):
    ctx = _ctx(tmp_path)
    pc.logging.reset_errors()
    own = _converted(ctx, section=_raw(color="#C91A09", rgba=(201, 26, 9, 1.0)), convention="nosuch")

    assert own.color == "//src:signal-red"
    assert pc.logging.had_errors is True


def test_an_instance_s_colour_is_converted_one_fact_at_a_time(tmp_path):
    ctx = _ctx(tmp_path)

    assert cmf_conventions.reference_for(ctx, "//src", "color", "#c91a09", (201, 26, 9, 1.0)) == "//src:signal-red"
    assert cmf_conventions.reference_for(ctx, "//src", "color", "#000000", (0, 0, 0, 1.0)) == (
        "//pub/std/color:rgba;color=000000FF"
    )
    assert cmf_conventions.reference_for(ctx, "//src", "material", "Unobtainium") is None


def test_the_core_converts_and_then_completes(tmp_path):
    """'apply_declared' converts the source's sets first, and the part's own parameters fill what is left."""
    pytest.importorskip("build123d")
    import build123d as bd
    import ocp_serialize

    ctx = _ctx(tmp_path, box={"type": "stl", "path": "box.stl", "parameters": _declare(material=":al-6061")})
    part = ctx.get_part("//src:box")
    section = Section(
        [CmfSet(color="#C91A09", rgba=(201, 26, 9, 1.0), origin="raw:step")], NONE, faces=[0] + [NONE] * 5
    )
    envelope = ocp_serialize.encode_shape(bd.Box(1, 2, 3).wrapped, cmf=section)

    applied, recorded = cmf.apply_declared(ctx, part, envelope, shape_envelope.metadata_of(envelope))

    result = cmf_section.split(shape_envelope.brep_plain(applied[shape_envelope.KEY_BREP]))[1]
    assert result.face_set(0).color == "//src:signal-red"
    assert result.face_set(1).color == "//src:natural"
    assert {result.face_set(i).material for i in range(6)} == {"//src:al-6061"}
    assert recorded[shape_envelope.METADATA_CMF]["unspecified"] == {}


# ---------------------------------------------------------------- STEP


def _wrappers():
    pytest.importorskip("build123d")
    import step_cmf

    return step_cmf


def test_a_step_file_s_colours_and_material_round_trip(tmp_path):
    step_cmf = _wrappers()
    import build123d as bd

    shape = bd.Box(10, 20, 30).wrapped
    section = Section(
        [
            CmfSet(color="#C91A09", rgba=(201, 26, 9, 1.0), material="Aluminium 6061", origin="raw:step"),
            CmfSet(material="Aluminium 6061", origin="raw:step"),
        ],
        1,
        faces=[0] + [NONE] * 5,
    )
    path = str(tmp_path / "box.step")
    step_cmf.write(path, shape, section)

    _read, found = step_cmf.read(path)

    assert found.face_set(0).color == "#C91A09"
    assert found.face_set(1).color is None
    assert found.solid_set(0).material == "Aluminium 6061"


def test_a_solid_s_own_style_wins_over_the_compound_around_it():
    """A red compound holding a box styled blue: the box is blue, the other red."""
    step_cmf = _wrappers()
    import build123d as bd
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    red_box = bd.Box(10, 10, 10).wrapped
    blue_box = bd.Pos(20, 0, 0) * bd.Box(10, 10, 10)
    compound = bd.Compound([bd.Solid(red_box), blue_box]).wrapped
    blue = [solid for solid in bd.Compound(compound).solids()][1].wrapped

    class _Facts:
        colors = [(compound, ("#FF0000", (255, 0, 0, 1.0))), (blue, ("#0000FF", (0, 0, 255, 1.0)))]
        definition_colors = []
        materials = []

        def __bool__(self):
            return True

    section = step_cmf.section_of(compound, _Facts())

    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(compound, TopAbs_FACE, faces)
    of_blue = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(blue, TopAbs_FACE, of_blue)
    # The compound's red was written onto every face before the solid was
    # styled; the solid's blue is what its faces are drawn in all the same.
    for i in range(faces.Extent()):
        expected = "#0000FF" if of_blue.Contains(faces.FindKey(i + 1)) else "#FF0000"
        assert section.face_set(i).color == expected
    assert {section.solid_set(i).color for i in range(2)} == {"#0000FF", None}


def test_each_placed_instance_of_a_solid_is_in_its_own_colour():
    """Two placements of one box, styled red and blue: read as the whole file, each is in its own."""
    step_cmf = _wrappers()
    import build123d as bd
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    box = bd.Box(10, 10, 10)
    here, there = box.wrapped, box.moved(bd.Location((20, 0, 0))).wrapped
    compound = bd.Compound([bd.Solid(here), bd.Solid(there)]).wrapped
    solids = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(compound, TopAbs_SOLID, solids)
    assert solids.Extent() == 2 and solids.FindKey(1).IsPartner(solids.FindKey(2))

    class _Facts:
        colors = [
            (solids.FindKey(1), ("#FF0000", (255, 0, 0, 1.0))),
            (solids.FindKey(2), ("#0000FF", (0, 0, 255, 1.0))),
        ]
        definition_colors = []
        materials = [(here, "ABS")]

        def __bool__(self):
            return True

    section = step_cmf.section_of(compound, _Facts())

    assert [section.solid_set(i).color for i in range(2)] == ["#FF0000", "#0000FF"]
    # A product's material is every instance of it, wherever it is placed.
    assert [section.solid_set(i).material for i in range(2)] == ["ABS", "ABS"]


def test_a_step_file_is_the_geometry_the_plain_reader_read(tmp_path):
    step_cmf = _wrappers()
    import ocp_serialize
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    path = os.path.join(ROOT, "examples", "feature_interface", "example-motor.step")
    reader = STEPControl_Reader()
    assert reader.ReadFile(path) == IFSelect_RetDone
    for index in range(reader.NbRootsForTransfer()):
        reader.TransferRoot(index + 1)
    plain = ocp_serialize.compound_of([reader.Shape(index + 1) for index in range(reader.NbShapes())])

    shape, section = step_cmf.read(path)

    assert ocp_serialize.shape_to_brep(shape) == ocp_serialize.shape_to_brep(plain)
    # Its faces in the six colours the file paints them.
    assert len({section.face_set(i).color for i in range(len(section.faces))}) == 6


# ---------------------------------------------------------------- scripts and meshes


def test_a_script_s_colours_land_on_the_shapes_they_were_said_of():
    pytest.importorskip("build123d")
    import build123d as bd
    import cmf_capture
    import ocp_serialize

    cmf_capture.reset()
    body = bd.Box(10, 10, 10)
    body.color = bd.Color(1, 0, 0)
    peg = bd.Pos(20, 0, 0) * bd.Box(2, 2, 2)
    cmf_capture.note_build123d(body)
    cmf_capture.set_cmf(peg, color=":blue", material=":pla")
    top = max(body.faces(), key=lambda face: face.center().Z)
    cmf_capture.set_cmf(top, color=":green")
    part = ocp_serialize.compound_of([body.wrapped, peg.wrapped])

    section = cmf_capture.section_for(part)

    colors = [section.face_set(i).color for i in range(len(section.faces))]
    assert colors.count("#FF0000") == 5
    assert colors.count(":green") == 1
    assert colors.count(":blue") == 6
    assert [section.solid_set(i).material for i in range(2)] == [None, ":pla"]
    cmf_capture.reset()


def test_a_cadquery_colour_option_is_noted():
    pytest.importorskip("build123d")
    import build123d as bd
    import cmf_capture
    import ocp_serialize

    cmf_capture.reset()
    box = bd.Box(1, 1, 1)
    cmf_capture.note_cadquery(box, {"color": (0, 0, 255), "alpha": 0.5})

    section = cmf_capture.section_for(ocp_serialize.compound_of([box.wrapped]))

    assert section.solid_set(0).color == "#0000FF"
    assert section.solid_set(0).rgba == (0, 0, 255, 0.5)
    cmf_capture.reset()


def _colored_3mf(path, boxes):
    """A 3MF of an object per box, each with a base material's display colour, as OpenSCAD's colour-writing releases write one."""
    import build123d as bd

    mesher = bd.Mesher()
    for box, _color in boxes:
        mesher.add_shape(box)
    plain = str(path) + ".plain.3mf"
    mesher.write(plain)
    with zipfile.ZipFile(plain) as source:
        model = [name for name in source.namelist() if name.endswith(".model")][0]
        xml = source.read(model).decode()
        bases = "".join('<base name="c%d" displaycolor="%s"/>' % (i, color) for i, (_box, color) in enumerate(boxes))
        xml = xml.replace("<resources>", '<resources><basematerials id="900">%s</basematerials>' % bases, 1)
        import re

        for index, object_id in enumerate(re.findall(r'<object id="(\d+)" type="model"[^>]*>\s*<mesh>', xml)):
            xml = xml.replace(
                '<object id="%s" type="model"' % object_id,
                '<object id="%s" type="model" pid="900" pindex="%d"' % (object_id, index),
                1,
            )
        with zipfile.ZipFile(str(path), "w") as out:
            for name in source.namelist():
                out.writestr(name, xml if name == model else source.read(name))


def test_a_3mf_is_every_object_in_it_each_in_its_colour(tmp_path):
    pytest.importorskip("build123d")
    import build123d as bd
    import cmf_capture

    path = tmp_path / "two.3mf"
    _colored_3mf(path, [(bd.Box(10, 10, 10), "#FF0000FF"), (bd.Pos(20, 0, 0) * bd.Box(10, 10, 10), "#0000FFFF")])

    shape, section = cmf_capture.read_mesh(str(path), "openscad")

    assert shape.ShapeType().name == "TopAbs_COMPOUND"
    assert [section.solid_set(i).color for i in range(2)] == ["#FF0000", "#0000FF"]
    assert {cmf_set.origin for cmf_set in section.sets} == {"raw:openscad"}


def test_a_3mf_that_cannot_be_read_in_colour_is_read_without_it(tmp_path, monkeypatch):
    """The STL fallback is for an STL: a 3MF is read again as Mesher reads it, and never handed to 'import_stl'."""
    pytest.importorskip("build123d")
    import build123d as bd
    import cmf_capture
    import wrapper_common

    path = tmp_path / "two.3mf"
    _colored_3mf(path, [(bd.Box(10, 10, 10), "#FF0000FF"), (bd.Pos(20, 0, 0) * bd.Box(10, 10, 10), "#0000FFFF")])

    def unreadable(*_args, **_kwargs):
        raise ValueError("not in colour")

    def not_an_stl(*_args, **_kwargs):
        raise AssertionError("a 3MF was handed to the STL reader")

    request = {"fallback_import_stl": True, "cmfConvention": "openscad"}
    written = []
    monkeypatch.setattr(wrapper_common, "handle_input", lambda *_args, **_kwargs: (str(path), request))
    monkeypatch.setattr(wrapper_common, "handle_output", written.append)
    monkeypatch.setattr(cmf_capture, "read_mesh", unreadable)
    monkeypatch.setattr(bd, "import_stl", not_an_stl)
    # The wrapper is a script: importing it runs the request it is handed.
    sys.modules.pop("wrapper_import_mesh", None)
    try:
        import wrapper_import_mesh  # noqa: F401
    finally:
        sys.modules.pop("wrapper_import_mesh", None)

    (said,) = written
    assert said["success"], said["exception"]
    assert len(bd.Compound(said["shape"]).solids()) == 2


def test_an_openscad_that_writes_colours_is_told_by_its_version():
    from partcad import part_factory_scad

    assert part_factory_scad._version_year("OpenSCAD version 2021.01") == 2021
    assert part_factory_scad._version_year("OpenSCAD version 2025.06.19") == 2025
    assert part_factory_scad._version_year("nonsense") is None
    assert part_factory_scad.FIRST_YEAR_WITH_COLORS > 2021


def test_the_openscad_command_asks_for_the_format_it_is_given():
    from partcad import part_factory_scad

    args, _ = part_factory_scad._build_render_args("openscad", "/tmp/out.3mf", "part.scad", {}, "3mf")
    assert args[:5] == ["openscad", "--export-format", "3mf", "-o", "/tmp/out.3mf"]
    args, _ = part_factory_scad._build_render_args("openscad", "/tmp/out.stl", "part.scad", {})
    assert args[2] == "binstl"


# ---------------------------------------------------------------- finishing


def test_finishing_keeps_a_section_where_the_faces_are_kept():
    pytest.importorskip("build123d")
    import build123d as bd
    import wrapper_common

    box = bd.Box(1, 2, 3).wrapped
    moved = bd.Pos(5, 0, 0) * bd.Box(1, 2, 3)
    section = Section([CmfSet(color="#FF0000", origin="raw:step")], NONE, solids=[0], faces=[0] * 6)

    assert wrapper_common.carried_cmf(section, box, moved.wrapped) is section
    assert wrapper_common.carried_cmf(section, box, box) is section


def test_finishing_that_rebuilds_the_faces_drops_the_section_and_says_so(capsys):
    pytest.importorskip("build123d")
    import build123d as bd
    import wrapper_common

    box = bd.Box(1, 2, 3).wrapped
    rebuilt = (bd.Box(1, 2, 3) - bd.Cylinder(0.2, 5)).wrapped
    section = Section([CmfSet(color="#FF0000", origin="raw:step")], NONE, faces=[0] * 6)

    assert wrapper_common.carried_cmf(section, box, rebuilt) is None
    assert "dropped" in capsys.readouterr().err


# ---------------------------------------------------------------- pc import


def test_an_imported_assembly_keeps_its_parts_colours_and_its_instances_own(tmp_path):
    pytest.importorskip("build123d")
    import build123d as bd
    import step_cmf
    import wrapper_import_assy
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool

    document = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    XCAFApp_Application.GetApplication_s().NewDocument(TCollection_ExtendedString("MDTV-XCAF"), document)
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colors = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    brick = shapes.AddShape(bd.Box(10, 20, 30).wrapped, False)
    TDataStd_Name.Set_s(brick, TCollection_ExtendedString("brick"))
    colors.SetColor(brick, Quantity_Color(1, 0, 0, Quantity_TOC_RGB), XCAFDoc_ColorSurf)
    wall = shapes.NewShape()
    TDataStd_Name.Set_s(wall, TCollection_ExtendedString("wall"))
    moved = gp_Trsf()
    moved.SetTranslation(gp_Vec(0, 40, 0))
    shapes.AddComponent(wall, brick, TopLoc_Location(gp_Trsf()))
    second = shapes.AddComponent(wall, brick, TopLoc_Location(moved))
    shapes.UpdateAssemblies()
    colors.SetColor(second, Quantity_Color(0, 0, 1, Quantity_TOC_RGB), XCAFDoc_ColorSurf)

    wrapper_import_assy._shape_cache.clear()
    wrapper_import_assy._used_files.clear()
    (root,) = [node for node in wrapper_import_assy.parse_document(document) if node is not None]
    flat = wrapper_import_assy.flatten_assembly_tree(root, str(tmp_path), 5)

    first, override = flat["links"]
    assert "cmf" not in first
    assert override["cmf"]["color"] == "#0000FF"
    # One part file, in its definition's colour.
    assert first["part_file"] == override["part_file"]
    _shape, section = step_cmf.read(first["part_file"])
    assert {section.face_set(i).color for i in range(6)} == {"#FF0000"}


def test_two_parts_of_one_geometry_in_different_materials_are_two_parts():
    pytest.importorskip("build123d")
    import wrapper_import_assy

    def signature(**values):
        return wrapper_import_assy._colors_of(Section([CmfSet(**values)], 0))

    assert signature(color="#FF0000", material="Steel") != signature(color="#FF0000", material="Aluminium")
    assert signature(color="#FF0000", finish="Matte") != signature(color="#FF0000")
    assert signature(color="#FF0000", material="Steel") == signature(color="#FF0000", material="Steel")
    assert wrapper_import_assy._colors_of(None) == ()


def test_an_instance_s_colour_becomes_its_link_s_params(tmp_path):
    from partcad.actions.assembly import import_assy

    root = _package(tmp_path / "pkg", colors=COLORS)
    project = pc.Context(str(root)).get_project("//src")

    assert import_assy._instance_params(project, {"color": "#C91A09", "rgba": [201, 26, 9, 1.0]}) == {
        "color": "//src:signal-red",
        "sourceCmf": "color",
    }
    assert import_assy._instance_params(project, None) is None


def test_an_end_to_end_step_part_is_drawn_in_what_its_package_claims(tmp_path):
    """Read in a sandbox, converted and completed in the core."""
    step_cmf = _wrappers()
    import build123d as bd

    root = _package(
        tmp_path / "pkg",
        parts={"box": {"type": "step", "path": "box.step", "parameters": _declare(material=":al-6061")}},
        colors=COLORS,
        materials=MATERIALS,
    )
    step_cmf.write(
        str(root / "box.step"),
        bd.Box(10, 20, 30).wrapped,
        Section([CmfSet(color="#C91A09", rgba=(201, 26, 9, 1.0), origin="raw:step")], NONE, faces=[0] * 6),
    )
    ctx = pc.Context(str(root))
    part = ctx.get_part("//src:box")
    asyncio.run(part.get_wrapped(ctx))

    summary = cmf.summary_of(part)
    assert [entry["color"] for entry in summary["sets"]] == ["//src:signal-red"]
    assert summary["sets"][0]["material"] == "//src:al-6061"
    assert summary["unspecified"] == {}


# ---------------------------------------------------------------- part types


PART_TYPE = """
from build123d import Box

if __name__ == "__partcad_part__":
    box = Box(10, 10, 10).wrapped
    red = {"color": "4", "material": "abs", "rgba": [201, 26, 9, 1.0]}
    unknown = {"color": "999", "rgba": [1, 2, 3, 1.0]}
    output = {"shape": box, "cmf": {"convention": "ldraw", "faces": [red, red, unknown, None, None, None]}}
"""


def test_a_part_type_says_what_its_faces_are_in(tmp_path):
    """A package's own part type hands back its CMF as plain data; the core converts it by the convention."""
    pytest.importorskip("build123d")
    root = _package(
        tmp_path / "pkg",
        parts={"brick": {"type": ":coloured"}},
        partTypes={"coloured": {"kind": "wrapper", "path": "coloured.py"}},
        colors={"Red": {"display": "#C91A09", "ids": {"ldraw": "4"}}},
        materials={"ABS": {"density": 1040, "ids": {"ldraw": "abs"}}},
    )
    (root / "coloured.py").write_text(PART_TYPE)
    ctx = pc.Context(str(root))
    part = ctx.get_part("//src:brick")
    asyncio.run(part.get_wrapped(ctx))

    summary = cmf.summary_of(part)
    by_color = {entry.get("color"): entry for entry in summary["sets"]}
    assert by_color["//src:Red"]["faces"] == 2
    assert by_color["//src:Red"]["material"] == "//src:ABS"
    # Nothing claims '999': drawn as the part type said, and only a picture.
    assert "//pub/std/color:rgba;color=010203FF" in by_color
    assert summary["unspecified"]["color"] == 3


def test_a_system_with_several_ids_for_a_colour_lists_them(tmp_path):
    """LEGO's white is both 1 and 426: either names it."""
    root = _package(tmp_path / "pkg", colors={"White": {"display": "#FFFFFF", "ids": {"step": ["#FFFFFF", "#FEFEFE"]}}})
    ctx = pc.Context(str(root))

    assert ctx.get_project("//src").get_cmf("color", "White").ids == {"step": ["#FFFFFF", "#FEFEFE"]}
    for value in ["#FFFFFF", "#FEFEFE"]:
        assert cmf_conventions.reference_for(ctx, "//src", "color", value, (255, 255, 255, 1.0)) == "//src:White"


def test_a_source_may_name_a_package_s_convention_and_with_it_that_package_s_declarations(tmp_path, caplog):
    """A plugin's part type builds parts in packages below the one that declares its colours."""
    root = _package(
        tmp_path / "pkg",
        colors={"Red": {"display": "#B40000", "ids": {"ldraw": "4"}}},
        cmfConventions={"ldraw": {"extends": "ldraw"}},
    )
    _package(root / "category", name="//src/category")
    ctx = pc.Context(str(root))
    part = ctx.get_part("//src/category:box")
    section = Section([CmfSet(color="4", rgba=(180, 0, 0, 1.0), origin="raw://src:ldraw")], 0)

    own = cmf_conventions.convert(ctx, part, section, None).own()

    assert (own.color, own.origin) == ("//src:Red", "source:ldraw")

    # A 'cmfConvention' naming nothing falls back to that convention, not to PartCAD's own.
    with caplog.at_level(logging.ERROR):
        fallback = cmf_conventions.convert(ctx, part, section, "no-such-convention").own()
    assert "names no convention" in caplog.text
    assert (fallback.color, fallback.origin) == ("//src:Red", "source:ldraw")


def test_a_part_type_takes_the_cmf_parameters_every_type_takes():
    """'58121;color=...' names a plugin's part in a colour, as it does any other part."""
    from partcad import factory

    accepted = factory.accepted_object_type_parameters("part", "//pub/universe/lego:ldraw")
    assert set(cmf.TYPE_PARAMETERS) <= set(accepted)
    assert "tolerance" not in accepted
