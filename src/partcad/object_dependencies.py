#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which packages an object is built from: what 'has_dependencies' and 'has_private_dependencies' are about.

A package's ``dependencies:`` say what it *imports*; what an object *draws on*
is narrower and is the thing a requirement on that object can be about. It is
every package other than the object's own that holds something the object is
made of, followed all the way down:

    an alias or an enrich    the object it is of ('source_resolved');
    an assembly or a scene   every part, assembly and scene in it, and what
                             each of those draws on in turn;
    a part                   the colours, materials and finishes its faces and
                             solids are in, as recorded with its geometry (the
                             CMF summary the 'cmf' check and 'has_material'
                             read), so it is built to be asked;
    any of them              the interfaces it implements, and every one they
                             inherit;
    a scene                  the medium it is filled with.

What it does not count: PartCAD's own '//builtin' packages, which ship with
PartCAD and are part of it rather than something it depends on; and the files
an object's own package holds, which are the object itself. A Python script's
pip packages are not PartCAD packages either.

A dependency is *private* unless it is '//pub' or a package under it: the
public index, which anybody installing PartCAD can reach. So
'has_private_dependencies: false' says that whoever gets this object can get
everything it needs too -- which a package that is about to be published wants
to be true, and cannot see from its own 'partcad.yaml'.
"""

from __future__ import annotations

import typing

from . import reference, shape_envelope

PUBLIC = "//pub"
BUILTIN = "//builtin"

# The CMF components a part's summary records, and the key each set names it under.
_CMF = ("color", "material", "finish")


def _under(package: str, root: str) -> bool:
    return package == root or package.startswith(root + "/")


def is_public(package: str) -> bool:
    """Whether 'package' is the public index, '//pub', or a package under it."""
    return _under(package, PUBLIC)


def is_builtin(package: str) -> bool:
    """Whether 'package' is one of PartCAD's own, which nothing depends on: it is part of PartCAD."""
    return _under(package, BUILTIN)


class Dependencies:
    """The packages an object draws on, each with what of it is used and by what, in the order found."""

    def __init__(self, own: str):
        self.own = own
        # package -> ["<what> (<why>)", ...]
        self.packages: dict = {}
        # What could not be followed: an object that did not build, a reference
        # that named nothing. Not known is not "none".
        self.unknown: list = []

    def add(self, package: str, what: str) -> None:
        if not package or package == self.own or is_builtin(package):
            return
        uses = self.packages.setdefault(package, [])
        if what not in uses:
            uses.append(what)

    @property
    def private(self) -> dict:
        return {package: uses for package, uses in self.packages.items() if not is_public(package)}


def _package_of(ctx, owner: str, written: str) -> typing.Optional[str]:
    """The package a reference written in 'owner' names, or None for text that is no reference."""
    if not isinstance(written, str) or ":" not in written:
        # A colour named by its word ('red') or by its numbers names no package.
        return None
    project = ctx.get_project(owner) if ctx is not None else None
    resolved = project.normalize(written) if project is not None else written
    package, _ = reference.split(resolved)
    return package or owner


async def _object(ctx, kind: str, path: str):
    if kind == "part":
        return await ctx._get_part_async(path)
    if kind == "assembly":
        return ctx._get_assembly(path)
    if kind == "scene":
        return ctx._get_scene(path)
    if kind == "sketch":
        return ctx._get_sketch(path)
    return None


async def collect_async(ctx, shape) -> Dependencies:
    """The packages 'shape' draws on, through everything it is made of (see the module docstring)."""
    from .assembly import Assembly
    from .requirements import implemented_interfaces

    found = Dependencies(shape.project_name)
    seen: set = set()

    async def visit(obj, via: str) -> None:
        name = "%s:%s" % (obj.project_name, obj.name)
        key = (getattr(obj, "kind", ""), name)
        if key in seen:
            return
        seen.add(key)
        if obj is not shape:
            found.add(obj.project_name, "%s %s%s" % (getattr(obj, "kind", "object"), name, via))
        config = obj.config if isinstance(getattr(obj, "config", None), dict) else {}

        # What a reference is of: an alias or an enrich is the object it points at.
        source = config.get("source_resolved")
        if isinstance(source, str) and source:
            package, _ = reference.split(source)
            found.add(package, "%s %s (what %s is of)" % (getattr(obj, "kind", "object"), source, name))
            try:
                target = await _object(ctx, getattr(obj, "kind", ""), source)
            except Exception as e:  # pylint: disable=broad-except
                target, why = None, ": %s" % e
            else:
                why = ""
            if target is None:
                found.unknown.append("%s, what %s is of, could not be found%s" % (source, name, why))
            elif target is not obj:
                await visit(target, " (what %s is of)" % name)

        # The interfaces it implements, every level of the inheritance.
        try:
            from . import shape_ports

            await shape_ports.prepare_async(obj, ctx)
            interfaces = implemented_interfaces(obj)
        except Exception:  # pylint: disable=broad-except
            # An object with no ports to prepare implements nothing: an
            # interface it names and cannot have is the 'interfaces' check's to
            # report, not this one's.
            interfaces = {}
        for interface in interfaces:
            if ":" in interface:
                package, _ = reference.split(interface)
                found.add(package, "interface %s (implemented by %s)" % (interface, name))

        if isinstance(obj, Assembly):
            from .assembly_guide import resolve_alias

            target = resolve_alias(ctx, obj)
            medium = getattr(target, "medium_reference", None)
            if medium is not None:
                package = _package_of(ctx, target.project_name, medium)
                if package is not None:
                    found.add(package, "medium %s (of %s)" % (medium, name))
            try:
                await target.do_instantiate()
            except Exception as e:  # pylint: disable=broad-except
                found.unknown.append("%s could not be put together: %s" % (name, e))
                return
            for child in getattr(target, "children", None) or []:
                if child.item is not None:
                    await visit(child.item, " (in %s)" % name)
            return

        if getattr(obj, "kind", None) != "part":
            return
        # What its faces and solids are in, as recorded with its geometry.
        try:
            built = await obj.get_wrapped(ctx)
        except Exception as e:  # pylint: disable=broad-except
            built, why = None, ": %s" % e
        else:
            why = ""
        if built is None:
            found.unknown.append("%s did not build%s" % (name, why))
            return
        metadata = await obj.get_metadata_async(ctx) or {}
        summary = metadata.get(shape_envelope.METADATA_CMF) or {}
        for entry in summary.get("sets") or []:
            for component in _CMF:
                written = entry.get(component)
                package = _package_of(ctx, obj.project_name, written)
                if package is not None:
                    found.add(package, "%s %s (of %s)" % (component, written, name))

    await visit(shape, "")
    return found


def describe(packages: dict, limit: int = 3) -> str:
    """The packages, each with the first thing that uses it, and how many more there are."""
    items = ["%s: %s" % (package, uses[0]) for package, uses in packages.items()]
    shown = items[:limit] + (["and %d more" % (len(items) - limit)] if len(items) > limit else [])
    return "; ".join(shown)
