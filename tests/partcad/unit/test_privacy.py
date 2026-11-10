#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'private: true': an object its package keeps to itself (see 'partcad.privacy').

Two packages: '//kept', which declares private objects of every kind a reference
can name and builds on them itself, and the root, which tries to build on them
from outside. Every object here is a 'basic' shape - written, not built - so no
sandbox is involved: what is held is which lookups are refused, and how.
"""

import asyncio
import textwrap

import pytest

import partcad as pc
from partcad import privacy

KEPT = """
software:
  firmware:
    private: true
    path: firmware.bin
  tool: tool.sh

sketches:
  profile:
    type: basic
    private: true
    rectangle: {side-x: 10, side-y: 10}

parts:
  secret:
    type: basic
    private: true
    cuboid: [10, 10, 10]
    aliases: [hidden]
  sized:
    type: basic
    private: true
    cuboid: [10, 10, "%size%"]
    parameters:
      size: {type: float, default: 10.0}
  # Built on the private objects, in their own package: all allowed.
  own-alias:
    type: alias
    source: secret
  own-enrich:
    type: enrich
    source: sized
    with: {size: 20}
  own-extrusion:
    type: extrude
    sketch: profile
    depth: 5
  # The package publishing a private object under a public name of its own.
  published:
    type: alias
    source: secret
  board:
    type: basic
    cuboid: [10, 10, 1]
    software: [firmware]

assemblies:
  own-assembly:
    type: assy
    path: own-assembly.assy
"""

OWN_ASSEMBLY = """
links:
  - part: secret
    name: one
  - part: sized;size=30
    name: two
"""

ROOT = """
dependencies:
  kept:
    path: kept

parts:
  borrowed:
    type: alias
    source: //kept:secret
  borrowed-instance:
    type: enrich
    source: //kept:sized
    with: {size: 40}
  borrowed-extrusion:
    type: extrude
    sketch: //kept:profile
    depth: 5
  borrowed-published:
    type: alias
    source: //kept:published
  flashed:
    type: basic
    cuboid: [10, 10, 1]
    software: [//kept:firmware, //kept:tool]

assemblies:
  outside:
    type: assy
    path: outside.assy
"""

OUTSIDE = """
links:
  - part: //kept:secret
    name: one
"""


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    root = tmp_path_factory.mktemp("privacy")
    (root / "partcad.yaml").write_text(textwrap.dedent(ROOT).lstrip())
    (root / "outside.assy").write_text(textwrap.dedent(OUTSIDE).lstrip())
    kept = root / "kept"
    kept.mkdir()
    (kept / "partcad.yaml").write_text(textwrap.dedent(KEPT).lstrip())
    (kept / "own-assembly.assy").write_text(textwrap.dedent(OWN_ASSEMBLY).lstrip())
    (kept / "firmware.bin").write_bytes(b"\x00")
    (kept / "tool.sh").write_text("#!/bin/sh\n")
    return pc.Context(str(root))


def _refusal(kind, name, referrer="//"):
    return "%s '//kept:%s' is private to //kept, and a reference written in %s cannot name it" % (kind, name, referrer)


def test_only_a_real_true_makes_an_object_private():
    assert privacy.is_private({"private": True})
    assert not privacy.is_private({"private": "yes"})
    assert not privacy.is_private({})
    assert privacy.refusal("part", "//kept", "secret", None) is None
    assert privacy.refusal("part", "//kept", "secret", "//kept") is None
    assert privacy.refusal("part", "//kept", "secret", "//") == _refusal("A part", "secret")


def test_a_command_reaches_a_private_object_by_name(context):
    """Not a reference: what 'pc render //kept:secret' and the Explorer ask."""
    assert context.get_part("//kept:secret") is not None
    assert context.get_sketch("//kept:profile") is not None


def test_a_reference_from_another_package_is_refused_naming_why(context, caplog):
    assert context.get_part("//kept:secret", referrer="//") is None
    assert _refusal("A part", "secret") in caplog.text
    assert context.get_sketch("//kept:profile", referrer="//") is None
    assert _refusal("A sketch", "profile") in caplog.text
    assert context.get_assembly("//kept:own-assembly", referrer="//") is not None


def test_its_instances_and_its_other_names_are_as_private_as_it_is(context, caplog):
    assert context.get_part("//kept:sized;size=12", referrer="//") is None
    assert "//kept:sized;size=12' is private to //kept" in caplog.text
    assert context.get_part("//kept:hidden", referrer="//") is None


def test_its_own_package_builds_on_it(context):
    for name in ("own-alias", "own-enrich", "own-extrusion"):
        part = context.get_part("//kept:%s" % name)
        assert asyncio.run(part.get_wrapped(context)) is not None, name
        assert part.errors == [], (name, part.errors)
    assembly = context.get_assembly("//kept:own-assembly")
    assert asyncio.run(assembly.get_wrapped(context)) is not None
    assert assembly.errors == []


def test_another_package_cannot_alias_enrich_or_extrude_it(context, caplog):
    for name, refused in (
        ("borrowed", "secret"),
        ("borrowed-instance", "sized;size=40"),
    ):
        caplog.clear()
        part = context.get_part(name)
        with pytest.raises(Exception, match="is not found"):
            asyncio.run(part.get_wrapped(context))
        assert _refusal("A part", refused) in caplog.text, name

    caplog.clear()
    part = context.get_part("borrowed-extrusion")
    assert asyncio.run(part.get_wrapped(context)) is None
    assert _refusal("A sketch", "profile") in caplog.text


def test_another_package_cannot_place_it(context, caplog):
    assembly = context.get_assembly("outside")
    with pytest.raises(Exception):
        asyncio.run(assembly.get_wrapped(context))
    assert _refusal("A part", "secret") in caplog.text


def test_what_its_package_publishes_under_a_name_of_its_own_is_public(context):
    part = context.get_part("borrowed-published")
    assert asyncio.run(part.get_wrapped(context)) is not None
    assert part.errors == []


def _software(context, name):
    from partcad import software as pc_software
    from partcad.shape_config import final_config

    part = context.get_part(name)
    config = final_config(part)
    found = []
    for ref in pc_software.resolved_software_refs(part.project_name, config):
        _project, software = pc_software.lookup(context, ref, referrer=pc_software.referrer_of(config))
        found.append((ref, software is not None))
    return found


def test_software_another_package_keeps_to_itself_is_not_what_a_part_of_this_one_ships_with(context, caplog):
    """A part's 'software:' is a reference like any other, checked against the package that wrote it."""
    assert _software(context, "flashed") == [("//kept:firmware", False), ("//kept:tool", True)]
    assert "Software '//kept:firmware' is private to //kept, and a reference written in // cannot name it" in (
        caplog.text
    )
    # Its own package's part ships it, and so does a command naming it.
    assert _software(context, "//kept:board") == [("//kept:firmware", True)]
    assert context.get_project("//kept").get_software("firmware") is not None
