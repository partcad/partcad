#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a reference and an assembly say a part is made of and weighs.

Two ways a part's 'properties:' - the material it is made of, a mass it states -
went missing on the way to a mass or a simulation:

* An alias reported only the 'properties:' written on the alias, and almost no
  alias writes any: a package that catalogues its purchased parts in one place
  and aliases them into its products had every one of them weigh nothing.
* An assembly's cache entry holds every part as it was read, properties
  included, and its key covered each part's content and not its properties - so
  a part changed from one material to another went on weighing what it used to
  inside every assembly already cached.

No CAD library and no sandbox: both are configuration and keys.
"""

import asyncio

import partcad as pc

_SOURCE = """
parts:
  block:
    type: step
    path: block.step
    properties:
      material: :steel
      color: "#808080"
      physics:
        mass: 0.375
        centerOfMass: [0, 0, 5]

materials:
  steel:
    density: 7850
"""

_ROOT = """
dependencies:
  sub:
    type: local
    path: sub

parts:
  plain:
    type: alias
    source: //sub:block
  recoloured:
    type: alias
    source: //sub:block
    properties:
      color: "#FF0000"
  moved:
    type: alias
    source: //sub:block
    offset: [[10, 0, 0], [0, 0, 1], 0]
  scaled:
    type: alias
    source: //sub:block
    scale: 2

assemblies:
  pair:
    type: assy
"""


def _package(tmp_path, material=":steel"):
    sub = tmp_path / "sub"
    sub.mkdir(exist_ok=True)
    (sub / "partcad.yaml").write_text(_SOURCE.replace("material: :steel", "material: %s" % material))
    # Only the bytes matter: nothing here is built, only read and keyed.
    (sub / "block.step").write_text("block\n")
    (tmp_path / "partcad.yaml").write_text(_ROOT)
    (tmp_path / "pair.assy").write_text("links:\n  - part: plain\n  - part: //sub:block\n")
    return tmp_path


def _properties(path, name):
    ctx = pc.Context(str(path))
    return ctx._get_part(":" + name)._shape_properties()


#
# An alias reports what it points at
#


def test_an_alias_reports_its_sources_material_and_mass(tmp_path):
    properties = _properties(_package(tmp_path), "plain")
    assert properties["physics"]["mass"] == 0.375
    assert properties["color"] == "#808080"


def test_an_inherited_material_is_named_in_the_package_that_wrote_it(tmp_path):
    """':steel' in the source's package is that package's steel, whoever points at the part."""
    assert _properties(_package(tmp_path), "plain")["material"] == "//sub:steel"


def test_what_an_alias_states_itself_wins(tmp_path):
    properties = _properties(_package(tmp_path), "recoloured")
    assert properties["color"] == "#FF0000"
    assert properties["physics"]["mass"] == 0.375


def test_a_moved_alias_does_not_inherit_a_centre_stated_for_the_unmoved_geometry(tmp_path):
    physics = _properties(_package(tmp_path), "moved")["physics"]
    assert physics == {"mass": 0.375}


def test_a_scaled_alias_does_not_inherit_the_mass_of_the_unscaled_geometry(tmp_path):
    """What is dropped is worked out again from the material, which the scale does not change."""
    properties = _properties(_package(tmp_path), "scaled")
    assert "physics" not in properties
    assert properties["material"] == "//sub:steel"


#
# An assembly is keyed on what its parts say about themselves
#


def _key(path):
    async def key():
        return await pc.Context(str(path))._get_assembly(":pair").get_cache_key_async()

    return asyncio.run(key())


def test_an_assembly_is_keyed_on_what_its_parts_are_made_of(tmp_path):
    steel = _key(_package(tmp_path))
    assert _key(_package(tmp_path)) == steel, "the same declaration is the same key"
    aluminium = _key(_package(tmp_path, material="//pub/std/manufacturing/material/metal:al-6061-t6"))
    assert aluminium != steel
