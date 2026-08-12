#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the 'urdf' assembly type, the URDF exporter and 'pc convert assembly'.

The point of all three is that a URDF becomes the same in-memory representation
an ASSY file produces, so the tests compare trees and placements directly rather
than inspecting URDF-specific internals.
"""

import asyncio
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

import partcad as pc
from partcad.actions.assembly import convert_assembly_action
from partcad.adhoc.convert import convert_cad_file
from partcad.assembly_factory_urdf import DROPPED_LABELS
from partcad.geom import Location

EXAMPLES = "examples"
URDF_EXAMPLE = "//produce_assembly_urdf:robot"
URDF_PACKAGE = "//pub/examples/partcad/produce_assembly_urdf"

# The packages the example URDF reaches: it resolves a 'package://' mesh
# reference by walking up from its own directory.
URDF_EXAMPLE_PACKAGES = ("produce_assembly_urdf", "produce_part_stl")
ASSY_EXAMPLE_PACKAGES = ("produce_assembly_assy", "produce_part_cadquery_logo", "produce_part_step")


def sandbox(tmp_path, packages):
    """A throwaway copy of some example packages, as a package root of its own."""
    root = tmp_path / "workspace"
    root.mkdir()
    shutil.copy(os.path.join(EXAMPLES, "partcad.yaml"), root)
    for package in packages:
        shutil.copytree(os.path.join(EXAMPLES, package), root / package)
    return root


def assert_valid_package_config(config):
    """Check a 'partcad.yaml' against the schema editors validate it with."""
    import json

    from jsonschema import Draft7Validator

    schema_path = Path(pc.__file__).parent / "schema" / "partcad.json"
    with open(schema_path) as f:
        schema = json.load(f)
    errors = sorted(Draft7Validator(schema).iter_errors(config), key=lambda e: list(e.path))
    assert not errors, "\n".join("%s: %s" % (list(e.path), e.message) for e in errors)


def structure(assembly):
    """The shape of an assembly tree: kinds, placements and nesting, without names.

    Names do not survive a URDF round trip (URDF has its own naming rules, and a
    PartCAD name carries a package path that a ROS name cannot), so equality of
    the *structure* is what a round trip has to preserve.
    """

    def walk(item, location):
        packed = location.as_packed() if location is not None else None
        node = {
            "kind": "assembly" if hasattr(item, "children") else "part",
            "location": None if packed is None else placement(packed),
            "children": [],
        }
        for child in getattr(item, "children", []):
            node["children"].append(walk(child.item, child.location))
        return node

    return walk(assembly, None)


def placement(packed):
    """A packed location as a comparable value, up to the sign of the axis."""
    return (
        tuple(round(v, 4) for v in packed[0]),
        # The axis only means something when there is a rotation, and an
        # axis/angle pair and its negation are the same rotation.
        tuple(round(abs(v) * (1 if packed[2] >= 0 else -1), 4) for v in packed[1])
        if abs(packed[2]) > 1e-6
        else None,
        round(abs(packed[2]), 4),
    )


def link_frames(urdf_assembly):
    """Where each URDF link's own frame ends up, relative to the assembly.

    The frame of a link is not always where its geometry sits - a link that is
    one shape placed at an ``<origin>`` has its part offset from it - so this is
    what a conversion has to reproduce, and what the generated connections claim
    to. Composed from the table the import records rather than from the tree.
    """
    links = urdf_assembly.urdf_factory.urdf_info["links"]
    resolved = {}

    def absolute(name):
        # The table is recorded as the walk unwinds, so a parent may come after
        # its children in it; resolve by following the parent links instead.
        if name not in resolved:
            parent = links[name]["parent"]
            base = absolute(parent) if parent in links else Location()
            resolved[name] = base * Location(links[name]["origin"])
        return resolved[name]

    return {name: placement(absolute(name).as_packed()) for name in links}


def find_child(assembly, name):
    """The item an assembly holds under 'name', at any depth."""
    for child in getattr(assembly, "children", []):
        if child.name == name:
            return child.item
        found = find_child(child.item, name)
        if found is not None:
            return found
    return None


def absolute_placements(assembly):
    """Every leaf part's placement relative to the assembly, keyed by its name."""
    found = {}

    def walk(item, location):
        for child in getattr(item, "children", []):
            here = location * (child.location or Location())
            if hasattr(child.item, "children"):
                walk(child.item, here)
            else:
                found[child.name] = placement(here.as_packed())

    walk(assembly, Location())
    return found


#
# Reading a URDF
#


def test_urdf_example_builds_the_expected_tree():
    """The example URDF becomes a nested assembly with one part per link.

    It exercises every geometry source a URDF can name: primitives
    (box/cylinder/sphere), a mesh reached through 'package://', a link that
    states its collision and visual shapes separately, and a movable joint
    (which is placed at its zero position).
    """
    ctx = pc.init(EXAMPLES)
    robot = ctx._get_assembly(URDF_EXAMPLE)
    assert robot is not None
    asyncio.run(robot.do_instantiate())

    tree = structure(robot)
    # base_link's own shape, then the shoulder sub-tree.
    assert [child["kind"] for child in tree["children"]] == ["part", "assembly"]

    # A URDF joint origin is metres; PartCAD is millimetres. 'shoulder_pan' sits
    # at z=0.02 m above the base.
    assert tree["children"][1]["location"][0] == (0.0, 0.0, 20.0)

    # The 'elbow' joint's rpy of (0, pi/4, 0) is a 45 degree rotation.
    forearm = tree["children"][1]["children"][1]
    assert forearm["location"][2] == pytest.approx(45.0, abs=1e-3)

    # The wrist's collision geometry is a single mesh, so the link is one part
    # even though its visual geometry is two elements.
    wrist = forearm["children"][1]
    assert wrist["kind"] == "part"

    bom = asyncio.run(robot.get_bom())
    assert sorted(name.rsplit(":", 1)[1] for name in bom) == [
        "robot/base_link",
        "robot/forearm",
        "robot/shoulder",
        "robot/wrist",
    ]


def test_urdf_example_produces_geometry():
    ctx = pc.init(EXAMPLES)
    robot = ctx._get_assembly(URDF_EXAMPLE)
    assert asyncio.run(robot.get_wrapped(ctx)) is not None


def test_urdf_links_are_ordinary_parts():
    """Each link is a part of the package, named '<assembly>/<link>'.

    They are not declared in 'partcad.yaml' - the URDF is what declares them -
    so a package that is handed one of these names builds the assembly that owns
    it first. That has to work on a context that has never touched the assembly.
    """
    # A context of its own, which has never touched the assembly.
    ctx = pc.Context(EXAMPLES)
    part = ctx.get_part("//produce_assembly_urdf:robot/wrist")
    assert part is not None
    assert part.name == "robot/wrist"
    # A part like any other: it builds, and it can be exported on its own.
    assert asyncio.run(part.get_wrapped(ctx)) is not None
    assert asyncio.run(part.convert("step", ctx))

    project = ctx.get_project(URDF_PACKAGE)
    assert "robot/base_link" in project.parts
    # Still not something the package declares.
    assert "robot/base_link" not in (project.config_obj.get("parts") or {})


def test_a_slash_in_a_part_name_is_not_enough():
    """Only a name whose prefix really is such an assembly triggers the build."""
    project = pc.Context(EXAMPLES).get_project(URDF_PACKAGE)
    assert project._derived_part_owner("robot/wrist") == "robot"
    assert project._derived_part_owner("brackets/left") is None
    assert project._derived_part_owner("wrist") is None


def test_urdf_parts_carry_what_partcad_does_not_model():
    """A link's mass, inertia, materials and geometry are kept verbatim."""
    ctx = pc.Context(EXAMPLES)
    urdf = ctx.get_part("//produce_assembly_urdf:robot/shoulder").config["physics"]["urdf"]

    assert urdf["link"] == "shoulder"
    assert urdf["inertial"]["mass"] == pytest.approx(0.32)
    assert urdf["visual"][0]["material"]["name"] == "orange"

    # The robot's root link is the assembly itself, so what it said about itself
    # belongs to the assembly - there is no part above it to hold it.
    robot = ctx._get_assembly(URDF_EXAMPLE)
    asyncio.run(robot.do_instantiate())
    root = robot.config["physics"]["urdf"]
    assert root["inertial"]["mass"] == pytest.approx(0.78)
    assert root["inertial"]["inertia"]["izz"] == pytest.approx(1.87e-3)
    # Both the geometry the shape was built from and the geometry that was not.
    assert root["collision"][0]["box"]["size"] == pytest.approx([0.13, 0.13, 0.02])
    assert root["visual"][0]["box"]["size"] == pytest.approx([0.12, 0.12, 0.02])
    assert root["visual"][0]["material"]["name"] == "grey"
    # The Gazebo block, as the XML it was.
    assert "<mu1>" in root["gazebo"][0]


def test_a_link_of_several_shapes_is_a_sub_assembly(tmp_path):
    """Nothing is combined: one part per shape, each reading its own file.

    The example's wrist has two visuals - a sphere and a mesh - at different
    offsets. Built from those, it is a sub-assembly of two parts, the mesh one
    reading the very file the URDF named, and each placed at the offset the URDF
    gave it rather than having it baked into new geometry.
    """
    root = sandbox(tmp_path, URDF_EXAMPLE_PACKAGES)
    package = root / "produce_assembly_urdf"
    config = (package / "partcad.yaml").read_text().replace("ignoreCollision: false", "ignoreCollision: true")
    (package / "partcad.yaml").write_text(config)

    ctx = pc.Context(str(root))
    sphere = ctx.get_part("//produce_assembly_urdf:robot/wrist/1")
    mesh = ctx.get_part("//produce_assembly_urdf:robot/wrist/2")
    assert sphere is not None and mesh is not None

    # The mesh part reads the URDF's own file; only the primitive is generated.
    assert mesh.config["type"] == "stl"
    assert Path(mesh.config["path"]).name == "cube.stl"
    assert sphere.config["type"] == "step"

    # And the offsets are still offsets: each shape sits inside the link's
    # sub-assembly exactly where the URDF's '<origin>' put it (0.015 m and
    # 0.03 m up), rather than having been moved there before the file was read.
    robot = ctx._get_assembly("//produce_assembly_urdf:robot")
    asyncio.run(robot.do_instantiate())
    wrist = find_child(robot, "wrist")
    assert [child.name for child in wrist.children] == ["wrist/1", "wrist/2"]
    assert [placement(child.location.as_packed())[0] for child in wrist.children] == [
        (0.0, 0.0, 15.0),
        (0.0, 0.0, 30.0),
    ]


def test_collision_geometry_wins_unless_ignored(tmp_path):
    """A link that states both is built from its collision geometry.

    In the example the wrist's collision geometry is one simple mesh while its
    visual geometry is two elements, so which was used decides whether the link
    is one part or a sub-assembly of two.
    """
    root = sandbox(tmp_path, URDF_EXAMPLE_PACKAGES)
    package = root / "produce_assembly_urdf"

    default = pc.Context(str(root)).get_project(URDF_PACKAGE)
    assert default.get_part("robot/wrist").config["type"] == "stl"
    assert default.get_part("robot/wrist/1", quiet=True) is None

    config = (package / "partcad.yaml").read_text().replace("ignoreCollision: false", "ignoreCollision: true")
    (package / "partcad.yaml").write_text(config)
    ignored = pc.Context(str(root)).get_project(URDF_PACKAGE)
    assert ignored.get_part("robot/wrist", quiet=True) is None
    assert ignored.get_part("robot/wrist/1") is not None


def test_urdf_reports_what_it_could_not_keep():
    """The metadata a PartCAD assembly cannot hold is reported, not passed over."""
    ctx = pc.init(EXAMPLES)
    robot = ctx._get_assembly(URDF_EXAMPLE)
    asyncio.run(robot.do_instantiate())

    info = robot.info()
    assert info["Robot"] == "partcad_urdf_example"
    assert info["RootLink"] == "base_link"

    dropped = info["UrdfDropped"]
    for key in ("inertial", "material", "joint_kinematics", "joint_limits", "joint_dynamics", "visual"):
        assert dropped[DROPPED_LABELS[key]] > 0

    assert info["UrdfMovableJoints"] == ["shoulder_pan (revolute)"]


#
# Writing a URDF
#


def _export_urdf(ctx, assembly, directory, name="logo", **kwargs):
    path = os.path.join(directory, "%s.urdf" % name)
    # A coarse mesh: this is about the structure of the export, and the default
    # tolerance turns the logo's bolt into tens of megabytes of triangles.
    asyncio.run(assembly.render_async(ctx, "urdf", filepath=path, tolerance=1.0, angularTolerance=0.5, **kwargs))
    return path


def mesh_scale(robot, filename):
    for mesh in robot.findall("link/visual/geometry/mesh"):
        if mesh.get("filename") == filename:
            return [float(v) for v in mesh.get("scale").split()]
    raise AssertionError("no mesh named %s" % filename)


def test_export_logo_to_urdf(tmp_path):
    """The PartCAD logo exports as a valid URDF plus its mesh files."""
    ctx = pc.init(EXAMPLES)
    logo = ctx._get_assembly("//produce_assembly_assy:logo")
    path = _export_urdf(ctx, logo, str(tmp_path))

    robot = ET.parse(path).getroot()
    assert robot.tag == "robot"

    links = {link.get("name") for link in robot.findall("link")}
    joints = robot.findall("joint")
    # Every link but the root is reached by exactly one joint, and every joint
    # is fixed - a static assembly has no kinematics to express.
    assert len(joints) == len(links) - 1
    assert {joint.get("type") for joint in joints} == {"fixed"}
    children = [joint.find("child").get("link") for joint in joints]
    assert len(children) == len(set(children))
    assert set(children) <= links
    # Exactly one root: a link that is no joint's child.
    assert len(links - set(children)) == 1

    # The five placed parts of the logo carry meshes; the two structural links
    # (the assembly and its ASSY container) do not.
    meshes = robot.findall("link/visual/geometry/mesh")
    assert len(meshes) == 5
    # The logo places two bones and two head halves, so three distinct meshes.
    referenced = {mesh.get("filename") for mesh in meshes}
    assert len(referenced) == 3
    for reference in referenced:
        assert (tmp_path / reference).is_file()
        # Millimetre meshes, as URDF states it.
        assert mesh_scale(robot, reference) == pytest.approx([0.001, 0.001, 0.001])

    # Collision geometry mirrors the visual geometry.
    assert len(robot.findall("link/collision/geometry/mesh")) == 5

    # Solids have computable inertial properties, so they are written out.
    for inertial in robot.findall("link/inertial"):
        assert float(inertial.find("mass").get("value")) > 0.0
        inertia = inertial.find("inertia")
        for axis in ("ixx", "iyy", "izz"):
            assert float(inertia.get(axis)) > 0.0


def test_export_puts_back_what_a_urdf_import_carried(tmp_path):
    """Exporting a URDF assembly restores what PartCAD carried but did not model."""
    ctx = pc.init(EXAMPLES)
    robot = ctx._get_assembly(URDF_EXAMPLE)
    path = _export_urdf(ctx, robot, str(tmp_path), name="robot")
    exported = ET.parse(path).getroot()

    # One link per link of the source, with its shapes back where they were:
    # the sub-assembly a link of several shapes becomes does not turn into a
    # frame link with a link per shape.
    links = [link.get("name") for link in exported.findall("link")]
    assert len(links) == 4
    for link in exported.findall("link"):
        assert link.find("visual") is not None

    # The root link is the assembly itself, so it is what carries what the
    # URDF's own root link said - the stated mass, not one recomputed from the
    # geometry and a density.
    base = exported.find("link")
    assert float(base.find("inertial/mass").get("value")) == pytest.approx(0.78)
    assert float(base.find("inertial/inertia").get("izz")) == pytest.approx(1.87e-3)
    assert base.find("visual/material").get("name") == "grey"
    # The '<origin>' of a shape within its link survived as an origin.
    assert [float(v) for v in base.find("visual/origin").get("xyz").split()] == pytest.approx([0.0, 0.0, 0.01])

    # The Gazebo block came back, pointing at the link it went out on.
    gazebo = exported.findall("gazebo")
    assert [element.get("reference") for element in gazebo] == [base.get("name")]
    assert gazebo[0].find("mu1") is not None


def test_logo_round_trip_through_urdf(tmp_path):
    """logo.assy -> URDF + STL -> 'urdf' assembly gives back the same tree.

    Names, materials and every other thing URDF cannot carry are gone; the tree
    of placed shapes is not.
    """
    ctx = pc.init(EXAMPLES)
    logo = ctx._get_assembly("//produce_assembly_assy:logo")
    asyncio.run(logo.do_instantiate())

    _export_urdf(ctx, logo, str(tmp_path))
    Path(tmp_path / "partcad.yaml").write_text("assemblies:\n  logo:\n    type: urdf\n")

    imported_ctx = pc.Context(str(tmp_path))
    imported = imported_ctx._get_assembly(":logo")
    assert imported is not None
    asyncio.run(imported.do_instantiate())

    assert structure(imported) == structure(logo)

    # And it is still buildable geometry, not just a matching tree.
    assert asyncio.run(imported.get_wrapped(imported_ctx)) is not None


#
# Converting between the two
#


def test_convert_urdf_to_assy(tmp_path):
    """A URDF assembly becomes an ASSY one: stl parts, interfaces, connections.

    The placements have to come out identical, because they are now produced by
    the port/interface algebra rather than copied - which is the whole claim the
    joint-to-interface mapping makes.
    """
    root = sandbox(tmp_path, URDF_EXAMPLE_PACKAGES)
    package = root / "produce_assembly_urdf"

    before = pc.Context(str(root))._get_assembly("//produce_assembly_urdf:robot")
    asyncio.run(before.do_instantiate())
    expected = link_frames(before)

    ctx = pc.Context(str(root))
    convert_assembly_action(ctx.get_project("//produce_assembly_urdf"), "robot", "assy")

    config = yaml.safe_load((package / "partcad.yaml").read_text())
    assert config["assemblies"]["robot"]["type"] == "assy"
    assert (package / "robot.assy").is_file()
    # What was generated has to be a package configuration a human could have
    # written, not merely one PartCAD happens to accept.
    assert_valid_package_config(config)

    # An stl part per link, next to the assembly it belongs to.
    for link in ("base_link", "shoulder", "forearm", "wrist"):
        entry = config["parts"]["robot/%s" % link]
        assert entry["type"] == "stl"
        assert (package / entry["path"]).is_file()
    # What the URDF said about a link travelled with it.
    assert config["parts"]["robot/base_link"]["physics"]["urdf"]["inertial"]["mass"] == pytest.approx(0.78)

    # One interface pair per distinct joint, reused where the joints agree: the
    # two fixed joints share a pair, the revolute one gets its own.
    interfaces = config["interfaces"]
    assert set(interfaces) == {
        "robot/fixed-socket",
        "robot/fixed-plug",
        "robot/shoulder_pan-socket",
        "robot/shoulder_pan-plug",
    }
    revolute = interfaces["robot/shoulder_pan-socket"]
    assert revolute["motion"]["type"] == "revolute"
    assert revolute["motion"]["axis"] == pytest.approx([0.0, 0.0, 1.0])
    assert revolute["motion"]["limits"]["upper"] == pytest.approx(3.14)
    assert revolute["physics"]["urdf"]["limit"]["effort"] == pytest.approx(12.0)
    assert revolute["physics"]["urdf"]["dynamics"]["damping"] == pytest.approx(0.1)
    assert interfaces["robot/shoulder_pan-plug"]["mates"] == "robot/shoulder_pan-socket"

    after = pc.Context(str(package))._get_assembly(":robot")
    asyncio.run(after.do_instantiate())
    assert absolute_placements(after) == expected


def test_a_converted_joint_can_be_posed(tmp_path):
    """The interface a movable joint becomes actually moves the parts.

    'motion:' records what the joint is; the parameter generated next to it is
    the executable half, and naming it in a connection places the child where
    the joint at that value puts it.
    """
    root = sandbox(tmp_path, URDF_EXAMPLE_PACKAGES)
    package = root / "produce_assembly_urdf"
    convert_assembly_action(pc.Context(str(root)).get_project("//produce_assembly_urdf"), "robot", "assy")

    assy = package / "robot.assy"
    assy.write_text(
        assy.read_text().replace(
            "      toInstance: shoulder_pan\n",
            "      toInstance: shoulder_pan\n      toParams: {angle: 90}\n",
        )
    )

    posed = pc.Context(str(package))._get_assembly(":robot")
    asyncio.run(posed.do_instantiate())
    placements = absolute_placements(posed)

    # A quarter turn about the joint's own axis (+Z), and the base is untouched.
    assert placements["shoulder"] == ((0.0, 0.0, 20.0), (0.0, 0.0, 1.0), 90.0)
    assert placements["base_link"][2] == 0.0


def test_convert_assy_to_urdf(tmp_path):
    """An ASSY assembly becomes a URDF one, with an STL per shape in it."""
    root = sandbox(tmp_path, ASSY_EXAMPLE_PACKAGES)
    package = root / "produce_assembly_assy"

    ctx = pc.Context(str(root))
    convert_assembly_action(ctx.get_project("//produce_assembly_assy"), "logo", "urdf")

    config = yaml.safe_load((package / "partcad.yaml").read_text())
    assert config["assemblies"]["logo"] == {
        "type": "urdf",
        "desc": "PartCAD logo",
        "path": "logo.urdf",
    }
    assert (package / "logo.urdf").is_file()

    exported = ET.parse(package / "logo.urdf").getroot()
    for mesh in exported.findall("link/visual/geometry/mesh"):
        assert (package / mesh.get("filename")).is_file()

    # And the package still works, now reading the URDF it just wrote.
    converted = pc.Context(str(root))._get_assembly("//produce_assembly_assy:logo")
    asyncio.run(converted.do_instantiate())
    assert converted.children


def test_convert_rejects_formats_that_are_not_assemblies(tmp_path):
    root = sandbox(tmp_path, URDF_EXAMPLE_PACKAGES)
    project = pc.Context(str(root)).get_project("//produce_assembly_urdf")
    with pytest.raises(ValueError, match="assy and urdf"):
        convert_assembly_action(project, "robot", "step")


def test_adhoc_convert_rejects_urdf(tmp_path):
    """An ad-hoc conversion has no package, and a URDF is nothing without one."""
    source = tmp_path / "robot.urdf"
    source.write_text("<robot name='r'><link name='a'/></robot>")

    with pytest.raises(ValueError, match="only means anything inside a package"):
        convert_cad_file(str(source), "urdf", str(tmp_path / "out.stl"), "stl")
    with pytest.raises(ValueError, match="only means anything inside a package"):
        convert_cad_file(str(source), "stl", str(tmp_path / "out.urdf"), "urdf")
