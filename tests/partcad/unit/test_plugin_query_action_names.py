#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Each query a repository plugin is asked gets an action name of its own.

The ANSI progress display tracks running actions by name. A repository plugin
is asked for many keys at once -- a recursive listing gathers one 'get' per
sub-package and object kind -- and while every one of those was called just
'Get <package>:<plugin>', the first to finish removed the one entry they all
shared and each of the rest reported "action_key not found": 267 of them for
'pc list packages //pub/...' on a cold cache, and a failing exit status.
"""

import asyncio
import logging

import partcad as pc
from partcad import logging as pc_logging
from partcad.plugin_factory_python import PluginFactoryPython
from partcad.plugin_repository import Repository
from partcad_utils.logging_ansi_terminal import AnsiTerminalProgressHandler


def _refusing_factory_and_plugin():
    """A factory whose plugin is latched, so a query runs no script at all.

    The action is entered before the latch is checked, which is all this needs.
    """
    factory = object.__new__(PluginFactoryPython)
    factory.ctx = pc.Context("examples")
    plugin = Repository("ldraw", {"mute": True}, "//pub/universe/lego")
    plugin.mark_deadline_exceeded("skipped: the plugin script exceeded its 180 second deadline")
    return factory, plugin


def test_a_keyed_query_names_its_action_after_the_key(monkeypatch):
    started = []
    monkeypatch.setattr(pc_logging.ops, "action_start", lambda op, package, item=None: started.append((op, item)))
    monkeypatch.setattr(pc_logging.ops, "action_end", lambda op, package, item=None: None)
    factory, plugin = _refusing_factory_and_plugin()

    async def both():
        await asyncio.gather(
            factory.query_script(plugin, "get", {"key": "Technic/objects/part"}),
            factory.query_script(plugin, "get", {"key": "Duplo/objects/part"}),
        )

    asyncio.run(both())

    gets = [item for op, item in started if op == "Get"]
    assert len(gets) == 2
    assert len(set(gets)) == 2
    assert any("Technic/objects/part" in item for item in gets)


def test_overlapping_keyed_queries_leave_the_progress_display_consistent(monkeypatch):
    """Drive the real display with overlapping queries, as a listing does."""

    class _Sink:
        def write(self, _text):
            pass

        def flush(self):
            pass

    handler = AnsiTerminalProgressHandler(_Sink())
    reported = []
    monkeypatch.setattr(
        "partcad_utils.logging_ansi_terminal.error",
        lambda *args, **kwargs: reported.append(args),
    )
    starts, ends = [], []
    monkeypatch.setattr(
        pc_logging.ops, "action_start", lambda op, package, item=None: starts.append((op, package, item))
    )
    monkeypatch.setattr(pc_logging.ops, "action_end", lambda op, package, item=None: ends.append((op, package, item)))
    factory, plugin = _refusing_factory_and_plugin()

    async def both():
        await asyncio.gather(
            factory.query_script(plugin, "get", {"key": "Technic/objects/part"}),
            factory.query_script(plugin, "get", {"key": "Duplo/objects/part"}),
        )

    asyncio.run(both())

    def record(kind, op, package, item):
        rec = logging.LogRecord("partcad", logging.CRITICAL, "", 0, "", (), None)
        rec.pc_event, rec.op, rec.package, rec.item = kind, op, package, item
        return rec

    starts = [event for event in starts if event[0] == "Get"]
    ends = [event for event in ends if event[0] == "Get"]
    assert len(starts) == 2

    # Both start before either ends: the interleaving that used to collide.
    for event in starts:
        handler.emit(record("action_start", *event))
    for event in ends:
        handler.emit(record("action_end", *event))

    assert reported == []
    assert handler.actions.keys() == []
