#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a link of an exported URDF weighs, and what 'pc info' says it weighs.

A package exported end to end, through the sandbox, because what is under test
is the whole of the chain: a material declared in one place, its density in
kg/m^3, the part's solid measured as it was built, the mass worked out once in
the core, handed to the exporter in the part's properties, and written into
the URDF - and the same number reported by 'pc info'. The arithmetic itself is
'test_mass_properties.py' and the order it is resolved in 'test_physics.py';
this is about the pieces being connected.

The package is five blocks of one geometry, made of different things, and a
link of two of them: every rung of the order, in one export.
"""

import asyncio
import os
import xml.etree.ElementTree as ET

import pytest

import partcad as pc
from partcad import physics

# 'partcad' before OCP, and 'isort: split' so it stays there: importing the
# package pins the standard library's expat (see the comment on 'import
# pyexpat' in partcad/__init__.py), and whatever loads first wins for the
# process.
# isort: split

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepTools import BRepTools

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
    density: 8000 # kg/m^3
  foam:
    density: 100
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
    # Nothing said, or nothing that weighs: the export's fallback, aluminium.
    assert mass("plain") == pytest.approx(physics.DEFAULT_EXPORT_DENSITY * VOLUME_M3)
    assert mass("vague") == pytest.approx(physics.DEFAULT_EXPORT_DENSITY * VOLUME_M3)
    # Stated mass, derived inertia: the box's, at the weight it says.
    weighed = [float(inertial["weighed"].find("inertia").get(axis)) for axis in ("ixx", "iyy", "izz")]
    assert weighed == pytest.approx(_box_inertia(0.5))

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


def _info(ctx, name, kind):
    shape = ctx._get_assembly(name) if kind == "assembly" else ctx.get_part(name)
    return shape.shape_info(ctx)["MassProperties"]


def test_pc_info_reports_what_the_export_writes(weighing):
    """The same number in 'pc info' as in the URDF, and where it came from."""
    ctx = pc.Context(str(weighing))

    steel = _info(ctx, "//weighing:steel_block", "part")
    assert steel["mass"]["value"] == pytest.approx(STEEL * VOLUME_M3)
    assert steel["mass"]["unit"] == "kg"
    assert steel["mass"]["source"] == "derived: 6000 mm^3 at 8000 kg/m^3"
    assert steel["density"]["source"] == "the material //weighing:steel"
    assert steel["volume"] == {"value": 6000.0, "unit": "mm^3", "source": "measured"}
    assert steel["centerOfMass"]["value"] == pytest.approx([5.0, 10.0, 15.0])

    weighed = _info(ctx, "//weighing:weighed_block", "part")
    assert weighed["mass"] == {"value": 0.5, "unit": "kg", "source": "stated"}
    assert weighed["inertia"]["source"] == "derived: the solid, scaled to the stated mass"

    # No density anywhere: 'pc info' says so rather than weighing it at the
    # export's fallback, and keeps what it does know.
    plain = _info(ctx, "//weighing:plain_block", "part")
    assert plain["mass"]["value"] is None
    assert "names no material" in plain["mass"]["source"]
    assert "density" not in plain
    assert plain["centerOfMass"]["value"] == pytest.approx([5.0, 10.0, 15.0])


def test_pc_info_adds_an_assembly_up_and_names_what_it_could_not_weigh(weighing):
    ctx = pc.Context(str(weighing))

    bench = _info(ctx, "//weighing:bench", "assembly")

    # Steel, foam, the stated half kilogram, and the wrist's steel and foam;
    # the plain and the vague blocks have no mass, and are named.
    expected = (STEEL + FOAM + STEEL + FOAM) * VOLUME_M3 + 0.5
    assert bench["mass"]["value"] == pytest.approx(expected)
    assert "5 parts" in bench["mass"]["source"]
    assert "//weighing:plain_block" in bench["mass"]["source"]
    assert "//weighing:vague_block" in bench["mass"]["source"]
    assert bench["volume"]["value"] == pytest.approx(7 * 6000.0)
    assert bench["centerOfMass"]["source"] == "combined from 5 parts"
