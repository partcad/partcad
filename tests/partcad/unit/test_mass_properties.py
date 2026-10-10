#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The one copy of mass-property arithmetic: 'wrappers/mass_properties.py'.

The core works out what a part weighs with it, and every exporter that writes a
body's inertia - URDF here, MJCF and SDFormat in the simulation plugins - adds
the shapes of a body up with it. So it is tested against something it cannot
share a mistake with: OCCT integrating the same solids itself, placed and
compounded the way the helper places and combines their numbers. Boxes, whose
answers are known in closed form, pin the units.
"""

import math
import os
import sys

import pytest

import partcad as pc

# 'partcad' before OCP, and 'isort: split' so it stays there: importing the
# package pins the standard library's expat (see the comment on 'import
# pyexpat' in partcad/__init__.py), and whatever loads first wins for the
# process.
# isort: split

from OCP.BRep import BRep_Builder
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.TopoDS import TopoDS_Compound

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import mass_properties  # noqa: E402
import ocp_serialize  # noqa: E402
import shape_measure  # noqa: E402

# 10 x 20 x 30 mm, so 6000 mm^3.
SIZE = (10.0, 20.0, 30.0)
STEEL = 8000.0  # kg/m^3
FOAM = 100.0


def _box():
    return BRepPrimAPI_MakeBox(*SIZE).Shape()


def _box_moments(mass, size=SIZE):
    """A box's principal moments about its own centre, in kg*m^2."""
    a, b, c = (v / 1000.0 for v in size)
    return (mass * (b * b + c * c) / 12.0, mass * (a * a + c * c) / 12.0, mass * (a * a + b * b) / 12.0)


def _solid_physics(shape, density):
    """What the core works out for a solid: its measurements at a density."""
    measured = shape_measure.measurements(shape)
    return mass_properties.of_solid(measured["volume"], measured["centroid"], measured["unitInertia"], density)


def _occt(shape, density):
    """What OCCT integrates for 'shape' as it stands - already placed, or compounded.

    The same call as '_solid_physics()', and that is the point of it: the shape
    handed in has been moved or put together by OCCT, so the numbers are OCCT's
    answer for the result rather than the helper's arithmetic on the parts.
    """
    return _solid_physics(shape, density)


def _tensor(physics):
    return mass_properties.tensor_of(physics)


def _assert_same(a, b, rel=1e-9):
    assert a["mass"] == pytest.approx(b["mass"], rel=rel)
    assert a["centerOfMass"] == pytest.approx(b["centerOfMass"], rel=rel, abs=1e-9)
    tensor_a, tensor_b = _tensor(a), _tensor(b)
    scale = max(abs(v) for row in tensor_b for v in row)
    for row in range(3):
        for col in range(3):
            assert tensor_a[row][col] == pytest.approx(tensor_b[row][col], abs=scale * 1e-9)


#
# A volume and a density
#


def test_a_mass_is_a_volume_in_cubic_millimetres_at_a_density_in_kg_per_cubic_metre():
    """Water: a litre of it weighs a kilogram."""
    assert mass_properties.mass_of(1.0e6, 1000.0) == pytest.approx(1.0)
    assert mass_properties.mass_of(6000.0, STEEL) == pytest.approx(0.048)


def test_a_solid_s_mass_properties_are_its_measurements_at_a_density():
    physics = _solid_physics(_box(), STEEL)

    assert physics["mass"] == pytest.approx(0.048)
    assert physics["centerOfMass"] == pytest.approx([5.0, 10.0, 15.0])
    moments = (physics["inertia"]["ixx"], physics["inertia"]["iyy"], physics["inertia"]["izz"])
    assert moments == pytest.approx(_box_moments(0.048))
    assert "inertiaOrientation" not in physics


def test_the_centroid_and_the_unit_inertia_are_measured_with_the_volume():
    """The geometry's half, taken as the shape is encoded and cached with it."""
    measured = shape_measure.measurements(_box())

    assert measured["centroid"] == pytest.approx([5.0, 10.0, 15.0])
    # Ixx at unit density, mm^5: V (b^2 + c^2) / 12.
    assert measured["unitInertia"][0][0] == pytest.approx(6000.0 * (400.0 + 900.0) / 12.0)


def test_a_shape_with_no_solid_has_nothing_to_weigh():
    """A sketch or a shell: no centroid, no inertia, and so no mass to derive."""
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer

    shell = TopExp_Explorer(_box(), TopAbs_SHELL).Current()
    measured = shape_measure.measurements(shell)

    assert "centroid" not in measured
    assert "unitInertia" not in measured


#
# Placing and adding up
#


def test_placing_moves_the_centre_and_turns_the_tensor_as_occt_does():
    """A box turned 30 degrees about a skew axis and moved: the helper against OCCT."""
    location = [[100.0, -20.0, 5.0], [1.0, 2.0, 3.0], 30.0]
    placed = mass_properties.placed(_solid_physics(_box(), STEEL), location)

    moved = _box().Located(ocp_serialize.toploc_from_packed(location))
    _assert_same(placed, _occt(moved, STEEL))


def test_two_materials_in_one_body_add_up_as_occt_weighs_them():
    """Steel and foam, as one rigid body: the combined numbers against OCCT's Add()."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    location = [[100.0, 0.0, 0.0], [0.0, 0.0, 1.0], 90.0]
    body = mass_properties.of_body(
        [(_solid_physics(_box(), STEEL), None), (_solid_physics(_box(), FOAM), location)],
    )

    total = GProp_GProps()
    for shape, density in ((_box(), STEEL), (_box().Located(ocp_serialize.toploc_from_packed(location)), FOAM)):
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        total.Add(props, density)
    matrix = total.MatrixOfInertia()
    centre = total.CentreOfMass()
    expected = {
        "mass": total.Mass() * 1e-9,
        "centerOfMass": [centre.X(), centre.Y(), centre.Z()],
        "inertia": mass_properties.inertia_of([[matrix.Value(r, c) * 1e-15 for c in (1, 2, 3)] for r in (1, 2, 3)]),
    }
    _assert_same(body, expected)
    # Near the steel: the foam is an eightieth of the weight a hundred millimetres away.
    assert body["centerOfMass"][0] < 10.0


def test_a_body_of_one_material_weighs_what_one_compound_of_it_would():
    """No change for a body whose shapes agree: the sum is the compound."""
    location = [[0.0, 50.0, 0.0], [1.0, 0.0, 0.0], 45.0]
    body = mass_properties.of_body([(_solid_physics(_box(), 2700.0), None), (_solid_physics(_box(), 2700.0), location)])

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, _box())
    builder.Add(compound, _box().Located(ocp_serialize.toploc_from_packed(location)))
    _assert_same(body, _occt(compound, 2700.0))


def test_a_body_that_is_one_unplaced_part_is_that_part_as_stated():
    """What was read from a file goes back into one unchanged, orientation and all."""
    stated = {"mass": 0.78, "inertia": {"izz": 1.87e-3}, "inertiaOrientation": [0.0, 0.0, 90.0], "friction": 0.9}

    assert mass_properties.of_body([(stated, None)]) is stated


def test_a_body_that_states_its_own_mass_beats_the_sum_of_its_parts():
    own = {"mass": 5.0, "centerOfMass": [1.0, 2.0, 3.0]}
    parts = [(_solid_physics(_box(), STEEL), None), (_solid_physics(_box(), FOAM), [[50.0, 0, 0], [0, 0, 1], 0])]

    assert mass_properties.of_body(parts, own=own) is own


def test_a_part_with_no_mass_adds_nothing_and_a_body_of_nothing_weighs_nothing():
    """An open shell or an unweighed mesh, as it adds nothing to an integral."""
    steel = _solid_physics(_box(), STEEL)
    body = mass_properties.of_body([(steel, None), ({"friction": 0.2}, [[100.0, 0, 0], [0, 0, 1], 0])])

    _assert_same(body, mass_properties.placed(steel, None))
    assert mass_properties.of_body([({}, None)]) is None
    assert mass_properties.combined([{"mass": 0.0}, {"mass": -1.0}, {}]) is None


def test_point_masses_turn_about_their_common_centre():
    """Two kilograms a metre apart: 0.5 kg*m^2 about the middle, none about the line."""
    body = mass_properties.combined(
        [{"mass": 1.0, "centerOfMass": [-500.0, 0.0, 0.0]}, {"mass": 1.0, "centerOfMass": [500.0, 0.0, 0.0]}]
    )

    assert body["mass"] == pytest.approx(2.0)
    assert body["centerOfMass"] == pytest.approx([0.0, 0.0, 0.0])
    assert body["inertia"]["ixx"] == pytest.approx(0.0)
    assert body["inertia"]["iyy"] == pytest.approx(0.5)
    assert body["inertia"]["izz"] == pytest.approx(0.5)
    # One point has nothing to turn about, and no tensor is invented for it.
    assert "inertia" not in mass_properties.combined([{"mass": 1.0}])


def test_a_stated_orientation_is_folded_into_the_tensor():
    """An inertia stated in a frame turned 90 degrees about Z swaps Ixx and Iyy."""
    physics = {"mass": 1.0, "inertia": {"ixx": 1.0, "iyy": 2.0, "izz": 3.0}, "inertiaOrientation": [0.0, 0.0, 90.0]}

    tensor = mass_properties.tensor_of(physics)
    assert [tensor[0][0], tensor[1][1], tensor[2][2]] == pytest.approx([2.0, 1.0, 3.0])


def test_a_new_mass_scales_the_inertia_and_moves_nothing():
    """What a part that states its mass and not its inertia is given."""
    physics = _solid_physics(_box(), STEEL)

    heavier = mass_properties.with_mass(physics, 2 * physics["mass"])
    assert heavier["centerOfMass"] == physics["centerOfMass"]
    assert heavier["inertia"]["ixx"] == pytest.approx(2 * physics["inertia"]["ixx"])
    assert math.isclose(heavier["mass"], 0.096)
