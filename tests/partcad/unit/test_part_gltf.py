#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'gltf' part type: '.gltf' with its buffers beside it, or a single '.glb'; and the 'gltf' assembly type.

The fixture is what build123d's 'export_gltf' -- PartCAD's own glTF export --
writes for a 10 x 20 x 30 mm box centred at (100, 0, 0), so reading it back
exactly is the round trip: glTF's metres and Y-up have to come back as
millimetres and Z-up for the box to land where it started. The same box is
stored the four ways the web's glTF is made small (Draco, quantization, and
meshoptimizer's codecs under both extensions), each written by the tool's own
encoder ('data/import_gltf/make_fixtures.py'), and reads back as the same box.

'scene.glb' is a scene of six nodes under a root, in metres and Y-up:

- 'red_box': a 10 mm cube in the material 'Red', at (0.05, 0, 0);
- 'two_tone_box': the cube again as two primitives, its +Y face in 'Blue' and the
  rest in 'Grey', at (0, 0.05, 0);
- 'stretched': the red cube scaled to 20 mm along X, at (-0.05, 0, 0);
- 'rivets': a 2 mm cube with no material, drawn three times by
  'EXT_mesh_gpu_instancing' at (0, 0, 0.05), (0.01, 0, 0.05) and (0.02, 0, 0.05),
  each a quarter turn about Y (stored as normalized 16-bit integers);
- 'marker': a point, which is no part of a shape;
- 'hidden': the red cube, hidden by 'KHR_node_visibility'.

In PartCAD's millimetres and Z-up that is 1000 + 1000 + 2000 + 3 x 8 mm3 in six
solids, the rivets at y = -50.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

import partcad as pc
from partcad import factory, shape_envelope
from partcad.actions.part import import_part_action
from partcad.part_factory_gltf import PartFactoryGltf, gltf_companions, gltf_extensions

DATA = Path("tests/partcad/unit/data/import_gltf")
PACKAGE = str(DATA / "partcad.yaml")


def test_gltf_is_a_part_type():
    assert factory.all["part"]["gltf"] is PartFactoryGltf


def test_a_gltf_part_is_its_file():
    ctx = pc.Context(PACKAGE)
    part = ctx.get_part(":box")
    assert os.path.abspath(part.path) == os.path.abspath(DATA / "box.gltf")
    assert os.path.abspath(ctx.get_part(":box_binary").path) == os.path.abspath(DATA / "box.glb")


def test_the_buffers_a_gltf_names_are_its_companions():
    assert gltf_companions(DATA / "box.gltf") == ["box.bin"]
    # A '.glb' carries them inside, and is not JSON at all.
    assert gltf_companions(DATA / "box.glb") == []


def test_a_gltf_s_buffers_are_part_of_its_cache_key():
    part = pc.Context(PACKAGE).get_part(":box")
    assert [os.path.abspath(path) for path in part.cache_dependencies] == [
        os.path.abspath(DATA / "box.bin"),
        os.path.abspath(DATA / "box.gltf"),
    ]


def test_a_companion_uri_is_percent_encoded(tmp_path):
    (tmp_path / "mesh data.bin").write_bytes(b"")
    (tmp_path / "outside.bin").write_bytes(b"")
    (tmp_path / "inner").mkdir()
    uris = ["mesh%20data.bin", "%2E%2E/outside.bin", "data:application/octet-stream;base64,AA==", "missing.bin"]
    (tmp_path / "inner" / "a.gltf").write_text(json.dumps({"buffers": [{"uri": uri} for uri in uris]}))
    (tmp_path / "a.gltf").write_text(json.dumps({"buffers": [{"uri": uris[0]}]}))
    assert gltf_companions(tmp_path / "a.gltf") == ["mesh data.bin"]
    assert gltf_companions(tmp_path / "inner" / "a.gltf") == []


def _package(tmp_path):
    project_dir = tmp_path / "package"
    project_dir.mkdir()
    (project_dir / "partcad.yaml").write_text("parts: {}\n")
    return project_dir, pc.Context(str(project_dir)).get_project("")


def test_importing_a_gltf_brings_its_buffers(tmp_path):
    project_dir, project = _package(tmp_path)

    import_part_action(project, "gltf", "imported", str(DATA / "box.gltf"))

    assert (project_dir / "imported.gltf").is_file()
    assert (project_dir / "box.bin").read_bytes() == (DATA / "box.bin").read_bytes()
    # The same buffer again is no conflict.
    import_part_action(project, "gltf", "again", str(DATA / "box.gltf"))
    assert (project_dir / "again.gltf").is_file()


def test_importing_a_gltf_never_replaces_another_part_s_buffer(tmp_path):
    project_dir, project = _package(tmp_path)
    (project_dir / "box.bin").write_bytes(b"another part's triangles")

    with pytest.raises(ValueError, match="would replace the package's own"):
        import_part_action(project, "gltf", "imported", str(DATA / "box.gltf"))

    assert (project_dir / "box.bin").read_bytes() == b"another part's triangles"
    assert not (project_dir / "imported.gltf").exists()


@pytest.mark.parametrize("filename", ["box.gltf", "box.glb"])
def test_the_reader_makes_a_solid_of_the_triangles(filename):
    # In process, as the sandbox runs it.
    sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
    import wrapper_import_gltf
    from OCP.TopAbs import TopAbs_SOLID

    result = wrapper_import_gltf.process(str(DATA / filename), {})
    assert result["success"], result["exception"]
    assert result["shape"].ShapeType() == TopAbs_SOLID


def test_a_file_that_is_not_gltf_is_an_error(tmp_path):
    sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
    import wrapper_import_gltf

    (tmp_path / "broken.gltf").write_text("not glTF")
    result = wrapper_import_gltf.process(str(tmp_path / "broken.gltf"), {})
    assert not result["success"]
    assert result["shape"] is None


def test_a_gltf_that_is_not_an_object_names_no_companions(tmp_path):
    (tmp_path / "list.gltf").write_text("[]")
    assert gltf_companions(tmp_path / "list.gltf") == []


def test_importing_a_gltf_never_writes_outside_the_package(tmp_path):
    project_dir, project = _package(tmp_path)
    source = tmp_path / "source"
    (source / "buffers").mkdir(parents=True)
    (source / "buffers" / "mesh.bin").write_bytes(b"triangles")
    (source / "model.gltf").write_text(json.dumps({"buffers": [{"uri": "buffers/mesh.bin"}]}))
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, project_dir / "buffers", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("No symbolic links here")

    with pytest.raises(ValueError, match="outside the package"):
        import_part_action(project, "gltf", "imported", str(source / "model.gltf"))
    assert not (outside / "mesh.bin").exists()


@pytest.mark.slow
@pytest.mark.parametrize("name", [":box", ":box_binary"])
def test_a_gltf_reads_back_where_it_was_written(name):
    ctx = pc.Context(PACKAGE)
    part = ctx.get_part(name)
    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None, part.errors
    measured = envelope[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
    assert measured["solids"] == 1
    assert measured["volume"] == pytest.approx(6000)
    assert measured["bbox"] == pytest.approx([95, -10, -15, 105, 10, 15], abs=1e-6)


@pytest.mark.slow
def test_a_gltf_part_that_cannot_be_read_is_an_error(tmp_path):
    (tmp_path / "partcad.yaml").write_text("parts:\n  broken:\n    type: gltf\n")
    (tmp_path / "broken.gltf").write_text("not glTF")
    ctx = pc.Context(str(tmp_path))
    with pytest.raises(Exception, match="Failed to read the glTF file"):
        asyncio.run(ctx.get_part(":broken").get_wrapped(ctx))


# --------------------------------------------------------------------------- #
# The web's glTF, and what a scene holds                                      #
# --------------------------------------------------------------------------- #

COMPRESSED = ["box_quantized", "box_meshopt", "box_meshopt_khr", "box_draco"]


def _wrappers():
    sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))


def _measured(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    box.SetGap(0)
    solids = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, solids)
    return props.Mass(), list(box.Get()), solids.Extent()


def test_a_part_with_no_path_is_its_glb_when_there_is_no_gltf():
    ctx = pc.Context(PACKAGE)
    for name in COMPRESSED + ["scene"]:
        assert os.path.abspath(ctx.get_part(":" + name).path) == os.path.abspath(DATA / (name + ".glb"))
    # And '<name>.gltf' first, where there is one.
    assert os.path.abspath(ctx.get_part(":box").path) == os.path.abspath(DATA / "box.gltf")


def test_what_a_file_uses_is_known_before_it_is_read():
    assert gltf_extensions(DATA / "box_draco.glb") == {"KHR_draco_mesh_compression"}
    assert gltf_extensions(DATA / "box_meshopt.glb") == {"KHR_mesh_quantization", "EXT_meshopt_compression"}
    assert gltf_extensions(DATA / "box.gltf") == set()
    assert gltf_extensions(DATA / "missing.glb") == set()


@pytest.mark.parametrize("name", COMPRESSED)
def test_the_web_s_compressed_glb_reads_back_as_the_box(name):
    if name == "box_draco":
        pytest.importorskip("DracoPy")
    _wrappers()
    import wrapper_import_gltf

    shape, _section, warnings = wrapper_import_gltf.read(str(DATA / (name + ".glb")))
    volume, bbox, solids = _measured(shape)
    assert solids == 1
    assert volume == pytest.approx(6000, abs=1e-3)
    assert bbox == pytest.approx([95, -10, -15, 105, 10, 15], abs=1e-4)
    assert warnings == []


def test_a_scene_is_a_solid_per_closed_piece_each_where_its_node_puts_it():
    _wrappers()
    import wrapper_import_gltf

    shape, section, warnings = wrapper_import_gltf.read(str(DATA / "scene.glb"))
    volume, bbox, solids = _measured(shape)
    assert solids == 6
    assert volume == pytest.approx(4024, abs=1e-3)
    # The stretched cube's far end, the rivets' row, the two-tone cube's top.
    assert bbox == pytest.approx([-60, -51, -5, 55, 5, 55], abs=1e-4)
    assert warnings == ["Not read, since a shape does not hold them: 1 hidden nodes, 1 point primitives"]

    # Each face in its triangle's material, stated in glTF's terms; the rivets,
    # in none, in nothing.
    faces = {}
    for index in range(len(section.faces)):
        found = section.face_set(index)
        key = (found.color, found.rgba, found.roughness, found.metallic, found.origin) if found.color else None
        faces[key] = faces.get(key, 0) + 1
    assert faces == {
        ("Red", (255, 0, 0, 1.0), 0.5, 0.0, "raw:gltf"): 24,
        ("Blue", (0, 0, 255, 1.0), 0.2, 1.0, "raw:gltf"): 2,
        ("Grey", (128, 128, 128, 1.0), 0.9, 0.1, "raw:gltf"): 10,
        None: 36,
    }


def test_a_file_that_requires_what_partcad_does_not_read_says_what(tmp_path):
    _wrappers()
    import wrapper_import_gltf

    path = tmp_path / "future.gltf"
    path.write_text(json.dumps({"asset": {"version": "2.0"}, "extensionsRequired": ["EXT_some_future_compression"]}))
    result = wrapper_import_gltf.process(str(path), {})
    assert not result["success"]
    assert result["exception"] == (
        "Failed to read the glTF file: the file requires 'EXT_some_future_compression', which PartCAD does not read"
    )


def test_importing_a_glb_keeps_it_a_glb(tmp_path):
    project_dir, project = _package(tmp_path)

    import_part_action(project, "gltf", "imported", str(DATA / "box_meshopt.glb"))

    assert (project_dir / "imported.glb").read_bytes() == (DATA / "box_meshopt.glb").read_bytes()
    assert not (project_dir / "imported.gltf").exists()


@pytest.mark.slow
@pytest.mark.parametrize("name", COMPRESSED)
def test_a_compressed_glb_part_reads_back_as_the_box(name):
    """Through the sandbox, which is given DracoPy for the one file that needs it."""
    ctx = pc.Context(PACKAGE)
    part = ctx.get_part(":" + name)
    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is not None, part.errors
    measured = envelope[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
    assert measured["solids"] == 1
    assert measured["volume"] == pytest.approx(6000, abs=1e-3)
    assert measured["bbox"] == pytest.approx([95, -10, -15, 105, 10, 15], abs=1e-4)


@pytest.mark.slow
def test_a_package_claims_a_gltf_material_by_its_name(tmp_path):
    import shutil

    import yaml

    from partcad import cmf

    shutil.copy(DATA / "scene.glb", tmp_path / "scene.glb")
    package = {
        "name": "//src",
        "colors": {"signal-red": {"display": "#C91A09", "ids": {"gltf": "Red"}}},
        "parts": {"scene": {"type": "gltf"}},
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(package))
    ctx = pc.Context(str(tmp_path))
    part = ctx.get_part("//src:scene")
    assert asyncio.run(part.get_wrapped(ctx)) is not None, part.errors

    colors = {entry["color"]: entry.get("faces") for entry in cmf.summary_of(part)["sets"] if entry.get("color")}
    # Claimed, it is the package's colour; unclaimed, the colour the file draws.
    assert colors["//src:signal-red"] == 24
    assert {color for color in colors if color != "//src:signal-red"} == {
        "//builtin/color:rgba;color=0000FFFF",
        "//builtin/color:rgba;color=808080FF",
    }


# --------------------------------------------------------------------------- #
# The 'gltf' assembly type                                                    #
# --------------------------------------------------------------------------- #


def _read_as_assembly(tmp_path):
    sys.path.append(os.path.join(os.path.dirname(pc.__file__), "builtin", "import"))
    _wrappers()
    import import_gltf

    return import_gltf.process(None, {"source_file": str(DATA / "scene.glb"), "output_folder": str(tmp_path)})


def test_a_scene_read_as_an_assembly_is_a_part_per_mesh_where_its_nodes_put_it(tmp_path):
    result = _read_as_assembly(tmp_path)
    root = result["root"]
    assert (root["type"], root["name"], result["model_name"]) == ("assembly", "root", "root")
    assert result["warnings"] == ["Not read, since a shape does not hold them: 1 hidden nodes, 1 point primitives"]

    def flat(node):
        if node["type"] == "part":
            # A float32 vertex is all a glTF holds: 0.05 m is 50.000001 mm.
            translation, axis, angle = node["location"]
            location = [[round(value, 4) for value in translation], axis, angle]
            return [(node["name"], os.path.basename(node["part_file"]), node["part_type"], location)]
        return [(node["name"], [entry for link in node["links"] for entry in flat(link)])]

    quarter_about_z = [[0.0, 0.0, 1.0], 90.0]
    assert flat(root) == [
        (
            "root",
            [
                ("cube", "cube.glb", "gltf", [[50.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]),
                ("two_tone", "two_tone.glb", "gltf", [[0.0, 0.0, 50.0], [0.0, 0.0, 1.0], 0.0]),
                # The red cube stretched is a mesh of its own: a placement cannot stretch.
                ("cube_2", "cube_2.glb", "gltf", [[-50.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]),
                (
                    "rivets",
                    [
                        ("rivet", "rivet.glb", "gltf", [[0.0, -50.0, 0.0], *quarter_about_z]),
                        ("rivet", "rivet.glb", "gltf", [[10.0, -50.0, 0.0], *quarter_about_z]),
                        ("rivet", "rivet.glb", "gltf", [[20.0, -50.0, 0.0], *quarter_about_z]),
                    ],
                ),
            ],
        )
    ]


def test_each_part_of_a_gltf_assembly_is_read_as_a_gltf_part_is(tmp_path):
    _read_as_assembly(tmp_path)
    import wrapper_import_gltf

    stretched, _section, _warnings = wrapper_import_gltf.read(str(tmp_path / "cube_2.glb"))
    volume, bbox, solids = _measured(stretched)
    assert (solids, volume) == (1, pytest.approx(2000, abs=1e-3))
    assert bbox == pytest.approx([-10, -5, -5, 10, 5, 5], abs=1e-4)
    # Its material went with it: the file holds the mesh and what it is drawn in.
    _shape, section, _warnings = wrapper_import_gltf.read(str(tmp_path / "two_tone.glb"))
    assert sorted(found.color for found in section.sets) == ["Blue", "Grey"]


@pytest.mark.slow
def test_a_gltf_assembly_is_built_from_its_parts():
    ctx = pc.Context(PACKAGE)
    assembly = ctx.get_assembly(":scene_assembly")
    assert asyncio.run(assembly.get_wrapped(ctx)) is not None
    # The tree the file's nodes make, which a build from the cache skips.
    asyncio.run(assembly.do_instantiate())
    assert [(child.name, child.item.name) for child in assembly.children] == [
        ("cube", "scene_assembly/cube"),
        ("two_tone", "scene_assembly/two_tone"),
        ("cube_2", "scene_assembly/cube_2"),
        ("rivets", "scene_assembly:rivets"),
    ]
    rivets = assembly.children[-1].item
    assert [child.item.name for child in rivets.children] == ["scene_assembly/rivet"] * 3


@pytest.mark.slow
def test_importing_a_glb_as_an_assembly_writes_its_parts_and_an_assy(tmp_path):
    import yaml

    from partcad.actions.assembly import import_assy_action

    project_dir, project = _package(tmp_path)
    name = import_assy_action(project, "gltf", str(DATA / "scene.glb"), {})

    assert name == "root"
    folder = project_dir / "scene"
    assert sorted(path.name for path in folder.iterdir()) == [
        "cube.glb",
        "cube_2.glb",
        "rivet.glb",
        "root.assy",
        "two_tone.glb",
    ]
    config = yaml.safe_load((project_dir / "partcad.yaml").read_text())
    assert config["parts"]["scene/rivet"] == {"type": "gltf", "path": "scene/rivet.glb"}
    assert config["assemblies"] == {"scene/root": {"type": "assy"}}
    ctx = pc.Context(str(project_dir))
    assembly = ctx.get_assembly(":scene/root")
    assert asyncio.run(assembly.get_wrapped(ctx)) is not None


def test_a_glb_added_as_an_assembly_is_named_after_its_file(tmp_path):
    import shutil

    import yaml

    project_dir, project = _package(tmp_path)
    shutil.copy(DATA / "scene.glb", project_dir / "scene.glb")
    shutil.copy(DATA / "box.gltf", project_dir / "box.gltf")

    assert project.add_assembly("gltf", str(project_dir / "scene.glb"), {})
    assert project.add_assembly("gltf", str(project_dir / "box.gltf"), {})

    assert yaml.safe_load((project_dir / "partcad.yaml").read_text())["assemblies"] == {
        "scene": {"type": "gltf", "path": "scene.glb"},
        "box": {"type": "gltf"},
    }
