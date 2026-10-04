#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An assembly's 'timeout:', on the side of the package that declares it.

Two things read it. Whatever works on the assembly announces it, so that a
client waiting on the daemon waits that long instead of its default (see
'partcad_utils.timeouts'); and '--fast-only' leaves the assembly out (see
'partcad.fast_only'). Both are pinned here against a package of two
assemblies alike but for the one saying it is slow.

Nothing is built: the work an assembly would be put to is replaced by a
recording, and what is under test is which objects are handed to it and what is
said around it. So none of this needs a CAD sandbox.
"""

import asyncio
import logging

import pytest
from cache_config import CacheUserConfig

import partcad as pc
import partcad_utils.logging as pc_logging
import partcad_utils.logging_remote_server as remote_server
from partcad import fast_only
from partcad.cache_shape import ShapeCache
from partcad.shape import Shape

DATA = "tests/partcad/unit/data/fast_only"


@pytest.fixture
def ctx(tmp_path):
    context = pc.Context(DATA)
    context.cache_shapes = ShapeCache(user_config=CacheUserConfig(tmp_path / "state"))
    return context


@pytest.fixture
def markers():
    """The timeout windows the code under test opened, as a daemon forwards them."""
    saved = logging.getLogger("partcad").level
    events = []
    remote_server.init(events.append)
    try:
        yield lambda: [e for e in events if e["kind"] in ("timeout_start", "timeout_end")]
    finally:
        remote_server.fini()
        logging.getLogger("partcad").setLevel(saved)


def test_an_assembly_reads_its_timeout_from_its_declaration(ctx):
    assert ctx._get_assembly(":slow").timeout == 1800.0
    assert ctx._get_assembly(":quick").timeout is None


def test_a_part_has_no_timeout(ctx):
    assert ctx._get_part(":cube").timeout is None


def test_declaring_a_timeout_costs_an_assembly_nothing_in_the_cache(ctx):
    """How long building it may take is not what gets built."""
    quick = ctx._get_assembly(":quick")
    slow = ctx._get_assembly(":slow")

    assert asyncio.run(slow.get_cache_key_async()) == asyncio.run(quick.get_cache_key_async())


def test_working_on_an_assembly_opens_the_window_it_declares(ctx, markers):
    slow = ctx._get_assembly(":slow")

    async def work():
        async with slow.locked():
            # Re-entered, as building it inside an analysis is: one window, not two.
            async with slow.locked():
                pass

    asyncio.run(work())

    assert markers() == [
        {"kind": "timeout_start", "seconds": 1800.0, "package": "//", "item": "slow"},
        {"kind": "timeout_end", "seconds": 1800.0, "package": "//", "item": "slow"},
    ]


def test_working_on_one_that_declares_none_says_nothing(ctx, markers):
    quick = ctx._get_assembly(":quick")

    async def work():
        async with quick.locked():
            pass

    asyncio.run(work())

    assert markers() == []


def test_fast_only_leaves_out_what_declares_a_timeout_and_says_so(ctx, caplog):
    shapes = [ctx._get_part(":cube"), ctx._get_assembly(":quick"), ctx._get_assembly(":slow")]

    with caplog.at_level(logging.INFO, logger="partcad"):
        kept = fast_only.without_slow(shapes)

    assert [shape.name for shape in kept] == ["cube", "quick"]
    assert any("'//:slow'" in r.getMessage() and "timeout: 1800" in r.getMessage() for r in caplog.records)


def test_fast_only_reads_a_declaration_the_way_a_listing_does(ctx):
    project = ctx.get_project("//")

    assert fast_only.leaves_out_declared(project, "assembly", "slow", quiet=True)
    assert fast_only.leaves_out_declared(project, "assembly", "slow;gap=4.0", quiet=True)
    assert not fast_only.leaves_out_declared(project, "assembly", "quick", quiet=True)
    assert not fast_only.leaves_out_declared(project, "part", "cube", quiet=True)


def _record_renders(monkeypatch):
    rendered = []

    async def render_async(self, ctx, format_name, **kwargs):
        rendered.append(self.name)

    monkeypatch.setattr(Shape, "render_async", render_async)
    return rendered


def test_a_package_render_with_fast_only_passes_over_the_slow_assembly(ctx, monkeypatch):
    rendered = _record_renders(monkeypatch)

    asyncio.run(ctx.get_project("//").render_async(format="svg", fast_only=True))

    assert sorted(rendered) == ["cube", "quick"]


def test_a_package_render_without_it_renders_everything(ctx, monkeypatch):
    rendered = _record_renders(monkeypatch)

    asyncio.run(ctx.get_project("//").render_async(format="svg"))

    assert sorted(rendered) == ["cube", "quick", "slow"]


class _RecordingTest:
    """A check that records what it was asked to check, and passes."""

    name = "recording"

    def __init__(self):
        self.checked = []

    async def test_log_wrapper(self, tests, ctx, shape):
        self.checked.append(shape.name)
        return True


@pytest.mark.parametrize("fast, expected", [(True, ["cube", "quick"]), (False, ["cube", "quick", "slow"])])
def test_a_package_test_run_passes_over_the_slow_assembly_only_with_fast_only(ctx, fast, expected):
    check = _RecordingTest()

    assert asyncio.run(ctx.get_project("//").test_log_wrapper_async(ctx, [check], fast_only=fast))
    assert sorted(check.checked) == expected


def test_in_process_the_window_is_nothing():
    """No daemon, nobody waiting on one: the default ops do nothing at all."""
    with pc_logging.Timeout(1800.0, "//", "slow"):
        pass
