#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-02-19
#
# Licensed under Apache License, Version 2.0.
#

from . import logging as pc_logging


class Factory:
    def __init__(self) -> None:
        pass


all = {
    "assembly": {},
    "part": {},
    "file": {},
    "provider": {},
    "repository": {},
    "sketch": {},
}


def register(kind: str, t: str, factory_class: Factory.__class__):
    all[kind][t] = factory_class


def instantiate(kind: str, t: str, ctx, source_project, target_project, config):
    # A part 'type' that starts with ':' is a short reference to a partType
    # declared in the part's own package. Expand it to the fully-qualified
    # '<package path>:<name>' and store it back so the config carries the
    # resolved reference from here on (see the "partTypes" documentation).
    if kind == "part" and isinstance(t, str) and t.startswith(":"):
        t = target_project.name + t
        config["type"] = t

    if t in all[kind]:
        # The return value is not always used
        return all[kind][t](ctx, source_project, target_project, config)

    # A part 'type' that carries a package path ('<package>:<name>') is not a
    # built-in factory but a reference to a partType. It is constructed by the
    # generic wrapper factory, which resolves the partType and runs it.
    if kind == "part" and isinstance(t, str) and ":" in t and "wrapper" in all[kind]:
        return all[kind]["wrapper"](ctx, source_project, target_project, config)

    pc_logging.error("Invalid %s type encountered: %s" % (kind, config))
