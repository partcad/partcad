#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an 'alias' or an 'enrich' says about the loads the object it points at carries.

A part's analysis sections ('fea:' and the rest) are its boundary conditions,
and the loads a bought part carries are a fact about the product it is used in
rather than about the part: one gear, two gearboxes, two loads. So a reference
may state them, and its own replace what the source states; one that states
none analyses as its source does. Nothing else changes -- the geometry and the
ports the conditions land on are still the source's.
"""

import asyncio
import textwrap

import pytest

import partcad as pc
from partcad import cae

PACKAGE = textwrap.dedent("""
    name: //reference-analysis
    parts:
      gear:
        type: step
        path: gear.step
        parameters:
          teeth:
            type: int
            default: 28
        fea:
          fix: [hub]
          load:
            tooth: 1 kg
      gear-in-the-arm:
        type: alias
        source: :gear
        desc: The gear, as the arm loads it
        fea:
          fix: [hub]
          load:
            tooth:
              "21": [0 N, -146 N, 12 N]
          gravity: [0, 0, 9.81]
      gear-as-bought:
        type: alias
        source: :gear
      gear-alias-of-the-arm:
        type: alias
        source: :gear-in-the-arm
      gear-enriched:
        type: enrich
        source: :gear
        with:
          teeth: 30
        thermal:
          heat:
            tooth: 2 W
    """)


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    (tmp_path / "gear.step").write_text("")
    return pc.Context(str(tmp_path))


def _config(ctx, name, analysis):
    part = ctx._get_part(":" + name)
    assert part is not None, name
    asyncio.run(part.prepare_async())
    return cae.config_of(part, analysis)


def test_a_reference_states_the_loads_its_product_puts_on_the_part(ctx):
    config = _config(ctx, "gear-in-the-arm", cae.FEA)
    assert config.loads == {"tooth": {"21": pytest.approx([0.0, -146.0, 12.0])}}
    assert config.gravity == pytest.approx([0.0, 0.0, 9.81])
    # The source's own are untouched.
    assert _config(ctx, "gear", cae.FEA).loads == {"tooth": {cae.EVERY_INSTANCE: pytest.approx(cae.GRAVITY)}}


def test_a_reference_that_states_none_analyses_as_its_source_does(ctx):
    assert _config(ctx, "gear-as-bought", cae.FEA).loads == _config(ctx, "gear", cae.FEA).loads


def test_what_a_reference_in_the_middle_states_travels_down_the_chain(ctx):
    assert _config(ctx, "gear-alias-of-the-arm", cae.FEA).gravity == pytest.approx([0.0, 0.0, 9.81])


def test_an_enrich_states_an_analysis_of_its_own_beside_the_ones_it_inherits(ctx):
    assert _config(ctx, "gear-enriched", cae.THERMAL).conditions["heat"] == {
        "tooth": {cae.EVERY_INSTANCE: pytest.approx(2.0)}
    }
    # Each section on its own: a thermal one stated says nothing about stress.
    assert _config(ctx, "gear-enriched", cae.FEA).loads == _config(ctx, "gear", cae.FEA).loads
