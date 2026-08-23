#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-02-19
#
# Licensed under Apache License, Version 2.0.
#


# The object types this PartCAD used to support and deliberately removed, each
# mapped to the release that removed it.
#
# These are 'part' types, and only 'part' types. All four are the built-in
# generative-AI part types retired by #486 ("retire the built-in generative-AI
# functionality"), which deleted the 'part_factory_ai_*' modules together with
# their 'register()' calls - every one of which was a
# 'factory.register("part", ...)'. The public index is a separate repository and
# still declares them, as does every package published while they existed - so
# this is not something the user of such a package can correct. That is why
# naming one of these is a warning and the object is skipped, while any other
# unknown type stays an error (see 'Project.record_broken_object').
#
# Because the scope is 'part', 'instantiate' consults this only for that kind.
# The same name on a sketch, an assembly, a provider or a repository was never a
# type PartCAD had, so it is not a retirement and must not be forgiven as one -
# and calling it retired would name a release that never supported it. Should a
# non-part type ever be retired, this map has to grow a kind before that entry
# can be added to it.
#
# Nothing else belongs in here. A type that never existed, or a typo in the
# user's own package, must keep failing loudly.
RETIRED_TYPES = {
    "ai-build123d": "0.7.153",
    "ai-cadquery": "0.7.153",
    "ai-openscad": "0.7.153",
    "ai-sdf": "0.7.153",
}


class UnknownTypeException(Exception):
    """A declared object names a type this PartCAD has no factory for.

    Nothing can be done with such an object, but the package it lives in is
    otherwise fine, so this is per object and never fails a whole package.

    A type PartCAD used to have and dropped raises the 'RetiredTypeException'
    subclass below instead, which is reported more gently.
    """

    def __init__(self, kind: str, t: str, name=None, message: str = None):
        self.kind = kind
        self.type = t
        self.name = name
        if message is None:
            known = ", ".join(sorted(all[kind])) if kind in all else ""
            message = "unknown %s type '%s'%s. This PartCAD supports: %s" % (
                kind,
                t,
                "" if name is None else " for '%s'" % name,
                known,
            )
        super().__init__(message)


class RetiredTypeException(UnknownTypeException):
    """A declared object names a type this PartCAD removed on purpose.

    What separates it from a plain unknown type is whose problem it is. An
    unknown type is a broken declaration - a typo, or a package to fix. A
    retired type is a declaration that was correct when it was written, in a
    package the user most often only depends on and cannot edit; PartCAD is the
    side that changed. Reporting it as an error would make every command that
    merely walks such a package exit non-zero, with nothing to act on.
    """

    def __init__(self, kind: str, t: str, name=None):
        self.release = RETIRED_TYPES[t]
        super().__init__(
            kind,
            t,
            name,
            message="the %s type '%s'%s was retired in PartCAD %s; the object is skipped"
            % (kind, t, "" if name is None else " of '%s'" % name, self.release),
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
    #
    # Checked after the lookups above, not before them, so that a type which is
    # somehow registered again is served rather than reported as retired. Gated
    # on 'part' because that is what every retired type was: naming one of them
    # on any other kind is a broken declaration, not a retirement (see
    # 'RETIRED_TYPES').
    if kind == "part" and isinstance(t, str) and t in RETIRED_TYPES:
        raise RetiredTypeException(kind, t, config.get("name"))
    raise UnknownTypeException(kind, t, config.get("name"))
