#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The boolean wrapper's operations, run in this process on shapes made here.

'test_part_boolean.py' builds boolean parts end to end, with the wrapper in a
sandbox of its own; this calls the wrapper's functions directly, on operands
encoded the way a part's envelope is ('ocp_serialize.encode_shape' with a CMF
section), so that what each operation keeps and what it is made of can be
asked case by case - and so that what it does is measured.
"""

import os
import sys

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

import partcad as pc

WRAPPERS = os.path.join(os.path.dirname(pc.__file__), "wrappers")
sys.path.append(WRAPPERS)
import cmf_section  # noqa: E402
import ocp_serialize  # noqa: E402
import wrapper_boolean  # noqa: E402

STEEL = cmf_section.CmfSet(material=":steel")
BRASS = cmf_section.CmfSet(material=":brass")
ALUMINIUM = cmf_section.CmfSet(material=":aluminium")


def _box(x, y, z, dx, dy, dz):
    return BRepPrimAPI_MakeBox(gp_Pnt(x, y, z), dx, dy, dz).Shape()


def _compound(*shapes):
    return ocp_serialize.compound_of(shapes)


def _envelope(shape, *materials):
    """'shape' as a part's envelope, its solids made of 'materials' in the order they are mapped."""
    solids = dict(zip(wrapper_boolean._solids(shape), materials))
    return ocp_serialize.encode_shape(shape, cmf=ocp_serialize.cmf_section_for(shape, solids=solids))


def _combined(operation, first, second, whole=False):
    """'[(volume, material)]' of the solids of 'first <operation> second', in order."""
    request = {"operation": operation, "operands": [first, second], "whole": whole}
    shape, section = wrapper_boolean.process(request)
    found = []
    for index, solid in enumerate(wrapper_boolean._solids(shape)):
        cmf_set = section.solid_set(index) if section is not None else None
        found.append((round(wrapper_boolean._volume(solid), 3), cmf_set.material if cmf_set else None))
    return found


# A 10mm steel cube, and a brass one overlapping it by a 5mm cube.
CUBE = _box(0, 0, 0, 10, 10, 10)
OTHER = _box(5, 5, 5, 10, 10, 10)


def test_by_volume_and_is_what_both_occupy_made_of_the_first():
    assert _combined("and", _envelope(CUBE, STEEL), _envelope(OTHER, BRASS)) == [(125.0, ":steel")]


def test_by_volume_or_is_one_solid_made_of_the_first():
    assert _combined("or", _envelope(CUBE, STEEL), _envelope(OTHER, BRASS)) == [(1875.0, ":steel")]


def test_by_volume_xor_is_each_without_the_other_each_in_its_own():
    assert _combined("xor", _envelope(CUBE, STEEL), _envelope(OTHER, BRASS)) == [
        (875.0, ":steel"),
        (875.0, ":brass"),
    ]


def test_by_volume_what_states_nothing_is_made_of_nothing():
    assert _combined("and", _envelope(CUBE), _envelope(OTHER)) == [(125.0, None)]


def test_a_solid_fused_of_two_ties_to_the_first_offered():
    """Fused anew, the solid is made of what most of its faces came from; of equals, the first's.

    Two separate cubes of the first part, in two materials, bridged by a bar of
    the second: each cube gives the fused solid as many faces as the other, and
    the steel cube's are mapped first. Taking the most common of a 'set' of
    them broke that tie in hash order, which differs from one process to the
    next; the answer has to be the same every time.
    """
    pair = _compound(_box(0, 0, 0, 10, 10, 10), _box(20, 0, 0, 10, 10, 10))
    bar = _box(5, 2, 2, 20, 6, 6)
    (fused,) = _combined("or", _envelope(pair, STEEL, ALUMINIUM), _envelope(bar, BRASS))
    assert fused[1] == ":steel"


# A model of two pieces that touch - a hub and a bolt in it - and a box around the bolt.
HUB = _box(0, 0, 0, 20, 20, 10)
BOLT = _box(20, 8, 3, 6, 4, 4)
MODEL = _compound(HUB, BOLT)
AROUND_BOLT = _box(19.7, 7.7, 2.7, 6.6, 4.6, 4.6)


def test_by_whole_solids_and_takes_the_piece_out_whole():
    model = _envelope(MODEL, ALUMINIUM, STEEL)
    assert _combined("and", model, _envelope(AROUND_BOLT), whole=True) == [(96.0, ":steel")]


def test_by_whole_solids_xor_is_the_rest_without_it():
    model = _envelope(MODEL, ALUMINIUM, STEEL)
    assert _combined("xor", model, _envelope(BOLT, STEEL), whole=True) == [(4000.0, ":aluminium")]


def test_by_whole_solids_or_adds_what_the_first_does_not_have():
    model = _envelope(MODEL, ALUMINIUM, STEEL)
    extra = _box(40, 0, 0, 2, 2, 2)
    assert _combined("or", model, _envelope(_compound(BOLT, extra), STEEL, BRASS), whole=True) == [
        (4000.0, ":aluminium"),
        (96.0, ":steel"),
        (8.0, ":brass"),
    ]


def test_a_solid_is_inside_only_when_all_of_it_is():
    solids = wrapper_boolean._solids
    bolt = solids(BOLT)[0]
    around = solids(AROUND_BOLT)
    assert wrapper_boolean.inside(bolt, around)
    # The same solid, whatever the round trip did to it.
    assert wrapper_boolean.inside(bolt, solids(ocp_serialize.shape_from_brep(ocp_serialize.shape_to_brep(BOLT))))
    # Nowhere near it.
    assert not wrapper_boolean.inside(bolt, solids(_box(100, 0, 0, 1, 1, 1)))
    # Near, and sticking out of the box around it.
    assert not wrapper_boolean.inside(solids(HUB)[0], around)
    # Within the box around two that leave a gap between them, and larger than both.
    halves = solids(_compound(_box(0, 0, 0, 4, 10, 10), _box(6, 0, 0, 4, 10, 10)))
    assert not wrapper_boolean.inside(solids(CUBE)[0], halves)
    # Within the box and no larger, and still not inside: the boolean is what says so.
    corners = solids(_compound(_box(0, 0, 0, 6, 6, 10), _box(4, 4, 0, 6, 6, 10)))
    assert not wrapper_boolean.inside(solids(_box(0, 4, 0, 6, 6, 10))[0], corners)


@pytest.mark.parametrize(
    "request_, message",
    [
        ({"operation": "nand", "operands": []}, "one of and, or, xor"),
        ({"operation": "and", "operands": ["just one"]}, "takes two parts"),
        ({"operation": "and", "operands": None}, "takes two parts"),
    ],
)
def test_a_request_that_is_not_one_says_why(request_, message):
    with pytest.raises(ValueError, match=message):
        wrapper_boolean.process(request_)


def test_an_operation_that_leaves_nothing_says_so():
    apart = _box(100, 0, 0, 1, 1, 1)
    with pytest.raises(ValueError, match="leaves no solid"):
        wrapper_boolean.process({"operation": "and", "operands": [_envelope(CUBE), _envelope(apart)]})


def test_a_part_of_several_shapes_is_combined_without_its_pieces_cmf(capsys):
    """The steel the first part's piece states is not carried, so what both occupy is the second's brass."""
    pieces = ocp_serialize.encode_assembly(
        [ocp_serialize.encode_shape(CUBE, cmf=ocp_serialize.cmf_section_for(CUBE, own=STEEL))]
    )
    assert _combined("and", pieces, _envelope(OTHER, BRASS)) == [(125.0, ":brass")]
    assert "not carried: it is several shapes" in capsys.readouterr().err
