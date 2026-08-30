#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

from async_lru import alru_cache
import itertools
import typing

from . import logging as pc_logging

# Which command is running. A plugin that blows its deadline is not asked again
# (see Plugin.deadline_is_current), and this is what bounds that: the latch is
# stamped with the generation it was set in, and goes stale as soon as the next
# command begins.
#
# The bound is the command rather than the process because the two costs are not
# the same. Within one command the latch is what keeps a runaway script cheap: a
# recursive listing asks a repository plugin once per package per object kind --
# LDraw's 104 categories at three kinds each -- and paying the deadline for
# every one of those is the wedge it exists to prevent. Between commands it buys
# nothing, and it costs a great deal: the daemon keeps its contexts, and so the
# Plugin objects hanging off them, warm indefinitely (see
# partcad_service_json_rpc.core.session), so a latch that outlived its command
# would leave one transient timeout muting a plugin until the daemon was
# restarted -- with nothing in the message to say that is the remedy.
#
# A CLI process runs exactly one command and exits, so nothing there ever has to
# advance this. The daemon serves many, and does advance it -- once per
# JSON-RPC request, in partcad_service_json_rpc.rpc.methods.build_registry().
#
# One generation for the process, rather than one per thread or per asyncio
# context. The HTTP transport dispatches concurrently, so two commands in flight
# at once share the counter and each one's latch can be staled by the other
# starting. That is deliberate: it costs a re-query of a plugin that had already
# timed out -- the behaviour before the latch existed, and bounded by the
# deadline itself -- whereas the per-context alternatives can strand a latch on
# a worker thread that no later command advances, which is the failure this is
# here to remove. Erring towards asking again is the safe direction.
_command_generations = itertools.count(1)
_command_generation = 0


def begin_command() -> int:
    """Note that a new command is starting, staling every plugin's deadline latch."""
    global _command_generation
    # next() on an itertools.count is atomic, so concurrent requests cannot be
    # handed the same generation and read each other's latches as their own.
    _command_generation = next(_command_generations)
    return _command_generation


def command_generation() -> int:
    """The generation that a latch set right now would be stamped with."""
    return _command_generation


class Plugin:
    name: str
    desc: str
    config: dict[str, typing.Any] = None
    path: typing.Optional[str] = None
    url: typing.Optional[str] = None
    errors: list[str]
    caps: dict[str, typing.Any] = None
    # The reason a query to this plugin blew its deadline, and the command
    # generation it happened in; see plugin_factory_python.query_with_deadline.
    # For the rest of that command the plugin is not asked again, so one runaway
    # script costs one deadline and not one per key -- and the next command asks
    # it afresh, so a transient failure does not mute it for good.
    deadline_exceeded: typing.Optional[str] = None
    deadline_generation: typing.Optional[int] = None

    def __init__(self, name: str, config: dict[str, typing.Any] = {}, target_project_name=None):
        super().__init__()
        if target_project_name is None:
            self.name = name
            self.project_name = "."
        else:
            self.name = f"{target_project_name}:{name}"
            self.project_name = target_project_name
        self.config = config
        self.errors = []
        self.deadline_exceeded = None
        self.deadline_generation = None
        self.desc = config.get("desc", "")
        self.url = config.get("url", None)

        self.get_caps = alru_cache(maxsize=1, typed=True)(self.get_caps)

    def mark_deadline_exceeded(self, reason: str) -> None:
        """Stop asking this plugin, for the rest of the command now running."""
        self.deadline_exceeded = reason
        self.deadline_generation = command_generation()

    def deadline_is_current(self) -> bool:
        """Whether this plugin blew its deadline during the command now running.

        A latch from an earlier command is stale by design. It was one command's
        finding about one slow script -- often a network that was briefly
        unreachable -- and not a standing verdict on the plugin, so the next
        command asks it again rather than reporting an empty answer forever.
        """
        return self.deadline_exceeded is not None and self.deadline_generation == command_generation()

    def error(self, msg: str):
        mute = self.config.get("mute", False)
        if mute:
            self.errors.append(msg)
        else:
            pc_logging.error(msg)
