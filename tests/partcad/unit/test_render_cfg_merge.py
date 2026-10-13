#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a shape's own 'render:' section does to its package's.

'render_cfg_merge' layers the one over the other wherever PartCAD decides what
to render and where the result went: which file types a shape gets, where the
README and an instruction book look for its picture, which of its objects a
document leaves out. A shape that overrides one field of a file type means that
field, and keeps the rest of what its package says about the type.

It did not. After merging two sections of one file type, the merge went on to
compare the merged section with the shape's and, finding them different -
because the merged one still held the package's fields - replaced it with the
shape's. So a shape that set 'viewport_origin' on 'svg' lost the package's
'prefix' for it, and the README looked for its picture where the package had
never put it.
"""

import copy

import partcad as pc
from partcad.render import render_cfg_merge

PACKAGE = {
    "readme": None,
    "svg": {"prefix": "images/", "reproducible": True, "line_weight": 1.0},
    "png": {"prefix": "images/", "exclude": ["sketches"]},
}


def test_a_shape_overriding_one_field_keeps_the_packages_others():
    shape = {"svg": {"viewport_origin": [0, 0, 100], "viewport_up": [0, 1, 0]}}

    merged = render_cfg_merge(copy.deepcopy(PACKAGE), shape)

    assert merged["svg"] == {
        "prefix": "images/",
        "reproducible": True,
        "line_weight": 1.0,
        "viewport_origin": [0, 0, 100],
        "viewport_up": [0, 1, 0],
    }
    # The file types the shape said nothing about are the package's.
    assert merged["png"] == PACKAGE["png"]
    assert "readme" in merged


def test_a_field_both_set_is_the_shapes():
    merged = render_cfg_merge(copy.deepcopy(PACKAGE), {"svg": {"prefix": "./img"}})

    assert merged["svg"] == {"prefix": "./img", "reproducible": True, "line_weight": 1.0}


def test_nested_sections_merge_all_the_way_down():
    package = {"svg": {"overlay": {"ports": True, "size": 0.1}}}

    merged = render_cfg_merge(copy.deepcopy(package), {"svg": {"overlay": {"size": 0.2}}})

    assert merged == {"svg": {"overlay": {"ports": True, "size": 0.2}}}


def test_lists_still_add_up():
    """A shape's exclusions add to its package's, as they always have."""
    merged = render_cfg_merge(copy.deepcopy(PACKAGE), {"png": {"exclude": ["parts"]}})

    assert merged["png"] == {"prefix": "images/", "exclude": ["sketches", "parts"]}


def test_a_section_replaced_by_something_else_is_replaced():
    """Only a section meeting a section is merged; anything else is the shape's."""
    assert render_cfg_merge(copy.deepcopy(PACKAGE), {"svg": None})["svg"] is None
    assert render_cfg_merge(copy.deepcopy(PACKAGE), {"svg": "./drawings"})["svg"] == "./drawings"
    assert render_cfg_merge({"svg": None}, {"svg": {"prefix": "./"}})["svg"] == {"prefix": "./"}


def test_the_readme_finds_a_picture_where_the_package_put_it(tmp_path):
    """The user-visible half: the path a document links a shape's picture at."""
    (tmp_path / "partcad.yaml").write_text("name: //p\n")
    project = pc.Context(str(tmp_path)).get_project("//")
    shape = {"svg": {"viewport_origin": [0, 0, 100]}}

    _src, test_path = project.readme_image_path("cylinder", render_cfg_merge(copy.deepcopy(PACKAGE), shape), ".")

    assert test_path == "images/cylinder.svg"
