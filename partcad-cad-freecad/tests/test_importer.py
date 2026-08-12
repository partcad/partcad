#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The FreeCAD-free half of the import: file naming and labelling."""

from partcad_freecad.importer import step_filename, unique_label
from partcad_freecad.model import KIND_PART, Item

CUBE = Item(KIND_PART, "cube", "//", {"type": "cadquery"})


def test_the_step_is_named_after_the_object(tmp_path):
    assert step_filename(str(tmp_path), CUBE) == str(tmp_path / "cube.step")


def test_the_parameter_values_are_part_of_the_name(tmp_path):
    path = step_filename(str(tmp_path), CUBE, {"width": 20.0, "height": 5})

    assert path == str(tmp_path / "cube_height5_width20.0.step")


def test_a_name_that_is_awkward_in_a_path_is_sanitized(tmp_path):
    item = Item(KIND_PART, "bracket/left v2", "//", {})

    assert step_filename(str(tmp_path), item) == str(tmp_path / "bracket_left_v2.step")


def test_an_existing_file_is_not_overwritten(tmp_path):
    (tmp_path / "cube.step").write_text("")

    assert step_filename(str(tmp_path), CUBE) == str(tmp_path / "cube_1.step")


def test_a_label_that_is_free_is_used_as_is():
    assert unique_label({"Box", "Cylinder"}, "cube") == "cube"


def test_a_taken_label_is_numbered():
    assert unique_label({"cube"}, "cube") == "cube (2)"
    assert unique_label({"cube", "cube (2)"}, "cube") == "cube (3)"
