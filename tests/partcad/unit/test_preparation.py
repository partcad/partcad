#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A shape is prepared once, and nobody reads its key before that is over.

The flag that guarded preparation was raised before the work started, so a
second caller arriving while the first was still adding the keys of what the
shape is made of was told it was done, and read a partial key - logging 'Hash
update after being used' for every key added after that, and leaving the shape
with a key that depended on who got there first. See 'partcad.preparation'.
"""

import asyncio
import logging
import threading

import pytest

import partcad as pc
from partcad import preparation
from partcad.part import Part
from partcad.shape import Shape

# Long enough for any of these to finish many times over; a test that reaches it
# has hung, which is the failure it is there to report rather than wait out.
_HANG = 30


class _Shape:
    """As much of a shape as 'preparation.prepare' looks at."""

    def __init__(self):
        self._prepared = False


def _run(coroutine):
    return asyncio.run(asyncio.wait_for(coroutine, _HANG))


def test_concurrent_callers_wait_for_the_one_preparation():
    shape = _Shape()
    runs = []
    finished = []

    async def hook(s):
        runs.append(s)
        await asyncio.sleep(0.05)
        finished.append(s)

    async def caller():
        await preparation.prepare(shape, hook)
        # Nobody comes back before the preparation is over.
        assert finished == [shape]

    async def main():
        await asyncio.gather(*(caller() for _ in range(5)))

    _run(main())
    assert runs == [shape]
    assert shape._prepared


def test_a_preparation_that_reaches_its_own_shape_again_is_let_through():
    """A reference cycle: what the shape is made of links back to it."""
    shape = _Shape()
    inner = []

    async def hook(s):
        await preparation.prepare(s, hook)
        inner.append("returned")

    _run(preparation.prepare(shape, hook))
    assert inner == ["returned"]
    assert shape._prepared


def test_two_preparations_each_waiting_on_the_other_are_a_cycle_too():
    """'a' links 'b' and 'b' links 'a', and each is asked for by a caller of its own."""
    a, b = _Shape(), _Shape()

    async def hook_a(s):
        await asyncio.sleep(0.02)
        await preparation.prepare(b, hook_b)

    async def hook_b(s):
        await asyncio.sleep(0.02)
        await preparation.prepare(a, hook_a)

    async def main():
        await asyncio.gather(preparation.prepare(a, hook_a), preparation.prepare(b, hook_b))

    _run(main())
    assert a._prepared and b._prepared


def test_a_failed_preparation_is_run_again_by_the_caller_that_waited():
    shape = _Shape()
    runs = []

    async def hook(s):
        runs.append(len(runs))
        await asyncio.sleep(0.02)
        if len(runs) == 1:
            raise RuntimeError("the download failed")

    async def main():
        return await asyncio.gather(
            preparation.prepare(shape, hook), preparation.prepare(shape, hook), return_exceptions=True
        )

    results = _run(main())
    assert [type(r) for r in results] == [RuntimeError, type(None)]
    assert runs == [0, 1]
    assert shape._prepared


def test_callers_on_other_threads_wait_too():
    """The callers can be on different event loops: a part is built on a worker thread's loop."""
    shape = _Shape()
    runs = []
    seen = []

    async def hook(s):
        runs.append(threading.get_ident())
        await asyncio.sleep(0.05)

    def caller():
        _run(preparation.prepare(shape, hook))
        seen.append(len(runs))

    threads = [threading.Thread(target=caller) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(_HANG)
    assert len(runs) == 1
    assert seen == [1, 1, 1, 1]


# --------------------------------------------------------------------------- #
# The same, with a real assembly                                               #
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

    async def prepare_async(self):
        if isinstance(self, Part):
            await asyncio.sleep(0.001)
        return await original(self)

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
        await asyncio.gather(a.prepare_async(), b.prepare_async())
        return a, b

    a, b = _run(both())
    assert a._prepared and b._prepared


# --------------------------------------------------------------------------- #
# What a connected assembly is keyed on does not depend on what else is loaded  #
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
