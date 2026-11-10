#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for reading '<package>:<object>[;<param>=<value>,...]'.

The separator between the package and the object is the first ':' -- a package
path holds none -- and only a ':' before the parameters is one. A parameter
value is the user's text: a material reference
('medium=//pub/std/materials:water'), a URL, a ratio. Splitting on every ':'
made such a name unreadable ("too many values to unpack"), and splitting on the
last one made it name an object called after the tail of its own value. Neither
is a rare spelling: it is what an enrich of a scene writes for a medium the
scene is in.

The forms below are the ones in use: fully qualified, relative to this
package, relative to another, bare, with parameters, with a ':' and a '//' in a
parameter value, and an assembly embedded in an ASSY file, whose own name holds
a ':' ('<file>:<assembly>').
"""

import pytest

from partcad_utils.utils import (
    format_parameterized_name,
    get_child_project_path,
    normalize_resource_path,
    parse_parameterized_name,
    resolve_parent_segments,
    resolve_resource_path,
    split_recursive_object,
    split_resource_path,
)

HERE = "//here"


@pytest.mark.parametrize(
    "pattern, package, item",
    [
        ("//pkg:obj", "//pkg", "obj"),
        (":obj", HERE, "obj"),
        ("pkg:obj", HERE + "/pkg", "obj"),
        ("../sibling:obj", "//sibling", "obj"),
        ("obj", HERE, "obj"),
        ("obj;a=1", HERE, "obj;a=1"),
        ("//pkg:obj;a=1,b=2", "//pkg", "obj;a=1,b=2"),
        # A ':' in a parameter value.
        ("//pkg:obj;a=x:y", "//pkg", "obj;a=x:y"),
        (":obj;a=x:y", HERE, "obj;a=x:y"),
        ("pkg:obj;a=x:y", HERE + "/pkg", "obj;a=x:y"),
        ("obj;a=x:y", HERE, "obj;a=x:y"),
        # A value that is itself a reference: '//' and ':' both.
        ("//pkg:room;medium=//pub/std/materials:water", "//pkg", "room;medium=//pub/std/materials:water"),
        ("room;medium=//pub/std/materials:water", HERE, "room;medium=//pub/std/materials:water"),
        # A '//' in a value with no ':' at all, and a URL, which has both.
        ("obj;path=//pub/std", HERE, "obj;path=//pub/std"),
        (":obj;url=https://example.com/a:b", HERE, "obj;url=https://example.com/a:b"),
        # Several parameters, more than one of them with a ':'.
        ("//pkg:obj;a=x:y,b=1,c=u:v:w", "//pkg", "obj;a=x:y,b=1,c=u:v:w"),
        # An assembly embedded in an ASSY file is named '<file>:<assembly>' in
        # its package, so the object half of a qualified name has a ':' too.
        ("//pkg:file:inner", "//pkg", "file:inner"),
    ],
)
def test_only_the_separator_before_the_parameters_is_split_on(pattern, package, item):
    assert resolve_resource_path(HERE, pattern) == (package, item)
    assert normalize_resource_path(HERE, pattern) == "%s:%s" % (package, item)


@pytest.mark.parametrize(
    "pattern, package, rest",
    [
        ("//pkg:obj", "//pkg", "obj"),
        (":obj", "", "obj"),
        ("obj", None, "obj"),
        ("obj;a=x:y", None, "obj;a=x:y"),
        ("obj;m=//pub/std:air", None, "obj;m=//pub/std:air"),
        ("//pkg:obj;a=x:y", "//pkg", "obj;a=x:y"),
        ("//pkg:file:inner", "//pkg", "file:inner"),
        ("", None, ""),
    ],
)
def test_a_reference_names_a_package_only_before_its_parameters(pattern, package, rest):
    """None when no package is named at all, '' when the current one is, by ':obj'."""
    assert split_resource_path(pattern) == (package, rest)


def test_a_wildcard_is_read_in_the_name_and_not_in_a_value():
    """'...' is the wildcard of an object name; a value is the user's text, '...' and all."""
    assert resolve_resource_path(HERE, "//pkg:bolt...") == ("//pkg", "bolt*")
    assert resolve_resource_path(HERE, "...:bolt") == (HERE + "/*", "bolt")
    assert resolve_resource_path(HERE, "//pkg:obj;label=wait...") == ("//pkg", "obj;label=wait...")
    assert resolve_resource_path(HERE, "//pkg:obj;a=x...:y") == ("//pkg", "obj;a=x...:y")


def test_the_root_and_an_unnamed_current_package_resolve_as_they_did():
    """The paths no ':' in a value can reach, kept exactly as they were."""
    assert resolve_resource_path("//", "obj") == ("//", "obj")
    assert resolve_resource_path("//", "sub:obj") == ("//sub", "obj")
    assert resolve_resource_path("", "obj") == ("/", "obj")
    assert resolve_resource_path("", "//pkg:obj;a=x:y") == ("//pkg", "obj;a=x:y")


# A package served at some depth below its own root - a catalogue's
# '<package>/products/<category>/<subcategory>' - names that root with as many
# '..' as it is deep. One pass of a regular expression resolved the first of
# them and not the rest.
CATALOGUE = "//x/store/products"


@pytest.mark.parametrize(
    "current, pattern, package",
    [
        (CATALOGUE, "..:store", "//x/store"),
        (CATALOGUE + "/resistors", "../..:store", "//x/store"),
        (CATALOGUE + "/resistors/chip", "../../..:store", "//x/store"),
        # A '..' is a whole segment: three of them in a row are three levels,
        # not a segment named '..' cancelling the one after it.
        ("//a/b/c/d", "../../..:obj", "//a"),
        ("//a/b/c/d", "../../../..:obj", "//"),
    ],
)
def test_every_level_of_parent_is_climbed(current, pattern, package):
    item = pattern.split(":", 1)[1]
    assert resolve_resource_path(current, pattern) == (package, item)
    assert normalize_resource_path(current, pattern) == "%s:%s" % (package, item)


@pytest.mark.parametrize(
    "current, pattern, package",
    [
        (HERE, "../sibling/child:item", "//sibling/child"),
        ("//a/b/c", "../../sibling/child:item", "//a/sibling/child"),
        ("//a/b/c", "../x/../y:item", "//a/b/y"),
        ("//a/b/c", "x/../../y:item", "//a/b/y"),
        # An absolute path is resolved too.
        (HERE, "//a/b/../c:item", "//a/c"),
        # And so is the deprecated single '/', once it has become '//'.
        (HERE, "/a/b/../../c:item", "//c"),
    ],
)
def test_parent_segments_mix_with_names(current, pattern, package):
    assert resolve_resource_path(current, pattern) == (package, "item")


@pytest.mark.parametrize(
    "current, pattern, package",
    [
        ("//a", "../..:obj", "//.."),
        ("//a", "../../b:obj", "//../b"),
        ("//", "..:obj", "//.."),
        ("//a/b", "../../../c/d:obj", "//../c/d"),
    ],
)
def test_a_reference_climbing_above_the_root_is_left_unresolved(current, pattern, package):
    """Not taken to mean the root, and not an error here.

    Every '..' that has nothing left to take away stays, so the result names no
    package and its lookup says "not found" under a name that shows why. Read as
    the root, a reference that miscounted its levels would quietly name another
    package.
    """
    assert resolve_resource_path(current, pattern) == (package, "obj")


def test_the_wildcard_and_a_parent_segment_resolve_together():
    """'...' is a name ('*'), never a '..' with a dot to spare."""
    assert resolve_resource_path(HERE, "../...:bolt") == ("//*", "bolt")
    assert resolve_resource_path("//a/b", ".../..:bolt") == ("//a/b", "bolt")
    assert resolve_resource_path("//a/b/c", "../../...:bolt...") == ("//a/*", "bolt*")
    assert resolve_resource_path(HERE, "//pkg/...:bolt") == ("//pkg/*", "bolt")


def test_resolving_parent_segments_leaves_everything_else_as_written():
    for path in ("//", "/", "//a", "//a/b/", "//*", "//a/.b", "//a/b..", "relative/path"):
        assert resolve_parent_segments(path) == path
    assert resolve_parent_segments("//a/b/../") == "//a/"
    assert resolve_parent_segments("a/b/../../..") == ".."


@pytest.mark.parametrize(
    "parent, child, expected",
    [
        ("//a/b", "c", "//a/b/c"),
        ("//a/b", "..", "//a"),
        ("//a/b", "../..", "//"),
        ("//a/b/c", "../../d", "//a/d"),
        ("//", "a", "//a"),
        ("//", "..", "//.."),
        ("//a", "b/", "//a/b"),
    ],
)
def test_a_child_package_path_climbs_the_same_way(parent, child, expected):
    """A dependency's or '--package' path, which used to share the regular expression."""
    assert get_child_project_path(parent, child) == expected


def test_a_recursive_object_keeps_a_colon_in_its_parameters():
    assert split_recursive_object("", "//pub/examples...:bolt;a=x:y") == ("//pub/examples", "bolt;a=x:y", True)
    # A value ending in '...' before a ':' is not a package asking for recursion.
    assert split_recursive_object("", "bolt;a=x...:y") == ("", "bolt;a=x...:y", False)
    assert split_recursive_object("//pkg", "bolt;a=x:y") == ("//pkg", "bolt;a=x:y", False)


def test_an_instance_name_keeps_a_colon_and_a_double_slash_in_a_value():
    """'parse_parameterized_name' never split on ':', and this keeps it that way."""
    name = "room;medium=//pub/std/materials:water,ratio=1:2"
    assert parse_parameterized_name(name) == ("room", {"medium": "//pub/std/materials:water", "ratio": "1:2"})
    assert format_parameterized_name("room", {"medium": "//pub/std/materials:water", "ratio": "1:2"}) == name
    assert format_parameterized_name("//pkg:room", {"medium": "//pub/std/materials:water"}) == (
        "//pkg:room;medium=//pub/std/materials:water"
    )


@pytest.mark.parametrize(
    "value",
    [["BEND_UP", "BEND_DOWN"], ("BEND_UP", "BEND_DOWN"), [["BEND_UP"], "BEND_DOWN"], "BEND_UP,BEND_DOWN"],
)
def test_a_list_is_named_by_its_items_in_their_order(value):
    """The one way a name holds a list, whatever it was handed over as; it reads back as the same text."""
    name = format_parameterized_name("panel", {"include": value})
    assert name == "panel;include=BEND_UP,BEND_DOWN"
    assert parse_parameterized_name(name) == ("panel", {"include": "BEND_UP,BEND_DOWN"})
    assert (
        format_parameterized_name("panel", {"include": ["BEND_DOWN", "BEND_UP"]}) == "panel;include=BEND_DOWN,BEND_UP"
    )
