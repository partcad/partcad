#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import pytest

from partcad import sandbox_versions


@pytest.mark.parametrize(
    "asked, minimum, expected",
    [
        # Below the floor: the floor wins.
        ("3.10", "3.11", "3.11"),
        # At or above it: what the package asked for wins.
        ("3.11", "3.11", "3.11"),
        ("3.12", "3.11", "3.12"),
        ("3.14", "3.11", "3.14"),
        # Compared numerically, not lexicographically -- "3.9" sorts after
        # "3.11" as a string, which is exactly the bug this guards against.
        ("3.9", "3.11", "3.11"),
        ("3.100", "3.11", "3.100"),
    ],
)
def test_at_least(asked, minimum, expected):
    assert sandbox_versions.at_least(asked, minimum) == expected


def test_cad_pins_are_exact():
    """The CAD stack has to be pinned, not floated.

    Two different OCP builds in one sandbox crash the wrapper process with no
    traceback, so these may not drift apart on their own.
    """
    for pin in (
        sandbox_versions.CADQUERY_OCP,
        sandbox_versions.OCPSVG,
        sandbox_versions.BUILD123D,
        sandbox_versions.CADQUERY,
        sandbox_versions.OCP_TESSELLATE,
    ):
        assert "==" in pin, pin


def test_default_python_version_is_supported():
    """The default sandbox interpreter has to be one PartCAD itself supports."""
    major, minor = (int(part) for part in sandbox_versions.DEFAULT_PYTHON_VERSION.split("."))
    assert (major, minor) >= (3, 10)
    assert (major, minor) <= (3, 14)


@pytest.mark.parametrize(
    "version, minimum, expected",
    [
        ("3.10", "3.11", False),
        ("3.11", "3.11", True),
        ("3.14", "3.11", True),
        # Numeric, not lexicographic: "3.9" > "3.11" as strings.
        ("3.9", "3.11", False),
    ],
)
def test_is_at_least(version, minimum, expected):
    assert sandbox_versions.is_at_least(version, minimum) is expected


@pytest.mark.parametrize(
    "python_version, expected",
    [
        # Below 3.14 the backport is what provides 'compression.zstd'...
        ("3.10", sandbox_versions.ZSTD),
        ("3.13", sandbox_versions.ZSTD),
        # ...and from 3.14 the standard library has it, while the backport
        # refuses to install there at all.
        ("3.14", None),
        ("3.15", None),
    ],
)
def test_zstd_requirement(python_version, expected):
    assert sandbox_versions.zstd_requirement(python_version) == expected


def test_cadquery_floor_excludes_the_oldest_supported_python():
    """CadQuery publishes nothing for 3.10, so sandboxes there must skip it."""
    assert not sandbox_versions.is_at_least("3.10", sandbox_versions.MIN_PYTHON_VERSION_CADQUERY)
    assert sandbox_versions.is_at_least("3.11", sandbox_versions.MIN_PYTHON_VERSION_CADQUERY)
