#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the MJCF (MuJoCo) reader and writer.

MJCF is the third description of a placed arrangement PartCAD reads, after URDF
and SDFormat, and the only one that is both an assembly type and a scene type:
the same element holds a robot and the table it is bolted to, and nothing in
the file says which it is, so the package says so instead.

Everything here runs without a CAD library and without MuJoCo. The reader only
needs OCCT for the primitives a model names instead of a mesh, and the exporter
only to triangulate what it writes; both are stubbed, because what is under test
is the mapping between the two models. Running a model is a simulation plugin's
business and is tested in 'test_simulation.py'.
"""

import asyncio
import math
import os
import sys
import xml.etree.ElementTree as ElementTree

import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
sys.path.append(os.path.join(os.path.dirname(pc.__file__), "builtin", "export"))

import mujoco_common  # noqa: E402
import primitive_shapes  # noqa: E402
import urdf_common  # noqa: E402
import wrapper_import_mjcf  # noqa: E402

EXAMPLES = "examples"
STL_EXAMPLE = os.path.abspath(os.path.join(EXAMPLES, "produce_part_stl", "cube.stl"))


@pytest.fixture
def no_occt(monkeypatch, tmp_path):
    """Write a primitive as a named placeholder instead of as geometry."""
    written = []

    def write(kind, dimensions, name, context):
        path = str(tmp_path / ("%s.step" % str(name).replace("/", "_")))
        written.append((kind, tuple(round(v, 6) for v in dimensions), path))
        return path

    monkeypatch.setattr(primitive_shapes, "write_primitive_step", write)
    monkeypatch.setattr(wrapper_import_mjcf.primitive_shapes, "write_primitive_step", write)
    return written


def read(path, **request):
    return wrapper_import_mjcf.process(dict({"mjcf_file": str(path)}, **request))


def model(tmp_path, body, extra="", compiler=""):
    """An MJCF file holding 'body' inside a worldbody, and its path."""
    path = tmp_path / "model.xml"
    path.write_text(
        '<mujoco model="m">%s%s<worldbody>%s</worldbody></mujoco>' % (compiler, extra, body),
        encoding="utf-8",
    )
    return path


#
# Orientations
#


def test_every_spelling_of_one_orientation_is_that_orientation():
    """MJCF states a rotation five ways, and all five appear in real models."""
    compiler = mujoco_common.Compiler()
    quarter_turn_about_z = urdf_common.axis_angle_to_quat((0.0, 0.0, 1.0), 90.0)

    spellings = (
        {"quat": "0.7071067811865476 0 0 0.7071067811865476"},
        {"axisangle": "0 0 1 90"},
        {"euler": "0 0 90"},
        {"xyaxes": "0 1 0 -1 0 0"},
    )
    for attributes in spellings:
        element = ElementTree.Element("body", attributes)
        rotation = mujoco_common.parse_orientation(element, compiler)
        axis, angle = urdf_common.quat_to_axis_angle(rotation)
        assert axis == pytest.approx((0.0, 0.0, 1.0), abs=1e-9), attributes
        assert angle == pytest.approx(90.0, abs=1e-9), attributes
    assert urdf_common.quat_to_axis_angle(quarter_turn_about_z)[1] == pytest.approx(90.0)


def test_angles_are_degrees_unless_the_compiler_says_otherwise():
    """The opposite of URDF and SDFormat, and the easiest thing to get wrong."""
    element = ElementTree.Element("body", {"euler": "0 0 1"})

    degrees = mujoco_common.parse_orientation(element, mujoco_common.Compiler())
    radians = mujoco_common.parse_orientation(
        element, mujoco_common.Compiler(ElementTree.Element("compiler", {"angle": "radian"}))
    )

    assert urdf_common.quat_to_axis_angle(degrees)[1] == pytest.approx(1.0)
    assert urdf_common.quat_to_axis_angle(radians)[1] == pytest.approx(math.degrees(1.0))


def test_a_zaxis_turns_the_frame_z_onto_the_direction_it_names():
    element = ElementTree.Element("geom", {"zaxis": "1 0 0"})
    rotation = mujoco_common.parse_orientation(element, mujoco_common.Compiler())
    assert urdf_common.rotate_vec(rotation, (0.0, 0.0, 1.0)) == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_an_unreadable_orientation_is_reported_and_leaves_the_body_unrotated():
    warnings = []
    element = ElementTree.Element("body", {"quat": "1 0 0"})
    assert mujoco_common.parse_orientation(element, mujoco_common.Compiler(), warnings) == urdf_common.IDENTITY_Q
    assert warnings and "four numbers" in warnings[0]


def test_a_pose_is_read_in_millimetres():
    element = ElementTree.Element("body", {"pos": "0.5 0 -0.25"})
    _, translation = mujoco_common.parse_pose(element, mujoco_common.Compiler())
    assert translation == pytest.approx((500.0, 0.0, -250.0))


#
# Reading a model
#


def test_a_body_of_one_geom_is_that_geom_named_after_the_body(tmp_path, no_occt):
    path = model(tmp_path, '<body name="brick" pos="0 0 1"><geom type="box" size="0.01 0.02 0.03"/></body>')

    result = read(path, output_folder=str(tmp_path))

    assert result["model_name"] == "m"
    (node,) = result["root"]["links"]
    assert node["type"] == "part"
    assert node["name"] == "brick"
    assert node["location"][0] == pytest.approx([0.0, 0.0, 1000.0])
    # MJCF states half-extents; PartCAD's primitive takes the whole size.
    assert no_occt == [("box", (20.0, 40.0, 60.0), node["part_file"])]


def test_a_body_of_several_geoms_becomes_a_node_holding_one_part_each(tmp_path, no_occt):
    path = model(
        tmp_path,
        '<body name="frame">'
        '<geom name="left" type="sphere" size="0.01"/>'
        '<geom name="right" type="sphere" size="0.01" pos="0.1 0 0"/>'
        "</body>",
    )

    (node,) = read(path, output_folder=str(tmp_path))["root"]["links"]

    assert node["type"] == "assembly"
    assert [child["name"] for child in node["links"]] == ["frame/left", "frame/right"]


def test_bodies_nest_the_way_the_tree_nests(tmp_path, no_occt):
    path = model(
        tmp_path,
        '<body name="base" pos="0 0 1">'
        '<geom type="sphere" size="0.01"/>'
        '<body name="arm" pos="0.5 0 0"><geom type="sphere" size="0.01"/></body>'
        "</body>",
    )

    (node,) = read(path, output_folder=str(tmp_path))["root"]["links"]

    assert node["type"] == "assembly"
    assert node["location"][0] == pytest.approx([0.0, 0.0, 1000.0])
    assert [child["name"] for child in node["links"]] == ["base", "base/arm"]
    # The nested body is placed inside the one that holds it, not in the world.
    arm = node["links"][1]
    assert arm["location"][0] == pytest.approx([500.0, 0.0, 0.0])


def test_a_mesh_is_referenced_where_it_lies(tmp_path):
    path = model(
        tmp_path,
        '<body name="cube"><geom type="mesh" mesh="cube"/></body>',
        extra='<asset><mesh name="cube" file="%s" scale="0.001 0.001 0.001"/></asset>' % STL_EXAMPLE,
    )

    (node,) = read(path, output_folder=str(tmp_path))["root"]["links"]

    assert node["part_type"] == "stl"
    assert node["part_file"] == STL_EXAMPLE
    # A mesh written in millimetres and scaled by 0.001 is a millimetre mesh.
    assert node["scale"] == pytest.approx(1.0)


def test_a_geom_takes_the_attributes_of_its_default_class(tmp_path, no_occt):
    path = model(
        tmp_path,
        '<body name="brick" childclass="blocks"><geom/></body>',
        extra='<default><default class="blocks"><geom type="box" size="0.01 0.01 0.01"/></default></default>',
    )

    (node,) = read(path, output_folder=str(tmp_path))["root"]["links"]

    assert node["name"] == "brick"
    assert no_occt[0][0] == "box"


def test_a_geoms_sliding_friction_is_read_as_the_property_all_three_formats_state(tmp_path, no_occt):
    """The MJCF end of the round trip 'mu' makes.

    One coefficient, three spellings: MJCF's first 'friction' component,
    SDFormat's '<friction><ode><mu>' and URDF's '<gazebo><mu1>' are the same
    number, and PartCAD calls it 'friction' in all three.
    """
    path = model(
        tmp_path,
        '<body name="brick"><geom type="sphere" size="0.01" friction="0.04 0.005 0.0001"/></body>',
    )

    (node,) = read(path, output_folder=str(tmp_path))["root"]["links"]

    assert node["physics"] == {"friction": 0.04}


def test_torsional_and_rolling_friction_are_reported_rather_than_invented_properties_for(tmp_path, no_occt):
    """PartCAD has a property for sliding friction and none for the other two."""
    path = model(
        tmp_path,
        '<body name="brick"><geom type="sphere" size="0.01" friction="0.5 0.01 0.002"/></body>',
    )

    result = read(path, output_folder=str(tmp_path))

    assert result["root"]["links"][0]["physics"] == {"friction": 0.5}
    assert result["dropped"]["friction"] == 1


def test_mujocos_own_defaults_are_not_read_as_something_the_model_said(tmp_path, no_occt):
    """A geom that states no friction states no friction."""
    path = model(tmp_path, '<body name="brick"><geom type="sphere" size="0.01"/></body>')

    (node,) = read(path, output_folder=str(tmp_path))["root"]["links"]

    assert "physics" not in node


def test_what_the_body_says_about_its_mass_and_what_the_geom_says_about_contact_both_survive(tmp_path, no_occt):
    path = model(
        tmp_path,
        '<body name="brick"><inertial pos="0 0 0" mass="0.5" diaginertia="1 1 1"/>'
        '<geom type="sphere" size="0.01" friction="0.3 0 0"/></body>',
    )

    (node,) = read(path, output_folder=str(tmp_path))["root"]["links"]

    assert node["physics"]["friction"] == 0.3
    assert node["physics"]["mass"] == 0.5


def test_what_a_static_tree_cannot_hold_is_counted_rather_than_dropped_in_silence(tmp_path, no_occt):
    path = model(
        tmp_path,
        '<body name="brick"><freejoint/><geom type="sphere" size="0.01"/>' '<site name="s"/><camera name="c"/></body>',
        extra='<actuator><motor name="a" joint="j"/></actuator>',
    )

    result = read(path, output_folder=str(tmp_path))

    assert result["dropped"]["joint"] == 1
    assert result["dropped"]["site"] == 1
    assert result["dropped"]["camera"] == 1
    assert result["dropped"]["actuator"] == 1


def test_a_plane_is_reported_rather_than_built(tmp_path, no_occt):
    path = model(
        tmp_path,
        '<geom name="floor" type="plane" size="1 1 0.1"/>'
        '<body name="brick"><geom type="sphere" size="0.01"/></body>',
    )

    result = read(path, output_folder=str(tmp_path))

    assert result["dropped"]["geometry"] == 1
    assert any("plane geom" in warning for warning in result["warnings"])
    assert [node["name"] for node in result["root"]["links"]] == ["brick"]


def test_an_include_is_spliced_in_rather_than_counted_as_dropped(tmp_path, no_occt):
    (tmp_path / "parts.xml").write_text(
        '<mujoco><worldbody><body name="brick"><geom type="sphere" size="0.01"/></body></worldbody></mujoco>',
        encoding="utf-8",
    )
    path = tmp_path / "model.xml"
    path.write_text('<mujoco model="m"><include file="parts.xml"/></mujoco>', encoding="utf-8")

    result = read(path, output_folder=str(tmp_path))

    assert [node["name"] for node in result["root"]["links"]] == ["brick"]
    assert not result["dropped"].get("include")


def test_an_include_that_cannot_be_resolved_is_reported(tmp_path, no_occt):
    path = tmp_path / "model.xml"
    path.write_text(
        '<mujoco model="m"><include file="missing.xml"/>'
        '<worldbody><body name="brick"><geom type="sphere" size="0.01"/></body></worldbody></mujoco>',
        encoding="utf-8",
    )

    result = read(path, output_folder=str(tmp_path))

    assert any("missing.xml" in warning for warning in result["warnings"])


def test_a_model_with_no_geometry_is_an_error(tmp_path):
    path = model(tmp_path, "")
    with pytest.raises(ValueError, match="No geometry"):
        read(path, output_folder=str(tmp_path))


def test_a_file_that_is_not_mjcf_says_so(tmp_path):
    path = tmp_path / "model.xml"
    path.write_text("<sdf><world/></sdf>", encoding="utf-8")
    with pytest.raises(ValueError, match="not <mujoco>"):
        read(path, output_folder=str(tmp_path))


def test_relative_references_resolve_against_the_declared_directory(tmp_path):
    """What makes an MJCF file a Jinja2 template rather than only a file.

    A rendered template lives in PartCAD's state directory while the meshes it
    names sit beside the file the package declared, so the reader is handed that
    directory separately.
    """
    source = tmp_path / "beside"
    source.mkdir()
    os.symlink(STL_EXAMPLE, str(source / "cube.stl"))
    path = model(
        tmp_path,
        '<body name="cube"><geom type="mesh" mesh="cube"/></body>',
        extra='<asset><mesh name="cube" file="cube.stl"/></asset>',
    )

    (node,) = read(path, output_folder=str(tmp_path), base_dir=str(source))["root"]["links"]

    assert os.path.realpath(node["part_file"]) == os.path.realpath(STL_EXAMPLE)


#
# The object the reader's tree becomes
#


def model_tree():
    """What the reader hands back for a model of one body of one shape."""
    return {
        "model_name": "stack",
        "warnings": [],
        "dropped": {"joint": 2},
        "root": {
            "type": "assembly",
            "name": "stack",
            "location": urdf_common.to_packed(mujoco_common.IDENTITY),
            "links": [
                {
                    "type": "part",
                    "name": "block",
                    "body": "block",
                    "link": "block",
                    "location": [[0.0, 0.0, 10.0], [0.0, 0.0, 1.0], 0.0],
                    "part_file": STL_EXAMPLE,
                    "part_type": "stl",
                    "scale": 1.0,
                    "physics": {"mass": 0.5},
                }
            ],
            "parts": [],
        },
    }


@pytest.fixture
def mjcf_package(tmp_path, monkeypatch):
    """A package declaring one MJCF file twice: as a scene and as an assembly."""
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "stack.xml").write_text(
        '<mujoco model="stack"><worldbody><body name="block"/></worldbody></mujoco>', encoding="utf-8"
    )
    (root / "partcad.yaml").write_text(
        "name: //mjcf\n"
        "scenes:\n  stack:\n    type: mjcf\n    path: stack.xml\n"
        "assemblies:\n  robot:\n    type: mjcf\n    path: stack.xml\n",
        encoding="utf-8",
    )

    project = pc.Context(str(root)).get_project("//")

    async def read_stub(_self=None):
        return model_tree()

    scene = project.get_scene("stack")
    assembly = project.get_assembly("robot")
    monkeypatch.setattr(scene.mjcf_factory, "_read_async", read_stub)
    monkeypatch.setattr(assembly.mjcf_factory, "_read_async", read_stub)
    return project, scene, assembly


def test_one_file_is_a_scene_or_an_assembly_depending_on_who_declared_it(mjcf_package):
    """The reason there are two MJCF types and one reader."""
    _project, scene, assembly = mjcf_package
    asyncio.run(scene.do_instantiate())
    asyncio.run(assembly.do_instantiate())

    assert scene.kind == "scene"
    assert assembly.kind == "assembly"
    assert [child.name for child in scene.children] == ["block"]
    assert [child.name for child in assembly.children] == ["block"]


def test_every_geom_becomes_a_part_of_the_package(mjcf_package):
    project, scene, _assembly = mjcf_package
    asyncio.run(scene.do_instantiate())

    # '<object>/<body>', declared by the MJCF file rather than by
    # 'partcad.yaml', and inspectable and exportable like any other part.
    assert "stack/block" in project.parts
    assert project.parts["stack/block"].config["properties"]["physics"]["mass"] == 0.5


def test_the_object_records_what_the_model_said_and_what_was_dropped(mjcf_package):
    from partcad.assembly_factory_mjcf import DROPPED_LABELS

    _project, scene, _assembly = mjcf_package
    scene.mjcf_factory._report(model_tree())

    assert scene.mjcf_factory.mjcf_info["model_name"] == "stack"
    assert scene.mjcf_factory.mjcf_info["dropped"] == {"joint": 2}
    assert "joint" in DROPPED_LABELS


def test_every_counter_the_reader_keeps_has_a_wording():
    """A counter with no label reads as a bare key in 'pc info'."""
    from partcad.assembly_factory_mjcf import DROPPED_LABELS

    assert set(wrapper_import_mjcf.DROPPABLE) <= set(DROPPED_LABELS)


#
# Writing a model
#


@pytest.fixture
def export_mjcf(monkeypatch):
    """The MJCF exporter, with the two things that need OCCT stubbed out."""
    import export_mjcf as module
    import ocp_serialize

    monkeypatch.setattr(ocp_serialize, "decode_shape", lambda obj: ("shape", obj.get("brep")))
    monkeypatch.setattr(module, "write_mesh", lambda shape, path, options: open(path, "wb").write(b"solid x\n"))
    return module


def exported(module, path, root, **request):
    result = module.process(str(path), dict({"wrapped": root}, **request))
    return result, ElementTree.parse(str(path)).getroot()


def envelope(name, label, brep, location=None):
    node = {"name": name, "label": label, "brep": brep}
    if location is not None:
        node["location"] = location
    return node


def test_a_scene_becomes_a_model_of_one_body_per_object(export_mjcf, tmp_path):
    cube = envelope("//p:cube", "cube", b"CUBE")
    group = {
        "name": "//p:group",
        "label": "group",
        "location": [[100.0, 0.0, 0.0], [0.0, 0.0, 1.0], 90.0],
        "assembly": [envelope("//p:cyl", "cylinder", b"CYL", [[0.0, 0.0, 10.0], [0.0, 0.0, 1.0], 0.0])],
    }
    root = {"name": "//p:bench", "label": "bench", "assembly": [cube, group]}

    result, mujoco = exported(export_mjcf, tmp_path / "bench.xml", root)

    assert result["success"]
    assert mujoco.tag == "mujoco"
    assert mujoco.get("model") == "bench"
    worldbody = mujoco.find("worldbody")
    assert [body.get("name") for body in worldbody.findall("body")] == ["cube", "group"]

    group_body = worldbody.findall("body")[1]
    assert group_body.get("pos").split()[0] == "0.1"  # 100 mm -> 0.1 m
    assert [body.get("name") for body in group_body.findall("body")] == ["cylinder"]

    # Meshes in millimetres, referenced with the scale that says so.
    mesh = mujoco.find("asset/mesh[@name='cylinder']")
    assert mesh.get("file") == "bench_meshes/cylinder.stl"
    assert mesh.get("scale").split() == ["0.001"] * 3
    assert os.path.isfile(str(tmp_path / "bench_meshes" / "cylinder.stl"))


def test_a_shape_used_twice_is_written_once(export_mjcf, tmp_path):
    cube = envelope("//p:cube", "cube", b"CUBE")
    twin = envelope("//p:cube", "cube", b"CUBE", [[10.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0])
    root = {"name": "//p:bench", "label": "bench", "assembly": [cube, twin]}

    result, mujoco = exported(export_mjcf, tmp_path / "bench.xml", root)

    assert result["meshes"] == ["bench_meshes/cube.stl"]
    assert [mesh.get("name") for mesh in mujoco.findall("asset/mesh")] == ["cube"]
    # And the two bodies are still told apart.
    assert [body.get("name") for body in mujoco.findall("worldbody/body")] == ["cube", "cube_1"]


def test_a_scene_is_welded_to_the_world_unless_told_otherwise(export_mjcf, tmp_path):
    """A scene states where things are, so nothing in it is meant to move."""
    root = {"name": "//p:bench", "label": "bench", "assembly": [envelope("//p:cube", "cube", b"CUBE")]}

    _result, welded = exported(export_mjcf, tmp_path / "a.xml", root)
    assert welded.find("worldbody/body/freejoint") is None

    _result, free = exported(export_mjcf, tmp_path / "b.xml", root, static=False)
    assert free.find("worldbody/body/freejoint") is not None


def test_flattening_places_every_shape_in_the_world_at_its_world_pose(export_mjcf, tmp_path):
    """What a physics simulation needs: bodies that can move independently.

    A body nested in another with no joint between them is one rigid body with
    it, so a stack of blocks written that way could never fall over.
    """
    group = {
        "name": "//p:group",
        "label": "group",
        "location": [[100.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0],
        "assembly": [
            envelope("//p:a", "a", b"A", [[0.0, 0.0, 10.0], [0.0, 0.0, 1.0], 0.0]),
            envelope("//p:b", "b", b"B", [[0.0, 0.0, 30.0], [0.0, 0.0, 1.0], 0.0]),
        ],
    }
    root = {"name": "//p:bench", "label": "bench", "assembly": [group]}

    _result, mujoco = exported(export_mjcf, tmp_path / "bench.xml", root, flatten=True, static=False)

    bodies = mujoco.findall("worldbody/body")
    assert [body.get("name") for body in bodies] == ["a", "b"]
    assert all(body.find("freejoint") is not None for body in bodies)
    # Each is placed where the tree put it, the group's own placement included.
    assert [float(v) for v in bodies[0].get("pos").split()] == pytest.approx([0.1, 0.0, 0.01])
    assert [float(v) for v in bodies[1].get("pos").split()] == pytest.approx([0.1, 0.0, 0.03])


def test_the_friction_written_is_the_one_the_round_trip_reads_back(export_mjcf, tmp_path, no_occt):
    """Out as MJCF's three-component 'friction', back as PartCAD's one."""
    root = {"name": "//p:bench", "label": "bench", "assembly": [envelope("//p:cube", "cube", b"CUBE")]}
    properties = {"//p:cube": {"physics": {"friction": 0.04}}}
    path = tmp_path / "bench.xml"

    exported(export_mjcf, path, root, properties=properties)
    (node,) = read(path, output_folder=str(tmp_path))["root"]["links"]

    assert node["physics"]["friction"] == pytest.approx(0.04)


def test_what_a_part_says_about_itself_is_written_rather_than_recomputed(export_mjcf, tmp_path):
    root = {"name": "//p:bench", "label": "bench", "assembly": [envelope("//p:cube", "cube", b"CUBE")]}
    properties = {"//p:cube": {"physics": {"mass": 2.5, "friction": 0.7}, "color": "#FF8000"}}

    result, mujoco = exported(export_mjcf, tmp_path / "bench.xml", root, properties=properties)

    body = mujoco.find("worldbody/body")
    assert float(body.find("inertial").get("mass")) == pytest.approx(2.5)
    geom = body.find("geom")
    # A part that states its mass does not also get a density, or the mass would
    # be computed from the geometry and the two would disagree.
    assert geom.get("density") is None
    assert geom.get("friction").split()[0] == "0.7"
    assert geom.get("rgba").split()[:3] == ["1", "0.502", "0"]
    assert result["unsupported"] == []


def test_a_property_mjcf_cannot_state_is_reported_rather_than_lost(export_mjcf, tmp_path):
    root = {"name": "//p:bench", "label": "bench", "assembly": [envelope("//p:cube", "cube", b"CUBE")]}
    properties = {"//p:cube": {"physics": {"selfCollide": True}}}

    result, _mujoco = exported(export_mjcf, tmp_path / "bench.xml", root, properties=properties)

    assert result["unsupported"] == ["selfCollide"]


def test_the_light_and_the_ground_are_what_makes_the_file_usable(export_mjcf, tmp_path):
    root = {"name": "//p:bench", "label": "bench", "assembly": [envelope("//p:cube", "cube", b"CUBE")]}

    _result, with_both = exported(export_mjcf, tmp_path / "a.xml", root)
    assert with_both.find("worldbody/light") is not None
    assert with_both.find("worldbody/geom[@type='plane']") is not None

    _result, without = exported(export_mjcf, tmp_path / "b.xml", root, light=False, ground_plane=False)
    assert without.find("worldbody/light") is None
    assert without.find("worldbody/geom[@type='plane']") is None


def test_ascii_stl_is_reported_because_mujoco_cannot_read_it(export_mjcf, tmp_path):
    root = {"name": "//p:bench", "label": "bench", "assembly": [envelope("//p:cube", "cube", b"CUBE")]}

    result, _mujoco = exported(export_mjcf, tmp_path / "bench.xml", root, ascii=True)

    assert any("binary STL" in warning for warning in result["warnings"])


def test_a_parameterized_name_does_not_become_the_model_name(export_mjcf, tmp_path):
    """What `pc sim` produces: a scene whose subject is a parameter."""
    root = {
        "name": "//p:subject;subject=//p:block,subject_kind=part",
        "label": "subject;subject=//p:block,subject_kind=part",
        "assembly": [envelope("//p:cube", "cube", b"CUBE")],
    }

    _result, mujoco = exported(export_mjcf, tmp_path / "scene.xml", root)

    assert mujoco.get("model") == "subject"


def test_the_exporter_needs_a_shape_or_an_assembly(export_mjcf, tmp_path):
    with pytest.raises(ValueError, match="needs a shape or an assembly"):
        export_mjcf.process(str(tmp_path / "x.xml"), {"wrapped": "not a shape"})


def test_a_model_written_here_reads_back_as_the_same_arrangement(export_mjcf, tmp_path, no_occt):
    """The round trip that makes the two halves one format and not two."""
    root = {
        "name": "//p:bench",
        "label": "bench",
        "assembly": [
            envelope("//p:a", "a", b"A", [[100.0, 0.0, 250.0], [0.0, 0.0, 1.0], 90.0]),
            envelope("//p:b", "b", b"B"),
        ],
    }
    path = tmp_path / "bench.xml"
    exported(export_mjcf, path, root)

    result = read(path, output_folder=str(tmp_path))

    placed = {node["name"]: node for node in result["root"]["links"]}
    assert set(placed) == {"a", "b"}
    assert placed["a"]["location"][0] == pytest.approx([100.0, 0.0, 250.0])
    assert placed["a"]["location"][2] == pytest.approx(90.0)
    assert placed["b"]["location"][0] == pytest.approx([0.0, 0.0, 0.0])
