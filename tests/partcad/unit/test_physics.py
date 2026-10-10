#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a shape's physics resolves to, and how 'partcad.physics' knows.

One order for every value, the same for 'pc info', for an export and for the
IDE: what the part states, else what its material lends, else what its solid
comes to at that density. These are about that order and about the account of
it - the 'source' every value is reported with - against measurements written
out by hand, so nothing here needs a sandbox. The material fixture package is
the one 'test_material.py' reads: PLA at 1320 kg/m^3 with a mu of 0.35, ABS at
1070 with none, and a material that states no density at all.

What OCCT measures, and how the helper adds bodies up, is
'test_mass_properties.py'; a package exported end to end is
'test_export_urdf_mass.py'.
"""

import asyncio

import pytest

import partcad as pc
from partcad import physics

DATA = "tests/partcad/unit/data/material"

# What a 10 x 20 x 30 mm box measures as it is built.
BOX = {
    "volume": 6000.0,
    "centroid": [5.0, 10.0, 15.0],
    "unitInertia": [[650000.0, 0.0, 0.0], [0.0, 500000.0, 0.0], [0.0, 0.0, 250000.0]],
    "solids": 1,
}
# 6000 mm^3 is 6e-6 m^3.
VOLUME_M3 = 6e-6


@pytest.fixture
def ctx():
    return pc.Context(DATA)


@pytest.fixture
def root(ctx):
    return ctx.get_project(ctx.get_current_project_path())


#
# The order
#


def test_a_material_s_density_weighs_the_solid(root):
    resolved, sources = physics.resolve(None, root.get_material("pla"), "//:pla", BOX)

    assert resolved["density"] == pytest.approx(1320.0)
    assert resolved["mass"] == pytest.approx(1320.0 * VOLUME_M3)
    assert resolved["centerOfMass"] == pytest.approx([5.0, 10.0, 15.0])
    assert resolved["inertia"]["izz"] == pytest.approx(1320.0 * 250000.0 * 1e-15)
    assert resolved["friction"] == pytest.approx(0.35)
    assert sources["density"] == "the material //:pla"
    assert sources["friction"] == "the material //:pla"
    assert sources["mass"] == "derived: 6000 mm^3 at 1320 kg/m^3"
    assert sources["centerOfMass"] == "derived: the centroid of the solid"
    assert sources["inertia"] == "derived: the solid at 1320 kg/m^3"


def test_what_the_part_states_beats_what_its_material_lends(root):
    stated = {"density": 1500.0, "friction": 0.9}
    resolved, sources = physics.resolve(stated, root.get_material("pla"), "//:pla", BOX)

    assert resolved["density"] == 1500.0
    assert resolved["friction"] == 0.9
    assert resolved["mass"] == pytest.approx(1500.0 * VOLUME_M3)
    assert sources["density"] == sources["friction"] == "stated"


def test_a_stated_mass_beats_the_density_and_scales_the_solid_s_inertia(root):
    """A part weighed on the bench still turns the way its shape says it does."""
    resolved, sources = physics.resolve({"mass": 0.5}, root.get_material("pla"), "//:pla", BOX)

    assert resolved["mass"] == 0.5
    assert sources["mass"] == "stated"
    # The inertia of the box at whatever density makes it weigh 0.5 kg.
    assert resolved["inertia"]["izz"] == pytest.approx(0.5 / VOLUME_M3 * 250000.0 * 1e-15)
    assert sources["inertia"] == "derived: the solid, scaled to the stated mass"


def test_a_stated_inertia_and_centre_are_kept_as_stated(root):
    stated = {"centerOfMass": [0.0, 0.0, 0.0], "inertia": {"ixx": 1.0}, "inertiaOrientation": [0.0, 0.0, 90.0]}
    resolved, sources = physics.resolve(stated, root.get_material("pla"), "//:pla", BOX)

    assert resolved["centerOfMass"] == [0.0, 0.0, 0.0]
    assert resolved["inertia"] == {"ixx": 1.0}
    assert resolved["inertiaOrientation"] == [0.0, 0.0, 90.0]
    assert sources["inertia"] == sources["centerOfMass"] == "stated"
    # The mass is still the material's: stating one value is not stating them all.
    assert sources["mass"].startswith("derived")


def test_no_density_is_no_mass_rather_than_an_invented_one(root):
    """'pc info' says it does not know. The centre of a homogeneous solid is still known."""
    for material in (None, root.get_material("mystery")):
        resolved, sources = physics.resolve(None, material, "//:mystery", BOX)
        assert "mass" not in resolved
        assert "inertia" not in resolved
        assert "density" not in resolved
        assert resolved["centerOfMass"] == pytest.approx([5.0, 10.0, 15.0])


def test_an_export_weighs_a_part_that_says_nothing_at_its_fallback(root):
    resolved, sources = physics.resolve(None, None, None, BOX, (2700.0, "the export default"))

    assert resolved["mass"] == pytest.approx(2700.0 * VOLUME_M3)
    assert sources["density"] == "the export default"
    # And a part that is made of something is weighed as that, fallback or not.
    resolved, _sources = physics.resolve(None, root.get_material("abs"), "//:abs", BOX, (2700.0, "x"))
    assert resolved["density"] == pytest.approx(1070.0)


def test_the_export_s_density_parameter_is_the_fallback_and_aluminium_is_the_default():
    value, source = physics.export_fallback({})
    assert value == physics.DEFAULT_EXPORT_DENSITY == 2700.0
    assert "default" in source
    assert physics.export_fallback({"density": 1000.0}) == (1000.0, "the export's 'density' parameter")
    # One that weighs nothing is no fallback.
    assert physics.export_fallback({"density": 0})[0] == 2700.0


def test_a_stated_density_that_weighs_nothing_is_passed_over(root):
    resolved, sources = physics.resolve({"density": -5.0}, root.get_material("pla"), "//:pla", BOX)

    assert resolved["density"] == pytest.approx(1320.0)
    assert sources["density"] == "the material //:pla"


def test_a_shape_that_encloses_nothing_gets_only_what_is_stated_and_lent(root):
    shell = {"volume": None, "solids": 0}
    resolved, _sources = physics.resolve({"mass": 1.0}, root.get_material("pla"), "//:pla", shell)

    assert resolved == {"mass": 1.0, "friction": 0.35, "density": pytest.approx(1320.0)}


#
# What an export is handed
#


def _leaf(name, material=None, physics_=None, volume=True, location=None):
    properties = {}
    if material:
        properties["material"] = material
    if physics_:
        properties["physics"] = physics_
    node = {"name": name, "label": name.rsplit(":", 1)[-1], "brep": "AAAA"}
    if properties:
        node["properties"] = properties
    if volume:
        node["metadata"] = {"measurements": dict(BOX)}
    if location:
        node["location"] = location
    return node


def test_an_export_is_handed_every_shape_resolved_by_its_own_name(ctx, root):
    pla, plain = "%s:pla_part" % root.name, "%s:plain" % root.name
    request = {
        "wrapped": {"name": "%s:rig" % root.name, "assembly": [_leaf(pla, ":pla"), _leaf(plain)]},
        "properties": True,
    }

    facts = physics.physics_by_shape(ctx, request, physics.export_fallback(request))

    assert facts[pla]["mass"] == pytest.approx(1320.0 * VOLUME_M3)
    assert facts[pla]["friction"] == pytest.approx(0.35)
    # No properties at all, and still weighed: at the export's fallback.
    assert facts[plain]["mass"] == pytest.approx(2700.0 * VOLUME_M3)
    assert facts[plain]["density"] == 2700.0
    # The assembly states nothing and is made of nothing: what it weighs is
    # the exporter's to add up, for the bodies it makes of it.
    assert "%s:rig" % root.name not in facts


#
# What an assembly weighs
#


def _tree(*children, physics_=None):
    node = {"name": "//p:rig", "label": "rig", "assembly": list(children)}
    if physics_:
        node["properties"] = {"physics": physics_}
    return node


def test_an_assembly_weighs_what_its_parts_add_up_to(ctx, root):
    pla = "%s:a" % root.name
    tree = _tree(_leaf(pla, ":pla"), _leaf(pla, ":pla", location=[[100.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]))

    resolved, sources, volume, parts, unweighed = asyncio.run(physics._tree_async(tree, physics._Materials(ctx)))

    mass = 1320.0 * VOLUME_M3
    assert resolved["mass"] == pytest.approx(2 * mass)
    assert resolved["centerOfMass"] == pytest.approx([55.0, 10.0, 15.0])
    # Each box's own Iyy, plus its mass at 50 mm from the combined centre.
    own_iyy = 1320.0 * 500000.0 * 1e-15
    assert resolved["inertia"]["iyy"] == pytest.approx(2 * (own_iyy + mass * 0.05**2))
    assert volume == pytest.approx(12000.0)
    assert (parts, unweighed) == (2, [])
    assert sources["mass"] == "the sum of 2 parts"


def test_a_part_with_no_mass_is_left_out_of_a_total_and_named(ctx, root):
    pla, vague = "%s:a" % root.name, "%s:vague" % root.name
    tree = _tree(_leaf(pla, ":pla"), _leaf(vague, ":mystery"))

    resolved, _sources, _volume, parts, unweighed = asyncio.run(physics._tree_async(tree, physics._Materials(ctx)))

    assert resolved["mass"] == pytest.approx(1320.0 * VOLUME_M3)
    assert parts == 2
    assert unweighed == [vague]


def test_an_assembly_that_states_its_mass_is_taken_at_its_word(ctx, root):
    pla = "%s:a" % root.name
    tree = _tree(
        _leaf(pla, ":pla"),
        _leaf(pla, ":pla", location=[[100.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]),
        physics_={"mass": 1.0},
    )

    resolved, sources, _volume, _parts, unweighed = asyncio.run(physics._tree_async(tree, physics._Materials(ctx)))

    assert resolved["mass"] == 1.0
    assert sources["mass"] == "stated"
    # Spread the way its parts say, at the weight it says.
    assert resolved["centerOfMass"] == pytest.approx([55.0, 10.0, 15.0])
    assert unweighed == []


def test_what_pc_info_reports_carries_a_unit_and_a_source_for_every_value(root):
    resolved, sources = physics.resolve(None, root.get_material("pla"), "//:pla", BOX)
    report = physics._report(resolved, sources, BOX["volume"], "measured")

    assert set(report) == {"volume", "density", "mass", "centerOfMass", "inertia"}
    assert report["mass"] == {
        "value": pytest.approx(0.00792),
        "unit": "kg",
        "source": "derived: 6000 mm^3 at 1320 kg/m^3",
    }
    assert report["volume"]["source"] == "measured"
    assert report["inertia"]["unit"] == "kg*m^2, about centerOfMass"


def test_noise_where_the_answer_is_nought_is_shown_as_nought():
    """A cube's centre at 1e-17 mm is the arithmetic's, not the cube's."""
    report = physics._report(
        {"centerOfMass": [1.2e-17, 0.0, 10.0], "inertia": {"ixx": 7.2e-6, "ixy": -9.6e-25}},
        {},
        None,
        "measured",
    )
    assert report["centerOfMass"]["value"] == [0.0, 0.0, 10.0]
    assert report["inertia"]["value"]["ixy"] == 0.0
