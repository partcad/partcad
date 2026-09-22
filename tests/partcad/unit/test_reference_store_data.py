#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an 'alias' or an 'enrich' says about buying the object it points at.

One piece of geometry is sold by several vendors, in several pack sizes, and
'Procurement' in 'docs/source/configuration.rst' says to write each of those as
a reference to the first. The schema accepts 'vendor', 'sku' and
'count_per_sku' on a reference for that reason - and every one of them used to
be thrown away, because a reference reported the configuration of what it
points at verbatim. An alias of an alias, and an enrich of an enrich, lost what
the reference in the middle declared for the same reason.
"""

import asyncio

import pytest

import partcad as pc
from partcad.shape_config_store import resolve_store_properties

DATA = "tests/partcad/unit/data/reference_store"


@pytest.fixture
def ctx():
    return pc.Context(DATA)


def _store(ctx, name):
    part = ctx._get_part(":" + name)
    assert part is not None, name
    # An enrich answers for the instance it resolved to, which it works out
    # while it is prepared rather than while it is built.
    asyncio.run(part.prepare_async())
    return part.get_store_data()


def _record(store_data):
    return (store_data.vendor, store_data.sku, store_data.count_per_sku)


def test_the_part_itself_is_ordered_as_it_declares(ctx):
    assert _record(_store(ctx, "bolt")) == ("acme", "BOLT-1", 10)


def test_a_reference_that_says_nothing_orders_what_it_points_at(ctx):
    assert _record(_store(ctx, "bolt_alias")) == ("acme", "BOLT-1", 10)
    assert _record(_store(ctx, "bolt_enrich_plain")) == ("acme", "BOLT-1", 10)


def test_an_alias_of_an_alias_that_says_nothing_orders_the_same(ctx):
    assert _record(_store(ctx, "bolt_alias_alias")) == ("acme", "BOLT-1", 10)


def test_an_alias_states_a_vendor_and_an_sku_of_its_own(ctx):
    """The documented way to sell one piece of geometry through two vendors."""
    assert _record(_store(ctx, "bolt_from_other")) == ("other", "OTHER-1", 5)


def test_an_alias_of_an_alias_keeps_what_the_middle_one_declared(ctx):
    """The record travels down the chain, not only off the end of it."""
    assert _record(_store(ctx, "bolt_from_other_alias")) == ("other", "OTHER-1", 5)


def test_an_enrich_states_a_vendor_and_an_sku_of_its_own(ctx):
    assert _record(_store(ctx, "bolt_enrich")) == ("third", "THIRD-1", 3)


def test_an_enrich_of_an_enrich_keeps_what_the_middle_one_declared(ctx):
    assert _record(_store(ctx, "bolt_enrich_enrich")) == ("third", "THIRD-1", 3)


def test_a_mixed_chain_carries_it_too(ctx):
    """Aliases and enriches chain in any order, and so does what they declare."""
    assert _record(_store(ctx, "bolt_alias_of_enrich")) == ("third", "THIRD-1", 3)
    assert _record(_store(ctx, "bolt_enrich_of_alias")) == ("other", "OTHER-1", 5)


def test_an_enrich_reports_the_same_record_it_stores(ctx):
    """'config' and 'get_final_config()' are one answer, not two."""
    part = ctx._get_part(":bolt_enrich")
    asyncio.run(part.prepare_async())
    for config in (part.config, part.get_final_config()):
        assert (config["vendor"], config["sku"], config["count_per_sku"]) == ("third", "THIRD-1", 3)


def test_another_vendors_sku_does_not_inherit_this_ones_pack_size(ctx):
    """A bag of ten belongs to the SKU it was written for."""
    assert _record(_store(ctx, "bolt_from_other_single")) == ("other", "OTHER-2", 1)


def test_a_pack_size_alone_corrects_the_record_rather_than_replacing_it(ctx):
    """It names no thing to order, so what is ordered is still the source's."""
    assert _record(_store(ctx, "bolt_repacked")) == ("acme", "BOLT-1", 7)


#
# Assemblies
#


def _assembly_store(ctx, name):
    assembly = ctx._get_assembly(":" + name)
    assert assembly is not None, name
    return assembly.get_store_data()


def test_an_assembly_alias_states_a_record_of_its_own(ctx):
    assert _record(_assembly_store(ctx, "pair")) == ("acme", "PAIR-1", 1)
    assert _record(_assembly_store(ctx, "pair_from_other")) == ("other", "OTHER-PAIR-1", 2)


def test_an_assembly_alias_of_an_alias_keeps_it(ctx):
    assert _record(_assembly_store(ctx, "pair_from_other_alias")) == ("other", "OTHER-PAIR-1", 2)


#
# The rule itself
#


def test_a_declaration_that_states_none_of_the_three_is_handed_the_source_as_is():
    """Nearly every reference, so it must not cost a copy."""
    source = {"vendor": "acme", "sku": "BOLT-1", "count_per_sku": 10}
    assert resolve_store_properties(source, {"type": "alias"}) is source
    assert resolve_store_properties(source, None) is source


def test_a_key_written_as_nothing_states_nothing():
    """Half a record is worse than none, and the schema offers no such value."""
    source = {"vendor": "acme", "sku": "BOLT-1", "count_per_sku": 10}
    assert resolve_store_properties(source, {"vendor": None}) is source
    assert resolve_store_properties(source, {"vendor": None, "sku": None, "count_per_sku": None}) is source


def test_a_declared_record_never_mixes_with_the_one_it_replaces():
    source = {"name": "bolt", "vendor": "acme", "sku": "BOLT-1", "count_per_sku": 10}
    resolved = resolve_store_properties(source, {"vendor": "other"})
    assert resolved["vendor"] == "other"
    assert "sku" not in resolved and "count_per_sku" not in resolved
    # Everything that is not about buying it is left alone.
    assert resolved["name"] == "bolt"
    # And the source is not written to.
    assert source["vendor"] == "acme"
