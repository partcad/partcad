#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the 'interference' and 'degenerate' checks decide, and on what.

The 'cad' test asks whether a shape was produced. These two ask whether what
was produced is a solid anybody meant, and whether the parts ended up anywhere
sensible - the questions an assembly is actually judged on, and the ones that
have needed a person looking at a render.

The geometry itself is exercised in the wrapper, which needs a CAD library and
so is not reachable from here; what is covered here is the deciding: which
verdict follows from which measurement, and what the configuration does.
"""

import asyncio

import pytest

from partcad.test.degenerate import DegenerateTest
from partcad.test.interference import InterferenceTest, _is_ignored, _matches


class _Shape:
    """The little a test needs of a shape: a config, a name, and a measurement."""

    def __init__(self, config=None, box=(0, 0, 0, 10, 10, 10), overlaps=None, raises=None, unchecked=()):
        self.config = config or {}
        self.project_name = "pkg"
        self.name = "thing"
        self._box = box
        self._overlaps = overlaps
        self._unchecked = list(unchecked)
        self._indeterminate = []
        self._raises = raises

    async def get_bounding_box_async(self, ctx):
        if self._raises:
            raise self._raises
        return self._box

    async def get_interference_async(self, ctx, min_volume=1.0, min_fraction=0.0):
        if self._raises:
            raise self._raises
        self.asked_with = (min_volume, min_fraction)
        if self._overlaps is None:
            return None
        return {
            "overlaps": self._overlaps,
            "unchecked": self._unchecked,
            "indeterminate": self._indeterminate,
            "parts": 0,
        }


class _Assembly(_Shape):
    pass


class _Sketch(_Shape):
    pass


@pytest.fixture(autouse=True)
def _assembly_is_an_assembly(monkeypatch):
    """Both tests branch on isinstance(); the stubs stand in for the real classes."""
    monkeypatch.setattr("partcad.test.interference.Assembly", _Assembly)
    monkeypatch.setattr("partcad.test.degenerate.Assembly", _Assembly)
    monkeypatch.setattr("partcad.test.degenerate.Sketch", _Sketch)


def _run(test, shape):
    """The repository drives its async work through asyncio.run(); so does this."""
    return asyncio.run(test.test([], None, shape))


# --- degenerate -------------------------------------------------------------


def test_a_solid_with_size_in_every_direction_passes():
    assert _run(DegenerateTest(), _Shape(box=(0, 0, 0, 8, 8, 9.6)))


def test_a_part_flattened_to_a_sheet_fails():
    """The regression: a 2 x 2 round brick 9.6 mm tall that meshed into a disc
    about a millimetre thick because a subfile could not be fetched. It
    rendered, it exported, and every test there was passed it."""
    assert not _run(DegenerateTest(), _Shape(box=(0, 0, 0, 16, 16, 0.0)))


def test_a_shape_with_no_extent_at_all_fails():
    assert not _run(DegenerateTest(), _Shape(box=None))


def test_something_meant_to_be_flat_can_say_so():
    shape = _Shape(config={"degenerate": {"skip": True}}, box=(0, 0, 0, 10, 10, 0))
    assert _run(DegenerateTest(), shape)


def test_the_tolerance_is_configurable():
    thin = _Shape(box=(0, 0, 0, 10, 10, 0.05))
    assert _run(DegenerateTest(), thin)  # thinner than a brick, but a solid
    strict = _Shape(config={"degenerate": {"tolerance": 0.1}}, box=(0, 0, 0, 10, 10, 0.05))
    assert not _run(DegenerateTest(), strict)


def test_an_assembly_is_checked_through_its_parts():
    """Each part is tested in its own right; an assembly's box says nothing."""
    assert _run(DegenerateTest(), _Assembly(box=None))


def test_a_shape_that_cannot_be_measured_is_left_to_the_cad_test():
    assert _run(DegenerateTest(), _Shape(raises=Exception("no runtime")))


# --- interference -----------------------------------------------------------


def test_an_assembly_whose_parts_keep_to_themselves_passes():
    assert _run(InterferenceTest(), _Assembly(overlaps=[]))


def test_parts_sharing_space_fail():
    overlaps = [{"a": "buttS8", "b": "gateW", "volume": 512.0}]
    assert not _run(InterferenceTest(), _Assembly(overlaps=overlaps))


def test_a_part_is_not_checked_against_itself_or_anything_else():
    assert _run(InterferenceTest(), _Shape())


def test_the_thresholds_reach_the_measurement():
    """They are what separates a design fault from a design that fits together,
    so a package that sets them has to have them honoured."""
    shape = _Assembly(config={"interference": {"minVolume": 0.5, "minFraction": 0.01}}, overlaps=[])
    _run(InterferenceTest(), shape)
    assert shape.asked_with == (0.5, 0.01)


def test_a_pair_that_is_meant_to_interfere_can_be_declared():
    config = {"interference": {"ignore": [["shaft", "hub"]]}}
    overlaps = [{"a": "shaft", "b": "hub", "volume": 90.0}]
    assert _run(InterferenceTest(), _Assembly(config=config, overlaps=overlaps))


def test_declaring_one_pair_does_not_excuse_the_others():
    config = {"interference": {"ignore": [["shaft", "hub"]]}}
    overlaps = [
        {"a": "shaft", "b": "hub", "volume": 90.0},
        {"a": "shaft", "b": "casing", "volume": 12.0},
    ]
    assert not _run(InterferenceTest(), _Assembly(config=config, overlaps=overlaps))


def test_a_whole_assembly_can_opt_out():
    config = {"interference": {"skip": True}}
    overlaps = [{"a": "a", "b": "b", "volume": 1e6}]
    assert _run(InterferenceTest(), _Assembly(config=config, overlaps=overlaps))


def test_an_ignored_pair_is_named_in_either_order():
    ignored = {("hub", "shaft")}
    assert _is_ignored({"a": "shaft", "b": "hub"}, ignored)
    assert _is_ignored({"a": "hub", "b": "shaft"}, ignored)
    assert not _is_ignored({"a": "hub", "b": "casing"}, ignored)


def test_parts_that_are_not_valid_solids_are_reported_rather_than_hidden(caplog):
    """A boolean against an inside-out solid returns a number unrelated to any
    shared space - two LDraw bricks 100 mm apart came back sharing 2282 mm^3 -
    so such parts are left out. An assembly built entirely from them is not
    being checked at all, and a pass must not be read as a clean bill."""
    import logging

    shape = _Assembly(overlaps=[], unchecked=["lower", "upper"])
    with caplog.at_level(logging.INFO):
        assert _run(InterferenceTest(), shape)
    assert "not valid solids" in caplog.text
    assert "lower" in caplog.text


def test_a_pair_is_named_without_saying_where_in_the_tree_it_sits():
    assert _matches("gearbox/shaft", "shaft")
    assert _matches("shaft", "shaft")
    # ...but not by accident: a suffix is a whole path element.
    assert not _matches("driveshaft", "shaft")


def test_the_cache_key_moves_when_the_thresholds_do():
    """A verdict reached under one threshold must not be read back under another."""
    test = InterferenceTest()
    loose = test.cache_key_suffix(None, _Assembly(config={"interference": {"minVolume": 1.0}}))
    strict = test.cache_key_suffix(None, _Assembly(config={"interference": {"minVolume": 0.1}}))
    assert loose != strict
    ignoring = test.cache_key_suffix(None, _Assembly(config={"interference": {"ignore": [["a", "b"]]}}))
    assert ignoring != test.cache_key_suffix(None, _Assembly())


# --- the request the core sends the wrapper ---------------------------------
#
# The tests above stub get_interference_async() out entirely, which is what let
# a broken request reach CI: the core sent the assembly under "wrapped", where
# ocp_serialize.decode turns anything shape-shaped into OCCT geometry, so the
# wrapper was handed one TopoDS_Compound and died reaching for a name on it.
# Nothing here exercised the handover. This does.


def test_the_assembly_is_sent_as_json_rather_than_as_geometry():
    import json as _json

    from partcad.assembly import Assembly

    envelope = {"name": "asm", "label": "asm", "assembly": [{"name": "a", "brep": "..."}]}
    captured = {}

    class _Runtime:
        async def ensure_async(self, *args):
            return None

        async def run_async(self, command, request_serialized):
            captured["request"] = request_serialized
            return 0, '{"success": true, "overlaps": [], "unchecked": [], "parts": 0}', ""

    class _Ctx:
        def get_python_runtime(self, version=None):
            return _Runtime()

    assembly = Assembly.__new__(Assembly)
    assembly.project_name = "pkg"
    assembly.name = "asm"

    async def _wrapped(ctx):
        return envelope

    assembly.get_wrapped = _wrapped
    asyncio.run(assembly.get_interference_async(_Ctx()))

    sent = _json.loads(captured["request"])
    # Carried as a string: a dict shaped like an assembly would be decoded into
    # a compound on arrival, and the names would go with it.
    assert isinstance(sent["assembly_json"], str)
    assert _json.loads(sent["assembly_json"]) == envelope
    assert "wrapped" not in sent, "the geometry key is decoded on arrival; do not use it here"


def test_an_indeterminate_pair_is_not_reported_as_no_overlap(caplog):
    """A boolean that did not come back is not an answer of "they are clear".

    Dropping such a pair silently is how a check comes to certify what it never
    looked at, which is the failure mode this whole set of tests exists for.
    """
    import logging

    shape = _Assembly(overlaps=[])
    shape._indeterminate = [{"a": "shaft", "b": "hub", "reason": "the boolean did not complete"}]
    with caplog.at_level(logging.INFO):
        assert _run(InterferenceTest(), shape)
    assert "could not decide" in caplog.text
    assert "shaft" in caplog.text


def test_the_interference_cache_key_covers_skip_as_well_as_the_thresholds():
    test = InterferenceTest()
    assert test.cache_key_suffix(None, _Assembly()) != test.cache_key_suffix(
        None, _Assembly(config={"interference": {"skip": True}})
    )


def test_a_verdict_that_turned_on_the_machine_is_not_remembered():
    ctx = {}
    assert asyncio.run(InterferenceTest().test([], None, _Assembly(raises=Exception("no runtime")), ctx))
    assert ctx.get(InterferenceTest.NOT_CACHEABLE) is True



def test_a_sketch_is_flat_because_that_is_what_a_sketch_is():
    """Found by CI: 'circle' in examples/provider_manufacturer is a sketch,
    20 x 20 x 0 mm, and this failed it for being what it was asked to be. A
    check an object cannot pass and should not be taking is worse than none.
    """
    assert _run(DegenerateTest(), _Sketch(box=(0, 0, 0, 20, 20, 0.0)))
