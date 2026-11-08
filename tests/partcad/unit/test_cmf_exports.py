#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the exports write of a part's CMF (docs/design/cmf.md, section 9, "Exports", and 11.6).

Pinned here, each by writing the file and reading it back:

- STEP, through XCAF: the product structure and names, the colours as the sRGB
  the file states, a material by its reference with its density, and PartCAD's
  references for every face and solid in a user-defined attribute - read back as
  the same references, and by value once the file no longer agrees with them;
- glTF: a material per set, named after it, with its display as a linear factor,
  its finish, and its references under 'extras';
- 3MF: a base material per set, per triangle, which the mesh reader reads back;
- URDF: a visual per set of a part in several;
- a format with no CMF warns, once, and only when there is something to drop;
- end to end, through the core and the sandbox: a part exported to STEP and read
  back with the 'partcad' convention has the same references on every face and
  solid; its 3MF reads back in its colours; its URDF draws each set.
"""

import asyncio
import json
import locale
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

import pytest
import yaml

import partcad as pc
from partcad import cmf

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
from cmf_section import NONE, CmfSet, Section  # noqa: E402

EXPORT = os.path.join(os.path.dirname(pc.__file__), "builtin", "export")


@pytest.fixture(autouse=True)
def _locale_put_back():
    """lib3mf, under build123d's Mesher, sets the process's locale to "C" and leaves it there (see test_cmf_sources)."""
    found = locale.setlocale(locale.LC_ALL)
    yield
    locale.setlocale(locale.LC_ALL, found)


RED = CmfSet(color="//src:signal-red", origin="declared", rgba=(201, 26, 9, 1.0))
GREY = CmfSet(color="//src:grey", origin="declared", rgba=(128, 128, 128, 1.0))
MATTE = CmfSet(
    color="//src:grey", finish="//src:matte", origin="declared", rgba=(128, 128, 128, 1.0), roughness=0.9, metallic=0.1
)
ABS = CmfSet(material="//src:abs", origin="declared")
ALUMINIUM = CmfSet(material="//src:al-6061", origin="declared")


def _kernel():
    pytest.importorskip("build123d")
    import build123d as bd

    return bd


def _two_bodies():
    """A compound of two boxes, the first face red, the rest grey or matte; one of ABS and one of aluminium."""
    bd = _kernel()
    import ocp_serialize

    first, second = bd.Box(10, 10, 10), bd.Pos(20, 0, 0) * bd.Box(10, 10, 10)
    shape = ocp_serialize.compound_of([first.wrapped, second.wrapped])
    faces = {first.faces()[0].wrapped: RED}
    for face in first.faces()[1:]:
        faces[face.wrapped] = GREY
    for face in second.faces():
        faces[face.wrapped] = MATTE
    # A build123d part is a compound holding its solid.
    solids = {first.solid().wrapped: ABS, second.solid().wrapped: ALUMINIUM}
    section = ocp_serialize.cmf_section_for(shape, faces=faces, solids=solids)
    return shape, section


def _envelope(shape, section=None, name="//src:bodies", label="bodies", **extra):
    import ocp_serialize

    envelope = ocp_serialize.encode_shape(shape, name=name, label=label, cmf=section)
    envelope.update(extra)
    return envelope


def _export(script, path, envelope, **parameters):
    """Run a built-in export implementation in this process, as the sandbox runs it."""
    import wrapper_export

    request = {"wrapped": envelope, "shape_name": "bodies", "tolerance": 0.5, "angularTolerance": 0.5}
    request.update(parameters)
    result = wrapper_export.run(os.path.join(EXPORT, script), str(path), request)
    assert result["success"], result
    return result


def _flat(path):
    """A STEP file's text with its line breaks, and the indentation after them, taken out.

    A STEP writer breaks its lines where it likes, strings included, and a
    reader drops the breaks.
    """
    return re.sub(r"\n\s*", "", path.read_text(encoding="utf-8"))


def _components(cmf_set):
    return (cmf_set.color, cmf_set.material, cmf_set.finish)


# ---------------------------------------------------------------- STEP


def test_a_step_export_reads_back_with_the_same_references_on_every_face_and_solid(tmp_path):
    import step_cmf

    shape, section = _two_bodies()
    path = tmp_path / "bodies.step"
    _export("export_step.py", path, _envelope(shape, section))

    _read, found = step_cmf.read(str(path))

    assert len(found.faces) == len(section.faces) == 12
    assert [_components(found.face_set(i)) for i in range(12)] == [_components(section.face_set(i)) for i in range(12)]
    assert [found.solid_set(i).material for i in range(2)] == ["//src:abs", "//src:al-6061"]
    # PartCAD's own terms: references the core looks up whatever 'cmfConvention' says.
    assert {cmf_set.origin for cmf_set in found.sets} == {step_cmf.PARTCAD}
    # And still drawn as the file draws it.
    assert found.face_set(0).rgba == (201, 26, 9, 1.0)


def test_a_step_colour_is_the_srgb_the_file_states(tmp_path):
    """OCCT turns a 'COLOUR_RGB' into linear values; the file's numbers are what goes in and comes out."""
    import step_cmf

    bd = _kernel()
    path = tmp_path / "red.step"
    step_cmf.write(str(path), bd.Box(1, 1, 1).wrapped, Section([CmfSet(color="#C91A09", rgba=(201, 26, 9, 1.0))], 0))

    text = _flat(path)
    assert re.search(r"COLOUR_RGB\('',0\.7882\d*,0\.1019\d*,3\.5294\d*E-02\)", text), text
    _shape, found = step_cmf.read(str(path))
    assert found.face_set(0).color == "#C91A09"


def _wall():
    """An assembly: a red aluminium brick placed twice, a peg its node draws blue, and the same peg in nothing."""
    import ocp_serialize

    bd = _kernel()
    brick = _envelope(bd.Box(10, 20, 30).wrapped, Section([RED.filled_from(ALUMINIUM)], 0), "//src:brick", "brick")
    peg = _envelope(bd.Cylinder(3, 10).wrapped, None, "//src:peg", "peg")
    return ocp_serialize.encode_assembly(
        [
            dict(brick, location=[[0, 0, 0], [0, 0, 1], 0], label="wall/left"),
            dict(brick, location=[[0, 40, 0], [0, 0, 1], 0], label="wall/right"),
            dict(peg, location=[[0, 0, 40], [0, 0, 1], 0], label="peg", properties={"color": "#0000FF"}),
            # The same peg in nobody's colour: the same geometry, drawn otherwise, so another product.
            dict(peg, location=[[0, 0, 80], [0, 0, 1], 0], label="bare"),
        ],
        name="//src:wall",
        label="wall",
    )


def test_a_step_export_is_the_assembly_s_products_named_and_placed(tmp_path):
    import step_cmf

    wall = _wall()
    path = tmp_path / "wall.step"
    facts = {"materials": {"//src:al-6061": {"name": "al-6061", "description": "Aluminium 6061", "density": 2700.0}}}
    _export("export_step.py", path, wall, cmf=facts)

    text = _flat(path)
    products = re.findall(r"PRODUCT\('([^']*)'", text)
    # The brick placed twice is one product.
    assert sorted(products) == ["brick", "peg", "peg", "wall"]
    occurrences = re.findall(r"NEXT_ASSEMBLY_USAGE_OCCURRENCE\('[^']*','([^']*)'", text)
    assert sorted(occurrences) == ["bare", "left", "peg", "right"]
    # The material by its reference, described, with its density in g/cm^3.
    assert "DESCRIPTIVE_REPRESENTATION_ITEM('//src:al-6061','Aluminium 6061')" in text
    assert re.search(r"MEASURE_REPRESENTATION_ITEM\('density',POSITIVE_RATIO_MEASURE\(2\.7\)", text)

    _shape, found = step_cmf.read(str(path))
    colors = {found.face_set(i).color for i in range(len(found.faces))}
    # The bricks by reference, the peg by the value its node draws it in, the bare one in nothing.
    assert colors == {"//src:signal-red", "#0000FF", None}


def test_an_attribute_that_counts_more_faces_than_there_are_is_refused_before_it_is_expanded():
    """A run of 10**12 is the file's to write, not a list to build: it is counted against the product first."""
    pytest.importorskip("build123d")
    import urllib.parse

    import build123d as bd
    import step_cmf

    box = bd.Box(1, 1, 1).wrapped
    text = urllib.parse.quote(
        json.dumps({"partcad": step_cmf.ATTRIBUTE_VERSION, "sets": [], "faces": [[10**12, 0]], "solids": [[1, 0]]})
    )

    table, reason = step_cmf.decode_table(text, box, [None] * 6)

    assert table is None
    assert "the product has 6" in reason


def test_a_step_file_another_tool_recoloured_is_read_by_value(tmp_path, capfd):
    import step_cmf

    bd = _kernel()
    path = tmp_path / "box.step"
    _export("export_step.py", path, _envelope(bd.Box(1, 1, 1).wrapped, Section([RED], 0)))
    text = path.read_text(encoding="utf-8")
    edited = re.sub(r"COLOUR_RGB\('',[^)]*\)", "COLOUR_RGB('',0.,0.,1.)", text)
    assert edited != text
    path.write_text(edited, encoding="utf-8")

    _shape, found = step_cmf.read(str(path))

    assert found.face_set(0).color == "#0000FF"
    assert found.face_set(0).origin == step_cmf.ORIGIN
    assert "read by value" in capfd.readouterr().err


def test_the_attribute_survives_any_text_a_reference_holds(tmp_path):
    """Quotes, backslashes and non-ASCII are written percent-encoded, so no STEP string escaping touches them."""
    import step_cmf

    bd = _kernel()
    odd = CmfSet(color="//src:Pantone 'Fiery' \\ Red °µ", origin="declared", rgba=(201, 26, 9, 1.0))
    path = tmp_path / "odd.step"
    _export("export_step.py", path, _envelope(bd.Box(1, 1, 1).wrapped, Section([odd], 0), "//src:Bügel", "Bügel"))

    _shape, found = step_cmf.read(str(path))
    assert found.face_set(0).color == odd.color
    assert "PRODUCT('Bügel'" in _flat(path)


# ---------------------------------------------------------------- glTF


@pytest.mark.parametrize("binary", [False, True])
def test_a_gltf_export_is_a_material_per_set(tmp_path, binary):
    import wrapper_gltf

    shape, section = _two_bodies()
    path = tmp_path / ("bodies.glb" if binary else "bodies.gltf")
    _export("export_gltf.py", path, _envelope(shape, section), binary=binary)

    meta = wrapper_gltf._read_glb(path.read_bytes())[0] if binary else json.loads(path.read_text())
    materials = {material["name"]: material for material in meta["materials"]}

    assert set(materials) == {"signal-red / abs", "grey / abs", "grey / al-6061 / matte"}
    red = materials["signal-red / abs"]
    # Linear, as glTF's factors are: sRGB 201 is 0.584 linear.
    assert red["pbrMetallicRoughness"]["baseColorFactor"] == pytest.approx([0.584078, 0.01033, 0.002732, 1.0], abs=1e-5)
    assert red["extras"]["partcad"] == {"color": "//src:signal-red", "material": "//src:abs"}
    matte = materials["grey / al-6061 / matte"]["pbrMetallicRoughness"]
    assert (matte["roughnessFactor"], matte["metallicFactor"]) == pytest.approx((0.9, 0.1), abs=0.01)


def test_a_gltf_of_a_shape_that_states_nothing_is_as_it_was(tmp_path):
    bd = _kernel()
    path = tmp_path / "plain.gltf"
    _export("export_gltf.py", path, _envelope(bd.Box(1, 1, 1).wrapped))

    for material in json.loads(path.read_text()).get("materials", []):
        assert "extras" not in material


def test_a_gltf_of_an_assembly_draws_each_part_in_its_sets_where_it_is_placed(tmp_path):
    path = tmp_path / "wall.gltf"
    _export("export_gltf.py", path, _wall())

    meta = json.loads(path.read_text())
    names = [material["name"] for material in meta["materials"]]
    # The brick placed twice is one material, and the peg's node colour another.
    assert sorted(names) == ["#0000FF", "signal-red / al-6061"]
    meshes = {node["mesh"]: node for node in meta["nodes"] if "mesh" in node}
    # A node per placement, in metres, in the order the assembly holds them.
    assert [meshes[index].get("translation", [0.0, 0.0, 0.0]) for index in sorted(meshes)] == [
        [0.0, 0.0, 0.0],
        [0.0, 0.04, 0.0],
        [0.0, 0.0, 0.04],
        [0.0, 0.0, 0.08],
    ]

    def drawn(index):
        return {
            names[primitive["material"]] if "material" in primitive else None
            for primitive in meta["meshes"][index]["primitives"]
        }

    assert drawn(0) == drawn(1) == {"signal-red / al-6061"}
    assert drawn(2) == {"#0000FF"}
    # The bare peg is drawn in nothing, as it was before any of this.
    assert drawn(3) == {None}


# ---------------------------------------------------------------- 3MF


def _cadquery_3mf(path, shape):
    """The 3MF CadQuery's writer writes of 'shape', tessellating it as 'Shape.tessellate()' does.

    The 3MF exporter runs in CadQuery's layer, which this process does not
    have: this is its writer's output, face by face in 'TopExp::MapShapes'
    order, id 0 and 'Override' content types included.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    BRepMesh_IncrementalMesh(shape, 0.1, True, 0.1, True)
    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
    vertices, triangles = [], []
    for index in range(1, faces.Extent() + 1):
        face = TopoDS.Face_s(faces.FindKey(index))
        location = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, location)
        if poly is None:
            continue
        offset = len(vertices)
        transform = location.Transformation()
        for node in range(1, poly.NbNodes() + 1):
            point = poly.Node(node).Transformed(transform)
            vertices.append((point.X(), point.Y(), point.Z()))
        for triangle in range(1, poly.NbTriangles() + 1):
            a, b, c = (poly.Triangle(triangle).Value(i) + offset - 1 for i in (1, 2, 3))
            triangles.append((a, c, b) if face.Orientation() == TopAbs_REVERSED else (a, b, c))
    core = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    model = (
        '<model xmlns="%s" unit="millimeter"><resources><object id="0" type="model"><mesh><vertices>%s</vertices>'
        '<triangles>%s</triangles></mesh></object><object id="1" type="model"><components><component objectid="0"/>'
        '</components></object></resources><build><item objectid="1"/></build></model>'
        % (
            core,
            "".join('<vertex x="%r" y="%r" z="%r"/>' % vertex for vertex in vertices),
            "".join('<triangle v1="%d" v2="%d" v3="%d"/>' % triangle for triangle in triangles),
        )
    )
    with zipfile.ZipFile(str(path), "w") as out:
        out.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
        )
        out.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/3D/3dmodel.model" '
            'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
            '<Override PartName="/_rels/.rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/></Types>',
        )
        out.writestr("3D/3dmodel.model", model)


def test_a_3mf_is_a_base_material_per_set_per_triangle_and_reads_back(tmp_path):
    import cmf_3mf
    import cmf_capture
    import wrapper_export

    shape, section = _two_bodies()
    request = wrapper_export.decode({"wrapped": _envelope(shape, section)})
    whole = request["wrapped"]
    path = tmp_path / "bodies.3mf"
    _cadquery_3mf(path, whole)

    assert cmf_3mf.finish(str(path), cmf_3mf.triangle_sets(whole, request["shape_tree"]))

    with zipfile.ZipFile(str(path)) as package:
        model = ET.fromstring(package.read("3D/3dmodel.model"))
    core = "{%s}" % cmf_3mf.CORE
    bases = [(base.get("name"), base.get("displaycolor")) for base in model.iter(core + "base")]
    assert sorted(bases) == [
        ("grey / abs", "#808080FF"),
        ("grey / al-6061 / matte", "#808080FF"),
        ("signal-red / abs", "#C91A09FF"),
    ]
    # Every resource numbered from 1, as the core specification has it.
    assert all(int(element.get("id")) > 0 for element in model.find(core + "resources"))

    _read, found = cmf_capture.read_mesh(str(path))
    colors = [found.face_set(i).color for i in range(len(found.faces))]
    assert set(colors) == {"#C91A09", "#808080"}
    # The one red face of each box is two triangles of its twelve.
    assert colors.count("#C91A09") == 2


def test_a_3mf_of_a_shape_that_states_nothing_keeps_its_model(tmp_path):
    import cmf_3mf
    import wrapper_export

    bd = _kernel()
    request = wrapper_export.decode({"wrapped": _envelope(bd.Box(1, 1, 1).wrapped)})
    path = tmp_path / "plain.3mf"
    _cadquery_3mf(path, request["wrapped"])

    assert cmf_3mf.triangle_sets(request["wrapped"], request["shape_tree"]) is None
    assert not cmf_3mf.finish(str(path), None)
    with zipfile.ZipFile(str(path)) as package:
        assert b"basematerials" not in package.read("3D/3dmodel.model")
        assert b'Extension="rels"' in package.read("[Content_Types].xml")
    # Which lib3mf now reads, as it did not read CadQuery's.
    assert len(bd.Mesher().read(str(path))) == 1


def test_a_3mf_of_an_assembly_paints_each_part_where_it_is_placed(tmp_path):
    import cmf_3mf
    import cmf_capture
    import wrapper_export

    request = wrapper_export.decode({"wrapped": _wall()})
    whole = request["wrapped"]
    path = tmp_path / "wall.3mf"
    _cadquery_3mf(path, whole)

    assert cmf_3mf.finish(str(path), cmf_3mf.triangle_sets(whole, request["shape_tree"]))

    _read, found = cmf_capture.read_mesh(str(path))
    colors = [found.face_set(i).color for i in range(len(found.faces))]
    assert set(colors) == {"#C91A09", "#0000FF", None}
    # Both bricks, each six faces of two triangles, in the brick's red.
    assert colors.count("#C91A09") == 24
    # The two pegs are one geometry: the one its node draws blue, the other in nothing.
    assert colors.count("#0000FF") == colors.count(None) > 0


# ---------------------------------------------------------------- formats with no CMF


@pytest.mark.parametrize("script", ["export_stl.py", "export_obj.py", "export_brep.py"])
def test_a_format_with_no_cmf_says_it_dropped_it_once(tmp_path, script):
    bd = _kernel()
    shape, section = _two_bodies()

    coloured = _export(script, tmp_path / "bodies.out", _envelope(shape, section))
    plain = _export(script, tmp_path / "plain.out", _envelope(bd.Box(1, 1, 1).wrapped))

    assert len(coloured["warnings"]) == 1
    assert "carries no colour, material or finish" in coloured["warnings"][0]
    assert "warnings" not in plain


# ---------------------------------------------------------------- names


def test_a_set_is_called_by_its_declarations_names():
    import cmf_export

    assert cmf_export.display_name(MATTE.filled_from(ALUMINIUM)) == "grey / al-6061 / matte"
    assert cmf_export.reference_name("//src:PA12%2C glass filled") == "PA12, glass filled"
    assert cmf_export.reference_name("//builtin/color:rgba;color=C91A09FF") == "#C91A09"


def test_the_exporters_copy_of_the_display_only_colour_is_the_core_s():
    """'cmf_export' runs where the core cannot be imported, so it keeps a copy: the one the core writes."""
    import cmf_export

    from partcad import cmf

    assert cmf_export._RGBA == cmf.RGBA
    assert cmf_export.reference_name(cmf.rgba_reference((201, 26, 9, 1.0))) == "#C91A09"
    assert cmf_export.display_name(CmfSet(rgba=(1, 2, 3, 0.5))) == "#01020380"
    assert cmf_export.display_name(CmfSet()) == cmf_export.UNSPECIFIED
    assert cmf_export.linear(255) == 1.0 and cmf_export.linear(0) == 0.0


# ---------------------------------------------------------------- end to end


def _declare(**values):
    return {name: {"type": "string", "default": value} for name, value in values.items()}


PACKAGE = {
    "name": "//src",
    "colors": {
        "signal-red": {"display": "#C91A09", "ids": {"step": "#c91a09"}},
        "grey": {"display": "#808080"},
    },
    "materials": {"al-6061": {"density": 2700, "color": ":grey", "full": "Aluminium 6061-T6"}},
    "finishes": {"matte": {"display": {"roughness": 0.9, "metallic": 0.1}}},
}


@pytest.fixture
def exported(tmp_path):
    """A STEP part whose file colours one face, completed by its material and finish; and its context."""
    step_cmf = pytest.importorskip("step_cmf")
    bd = _kernel()
    root = tmp_path / "pkg"
    root.mkdir()
    step_cmf.write(
        str(root / "box.step"),
        bd.Box(10, 20, 30).wrapped,
        Section([CmfSet(color="#C91A09", rgba=(201, 26, 9, 1.0), origin="raw:step")], NONE, faces=[0] + [NONE] * 5),
    )
    config = dict(PACKAGE)
    config["parts"] = {
        "box": {"type": "step", "path": "box.step", "parameters": _declare(material=":al-6061", finish=":matte")},
        "again": {"type": "step", "path": "out/box.step", "parameters": _declare(cmfConvention="partcad")},
    }
    (root / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    return pc.Context(str(root)), root


def _rows(summary):
    return sorted(
        (str(entry.get("color")), str(entry.get("material")), str(entry.get("finish")), entry.get("faces"))
        for entry in summary
    )


def test_a_part_exported_to_step_reads_back_with_the_partcad_convention_as_itself(exported):
    """docs/design/cmf.md, 11.6: the same references on every face and solid."""
    ctx, root = exported
    box = ctx.get_part("//src:box")
    asyncio.run(box.render_async(ctx, "step", filepath=str(root / "out" / "box.step")))

    again = ctx.get_part("//src:again")
    asyncio.run(again.get_wrapped(ctx))

    before, after = cmf.summary_of(box), cmf.summary_of(again)
    assert (
        _rows(after["sets"])
        == _rows(before["sets"])
        == [
            ("//src:grey", "//src:al-6061", "//src:matte", 5),
            ("//src:signal-red", "//src:al-6061", "//src:matte", 1),
        ]
    )
    assert after["unspecified"] == {}
    # The density the declaration states, on the product.
    assert "POSITIVE_RATIO_MEASURE(2.7)" in _flat(root / "out" / "box.step")


def test_a_part_exported_to_3mf_reads_back_in_its_colours(exported):
    import cmf_capture

    ctx, root = exported
    box = ctx.get_part("//src:box")
    path = root / "out" / "box.3mf"
    asyncio.run(box.render_async(ctx, "3mf", filepath=str(path)))

    _shape, found = cmf_capture.read_mesh(str(path))
    colors = {found.face_set(i).color for i in range(len(found.faces))}
    assert colors == {"#C91A09", "#808080"}


@pytest.mark.parametrize("extension", ["glb", "gltf"])
def test_a_part_exported_to_gltf_reads_back_with_its_references(exported, extension):
    """The references the glTF export keeps in each material's 'extras' are what the 'gltf' part reads back.

    A face of the box is two triangles in the file, and a face of the part read
    from it, so every set comes back on twice the faces, and nothing else changes.
    """
    ctx, root = exported
    box = ctx.get_part("//src:box")
    asyncio.run(box.render_async(ctx, "gltf", filepath=str(root / "out" / ("box." + extension))))
    asyncio.run(box.get_wrapped(ctx))
    config = yaml.safe_load((root / "partcad.yaml").read_text())
    config["parts"]["from_gltf"] = {"type": "gltf", "path": "out/box." + extension}
    (root / "partcad.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    ctx = pc.Context(str(root))

    again = ctx.get_part("//src:from_gltf")
    assert asyncio.run(again.get_wrapped(ctx)) is not None, again.errors

    before = [
        (color, material, finish, faces * 2) for color, material, finish, faces in _rows(cmf.summary_of(box)["sets"])
    ]
    assert _rows(cmf.summary_of(again)["sets"]) == before
    assert cmf.summary_of(again)["unspecified"] == {}


def test_a_part_exported_to_urdf_is_a_visual_per_set(exported):
    ctx, root = exported
    box = ctx.get_part("//src:box")
    path = root / "out" / "box.urdf"
    asyncio.run(box.render_async(ctx, "urdf", filepath=str(path), tolerance=1.0, angularTolerance=0.5))

    visuals = ET.parse(str(path)).getroot().findall("link/visual")
    colors = sorted(visual.find("material/color").get("rgba") for visual in visuals)
    assert colors == ["0.501961 0.501961 0.501961 1.0", "0.788235 0.101961 0.035294 1.0"]
    names = {visual.find("material").get("name") for visual in visuals}
    assert names == {"signal-red_al-6061_matte", "grey_al-6061_matte"}


def test_the_core_resolves_what_an_export_states_of_a_declaration(exported):
    ctx, _root = exported
    box = ctx.get_part("//src:box")
    asyncio.run(box.get_wrapped(ctx))
    envelope = {"brep": b"", "metadata": {"cmf": cmf.summary_of(box)}}

    facts = cmf.export_facts(ctx, envelope, "//src")

    assert facts["materials"]["//src:al-6061"] == {
        "name": "al-6061",
        "description": "Aluminium 6061-T6",
        "density": 2700.0,
    }
    assert set(facts["colors"]) == {"//src:grey", "//src:signal-red"}
    assert set(facts["finishes"]) == {"//src:matte"}
