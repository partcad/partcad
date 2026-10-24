#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an assembly is keyed on: the same whoever asks, whenever, and whatever else is loaded.

Read while a preparation begun elsewhere is under way, a key is a different key
for good (see 'Shape.prepare_async'); and a connected assembly's key used to
take in every mate the context had registered, which grew with whatever had
been built before it. 'Hash update after being used' in the log of a
recursive render was the first; the castle of the LEGO examples keying
differently according to whether the car had been built first was the second.
"""

import asyncio
import logging

import pytest

import partcad as pc
from partcad.part import Part
from partcad.shape import Shape

# Long enough for any of these to finish many times over; a test that reaches it
# has hung, which is the failure it is there to report rather than wait out.
_HANG = 30


def _run(coroutine):
    return asyncio.run(asyncio.wait_for(coroutine, _HANG))


# --------------------------------------------------------------------------- #
# Asked for by several callers at once                                        #
# --------------------------------------------------------------------------- #

_PARTS = 12

_CONFIG = """
parts:
%s
assemblies:
  assembly:
    type: assy
  outer:
    type: assy
  moved:
    type: alias
    source: :assembly
    offset: [[1, 0, 0], [0, 0, 1], 0]
"""


@pytest.fixture
def package(tmp_path):
    parts = "".join("  p%d:\n    type: step\n    path: p%d.step\n" % (i, i) for i in range(_PARTS))
    (tmp_path / "partcad.yaml").write_text(_CONFIG % parts)
    (tmp_path / "assembly.assy").write_text("links:\n" + "".join("  - part: p%d\n" % i for i in range(_PARTS)))
    (tmp_path / "outer.assy").write_text("links:\n  - assembly: assembly\n  - part: p0\n")
    # Only the bytes matter here: nothing is built, only keyed.
    for i in range(_PARTS):
        (tmp_path / ("p%d.step" % i)).write_text("p%d\n" % i)
    return tmp_path


@pytest.fixture
def parts_yield(monkeypatch):
    """Parts that wait on something while they are prepared, as a plugin's parts do.

    A part served by a repository plugin asks its sandbox while it is prepared,
    which hands the event loop to whatever else is running; a part read from a
    local file does not, and with nothing ever yielding nothing could interleave.
    """
    original = Shape.prepare_async

    async def prepare_async(self, wait=False):
        if isinstance(self, Part):
            await asyncio.sleep(0.001)
        return await original(self, wait=wait)

    monkeypatch.setattr(Shape, "prepare_async", prepare_async)


def _keys_alone(path):
    async def collect():
        ctx = pc.Context(str(path))
        return {
            name: await ctx._get_assembly(":" + name).get_cache_key_async() for name in ("assembly", "outer", "moved")
        }

    return asyncio.run(collect())


def test_an_assembly_asked_for_its_key_by_several_callers_at_once_has_one_key(package, parts_yield, caplog):
    alone = _keys_alone(package)

    async def together():
        ctx = pc.Context(str(package))
        assembly = ctx._get_assembly(":assembly")
        # Two callers of the assembly itself, one that is made of it, and one
        # that moves it: each reads the assembly's key while the others are
        # still preparing it.
        keys = await asyncio.gather(
            assembly.get_cache_key_async(),
            assembly.get_cache_key_async(),
            ctx._get_assembly(":outer").get_cache_key_async(),
            ctx._get_assembly(":moved").get_cache_key_async(),
        )
        return keys, await assembly.get_cache_key_async()

    with caplog.at_level(logging.WARNING, logger="partcad"):
        (first, second, outer, moved), after = _run(together())

    assert not [r for r in caplog.records if "Hash update after being used" in r.getMessage()]
    assert first == second == after == alone["assembly"]
    assert outer == alone["outer"]
    assert moved == alone["moved"]


def test_assemblies_that_link_each_other_are_prepared_without_waiting_forever(tmp_path, parts_yield):
    (tmp_path / "partcad.yaml").write_text(
        "parts:\n  p:\n    type: step\n    path: p.step\n" "assemblies:\n  a:\n    type: assy\n  b:\n    type: assy\n"
    )
    (tmp_path / "p.step").write_text("p\n")
    (tmp_path / "a.assy").write_text("links:\n  - part: p\n  - assembly: b\n")
    (tmp_path / "b.assy").write_text("links:\n  - part: p\n  - assembly: a\n")

    async def both():
        ctx = pc.Context(str(tmp_path))
        a, b = ctx._get_assembly(":a"), ctx._get_assembly(":b")
        # Each waits for the other's preparation, which is waiting for it: a
        # cycle, refused rather than waited for, so neither has a key.
        return await asyncio.gather(a.get_cache_key_async(), b.get_cache_key_async())

    assert _run(both()) == [None, None]


# --------------------------------------------------------------------------- #
# A connected assembly's key does not depend on what else is loaded           #
# --------------------------------------------------------------------------- #

# A base with a bore and an arm with a pin, connected; and an interface nothing
# here implements, 'axle', which declares that it mates the bore too. Declaring
# it registers the mate in both directions, so the bore's mates include it once
# anything has instantiated 'axle' - and nothing in 'rig' ever does. The interfaces
# are a dependency's, as they are for the LEGO models (whose castle has no axle
# and whose car has): an interface is instantiated the first time something
# asks for its ports.
_INTERFACES = """
interfaces:
  bore:
    ports:
      hole:
  pin:
    ports:
      tip: [[0, 0, 0], [0, 0, 1], 0]
    mates:
      bore: {}
  axle:
    ports:
      end:
    mates:
      bore:
        motion: fixed
%s
"""

_CONNECTED = """
dependencies:
  lib:
    type: local
    path: lib
parts:
  base:
    type: stl
    path: cube.stl
    implements:
      //lib:bore:
        top: [[0, 0, 10], [0, 0, 1], 0]
  arm:
    type: stl
    path: cube.stl
    implements:
      //lib:pin:
assemblies:
  rig:
    type: assy
"""

_RIG = """
links:
  - part: base
  - part: arm
    connect:
      name: base
      with: //lib:pin
      to: //lib:bore
"""


def _connected(root, mates=""):
    (root / "lib").mkdir(parents=True, exist_ok=True)
    (root / "lib" / "partcad.yaml").write_text(_INTERFACES % mates)
    (root / "partcad.yaml").write_text(_CONNECTED)
    (root / "rig.assy").write_text(_RIG)
    (root / "cube.stl").write_text("solid cube\nendsolid cube\n")
    return root


def _rig_key(root, first=()):
    """The key of 'rig', from a context that has instantiated the interfaces 'first' before it.

    Instantiated, as building something that implements one does: that is what
    registers the mates an interface declares.
    """

    async def key():
        ctx = pc.Context(str(root))
        for name in first:
            ctx.get_interface(name).get_ports()
        return await ctx._get_assembly(":rig").get_cache_key_async()

    return asyncio.run(key())


def test_a_mate_with_an_interface_nothing_here_implements_is_not_in_the_key(tmp_path):
    root = _connected(tmp_path / "pkg")
    assert _rig_key(root) == _rig_key(root, first=["//lib:axle"])


def test_a_mate_between_interfaces_implemented_here_is_in_the_key(tmp_path):
    """Declared by neither of them - by the package, in a 'mates:' of its own - and still the rig's."""
    plain = _rig_key(_connected(tmp_path / "plain"))
    fixed = _rig_key(_connected(tmp_path / "fixed", "mates:\n  bore:\n    pin:\n      motion: fixed\n"))
    assert plain is not None and fixed is not None
    assert plain != fixed


# The bore the base implements is an 'm4-bore', a drop-in for 'bore', and
# 'bore' declares that it mates the pin. A connection is worked out across what
# each side is a drop-in for, so that mate places the arm, and changing it has
# to move the key - though neither interface the rig's links implement says a
# word about it.
_INHERITED = """
interfaces:
  bore:
    ports:
      hole:
    mates:
      pin:%s
  m4-bore:
    inherits: bore
  pin:
    ports:
      tip: [[0, 0, 0], [0, 0, 1], 0]
"""

_INHERITED_CONNECTED = _CONNECTED.replace("//lib:bore:", "//lib:m4-bore:")
_INHERITED_RIG = _RIG.replace("to: //lib:bore", "to: //lib:m4-bore")


def _inherited(root, mating):
    (root / "lib").mkdir(parents=True, exist_ok=True)
    (root / "lib" / "partcad.yaml").write_text(_INHERITED % mating)
    (root / "partcad.yaml").write_text(_INHERITED_CONNECTED)
    (root / "rig.assy").write_text(_INHERITED_RIG)
    (root / "cube.stl").write_text("solid cube\nendsolid cube\n")
    return root


def test_a_mate_with_an_interface_an_implemented_one_is_a_drop_in_for_is_in_the_key(tmp_path):
    plain = _rig_key(_inherited(tmp_path / "plain", " {}"))
    fixed = _rig_key(_inherited(tmp_path / "fixed", "\n        motion: fixed"))
    assert plain is not None and fixed is not None
    assert plain != fixed


# Both ends are drop-ins this time: the base implements an 'm4-bore' and the
# arm an 'm4-pin'. The mating 'pin' declares with 'm4-bore' is in the rig's key,
# though no interface the links implement mentions it: a key keeping one mating
# per target lost it at both ends at once, to 'bore' with 'pin' at the base and
# to 'm4-pin' with 'm4-bore' at the arm.
_CROSSED = """
interfaces:
  bore:
    ports:
      hole:
    mates:
      pin: {}
      m4-pin: {}
  m4-bore:
    inherits: bore
    mates:
      m4-pin: {}
  pin:
    ports:
      tip: [[0, 0, 0], [0, 0, 1], 0]
    mates:
      m4-bore:%s
  m4-pin:
    inherits: pin
"""


def _crossed(root, mating):
    _inherited(root, "")
    (root / "lib" / "partcad.yaml").write_text(_CROSSED % mating)
    (root / "partcad.yaml").write_text(_INHERITED_CONNECTED.replace("//lib:pin:", "//lib:m4-pin:"))
    (root / "rig.assy").write_text(_INHERITED_RIG.replace("with: //lib:pin", "with: //lib:m4-pin"))
    return root


def test_every_mating_between_drop_ins_and_their_ancestors_is_in_the_key(tmp_path):
    plain = _rig_key(_crossed(tmp_path / "plain", " {}"))
    fixed = _rig_key(_crossed(tmp_path / "fixed", "\n        motion: fixed"))
    assert plain is not None and fixed is not None
    assert plain != fixed
