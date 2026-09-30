#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

import pytest

import partcad as pc


class BrokenPart:
    """A child whose shape failed to build.

    get_wrapped() returns None whenever the underlying shape could not be
    produced, which is what happens when the wrapper process dies before
    writing any output.
    """

    def __init__(self, project_name="//broken", name="broken_part"):
        self.project_name = project_name
        self.name = name

    async def get_wrapped(self, ctx=None):
        return None


def test_assembly_reports_child_that_failed_to_build():
    """A child with no shape must be named, not raise AttributeError from build123d."""
    ctx = pc.init("examples")

    model = pc.Assembly("//test", {"name": "broken_assembly"})
    model.add(BrokenPart(), name="child_a", loc=pc.Location((0, 0, 0), (0, 0, 1), 0))

    with pytest.raises(Exception) as excinfo:
        asyncio.run(model.get_wrapped(ctx))

    message = str(excinfo.value)
    # The failing child has to be identifiable from the error itself
    assert "broken_part" in message, message
    # The bare build123d symptom must no longer be what surfaces
    assert "TShape" not in message, message


def test_assembly_reports_child_without_name_or_location():
    """The guard must also cover children that skip the copy.copy() path."""
    ctx = pc.init("examples")

    model = pc.Assembly("//test", {"name": "broken_assembly"})
    # No name and no location, so per_child() does not call copy.copy() and the
    # failure would otherwise only appear once build123d builds the Compound.
    model.add(BrokenPart(name="unnamed_broken_part"))

    with pytest.raises(Exception) as excinfo:
        asyncio.run(model.get_wrapped(ctx))

    assert "unnamed_broken_part" in str(excinfo.value), str(excinfo.value)
