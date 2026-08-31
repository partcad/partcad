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

These two options put them on the picture instead. This module answers the
question the renderer cannot: *where are they*, in the coordinate system of the
thing being rendered. For a part that is a lookup ('implements:' already placed
every port). For an assembly it is a walk: each child contributes its own ports,
moved by where the assembly put the child, so a connection that went wrong is
visible as two frames that do not meet.

Everything here is plain Python arithmetic on 'geom.Location' plus the shape
envelopes the port sketches already come as, so the core stays free of OCP; the
drawing itself happens in the render implementation ('//builtin/render'), which
is the only side that knows where the camera is.
"""

from . import logging as pc_logging
from . import output
from .geom import Location


class Overlay:
    """Which of the two overlays a render was asked for.

    A single value rather than two booleans, because it travels the whole way
    from the command line through the context and the package down to the
    shape, and because "neither" - the overwhelmingly common case - is then one
    'None' rather than a pair of falses.
    """

    def __init__(self, ports: bool = False, interfaces: bool = False):
        self.ports = bool(ports)
        self.interfaces = bool(interfaces)

    def __bool__(self):
        return self.ports or self.interfaces

    def __repr__(self):
        return "Overlay(ports=%r, interfaces=%r)" % (self.ports, self.interfaces)

    @staticmethod
    def of(ports: bool = False, interfaces: bool = False, all: bool = False):
        """The overlay these flags ask for, or None if they ask for nothing."""
        overlay = Overlay(ports=ports or all, interfaces=interfaces or all)
        return overlay if overlay else None


def effective(overlay, impl):
    """Which overlay one output file ends up carrying, or None for none at all.

    Two things ask for it and neither overrides the other. "--with-ports" and
    "--with-interfaces" ask for it once, for this invocation. A package asks for
    it permanently, by declaring 'with_ports:' or 'with_interfaces:' on a file
    type of its own - which is how an example can keep a picture of its ports
    checked in beside the plain one, produced by the same 'pc render' as
    everything else.

    Only a 'render:' file type carries one. A projection is something to draw
    ports on; a STEP file is not, and every byte of a port boundary would travel
    to the sandbox for nothing.
    """
    if impl.section != output.RENDER:
        return None
    result = Overlay(
        ports=bool(impl.parameters.get("with_ports")) or (overlay is not None and overlay.ports),
        interfaces=bool(impl.parameters.get("with_interfaces")) or (overlay is not None and overlay.interfaces),
    )
    return result if result else None


def _interface_of_port(with_ports) -> dict:
    """port name -> (interface name, instance name), for one object's ports.

    'WithPorts.get_interfaces()' is keyed the other way round - interface, then
    instance, then the ports of that instance - and records an interface at
    every level of the inheritance it walks, most specific first. The first
    entry that claims a port is therefore the interface a user would name in a
    'connect:', which is the one worth drawing.
    """
    owner = {}
    for interface_name, instances in (with_ports.get_interfaces() or {}).items():
        for instance_name, ports in (instances or {}).items():
            for port_full_name in (ports or {}).values():
                owner.setdefault(port_full_name, (interface_name, instance_name))
    return owner


def _qualify(owner: str, name: str) -> str:
    """How a port of an assembly's child is named on the picture.

    The same way an ASSY file names it: the instance the port belongs to, then
    the port. The instance itself is a path when the assembly nests.
    """
    return ("%s:%s" % (owner, name)) if owner else name


def _short(name: str) -> str:
    """An interface's name without the package it lives in.

    The full name goes in the log, where there is room for it. What goes beside
    the port on the picture is what a user writes in a 'connect:' - which, for
    an interface of the package being worked in, is the short name.
    """
    return name.rsplit(":", 1)[-1] if name else name


async def _collect_object(shape, ctx, owner: str, placement: Location, sketches: bool, out: list):
    """The ports 'shape' declares itself, placed by 'placement'."""
    from .interface import _port_location, place_components

    with_ports = getattr(shape, "with_ports", None)
    if with_ports is None:
        return

    interfaces = _interface_of_port(with_ports)
    for port_name, port in with_ports.get_ports().items():
        location = placement * _port_location(port)
        interface_name, instance_name = interfaces.get(port_name, (None, None))
        record = {
            "port": _qualify(owner, port_name),
            "interface": interface_name,
            "interface_label": _short(interface_name),
            "instance": instance_name,
            "owner": owner,
            "location": location.as_packed(),
        }
        if sketches and port.sketch is not None:
            # The port's boundary - the circle of a hole, the profile of a rail.
            # It stays a BREP envelope and is placed as plain data, exactly as
            # the viewer places it (see Interface.get_components).
            components = list(await port.sketch.get_components(ctx))
            record["sketch"] = place_components(components, location)
        out.append(record)


def _child_owner(owner: str, child) -> str:
    """The instance path of one child of an assembly.

    An ASSY file's 'links:' becomes an assembly of its own inside the object the
    file defines, and so does every nested 'links:' - assemblies that are no
    object of any package and that nobody names in a 'connect:'. They are passed
    over here for exactly the reason 'Assembly.connected_children()' passes over
    them: what they hold belongs to the assembly that embeds them.
    """
    item = child.item
    if getattr(item, "config", {}).get("child", False):
        return owner
    name = child.name if child.name is not None else getattr(item, "name", None)
    return _qualify(owner, name) if name else owner


async def _collect(shape, ctx, owner: str, placement: Location, sketches: bool, out: list):
    """'shape' and, if it is an assembly, everything inside it."""
    from .assembly import Assembly

    if isinstance(shape, Assembly):
        # An assembly's own placement is carried on the envelope it renders as,
        # so the geometry moves by it and the ports have to move with it.
        root = shape._root_location()
        if root is not None:
            placement = placement * root
        await shape.do_instantiate()

    await _collect_object(shape, ctx, owner, placement, sketches, out)

    if not isinstance(shape, Assembly):
        return
    for child in shape.children:
        child_placement = placement
        if child.location is not None:
            child_placement = placement * (
                child.location if isinstance(child.location, Location) else Location(child.location)
            )
        await _collect(child.item, ctx, _child_owner(owner, child), child_placement, sketches, out)


async def collect_async(shape, ctx, overlay: Overlay) -> list:
    """Every port of 'shape', in the coordinate system 'shape' renders in.

    Each record names the port and the interface it belongs to as a user would
    have to name them in an ASSY file, and carries the port's placement. When
    the interfaces are to be drawn, it also carries the port's boundary sketch
    as a shape envelope, ready to be decoded and projected in the sandbox.
    """
    records = []
    await _collect(shape, ctx, "", Location(), overlay.interfaces, records)
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
