#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the 'urdf' assembly type and the URDF exporter.

The point of both is that a URDF becomes the same in-memory representation an
ASSY file produces, so the tests compare the two trees directly rather than
inspecting URDF-specific internals.
"""

import asyncio
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import partcad as pc
from partcad.assembly_factory_urdf import DROPPED_LABELS

EXAMPLES = "examples"
URDF_EXAMPLE = "//produce_assembly_urdf:robot"


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
            "location": (
                None
                if packed is None
                else (
                    tuple(round(v, 4) for v in packed[0]),
                    # The axis is only meaningful when there is a rotation, and
                    # an axis/angle pair and its negation are the same rotation.
                    tuple(round(abs(v) * (1 if packed[2] >= 0 else -1), 4) for v in packed[1])
                    if abs(packed[2]) > 1e-6
                    else None,
                    round(abs(packed[2]), 4),
                )
            ),
            "children": [],
        }
        for child in getattr(item, "children", []):
            node["children"].append(walk(child.item, child.location))
        return node

    return walk(assembly, None)


def test_urdf_example_builds_the_expected_tree():
    """The example URDF becomes a nested assembly of parts.

    The example exercises every geometry source a URDF can name: primitives
    (box/cylinder/sphere), a mesh reached through 'package://', a link with two
    visuals (which becomes a sub-assembly), and a movable joint (which is placed
    at its zero position).
    """
    ctx = pc.init(EXAMPLES)
    robot = ctx._get_assembly(URDF_EXAMPLE)
    assert robot is not None
    asyncio.run(robot.do_instantiate())

    tree = structure(robot)
    # base_link's box, then the shoulder sub-tree.
    assert [child["kind"] for child in tree["children"]] == ["part", "assembly"]

    # A URDF joint origin is metres; PartCAD is millimetres. 'shoulder_pan' sits
    # at z=0.02 m above the base.
    assert tree["children"][1]["location"][0] == (0.0, 0.0, 20.0)

    # The 'elbow' joint's rpy of (0, pi/4, 0) is a 45 degree rotation.
    forearm = tree["children"][1]["children"][1]
    assert forearm["location"][2] == pytest.approx(45.0, abs=1e-3)

    # The wrist link has two visuals, so it is a sub-assembly of two parts.
    wrist = forearm["children"][1]
    assert wrist["kind"] == "assembly"
    assert [child["kind"] for child in wrist["children"]] == ["part", "part"]

    bom = asyncio.run(robot.get_bom())
    assert sum(bom.values()) == 5


def test_urdf_example_produces_geometry():
    ctx = pc.init(EXAMPLES)
    robot = ctx._get_assembly(URDF_EXAMPLE)
    assert asyncio.run(robot.get_wrapped(ctx)) is not None


def test_urdf_parts_are_not_advertised_by_the_package():
    """The meshes a URDF points at are registered, but as an internal detail.

    They have to be reachable - the assembly's children are real Parts - but
    they are not part of what the package offers, so they are not documented.
    """
    ctx = pc.init(EXAMPLES)
    robot = ctx._get_assembly(URDF_EXAMPLE)
    asyncio.run(robot.do_instantiate())

    project = ctx.get_project("//pub/examples/partcad/produce_assembly_urdf")
    assert "robot/base_link" in project.parts
    assert project.parts["robot/base_link"].config["internal"] is True
    assert "robot/base_link" not in (project.config_obj.get("parts") or {})


def test_urdf_reports_what_it_could_not_keep():
    """The metadata a PartCAD assembly cannot hold is reported, not passed over.

    The example URDF has inertials, materials, a revolute joint with limits and
    dynamics, collision geometry and a Gazebo block - none of which survive.
    """
    ctx = pc.init(EXAMPLES)
    robot = ctx._get_assembly(URDF_EXAMPLE)
    asyncio.run(robot.do_instantiate())

    info = robot.info()
    assert info["Robot"] == "partcad_urdf_example"
    assert info["RootLink"] == "base_link"

    dropped = info["UrdfDropped"]
    for key in ("inertial", "material", "joint_kinematics", "joint_limits", "joint_dynamics", "collision"):
        assert dropped[DROPPED_LABELS[key]] > 0

    assert info["UrdfMovableJoints"] == ["shoulder_pan (revolute)"]


def _export_urdf(ctx, assembly, directory, **kwargs):
    path = os.path.join(directory, "logo.urdf")
    # A coarse mesh: this is about the structure of the export, and the default
    # tolerance turns the logo's bolt into tens of megabytes of triangles.
    asyncio.run(assembly.render_async(ctx, "urdf", filepath=path, tolerance=1.0, angularTolerance=0.5, **kwargs))
    return path


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
    roots = links - set(children)
    assert len(roots) == 1

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


def mesh_scale(robot, filename):
    for mesh in robot.findall("link/visual/geometry/mesh"):
        if mesh.get("filename") == filename:
            return [float(v) for v in mesh.get("scale").split()]
    raise AssertionError("no mesh named %s" % filename)


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
