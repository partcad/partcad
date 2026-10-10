#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a link of an exported URDF weighs, and what it weighs that at.

A part that states no mass is weighed: OCCT integrates its solid, and a density
turns the volume into a mass and the second moment into an inertia. Which
density is the subject here. It is the part's own where it has one - the
'density' of the material it names, which the core resolves and converts to
kg/m^3 before the exporter ever sees it - then the 'density' parameter of the
export, then the exporter's default; and a 'mass' the part states beats all of
them.

The first half runs the exporter's arithmetic in this process, against boxes
whose mass, centre and inertia are known in closed form. The second exports a
package through the sandbox, end to end, because what is under test there is
that a material declared in one place arrives as the right number in another.
"""

import asyncio
import os
import sys
import xml.etree.ElementTree as ET

import pytest

import partcad as pc

# 'partcad' before OCP, and 'isort: split' so it stays there: importing the
# package pins the standard library's expat (see the comment on 'import
# pyexpat' in partcad/__init__.py), and whatever loads first wins for the
# process.
# isort: split

from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepTools import BRepTools
from OCP.gp import gp_Pln
from OCP.GProp import GProp_GProps

# The exporter is a sandbox script: it finds 'ocp_serialize' and 'urdf_common'
# in PartCAD's 'wrappers/' directory, which a sandbox has on its path. Its
# URDF-writing half needs 'urdf_parser_py', which this process does not have and
# which the functions under test here do not import.
sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
sys.path.append(os.path.join(os.path.dirname(pc.__file__), "builtin", "export"))
import export_urdf  # noqa: E402

# 10 x 20 x 30 mm, so 6000 mm^3, 6e-6 m^3.
SIZE = (10.0, 20.0, 30.0)
VOLUME_M3 = 6e-6

STEEL = 8000.0  # kg/m^3
FOAM = 100.0


def _box():
    return BRepPrimAPI_MakeBox(*SIZE).Shape()


def _box_inertia(mass, size_mm=SIZE):
    """The principal moments of a box about its own centre, in kg.m^2."""
    a, b, c = (v / 1000.0 for v in size_mm)
    return (mass * (b * b + c * c) / 12.0, mass * (a * a + c * c) / 12.0, mass * (a * a + b * b) / 12.0)


#
# Which density
#


def test_the_shape_is_asked_first_then_its_link_then_the_export():
    """Most specific first: a shape of a link may be made of something else."""
    warnings = []
    assert export_urdf.density_of(({"density": STEEL}, {"density": FOAM}), 2700.0, warnings, "l") == STEEL
    assert export_urdf.density_of(({"mass": 1.0}, {"density": FOAM}), 2700.0, warnings, "l") == FOAM
    assert export_urdf.density_of(({}, {}), 1234.0, warnings, "l") == 1234.0
    assert export_urdf.density_of((), 1234.0, warnings, "l") == 1234.0
    assert warnings == []


def test_a_density_that_weighs_nothing_is_reported_and_passed_over():
    """Not written out as a link that weighs nothing, nor as one that weighs less."""
    for nothing in (0.0, -5.0, "heavy", float("nan")):
        warnings = []
        assert export_urdf.density_of(({"density": nothing}, {"density": FOAM}), 2700.0, warnings, "arm") == FOAM
        assert len(warnings) == 1
        assert "density" in warnings[0] and "'arm'" in warnings[0]


def test_the_default_is_aluminium_s_density():
    """What a part that says nothing about what it is made of has always weighed."""
    assert export_urdf.DEFAULT_DENSITY == 2700.0


#
# What it weighs
#


def test_a_solid_weighs_its_volume_at_its_density():
    mass, centre, inertia = export_urdf.mass_properties([(_box(), None, STEEL)])

    assert mass == pytest.approx(STEEL * VOLUME_M3)
    assert centre == pytest.approx((5.0, 10.0, 15.0))
    # About the centre of mass, which is the frame URDF states it in.
    assert [inertia[i][i] for i in range(3)] == pytest.approx(_box_inertia(mass))
    for row in range(3):
        for col in range(3):
            if row != col:
                assert inertia[row][col] == pytest.approx(0.0, abs=1e-15)


def test_mass_and_inertia_come_from_the_same_density():
    """Twice the density is twice the mass and twice the inertia, and the same centre."""
    light = export_urdf.mass_properties([(_box(), None, FOAM)])
    heavy = export_urdf.mass_properties([(_box(), None, 2 * FOAM)])

    assert heavy[0] == pytest.approx(2 * light[0])
    assert heavy[1] == pytest.approx(light[1])
    for row in range(3):
        assert heavy[2][row][row] == pytest.approx(2 * light[2][row][row])


def test_a_link_of_two_materials_balances_where_the_heavier_one_pulls_it():
    """Each shape at its own density, and the link as the sum of them.

    A steel box and a foam one 100 mm along X, as one link: the centre of mass
    sits a millimetre and a quarter from the steel box's own, not halfway
    between the two, and the inertia is each box's own about its centre moved
    to the link's by the parallel-axis theorem.
    """
    apart = [[100.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]
    mass, centre, inertia = export_urdf.mass_properties([(_box(), None, STEEL), (_box(), apart, FOAM)])

    steel, foam = STEEL * VOLUME_M3, FOAM * VOLUME_M3
    assert mass == pytest.approx(steel + foam)
    x = (steel * 5.0 + foam * 105.0) / (steel + foam)
    assert centre == pytest.approx((x, 10.0, 15.0))

    # Only the X offsets differ, so only Iyy and Izz move.
    offsets = ((5.0 - x) / 1000.0, (105.0 - x) / 1000.0)
    own = (_box_inertia(steel), _box_inertia(foam))
    expected = (
        own[0][0] + own[1][0],
        own[0][1] + own[1][1] + steel * offsets[0] ** 2 + foam * offsets[1] ** 2,
        own[0][2] + own[1][2] + steel * offsets[0] ** 2 + foam * offsets[1] ** 2,
    )
    assert [inertia[i][i] for i in range(3)] == pytest.approx(expected)


def test_a_link_of_one_material_weighs_what_one_solid_of_it_would():
    """No change for a link whose shapes agree: the sum is the compound."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    apart = [[100.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]
    mass, centre, inertia = export_urdf.mass_properties([(_box(), None, 2700.0), (_box(), apart, 2700.0)])

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, _box())
    builder.Add(compound, _box().Located(export_urdf._toploc(apart)))
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(compound, props)

    assert mass == pytest.approx(props.Mass() * 1e-9 * 2700.0)
    com = props.CentreOfMass()
    assert centre == pytest.approx((com.X(), com.Y(), com.Z()))
    matrix = props.MatrixOfInertia()
    for row in range(3):
        for col in range(3):
            assert inertia[row][col] == pytest.approx(matrix.Value(row + 1, col + 1) * 1e-15 * 2700.0, abs=1e-15)


def test_a_shape_with_no_volume_weighs_nothing_and_adds_nothing():
    """A face has nothing to weigh; beside a solid it changes nothing about it."""
    face = BRepBuilderAPI_MakeFace(gp_Pln(), 0.0, 10.0, 0.0, 10.0).Face()

    assert export_urdf.mass_properties([(face, None, STEEL)]) is None
    alone = export_urdf.mass_properties([(_box(), None, STEEL)])
    beside = export_urdf.mass_properties([(_box(), None, STEEL), (face, None, FOAM)])
    assert beside[0] == pytest.approx(alone[0])
    assert beside[1] == pytest.approx(alone[1])


#
# End to end: a material declared in a package, weighed in the URDF
#


ASSY = """\
links:
  - part: steel_block
    name: steel
  - part: foam_block
    name: foam
    location: [[100, 0, 0], [0, 0, 1], 0]
  - part: weighed_block
    name: weighed
    location: [[200, 0, 0], [0, 0, 1], 0]
  - part: plain_block
    name: plain
    location: [[300, 0, 0], [0, 0, 1], 0]
  - part: vague_block
    name: vague
    location: [[400, 0, 0], [0, 0, 1], 0]
  # One link of two shapes - the slash is what says so - in two materials.
  - name: wrist
    location: [[500, 0, 0], [0, 0, 1], 0]
    links:
      - part: steel_block
        name: wrist/1
      - part: foam_block
        name: wrist/2
        location: [[100, 0, 0], [0, 0, 1], 0]
"""

PACKAGE = """\
name: //weighing
materials:
  steel:
    density: 0.008 # g/mm^3, so 8000 kg/m^3
  foam:
    density: 0.0001
  vague:
    desc: A material that states no density
parts:
  steel_block:
    type: brep
    path: block.brep
    properties:
      material: ":steel"
  foam_block:
    type: brep
    path: block.brep
    properties:
      material: ":foam"
  weighed_block:
    type: brep
    path: block.brep
    properties:
      material: ":steel"
      physics:
        mass: 0.5
  plain_block:
    type: brep
    path: block.brep
  vague_block:
    type: brep
    path: block.brep
    properties:
      material: ":vague"
assemblies:
  bench:
    type: assy
"""


@pytest.fixture
def weighing(tmp_path):
    """A package of five blocks of one geometry, made of different things."""
    root = tmp_path / "weighing"
    root.mkdir()
    BRepTools.Write_s(_box(), str(root / "block.brep"))
    (root / "partcad.yaml").write_text(PACKAGE, encoding="utf-8")
    (root / "bench.assy").write_text(ASSY, encoding="utf-8")
    return root


def _masses(ctx, directory, **kwargs):
    """Export the bench and read back each link's '<inertial>'."""
    bench = ctx._get_assembly("//weighing:bench")
    path = os.path.join(directory, "bench.urdf")
    asyncio.run(bench.render_async(ctx, "urdf", filepath=path, tolerance=1.0, angularTolerance=0.5, **kwargs))
    robot = ET.parse(path).getroot()
    return {
        link.get("name"): link.find("inertial") for link in robot.findall("link") if link.find("inertial") is not None
    }


def test_each_part_is_weighed_at_what_it_is_made_of(weighing, tmp_path, caplog):
    """The whole order, one link per rung of it, in one export.

    Five blocks of one geometry: two made of materials that state a density,
    one that states its own mass beside a material, one that says nothing about
    what it is made of, and one made of a material that states no density. And
    a link of two of them, each weighed at its own.
    """
    ctx = pc.Context(str(weighing))
    with caplog.at_level("INFO"):
        inertial = _masses(ctx, str(tmp_path))

    def mass(link):
        return float(inertial[link].find("mass").get("value"))

    assert mass("steel") == pytest.approx(STEEL * VOLUME_M3)
    assert mass("foam") == pytest.approx(FOAM * VOLUME_M3)
    # Stated, so not computed - the material beside it decides nothing.
    assert mass("weighed") == pytest.approx(0.5)
    # Nothing said, or nothing that weighs: what every part weighed before
    # materials existed.
    assert mass("plain") == pytest.approx(export_urdf.DEFAULT_DENSITY * VOLUME_M3)
    assert mass("vague") == pytest.approx(export_urdf.DEFAULT_DENSITY * VOLUME_M3)

    # The centre of mass and the inertia are the steel's too, not aluminium's.
    steel = inertial["steel"]
    assert [float(v) for v in steel.find("origin").get("xyz").split()] == pytest.approx([0.005, 0.01, 0.015])
    moments = [float(steel.find("inertia").get(axis)) for axis in ("ixx", "iyy", "izz")]
    assert moments == pytest.approx(_box_inertia(STEEL * VOLUME_M3))

    # The two shapes of the wrist are looked up by their own names, so the
    # steel one and the foam one each weigh what they are made of, and the link
    # balances near the steel.
    assert mass("wrist") == pytest.approx((STEEL + FOAM) * VOLUME_M3)
    x = (STEEL * 5.0 + FOAM * 105.0) / (STEEL + FOAM) / 1000.0
    assert [float(v) for v in inertial["wrist"].find("origin").get("xyz").split()] == pytest.approx([x, 0.01, 0.015])

    # 'density' has no URDF element, and it is not reported as lost: it is in
    # the file as the mass it comes to.
    assert not any("cannot state" in record.message and "density" in record.message for record in caplog.records)


def test_the_export_s_density_is_for_a_part_that_says_nothing(weighing, tmp_path):
    """A fallback, not an override: a part that says what it is made of is weighed as that."""
    ctx = pc.Context(str(weighing))
    inertial = _masses(ctx, str(tmp_path), density=1000.0)

    def mass(link):
        return float(inertial[link].find("mass").get("value"))

    assert mass("plain") == pytest.approx(1000.0 * VOLUME_M3)
    assert mass("vague") == pytest.approx(1000.0 * VOLUME_M3)
    assert mass("steel") == pytest.approx(STEEL * VOLUME_M3)
    assert mass("foam") == pytest.approx(FOAM * VOLUME_M3)
    assert mass("weighed") == pytest.approx(0.5)
