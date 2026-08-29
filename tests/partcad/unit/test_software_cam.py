#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part is only manufacturable if the software it ships with holds up.

A board nobody can flash is not a board anybody can make, so the manufacturing
test asks the same question of a part's 'software:' that the bill of materials
leaves hanging: does the reference resolve, is the file there, and is it the one
that was meant. The fixture ('data/software_cam') is one board declared five
ways -- shipping nothing, shipping a file that checks out, shipping one whose
hash does not match, one that nothing identifies, and one that does not exist.
"""

import asyncio

import pytest

import partcad as pc
from partcad.file_factory import parse_hash
from partcad.test import cam
from partcad.test.test import Test

DATA = "tests/partcad/unit/data/software_cam"

PROVIDER_NAME = "//:store"


class _Provider:
    """A provider that answers without a sandbox, unlike a real one."""

    def __init__(self, available: bool = True) -> None:
        self.name = PROVIDER_NAME
        self.available = available

    async def is_part_available(self, cart_item) -> bool:
        return self.available


@pytest.fixture
def ctx():
    """A context whose supplier lookup is answered locally.

    'CamTest.test_part()' ends with a supplier query, and this is not the test
    for that: without this every part below would fail for the wrong reason.
    """
    ctx = pc.Context(DATA)

    async def find_part_suppliers(cart_item, cart=None):
        return [PROVIDER_NAME]

    ctx.find_part_suppliers = find_part_suppliers
    ctx.get_provider = lambda name, params=None: _Provider()
    return ctx


def _software_failure(ctx, name):
    part = ctx.get_part("//:%s" % name)
    assert part is not None
    return asyncio.run(cam.CamTest().software_failure(ctx, part))


def _test_part(ctx, name):
    part = ctx.get_part("//:%s" % name)
    assert part is not None
    test = cam.CamTest()
    return asyncio.run(test.test([test], ctx, part))


#
# What makes a software object usable
#


def test_a_file_the_package_carries_and_pins_is_fine(ctx):
    assert _software_failure(ctx, "board") is None


def test_a_part_that_ships_nothing_is_asked_nothing(ctx):
    """'software:' is optional; a part without one is unaffected by any of this."""
    assert _software_failure(ctx, "board-plain") is None


def test_a_file_that_does_not_match_its_hash_fails(ctx):
    failure = _software_failure(ctx, "board-mismatched")
    assert failure is not None
    assert "does not match its 'hash'" in failure
    assert "//:mismatched" in failure


def test_a_fetched_file_with_no_hash_fails(ctx):
    """The rule the 'Software' lint check states, enforced where it bites."""
    failure = _software_failure(ctx, "board-unpinned")
    assert failure is not None
    assert "declares no 'hash'" in failure
    # Nothing was fetched: the declaration is unusable before the network is.
    assert "example.com" not in failure


def test_a_reference_that_resolves_to_nothing_fails(ctx):
    failure = _software_failure(ctx, "board-missing")
    assert failure is not None
    assert "is not found" in failure
    assert "//:nowhere" in failure


def test_every_bad_reference_is_reported(ctx):
    """Two wrong hashes should be two messages, not one and a re-run."""
    part = ctx.get_part("//:board")
    part.config["software_resolved"] = ["//:mismatched", "//:nowhere"]
    failure = asyncio.run(cam.CamTest().software_failure(ctx, part))
    assert "//:mismatched" in failure and "//:nowhere" in failure


#
# The manufacturing test itself
#


def test_the_manufacturing_test_passes_a_board_whose_software_holds_up(ctx):
    assert _test_part(ctx, "board") == Test.TEST_PASSED


def test_the_manufacturing_test_fails_a_board_whose_software_does_not(ctx):
    assert _test_part(ctx, "board-mismatched") == Test.TEST_FAILED
    assert _test_part(ctx, "board-unpinned") == Test.TEST_FAILED
    assert _test_part(ctx, "board-missing") == Test.TEST_FAILED


def test_an_assembly_is_held_to_the_same_rule(ctx):
    """An assembly ships software of its own, and it is checked the same way."""
    assembly = ctx._get_assembly("//:device")
    assert assembly is not None
    assert asyncio.run(cam.CamTest().software_failure(ctx, assembly)) is None

    assembly.config["software_resolved"] = ["//:mismatched"]
    test = cam.CamTest()
    assert asyncio.run(test.test([test], ctx, assembly)) == Test.TEST_FAILED


def test_a_part_that_is_not_manufacturable_is_not_asked(ctx):
    """The whole test short-circuits on 'manufacturable', software included."""
    part = ctx.get_part("//:board-mismatched")
    part.is_manufacturable = False
    test = cam.CamTest()
    assert asyncio.run(test.test([test], ctx, part)) == Test.TEST_PASSED


#
# The cached answer has to follow the declaration
#


def test_the_cache_key_follows_the_software_declaration(ctx):
    """Correcting a hash must not be answered with the failure it replaced.

    A part's hash covers what it is built from, and software is not that, so
    without this the cached result of the old declaration would be handed back
    for the new one.
    """
    test = cam.CamTest()
    plain = ctx.get_part("//:board-plain")
    board = ctx.get_part("//:board")
    mismatched = ctx.get_part("//:board-mismatched")

    # A part that ships nothing keys exactly as it always did.
    assert test.cache_key_suffix(ctx, plain) == ""

    # Two parts pointing at two different declarations key differently...
    assert test.cache_key_suffix(ctx, board) != test.cache_key_suffix(ctx, mismatched)

    # ...and so do the same part before and after its hash is corrected.
    before = test.cache_key_suffix(ctx, mismatched)
    ctx.get_project("//").get_software("mismatched").config["hash"] = (
        ctx.get_project("//").get_software("firmware").config["hash"]
    )
    assert test.cache_key_suffix(ctx, mismatched) != before


#
# Reading a declared hash
#
# 'hash' pins the bytes of a file, and nothing else -- it is read and checked by
# 'FileFactory', which is why these live beside the software tests rather than
# inside them: a part, a sketch and an assembly declare it the same way.


@pytest.mark.parametrize(
    "declared, algorithm",
    [
        ("sha256:" + "a" * 64, "sha256"),
        ("SHA-256:" + "A" * 64, "sha256"),
        ("b" * 40, "sha1"),
        ("c" * 128, "sha512"),
    ],
)
def test_a_hash_is_read_with_or_without_its_algorithm(declared, algorithm):
    parsed_algorithm, digest, error = parse_hash(declared)
    assert error is None
    assert parsed_algorithm == algorithm
    assert digest == digest.lower()


@pytest.mark.parametrize(
    "declared, complaint",
    [
        ("sha999:" + "a" * 64, "unknown hash algorithm"),
        ("sha256:nothex", "is not a sha256 digest"),
        ("abc", "cannot tell which algorithm"),
    ],
)
def test_an_unusable_hash_says_what_is_wrong_with_it(declared, complaint):
    algorithm, digest, error = parse_hash(declared)
    assert algorithm is None and digest is None
    assert complaint in error


def test_an_unusable_hash_fails_the_part(ctx):
    ctx.get_project("//").get_software("firmware").config["hash"] = "not-a-hash"
    failure = _software_failure(ctx, "board")
    assert failure is not None and "unusable" in failure
