#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Reading a STEP file as it shows ('wrappers/step_visible.py').

An item the file declares invisible stays in the representation that lists it,
and OpenCASCADE's plain reader transfers it like any other. The filter takes it
out of that list, by each of the three ways a file can hide it, and changes
nothing else.
"""

import importlib.util
import os
import sys

import pytest

import partcad as pc

WRAPPERS = os.path.join(os.path.dirname(pc.__file__), "wrappers")


@pytest.fixture(scope="module")
def step_visible():
    sys.path.append(WRAPPERS)  # step_repair, which it parses argument lists with
    spec = importlib.util.spec_from_file_location("step_visible_under_test", os.path.join(WRAPPERS, "step_visible.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BODIES = (
    "#10 = MANIFOLD_SOLID_BREP('shown', #9);\n"
    "#20 = MANIFOLD_SOLID_BREP('hidden', #19);\n"
    "#30 = ADVANCED_BREP_SHAPE_REPRESENTATION('', (#10, #20), #5);\n"
)


def test_an_item_declared_invisible_leaves_its_representation(step_visible):
    text, removed = step_visible.shown_text(BODIES + "#40 = INVISIBILITY((#20));\n")
    assert removed == 1
    assert "ADVANCED_BREP_SHAPE_REPRESENTATION('',(#10), #5);" in text
    # Its record stays, unreferenced, and so does the invisibility.
    assert "#20 = MANIFOLD_SOLID_BREP('hidden', #19);" in text
    assert "#40 = INVISIBILITY((#20));" in text


def test_an_invisible_style_hides_the_item_it_styles(step_visible):
    text, removed = step_visible.shown_text(
        BODIES + "#35 = STYLED_ITEM('color', (#34), #20);\n#40 = INVISIBILITY((#35));\n"
    )
    assert removed == 1
    assert "(#10)" in text


def test_an_invisible_layer_hides_every_item_on_it(step_visible):
    text, removed = step_visible.shown_text(
        BODIES + "#35 = PRESENTATION_LAYER_ASSIGNMENT('construction', '', (#20, #10));\n#40 = INVISIBILITY((#35));\n"
    )
    assert removed == 2
    assert "ADVANCED_BREP_SHAPE_REPRESENTATION('',(), #5);" in text


def test_a_file_that_hides_nothing_is_left_as_it_is(step_visible, tmp_path):
    assert step_visible.shown_text(BODIES) == (BODIES, 0)
    path = tmp_path / "plain.step"
    path.write_text(BODIES)
    with step_visible.shown(str(path)) as shown:
        assert shown == str(path)


def test_a_copy_is_read_and_gone_afterwards(step_visible, tmp_path):
    path = tmp_path / "hidden.step"
    path.write_text(BODIES + "#40 = INVISIBILITY((#20));\n")
    with step_visible.shown(str(path)) as shown:
        assert shown != str(path)
        with open(shown) as f:
            assert "(#10)" in f.read()
    assert not os.path.exists(shown)
    # The file itself is untouched.
    assert "(#10, #20)" in path.read_text()


def test_a_name_that_looks_like_a_reference_is_not_one(step_visible):
    """The item list is what is filtered; a quoted name elsewhere in the record is text."""
    text, _ = step_visible.shown_text(
        "#10 = MANIFOLD_SOLID_BREP('#20', #9);\n"
        "#20 = MANIFOLD_SOLID_BREP('', #19);\n"
        "#30 = SHAPE_REPRESENTATION('#20', (#10, #20), #5);\n"
        "#40 = INVISIBILITY((#20));\n"
    )
    assert "#30 = SHAPE_REPRESENTATION('#20',(#10), #5);" in text
    assert "#10 = MANIFOLD_SOLID_BREP('#20', #9);" in text


def test_what_is_not_a_list_of_items_is_left_alone(step_visible):
    """A representation with fewer than its three parameters, or items that are not a list, is not edited."""
    text = (
        "#20 = MANIFOLD_SOLID_BREP('hidden', #19);\n"
        "#30 = SHAPE_REPRESENTATION('', #20, #5);\n"
        "#31 = DEFINITIONAL_REPRESENTATION('');\n"
        "#40 = INVISIBILITY((#20));\n"
    )
    assert step_visible.shown_text(text) == (text, 0)


def test_a_file_whose_hidden_items_no_representation_lists_is_read_as_it_is(step_visible, tmp_path):
    path = tmp_path / "unlisted.step"
    path.write_text(BODIES + "#50 = MANIFOLD_SOLID_BREP('elsewhere', #49);\n#60 = INVISIBILITY((#50));\n")
    with step_visible.shown(str(path)) as shown:
        assert shown == str(path)
