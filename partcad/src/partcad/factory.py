#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-02-19
#
# Licensed under Apache License, Version 2.0.
#


class UnknownTypeException(Exception):
    """A declared object names a type this PartCAD has no factory for.

    Most often a package written against an older PartCAD that used a feature
    since retired - the 'ai-cadquery'/'ai-build123d' part types, for instance.
    Nothing can be done with such an object, but the package it lives in is
    otherwise fine, so this is per object and never fails a whole package.
    """

    def __init__(self, kind: str, t: str, name=None):
        self.kind = kind
        self.type = t
        self.name = name
        known = ", ".join(sorted(all[kind])) if kind in all else ""
        super().__init__(
            "unknown %s type '%s'%s. This PartCAD supports: %s"
            % (kind, t, "" if name is None else " for '%s'" % name, known)
        )


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

    # An unknown type is a bad declaration, not a bad package: it is raised so
    # the caller records it against the one object and carries on with the rest.
    # It used to be logged here instead, which dropped the object silently and
    # printed the whole configuration - including the multi-page descriptions
    # the retired 'ai-*' types carry - into the log for every occurrence.
    raise UnknownTypeException(kind, t, config.get("name"))
