#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an object inherits from the object it is another name for.

An `alias` and an `enrich` resolve to another part's configuration, and two
things that are read off a part were read off the *declaration* instead of that
resolved configuration - so a part aliased into a second package lost both:

* its manufacturing tolerance, which an alias's own factory accepts no field
  for - so `pc test` failed the alias of a machined part with "the part type
  'alias' does not accept one" about a part whose resolved configuration states
  0.02;
* the package a reference in that configuration is written in. A subtractive
  part names the blank it is cut from, and resolving that name against the
  package the alias lives in looks for somebody else's blank in the wrong
  namespace.

No CAD library and no sandbox: both are configuration.
"""

import asyncio

import pytest

from partcad.shape_config import ShapeConfiguration
from partcad.test.manufacturability_reference import declaring_project_name

MACHINED = {
    "name": "rack",
    "type": "step",
    "path": "rack.step",
    "tolerance": 0.02,
    "manufacturing": {"method": "subtractive", "source": "rack-blank"},
    "properties": {"material": "//pub:aluminium-5052", "color": "#AAB0B4"},
}


class _Part(ShapeConfiguration):
    """A part declared where it is used: its own configuration is the final one."""

    kind = "part"

    def __init__(self, config, project_name="//pkg", final=None):
        super().__init__(config)
        self.project_name = project_name
        self._final = final

    def get_final_config(self):
        return self._final if self._final is not None else self.config


def _alias(source_package="//pub/b601-dm", package="//pub/b601-rs"):
    """An alias of MACHINED, declared in another package."""
    return _Part(
        {
            "name": "rack",
            "type": "alias",
            "source": "%s:rack" % source_package,
            "source_resolved": "%s:rack" % source_package,
        },
        project_name=package,
        final=MACHINED,
    )


#
# How precisely it has to be made
#


def test_an_alias_is_toleranced_like_its_source():
    """The tolerance of a part is the tolerance of the part it is another name for."""
    assert asyncio.run(_alias().get_tolerance()) == pytest.approx(0.02)


def test_a_part_declaring_its_own_tolerance_is_unaffected():
    part = _Part(MACHINED)
    part._tolerance = 0.05
    assert asyncio.run(part.get_tolerance()) == pytest.approx(0.05)


def test_an_alias_of_a_part_that_states_nothing_states_nothing():
    """0.0 is 'nobody said' and stays that, rather than becoming a number."""
    source = dict(MACHINED)
    del source["tolerance"]
    alias = _alias()
    alias._final = source
    assert asyncio.run(alias.get_tolerance()) is None


#
# Where the names in that configuration live
#


def test_a_reference_is_resolved_against_the_package_that_wrote_it():
    assert declaring_project_name(_alias()) == "//pub/b601-dm"


def test_a_part_of_its_own_package_resolves_there():
    assert declaring_project_name(_Part(MACHINED)) == "//pkg"


@pytest.mark.parametrize("kind", ["alias", "enrich"])
def test_both_kinds_of_second_name_behave_the_same(kind):
    part = _alias()
    part.config["type"] = kind
    assert declaring_project_name(part) == "//pub/b601-dm"


def test_a_source_in_the_same_package_is_still_that_package():
    """A bare 'source:' names a part next door, which is where its names live too."""
    part = _alias()
    part.config["source"] = "rack"
    part.config["source_resolved"] = "//pub/b601-rs:rack"
    assert declaring_project_name(part) == "//pub/b601-rs"
