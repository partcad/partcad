#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `partcad_client.object_types`: which object types are meshes.

What the tables *say* is checked against PartCAD's own in
`tests/partcad/unit/test_client_object_types.py`, which is where the heavy
import belongs. What they *mean* is here, and so is the one property that makes
answering by file name legitimate at all: no extension is shared by a mesh type
and a solid one, so a name is enough even where it does not name a single type.

Nothing here imports `partcad`. That is the point of the module under test --
`partcad_client` answers this question in a process that has no CAD kernel in
it -- and a test that needed one would be testing something else.
"""

import pytest

from partcad_client import object_types

# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------


def test_the_mesh_formats_are_the_ones_that_hold_triangles():
    meshes = {name for name, mesh in object_types.PART_TYPE_IS_MESH.items() if mesh}
    assert meshes == {"stl", "3mf", "obj", "gltf", "threejs"}


def test_every_type_answers_yes_or_no_and_nothing_else():
    """A missing answer would be read as 'not a mesh', which is a guess."""
    assert all(isinstance(mesh, bool) for mesh in object_types.PART_TYPE_IS_MESH.values())


def test_a_type_nobody_declared_is_unknown_rather_than_solid():
    # None and False are different answers: False is "PartCAD knows this type
    # and it is not a mesh", None is "PartCAD has never heard of it".
    assert object_types.is_mesh_type("stl") is True
    assert object_types.is_mesh_type("step") is False
    assert object_types.is_mesh_type("solidworks") is None
    assert object_types.is_mesh_type(None) is None


def test_the_type_is_read_case_insensitively():
    assert object_types.is_mesh_type("STL") is True


# ---------------------------------------------------------------------------
# Answering from the file name
# ---------------------------------------------------------------------------


def test_no_extension_is_claimed_by_both_a_mesh_and_a_solid():
    """The property that makes `is_mesh_file` an answer rather than a guess.

    '.py' is CadQuery, build123d and SDF at once, and '.json' is glTF and
    three.js at once -- but the members of each group agree about this one
    question, so the name still answers it. A format added on the other side of
    one of those groups would break that, and this is where it says so.
    """
    for extension, names in object_types.EXTENSION_TYPES.items():
        answers = {object_types.is_mesh_type(name) for name in names}
        answers.discard(None)
        assert len(answers) <= 1, "'.%s' is claimed by types that disagree: %s" % (extension, ", ".join(names))


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/w/cube.stl", True),
        ("/w/cube.STL", True),
        ("/w/cube.3mf", True),
        ("/w/cube.obj", True),
        ("/w/cube.step", False),
        ("/w/cube.stp", False),
        ("/w/cube.brep", False),
        # Three script types, one extension, one answer: none of them is a mesh.
        ("/w/cube.py", False),
        ("/w/cube.scad", False),
        # Neither PartCAD nor anything else claims it.
        ("/w/cube.sldprt", None),
        ("/w/cube", None),
    ],
)
def test_the_name_answers_where_it_can(path, expected):
    assert object_types.is_mesh_file(path) is expected


def test_the_other_spellings_of_a_format_are_the_same_format():
    """A file `pc open` is handed was written by something else as often as not."""
    assert object_types.type_of_file("/w/cube.stp") == "step"
    assert object_types.type_of_file("/w/cube.igs") == "iges"
    assert object_types.type_of_file("/w/scene.glb") == "gltf"


def test_an_extension_more_than_one_type_shares_names_none_of_them():
    """Which of the three a '.py' is decides how it is *run*; a guess is not it."""
    assert object_types.type_of_file("/w/cube.py") is None
    assert object_types.types_of_extension(".py") == ("build123d", "cadquery", "sdf")


def test_an_assy_is_recognized_even_though_it_is_not_a_part_type():
    """So that opening one is refused by name rather than as an unknown file."""
    assert object_types.type_of_file("/w/logo.assy") == "assy"
    assert "assy" in object_types.PACKAGE_ONLY_TYPES


# ---------------------------------------------------------------------------
# The two together
# ---------------------------------------------------------------------------


def test_a_declared_mesh_type_settles_it_whatever_the_file_is_called():
    assert object_types.is_mesh("/w/cube.dat", "stl") is True


def test_a_type_that_names_no_file_of_its_own_defers_to_the_file():
    """An `alias` is not a mesh; what it points at may well be one.

    This is the case that decides the precedence rule, and it is not academic:
    the VS Code tree hands `pc open` the declared type of the object the user
    clicked, and for a reference type that type says nothing about the file.
    """
    assert object_types.is_mesh_type("alias") is False
    assert object_types.is_mesh("/w/cube.stl", "alias") is True
    assert object_types.is_mesh("/w/cube.step", "alias") is False


def test_with_nothing_to_go_on_the_answer_is_unknown():
    assert object_types.is_mesh("/w/cube.sldprt") is None
    assert object_types.is_mesh("/w/cube.sldprt", "solidworks") is None


# ---------------------------------------------------------------------------
# What a conversion should read the file as
# ---------------------------------------------------------------------------


def test_a_declared_file_format_is_what_the_file_is_read_as():
    assert object_types.readable_type("/w/cube.dat", "build123d") == "build123d"


def test_a_type_that_is_not_a_file_format_falls_through_to_the_name():
    """Reading a KiCad part 'as kicad' would run KiCad on the STEP it already wrote.

    A `kicad` part *is* that STEP file, an `alias` is a reference, and neither
    names a format anything can be read as. The file in hand does.
    """
    assert object_types.readable_type("/w/board.step", "kicad") == "step"
    assert object_types.readable_type("/w/cube.stl", "alias") == "stl"


def test_a_partType_reference_is_not_an_error_it_is_just_not_a_format():
    """`type: //package:name` is a legitimate declaration, and it names a wrapper."""
    assert object_types.readable_type("/w/cube.step", "//package:mine") == "step"
    assert object_types.readable_type("/w/cube.dat", "//package:mine") is None


# ---------------------------------------------------------------------------
# Scene types: which description language a file is written in
# ---------------------------------------------------------------------------


def test_the_scene_formats_are_the_ones_a_file_can_hold_an_arrangement_in():
    assert set(object_types.SCENE_TYPE_EXTENSION) == {"assy", "world", "mjcf"}


def test_no_two_scene_types_share_an_extension():
    """Which makes `scene_type_of_file` an answer rather than a guess.

    Unlike the part types, where '.py' is three script types at once, a scene
    file's name says exactly which description language it is - so nothing here
    ever has to decline to answer for ambiguity.
    """
    extensions = list(object_types.SCENE_TYPE_EXTENSION.values())
    assert len(set(extensions)) == len(extensions)


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/w/warehouse.world", "world"),
        ("/w/stack.xml", "mjcf"),
        ("/w/bench.assy", "assy"),
        ("/w/cube.step", None),
        ("/w/cube", None),
    ],
)
def test_the_name_says_which_description_language_it_is(path, expected):
    assert object_types.scene_type_of_file(path) == expected


def test_a_declared_scene_type_settles_it_whatever_the_file_is_called():
    """'.sdf' is a world to whoever declared it and nothing to a file name."""
    assert object_types.readable_scene_type("/w/warehouse.sdf", "world") == "world"
    assert object_types.readable_scene_type("/w/warehouse.sdf") is None


def test_a_declared_type_that_is_no_scene_format_defers_to_the_file():
    assert object_types.readable_scene_type("/w/stack.xml", "alias") == "mjcf"


def test_the_assy_scene_is_the_one_that_cannot_be_converted_on_its_own():
    """It is references to the parts of a package, and there is no package."""
    assert "assy" in object_types.PACKAGE_ONLY_TYPES
    assert "world" not in object_types.PACKAGE_ONLY_TYPES
    assert "mjcf" not in object_types.PACKAGE_ONLY_TYPES
