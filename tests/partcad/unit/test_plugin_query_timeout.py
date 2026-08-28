#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The deadline a plugin script is given, and what happens when it blows it.

A plugin script is third-party code PartCAD waits for, and until this bound
existed it waited forever: 'pc list -r //pub' walked into the LDraw repository
plugin, which enumerates a category by fetching every part in it over HTTP, and
never came back. Six CI jobs were cancelled at the 60-minute mark with no
diagnostic at all.
"""

import asyncio
import subprocess
import sys
import time

import pytest

import partcad as pc
from partcad.plugin_factory_python import PluginFactoryPython, query_with_deadline
from partcad.plugin_repository import Repository
from partcad.runtime import communicate
from partcad_utils.user_config import UserConfig


def _plugin():
    """A plugin whose errors are collected rather than logged.

    'mute' keeps pc_logging.had_errors - the flag that becomes the CLI's exit
    code - out of the rest of the test session, and gives the assertions the
    messages to look at.
    """
    return Repository("ldraw", {"mute": True}, "//pub/universe/lego")


# ---- the configured bound ----------------------------------------------------


def test_the_deadline_defaults_to_five_minutes(monkeypatch):
    # Cleared rather than assumed absent: the option is environment-bound, and
    # a job that exports it to shorten the deadline would otherwise make this
    # assert whatever that job chose.
    monkeypatch.delenv("PC_PLUGIN_QUERY_TIMEOUT", raising=False)
    assert UserConfig().plugin_query_timeout == 300


def test_the_deadline_reads_the_environment(monkeypatch):
    monkeypatch.setenv("PC_PLUGIN_QUERY_TIMEOUT", "45")
    assert UserConfig().plugin_query_timeout == 45


def test_the_deadline_rejects_nonsense(monkeypatch):
    """A zero or negative value must not silently turn the bound back off."""
    monkeypatch.setenv("PC_PLUGIN_QUERY_TIMEOUT", "0")
    assert UserConfig().plugin_query_timeout == 300


def test_the_deadline_travels_to_the_daemon(monkeypatch):
    """The daemon does the work, so an option it never receives does nothing."""
    monkeypatch.delenv("PC_PLUGIN_QUERY_TIMEOUT", raising=False)
    assert "plugin.query.timeout" in UserConfig().to_dict()


# ---- what a blown deadline does ----------------------------------------------


def test_a_query_that_finishes_is_returned_untouched():
    plugin = _plugin()

    async def run():
        return (0, "answer", "")

    assert asyncio.run(query_with_deadline(plugin, run, 300)) == (0, "answer", "")
    assert plugin.deadline_exceeded is None
    assert plugin.errors == []


def test_a_blown_deadline_reads_as_no_answer():
    """The callers already treat None as 'this plugin has nothing to say'."""
    plugin = _plugin()

    async def run():
        raise asyncio.TimeoutError()

    assert asyncio.run(query_with_deadline(plugin, run, 300)) is None


def test_a_blown_deadline_is_reported_with_the_way_out():
    plugin = _plugin()

    async def run():
        raise asyncio.TimeoutError()

    asyncio.run(query_with_deadline(plugin, run, 300, "//pub/universe/lego:ldraw 'Brick/objects/part'"))

    assert len(plugin.errors) == 1
    message = plugin.errors[0]
    assert "Brick/objects/part" in message  # which package came out empty
    assert "300 seconds" in message
    assert "plugin.query.timeout" in message  # and how to wait longer


def test_a_plugin_that_blew_its_deadline_is_marked():
    """One runaway script has to cost one deadline, not one per key.

    A repository plugin serves a whole tree - LDraw's is 104 categories, each
    asked for three kinds of object - so retrying it would be the same wedge in
    slower motion: 312 queries at five minutes each is twenty-six hours.
    """
    plugin = _plugin()

    async def run():
        raise asyncio.TimeoutError()

    asyncio.run(query_with_deadline(plugin, run, 300))

    assert plugin.deadline_exceeded is not None


def test_a_marked_plugin_is_not_asked_again():
    """The refusal comes before anything is prepared, provisioned or spawned.

    Deliberately built without running the constructor: reaching any of the
    factory's own state would raise AttributeError here, which is what makes
    this assert that the query is refused up front rather than merely fast.
    """
    factory = object.__new__(PluginFactoryPython)
    factory.ctx = pc.Context("examples")
    plugin = _plugin()
    plugin.deadline_exceeded = "the plugin script did not answer within 300 seconds"

    result = asyncio.run(factory.query_script(plugin, "get", {"key": "Technic/objects/part"}))

    assert result is None


def test_a_refused_query_still_says_why():
    """Otherwise the next command against the same warm daemon would report a
    complete listing that quietly is not one."""
    factory = object.__new__(PluginFactoryPython)
    factory.ctx = pc.Context("examples")
    plugin = _plugin()
    plugin.deadline_exceeded = "skipped: the plugin script exceeded its 300 second deadline"

    asyncio.run(factory.query_script(plugin, "get", {"key": "Technic/objects/part"}))

    assert len(plugin.errors) == 1
    assert "Technic/objects/part" in plugin.errors[0]
    assert plugin.deadline_exceeded in plugin.errors[0]


def test_the_long_explanation_is_said_once():
    """A repository plugin serves hundreds of packages, and each of them has to
    report that it came out empty; repeating the whole paragraph that many times
    buries the one line that says what happened."""
    plugin = _plugin()

    async def run():
        raise asyncio.TimeoutError()

    asyncio.run(query_with_deadline(plugin, run, 300, "//pub/universe/lego:ldraw 'Brick/objects/part'"))

    assert "plugin.query.timeout" in plugin.errors[0]
    assert "plugin.query.timeout" not in plugin.deadline_exceeded


# ---- the subprocess the deadline has to reclaim ------------------------------


SLEEPER = [sys.executable, "-c", "import time; time.sleep(300)"]


async def _spawn():
    return await asyncio.create_subprocess_exec(
        *SLEEPER,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_communicate_bounds_the_wait():
    """Without this the caller waits on a sandbox interpreter that never
    finishes for as long as whatever is running it is allowed to run."""

    async def main():
        p = await _spawn()
        started = time.monotonic()
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await communicate(p, b"", timeout=0.5)
        await asyncio.wait_for(p.wait(), 10)
        return time.monotonic() - started

    assert asyncio.run(main()) < 30  # the child was told to sleep for 300


def test_communicate_kills_the_process_it_stops_waiting_for():
    """A timeout that leaves the interpreter running has moved the wedge, not
    removed it: nothing is left holding a reference to reap it."""

    async def main():
        p = await _spawn()
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await communicate(p, b"", timeout=0.5)
        # Reaped by the loop's child watcher once it has been killed.
        await asyncio.wait_for(p.wait(), 10)
        return p.returncode

    assert asyncio.run(main()) != 0


def test_a_cancelled_wait_kills_the_process_too():
    """Ctrl-C and a cancelled CI job take the same path as the deadline. This is
    where 'Terminate orphan process: pid (7107) (python)' came from."""

    async def main():
        p = await _spawn()
        task = asyncio.ensure_future(communicate(p, b"", timeout=None))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(p.wait(), 10)
        return p.returncode

    assert asyncio.run(main()) != 0


def test_communicate_without_a_deadline_still_returns_the_output():
    async def main():
        p = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "print('hello')",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = await communicate(p, b"")
        return stdout

    assert b"hello" in asyncio.run(main())
