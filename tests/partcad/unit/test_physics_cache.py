#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a part weighs is cached, and goes stale exactly when it should.

Its volume, mass, centre of mass and inertia are one entry of the shape cache,
keyed on the part's own cache key and on what the derivation reads that the
part's key does not cover: the density, where it came from, and every stated
value that stands in for a derived one (see 'physics._derived_async()'). So an
edit to the CAD is a new entry, an edit to the material's density is a new
entry, a stated value is a new entry - and an edit that changes nothing about
the weight is a hit, which answers without measuring anything.

A part here is a stub with a key and a measurement, and the measurement counts
how often it is asked for: that count is what tells a hit from a miss. The
package around it is real, so that a material is looked up the way 'pc info'
looks one up, and the cache is a real file tier in a temporary directory.
"""

import asyncio

import pytest
from cache_config import CacheUserConfig

import partcad as pc
from partcad import physics
from partcad.cache_shape import ShapeCache
from partcad.shape import Shape

# What a 10 x 20 x 30 mm box measures as it is built.
BOX = {
    "volume": 6000.0,
    "centroid": [5.0, 10.0, 15.0],
    "unitInertia": [[650000.0, 0.0, 0.0], [0.0, 500000.0, 0.0], [0.0, 0.0, 250000.0]],
    "solids": 1,
}
# The same box made twice as long, which is what an edit to its CAD looks like
# from here: another key, and another measurement.
LONGER = {
    "volume": 12000.0,
    "centroid": [10.0, 10.0, 15.0],
    "unitInertia": [[1300000.0, 0.0, 0.0], [0.0, 1700000.0, 0.0], [0.0, 0.0, 900000.0]],
    "solids": 1,
}
VOLUME_M3 = 6e-6

PACKAGE = """\
materials:
  steel:
    desc: {desc}
    density: {density}
    mu: {mu}
"""


class _Block(Shape):
    """A part with nothing behind it but its key and what it measured."""

    def __init__(self, geometry="v1", measurements=BOX, properties=None):
        config = {"name": "block", "properties": properties or {"material": ":steel"}}
        super().__init__("//", config)
        self.name = "block"
        self.kind = "part"
        # What the key covers: the CAD, and nothing a derivation reads.
        self.hash.add_string(geometry)
        self._measured = measurements
        self.measured = 0

    async def get_measurements_async(self, ctx):
        self.measured += 1
        return dict(self._measured) if self._measured is not None else None


@pytest.fixture
def workspace(tmp_path):
    """A package that catalogues steel, and a cache tier to keep what it weighs in."""
    root = tmp_path / "package"
    root.mkdir()
    state = tmp_path / "state"

    def context(density=8000, desc="Mild steel", mu=0.6):
        (root / "partcad.yaml").write_text(PACKAGE.format(density=density, desc=desc, mu=mu), encoding="utf-8")
        ctx = pc.Context(str(root))
        ctx.cache_shapes = ShapeCache(user_config=CacheUserConfig(state))
        return ctx

    return context


def _weigh(ctx, block):
    return asyncio.run(physics.mass_properties_async(ctx, block))


def test_a_second_read_is_a_hit_and_measures_nothing(workspace):
    ctx = workspace()
    first = _weigh(ctx, _Block())

    block = _Block()
    second = _weigh(ctx, block)

    assert block.measured == 0
    assert second == first
    assert second["mass"]["value"] == pytest.approx(8000.0 * VOLUME_M3)
    assert second["volume"]["value"] == pytest.approx(6000.0)
    assert second["centerOfMass"]["value"] == pytest.approx([5.0, 10.0, 15.0])
    # The number on its own, for the IDE, out of the same entry.
    assert asyncio.run(physics.part_mass_async(ctx, block)) == pytest.approx(0.048)
    assert block.measured == 0


def test_an_edit_to_the_cad_is_a_new_entry(workspace):
    ctx = workspace()
    _weigh(ctx, _Block())

    edited = _Block(geometry="v2", measurements=LONGER)
    weighed = _weigh(ctx, edited)

    assert edited.measured == 1
    assert weighed["mass"]["value"] == pytest.approx(8000.0 * 12e-6)
    assert weighed["centerOfMass"]["value"] == pytest.approx([10.0, 10.0, 15.0])


def test_an_edit_to_the_material_s_density_is_a_new_entry(workspace):
    _weigh(workspace(density=8000), _Block())

    block = _Block()
    weighed = _weigh(workspace(density=7000), block)

    assert block.measured == 1
    assert weighed["mass"]["value"] == pytest.approx(7000.0 * VOLUME_M3)
    assert weighed["inertia"]["source"] == "derived: the solid at 7000 kg/m^3"


def test_an_edit_that_does_not_weigh_anything_is_still_a_hit(workspace):
    """The material's description and its friction are not what the part weighs."""
    _weigh(workspace(desc="Mild steel", mu=0.6), _Block())

    block = _Block()
    weighed = _weigh(workspace(desc="Plain carbon steel", mu=0.8), block)

    assert block.measured == 0
    assert weighed["mass"]["value"] == pytest.approx(8000.0 * VOLUME_M3)


def test_a_stated_value_wins_and_is_part_of_the_key(workspace):
    ctx = workspace()
    _weigh(ctx, _Block())

    stated = _Block(properties={"material": ":steel", "physics": {"mass": 0.5}})
    weighed = _weigh(ctx, stated)

    # A new entry, because a stated mass is a reason the derived one does not apply.
    assert stated.measured == 1
    assert weighed["mass"] == {"value": 0.5, "unit": "kg", "source": "stated"}
    assert weighed["inertia"]["source"] == "derived: the solid, scaled to the stated mass"
    assert weighed["inertia"]["value"]["izz"] == pytest.approx(0.5 / VOLUME_M3 * 250000.0 * 1e-15)

    # And a different statement is a different entry again.
    restated = _Block(properties={"material": ":steel", "physics": {"mass": 0.6}})
    assert _weigh(ctx, restated)["mass"]["value"] == 0.6
    assert restated.measured == 1


def test_an_export_reads_what_pc_info_wrote(workspace, monkeypatch):
    """One entry per part, whoever asks: an export of a tree holding the part reads it too.

    The leaf in the tree carries a measurement that disagrees with the cached
    one, so that what comes back can only have come from the cache.
    """
    ctx = workspace()
    block = _Block()
    _weigh(ctx, block)

    async def part(self, name):
        return block if name == "//:block" else None

    monkeypatch.setattr(physics._Materials, "part", part)
    leaf = {
        "name": "//:block",
        "label": "block",
        "brep": "AAAA",
        "properties": {"material": ":steel"},
        "metadata": {"measurements": {"volume": 1.0, "solids": 1}},
    }
    request = {"wrapped": {"name": "//:rig", "assembly": [leaf]}, "properties": True}

    facts = asyncio.run(physics.physics_by_shape_async(ctx, request, physics.export_fallback(request)))

    assert facts["//:block"]["mass"] == pytest.approx(8000.0 * VOLUME_M3)
    assert facts["//:block"]["centerOfMass"] == pytest.approx([5.0, 10.0, 15.0])
    assert block.measured == 1


def test_a_shape_that_measured_nothing_is_not_remembered_as_weightless(workspace):
    """A part that failed to build has no weight to remember - and might build next time."""
    ctx = workspace()
    _weigh(ctx, _Block(measurements=None))

    block = _Block()
    weighed = _weigh(ctx, block)

    assert block.measured == 1
    assert weighed["mass"]["value"] == pytest.approx(8000.0 * VOLUME_M3)
