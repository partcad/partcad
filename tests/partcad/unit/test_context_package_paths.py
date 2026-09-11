#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A package name is a path, so a parent match has to stop at the separator.

'//foo' is not the parent of '//foobar'. Matching it as one put the neighbour
in a listing of '//foo' - and, since the listing now warms what it is about to
read, sent a round trip to that neighbour's repository plugin as well.
"""

from partcad.context import _is_within


def test_a_package_is_within_itself():
    assert _is_within("//foo", "//foo")


def test_a_child_is_within_its_parent():
    assert _is_within("//foo/bar", "//foo")
    assert _is_within("//foo/bar/baz", "//foo")


def test_a_neighbour_sharing_a_prefix_is_not_a_child():
    assert not _is_within("//foobar", "//foo")
    assert not _is_within("//foo-bar", "//foo")


def test_the_root_is_the_parent_of_everything():
    assert _is_within("//pub/examples", "//")
    assert _is_within("//", "//")


def test_no_parent_matches_every_package():
    assert _is_within("//anything", None)
