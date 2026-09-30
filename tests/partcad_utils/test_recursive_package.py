#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the `...` suffix: the written form of "and every package below it".

One reading of a package argument, shared by the CLI and the daemon, so that
`pc list parts //pub/examples...` and `pc render //pub/examples...:bolt` cannot
come to disagree about where the walk starts. The cases below are the ones a
user actually types -- a path with and without its last separator, a bare `...`,
the root -- plus the ones that must come back untouched, because this runs over
every package argument PartCAD has, including the ones that never carry a
suffix.
"""

import pytest

from partcad_utils.utils import split_recursive_object, split_recursive_package


@pytest.mark.parametrize(
    "argument, package",
    [
        ("//pub/examples...", "//pub/examples"),
        # The same request written the way a path is written: a user who has
        # typed a separator all the way along does not stop before the last one.
        ("//pub/examples/...", "//pub/examples"),
        # Relative, which is how a child of the current package is named.
        ("sub...", "sub"),
        ("sub/...", "sub"),
        # The whole of this workspace, from the root down.
        ("//...", "//"),
        # '...' with nothing in front of it: from here down.
        ("...", "."),
        ("./...", "."),
    ],
)
def test_a_suffix_names_the_package_it_walks_from(argument, package):
    assert split_recursive_package(argument) == (package, True)


@pytest.mark.parametrize(
    "argument",
    [
        "//pub/examples",
        "sub",
        "//",
        "/",
        ".",
        "",
        # Two dots are the parent package, not a suffix.
        "..",
        "../sibling",
        None,
    ],
)
def test_anything_without_the_suffix_is_left_alone(argument):
    assert split_recursive_package(argument) == (argument, False)


def test_the_object_half_can_carry_the_suffix_instead():
    # 'pc render ...:bolt' -- every bolt from the current package down. The
    # object comes back bare, because what resolves it is each package of the
    # walk in turn.
    assert split_recursive_object(".", "...:bolt") == (".", "bolt", True)


def test_an_object_suffix_says_where_the_walk_starts():
    # A name that says which package it is about wins over '--package', exactly
    # as a fully qualified object name already does.
    assert split_recursive_object("//elsewhere", "//pub/examples...:bolt") == ("//pub/examples", "bolt", True)


def test_a_relative_object_suffix_stays_relative():
    # Resolved against the current package later, by the caller that has a
    # context to resolve it in.
    assert split_recursive_object(".", "sub...:bolt") == ("sub", "bolt", True)


def test_the_package_half_still_counts_when_the_object_carries_none():
    assert split_recursive_object("//pub/examples...", "bolt") == ("//pub/examples", "bolt", True)


@pytest.mark.parametrize(
    "package, object_name",
    [
        ("//pub/examples", "bolt"),
        ("//pub/examples", "//elsewhere:bolt"),
        (".", None),
        (None, None),
    ],
)
def test_a_request_with_no_suffix_at_all_is_not_recursive(package, object_name):
    assert split_recursive_object(package, object_name) == (package, object_name, False)


def test_parameters_ride_along_with_the_object_name():
    # The parameters belong to the object, not to the package, so the suffix is
    # cut off in front of them and they are left where they were.
    assert split_recursive_object(".", "...:bolt;length=10") == (".", "bolt;length=10", True)
