#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What "pc render --with-ports" and "--with-interfaces" draw on top of a shape.

A port is a coordinate frame and an interface is a named set of them. Neither is
geometry, so neither appears in a rendered projection - which is exactly what
makes them hard to get right: a port ends up a millimetre off, or facing the
wrong way, and the only way to find out used to be to build an assembly and look
at where the parts landed.

These options put them on the picture instead. *Where* they are is not a
question about drawing and is not answered here: 'partcad.shape_ports' answers
it, for this and for everything else that asks. What is left here is the part
that is about drawing - which of the overlays a file type ends up carrying, the
port boundaries that travel to the renderer as geometry, and the log line that
repeats every name drawn on the picture at a size somebody can read.

An assembly is taken at its word by default: what is drawn is what it declares
and what its 'map:' externalizes, and not what is inside it. That is the same
boundary 'pc info' and a 'connect:' see, and an assembly that externalizes three
ports of the forty it contains means those three. '--with-internals' is for
looking inside one anyway, which is how a connection that went wrong is found -
two frames that should have met and did not.
"""

from . import logging as pc_logging
from . import output, shape_ports


class Overlay:
    """Which of the overlays a render was asked for.

    A single value rather than three booleans, because it travels the whole way
    from the command line through the context and the package down to the
    shape, and because "neither" - the overwhelmingly common case - is then one
    'None' rather than a set of falses.

    'internals' is not an overlay of its own: it says how deep the two above
    reach, and on its own it asks for nothing.
    """

    def __init__(self, ports: bool = False, interfaces: bool = False, internals: bool = False):
        self.ports = bool(ports)
        self.interfaces = bool(interfaces)
        self.internals = bool(internals)

    def __bool__(self):
        return self.ports or self.interfaces

    def __repr__(self):
        return "Overlay(ports=%r, interfaces=%r, internals=%r)" % (self.ports, self.interfaces, self.internals)

    @staticmethod
    def of(ports: bool = False, interfaces: bool = False, all: bool = False, internals: bool = False):
        """The overlay these flags ask for, or None if they ask for nothing."""
        overlay = Overlay(ports=ports or all, interfaces=interfaces or all, internals=internals)
        return overlay if overlay else None


def effective(overlay, impl):
    """Which overlay one output file ends up carrying, or None for none at all.

    Two things ask for it and neither overrides the other. "--with-ports" and
    "--with-interfaces" ask for it once, for this invocation. A package asks for
    it permanently, by declaring 'with_ports:'/'with_interfaces:' (and
    'with_internals:') on a file type of its own - which is how an example can
    keep a picture of its ports checked in beside the plain one, produced by the
    same 'pc render' as everything else.

    Only a 'render:' file type carries one. A projection is something to draw
    ports on; a STEP file is not, and every byte of a port boundary would travel
    to the sandbox for nothing.
    """
    if impl.section != output.RENDER:
        return None
    result = Overlay(
        ports=bool(impl.parameters.get("with_ports")) or (overlay is not None and overlay.ports),
        interfaces=bool(impl.parameters.get("with_interfaces")) or (overlay is not None and overlay.interfaces),
        internals=bool(impl.parameters.get("with_internals")) or (overlay is not None and overlay.internals),
    )
    return result if result else None


def _short(name: str) -> str:
    """An interface's name without the package it lives in.

    The full name goes in the log, where there is room for it. What goes beside
    the port on the picture is what a user writes in a 'connect:' - which, for
    an interface of the package being worked in, is the short name.
    """
    return shape_ports.short_interface_name(name)


async def collect_async(shape, ctx, overlay: Overlay) -> list:
    """Every port to be drawn, as the renderer is handed it.

    Each record names the port and the interface it belongs to as a user would
    have to name them in an ASSY file, and carries the port's placement. When
    the interfaces are to be drawn, it also carries the port's boundary sketch
    as a shape envelope, ready to be decoded and projected in the sandbox.
    """
    from .interface import place_components

    records = []
    for record in await shape_ports.ports_async(shape, ctx, deep=overlay.internals):
        drawn = {
            "port": record.name,
            "interface": record.interface,
            "interface_label": _short(record.interface),
            "instance": record.instance,
            "owner": record.owner,
            "location": record.location.as_packed(),
        }
        if overlay.interfaces and record.port.sketch is not None:
            # The port's boundary - the circle of a hole, the profile of a rail.
            # It stays a BREP envelope and is placed as plain data, exactly as
            # the viewer places it (see Interface.get_components).
            components = list(await record.port.sketch.get_components(ctx))
            drawn["sketch"] = place_components(components, record.location)
        records.append(drawn)
    return records


def report(shape, records: list, overlay: Overlay) -> None:
    """Say in the log what was drawn on the picture.

    The names on a projection are drawn small and there can be a lot of them, so
    the exact spelling of every one of them is repeated here, where it can be
    copied into an ASSY file.
    """
    asked_for = " and ".join(
        name for name, wanted in (("--with-ports", overlay.ports), ("--with-interfaces", overlay.interfaces)) if wanted
    )
    if not records:
        # Not the same fact for an assembly as for a part: an assembly full of
        # ports draws none of them until it says which of them are its own.
        from .assembly import Assembly

        if isinstance(shape, Assembly) and not overlay.internals:
            pc_logging.warning(
                "%s:%s: nothing to draw for %s: this assembly externalizes no ports of its own "
                "('map:'); '--with-internals' draws what is inside it" % (shape.project_name, shape.name, asked_for)
            )
        else:
            pc_logging.warning(
                "%s:%s: nothing to draw for %s: this object declares no ports"
                % (shape.project_name, shape.name, asked_for)
            )
        return

    lines = []
    for record in records:
        interface = record["interface"]
        if interface is None:
            lines.append("\t%s" % record["port"])
        elif record["instance"]:
            lines.append("\t%s\t(%s, instance %s)" % (record["port"], interface, record["instance"]))
        else:
            lines.append("\t%s\t(%s)" % (record["port"], interface))
    pc_logging.info(
        "%s:%s: %s: %d port(s) drawn on the projection:\n%s"
        % (shape.project_name, shape.name, asked_for, len(records), "\n".join(lines))
    )
