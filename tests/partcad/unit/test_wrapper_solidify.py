#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part handed back as a closed shell is the solid it bounds.

The wrapper side of the shell story: 'wrapper_common.solidify' states a closed
shell as the solid it already is, so that a cadquery or build123d script that
returns 'Shell' - or a partType that meshes triangles - produces the part it
meant rather than a skin nothing can compute with.

The verdicts are read back with 'partcad.brep_inspect', which is the core-side
half of the same story and needs no CAD kernel of its own; asking OCCT for the
volume as well is what makes it a test of the geometry rather than of the two
implementations agreeing with each other.
"""

import os
import sys
from io import BytesIO

import pytest

import partcad as pc
from partcad import brep_inspect

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shell
from OCP.gp import gp_Trsf, gp_Vec

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_common  # noqa: E402

BOX = (10.0, 20.0, 30.0)
BOX_VOLUME = BOX[0] * BOX[1] * BOX[2]


def _box():
    return BRepPrimAPI_MakeBox(*BOX).Shape()


def _sub_shape(shape, shape_type):
    return TopExp_Explorer(shape, shape_type).Current()


def _builder():
    return BRep_Builder()


def _compound(*children):
    builder = _builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for child in children:
        builder.Add(compound, child)
    return compound


def _moved(shape, copy=True):
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(100.0, 0.0, 0.0))
    return BRepBuilderAPI_Transform(shape, trsf, copy).Shape()


def _brep(shape):
    with BytesIO() as bio:
        BRepTools.Write_s(shape, bio)
        return bio.getvalue()


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _box_corners(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    return tuple(round(value, 6) for value in box.Get())


def _topology(shape):
    return brep_inspect.topology(_brep(shape))


def test_a_closed_shell_becomes_the_solid_it_bounds():
    shell = _sub_shape(_box(), TopAbs_SHELL)
    assert _topology(shell).free_shells == 1

    solid = wrapper_common.solidify(shell)

    assert solid.ShapeType() == TopAbs_SOLID
    assert _topology(solid).free_shells == 0
    assert _volume(solid) == BOX_VOLUME


def test_the_solid_is_oriented_rather_than_left_inside_out():
    """A closed shell whose faces point inward bounds the space outside it.

    Declaring a solid from one without orienting it produces a solid of negative
    volume - which renders correctly and makes every boolean against it
    meaningless, the failure 'partcad.test.solidity' exists to report. Converting
    a shell must not manufacture one.
    """
    reversed_shell = _sub_shape(_box(), TopAbs_SHELL).Reversed()

    solid = wrapper_common.solidify(reversed_shell)

    assert solid.ShapeType() == TopAbs_SOLID
    assert _volume(solid) == BOX_VOLUME


def test_a_shell_that_cannot_be_oriented_is_left_as_it_is(monkeypatch):
    """'BRepCheck_Shell.Closed()' and "can be oriented" are different questions.

    It asks whether the faces leave a free edge, not whether their orientations
    agree, so a closed shell can still be one 'OrientClosedSolid' refuses - and
    the solid that would come back from it is the inside-out one this conversion
    exists to avoid making. Forced here, because a shell in that state is
    laborious to build and the branch is one line either way.
    """
    import OCP.BRepLib

    shell = _sub_shape(_box(), TopAbs_SHELL)
    monkeypatch.setattr(OCP.BRepLib.BRepLib, "OrientClosedSolid_s", staticmethod(lambda solid: False))

    assert wrapper_common.solidify(shell) is shell


def test_a_shell_that_does_not_close_is_left_as_it_is():
    """There is no solid it bounds, and inventing one would be worse than saying so."""
    builder = _builder()
    open_shell = TopoDS_Shell()
    builder.MakeShell(open_shell)
    builder.Add(open_shell, _sub_shape(_box(), TopAbs_FACE))

    assert wrapper_common.solidify(open_shell) is open_shell
    assert _topology(open_shell).free_shells == 1


def test_a_shape_with_no_shell_to_convert_is_returned_untouched():
    """Byte for byte: rebuilding one would move a part nobody asked about."""
    box = _box()
    compound = _compound(box, _moved(box))

    for shape in (box, compound, _sub_shape(box, TopAbs_FACE)):
        result = wrapper_common.solidify(shape)
        assert result is shape
        assert _brep(result) == _brep(shape)


def test_a_solids_own_boundary_shell_is_not_converted():
    """A solid is made of a shell. That shell is not a free shell."""
    box = _box()
    topology = _topology(box)
    assert topology.count("shell") == 1 and topology.free_shells == 0

    assert wrapper_common.solidify(box) is box


def test_a_compound_holding_a_shell_beside_a_solid():
    """The case that needs the care, and the one that actually happens.

    Both wrappers compound whatever a script returned, so a shell arrives inside
    a compound rather than on its own.
    """
    cylinder = BRepPrimAPI_MakeCylinder(5.0, 12.0).Shape()
    shell = _moved(_sub_shape(_box(), TopAbs_SHELL))
    compound = _compound(cylinder, shell)
    assert _topology(compound).free_shells == 1

    result = wrapper_common.solidify(compound)

    assert _topology(result).free_shells == 0
    assert _topology(result).count("solid") == 2
    # The same geometry, in the same place: the conversion states what the
    # shape already was rather than changing it. (OCCT integrates the faces of
    # a closed shell too, so the volume was never what distinguished the two -
    # see test_a_shell_is_not_something_a_boolean_can_be_taken_against.)
    assert _volume(result) == pytest.approx(_volume(compound))
    assert _box_corners(result) == _box_corners(compound)


def test_a_shell_nested_two_compounds_deep():
    shell = _moved(_sub_shape(_box(), TopAbs_SHELL))
    compound = _compound(_box(), _compound(shell))
    assert _topology(compound).free_shells == 1

    result = wrapper_common.solidify(compound)

    assert _topology(result).free_shells == 0
    assert _topology(result).count("compound") == 2
    assert _box_corners(result) == _box_corners(compound)


def test_a_located_compound_is_not_displaced_when_it_is_rebuilt():
    """Its children are iterated cumulatively, so the replacement sits at the identity.

    Carrying the location onto the new compound as well would apply it twice.
    """
    shell = _moved(_sub_shape(_box(), TopAbs_SHELL))
    located = _moved(_compound(BRepPrimAPI_MakeCylinder(5.0, 12.0).Shape(), shell), copy=False)
    assert _topology(located).free_shells == 1

    result = wrapper_common.solidify(located)

    assert _topology(result).free_shells == 0
    assert _box_corners(result) == _box_corners(located)


def test_combine_states_a_parts_shell_as_a_solid():
    """'combine' is where both wrappers funnel a script's results."""
    shell = _sub_shape(_box(), TopAbs_SHELL)

    compound, components = wrapper_common.combine([shell], "part")

    assert _topology(compound).free_shells == 0
    assert [component.ShapeType() for component in components] == [TopAbs_SOLID]
    assert _volume(compound) == BOX_VOLUME


def test_combine_keeps_a_sketchs_faces_out_of_a_shell():
    """A sketch has no volume for a shell to bound, so it is descended into."""
    shell = _sub_shape(_box(), TopAbs_SHELL)

    compound, components = wrapper_common.combine([shell], "sketch")

    topology = _topology(compound)
    assert topology.count("shell") == 0
    assert topology.count("face") == 6
    assert [component.ShapeType() for component in components] == [TopAbs_FACE] * 6


def test_combine_still_walks_nested_lists_and_skips_what_it_always_skipped():
    box = _box()
    shell = _sub_shape(box, TopAbs_SHELL)
    face = _sub_shape(box, TopAbs_FACE)

    compound, components = wrapper_common.combine([None, "a string", [shell, face], box], "part")

    # The nested list is preserved as one, with the shell in it now a solid.
    assert len(components) == 2
    assert [shape.ShapeType() for shape in components[0]] == [TopAbs_SOLID, TopAbs_FACE]
    assert components[1].ShapeType() == TopAbs_SOLID
    # The face is a component but not part of a part's compound.
    assert _topology(compound).count("solid") == 2
    assert _volume(compound) == 2 * BOX_VOLUME


def test_a_shell_is_not_something_a_boolean_can_be_taken_against():
    """Why any of this matters, stated as OCCT's own answers.

    A closed shell and the solid it bounds are the same faces, and the shell
    measures the same size and even integrates to the same volume - so nothing
    about the shape says which it is. What does say it is a boolean: taken
    against the shell, every one of them comes back with no solid in it and a
    number unrelated to any shape. That is what makes a part handed back as a
    shell wrong for interference, CAM, FEA and a bill of materials while looking
    exactly right, and what 'solidify' is for.
    """
    cube = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
    shell = TopExp_Explorer(cube, TopAbs_SHELL).Current()
    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(5.0, 0.0, 0.0))
    other = BRepBuilderAPI_Transform(cube, trsf, True).Shape()

    def solids(shape):
        count = 0
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        while explorer.More():
            count += 1
            explorer.Next()
        return count

    # Nothing distinguishes the shell by measuring it.
    assert _volume(shell) == pytest.approx(1000.0)

    # Against the solid, the answers are the answers.
    assert _volume(BRepAlgoAPI_Common(other, cube).Shape()) == pytest.approx(500.0)
    assert _volume(BRepAlgoAPI_Cut(other, cube).Shape()) == pytest.approx(500.0)
    assert _volume(BRepAlgoAPI_Fuse(other, cube).Shape()) == pytest.approx(1500.0)

    # Against the shell, none of them is, and none of them holds a body.
    for operation in (BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse):
        result = operation(other, shell).Shape()
        assert solids(result) == 0

    # ...and after the conversion they are the answers again.
    solid = wrapper_common.solidify(shell)
    assert _volume(BRepAlgoAPI_Common(other, solid).Shape()) == pytest.approx(500.0)
    assert _volume(BRepAlgoAPI_Cut(other, solid).Shape()) == pytest.approx(500.0)
    assert _volume(BRepAlgoAPI_Fuse(other, solid).Shape()) == pytest.approx(1500.0)
