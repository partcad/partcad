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

Beside them, the callouts: what the IDE's 3D and 2D tabs call "Component names",
"Component prices", "Port names" and "Interface names", and what "pc render
--with-component-names", "--with-component-prices", "--without-port-names" and
"--without-interface-names" ask for. A component is a node of the tree that
holds no other node - a part, wherever it is placed - and its callout is one box
with a row for its name and a row for its price, pinned to the middle of it.
The names of the ports and the interfaces are on by default, because they are
what the two overlays above have always written beside what they draw; the two
switches take them off a picture that has too many of them to read. None of the
four draws anything of its own accord about ports: a port's name is written
only where the port is drawn.

A price is not something a package declares. It is what the market answers, so
it is the daemon's to work out - the very quote the IDE's Buy tab shows, shared
out over the components (see 'component_prices' in the JSON-RPC service) - and
it reaches a render as a source of prices the overlay carries ('Overlay.prices'),
asked once per object rendered and only when a picture is to show them.
"""

from . import logging as pc_logging
from . import output, shape_ports

# What the callout switches are called in the request a renderer is handed (see
# 'Shape._output_request'): whether every component gets a callout with its
# name; the text of each component's price, by the full name of the object it
# is; and whether the ports' and the interfaces' names are written, which is
# said only when they are not.
COMPONENT_NAMES_KEY = "component_names"
COMPONENT_PRICES_KEY = "component_prices"
PORT_NAMES_KEY = "port_names"
INTERFACE_NAMES_KEY = "interface_names"


class Overlay:
    """Which of the overlays a render was asked for, and of which ports.

    A single value rather than three booleans, because it travels the whole way
    from the command line through the context and the package down to the
    shape, and because "neither" - the overwhelmingly common case - is then one
    'None' rather than a set of falses.

    'internals' is not an overlay of its own: it says how deep the two above
    reach, and on its own it asks for nothing.

    'select' narrows *which* ports are drawn, by the name each is reported
    under: the port's own name for a port of the object, and the node path
    then the port for one inside it ('shape_ports.qualify'), which is exactly
    the name this module writes into the log beside every port it draws. None
    means all of them, which is what a plain '--with-ports' asks for; a set
    means those and no others, which is what the panel beside the IDE's 2D tab
    asks for and what 'pc render --port' spells on the command line.

    'component_names' and 'component_prices' ask for a callout on every
    component (see the module's docstring), with a row for each of the two
    asked for. 'port_names' and 'interface_names' say whether the two overlays
    above write their names; both are on unless somebody switched them off,
    and neither draws anything on its own.

    'prices' is where the prices come from: an async callable taking the
    context and the shape being rendered and answering, by the full name of
    each object ('<package>:<name>'), '{"price": <number>, "currency": <code
    or None>}' for the ones it has a price for. The daemon gives one (it is
    what asks the suppliers); nothing else does, and an overlay without one
    draws no prices and says so.
    """

    def __init__(
        self,
        ports: bool = False,
        interfaces: bool = False,
        internals: bool = False,
        select=None,
        component_names: bool = False,
        component_prices: bool = False,
        port_names: bool = True,
        interface_names: bool = True,
        prices=None,
    ):
        self.ports = bool(ports)
        self.interfaces = bool(interfaces)
        self.internals = bool(internals)
        self.select = None if select is None else frozenset(select)
        self.component_names = bool(component_names)
        self.component_prices = bool(component_prices)
        self.port_names = bool(port_names)
        self.interface_names = bool(interface_names)
        self.prices = prices

    def __bool__(self):
        """Whether it asks for anything to be drawn on the picture."""
        return self.ports or self.interfaces or self.components

    @property
    def components(self) -> bool:
        """Whether a callout is drawn on every component, whatever it says."""
        return self.component_names or self.component_prices

    def __repr__(self):
        return (
            "Overlay(ports=%r, interfaces=%r, internals=%r, select=%r, component_names=%r, "
            "component_prices=%r, port_names=%r, interface_names=%r)"
            % (
                self.ports,
                self.interfaces,
                self.internals,
                None if self.select is None else sorted(self.select),
                self.component_names,
                self.component_prices,
                self.port_names,
                self.interface_names,
            )
        )

    def key(self):
        """What makes two overlays ask for the same thing, for a cache to hash."""
        return (self.interfaces, self.internals, None if self.select is None else tuple(sorted(self.select)))

    def draws(self, name: str) -> bool:
        """Whether the port reported under ``name`` is one of the ones asked for."""
        return self.select is None or name in self.select

    @staticmethod
    def of(
        ports: bool = False,
        interfaces: bool = False,
        all: bool = False,
        internals: bool = False,
        select=None,
        component_names: bool = False,
        component_prices: bool = False,
        port_names: bool = True,
        interface_names: bool = True,
        prices=None,
    ):
        """The overlay these flags ask for, or None if they ask for nothing.

        A selection on its own asks for nothing: it says *which* ports, not that
        there are any to draw, so naming ports without naming an overlay draws
        the picture it would have drawn anyway. The two IDE tabs and the command
        line both send the flags beside the names for that reason.

        A name switched off is not nothing, although it draws nothing: it is
        kept, in an overlay that is false, so that it reaches a file type that
        declares 'with_ports:' of its own (see 'effective'). 'prices' alone is
        nothing - it says where prices would come from, not that any are drawn.
        """
        overlay = Overlay(
            ports=ports or all,
            interfaces=interfaces or all,
            internals=internals,
            select=select,
            component_names=component_names,
            component_prices=component_prices,
            port_names=port_names,
            interface_names=interface_names,
            prices=prices,
        )
        return overlay if overlay or not overlay.port_names or not overlay.interface_names else None


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
        # Which ports is this run's answer and nothing the configuration says: a
        # file type asks for an overlay permanently, and a selection is about
        # the one picture somebody is looking at.
        select=None if overlay is None else overlay.select,
        # The callouts are this run's too. A file type that draws its ports
        # writes their names, as it always did, unless the run says not to.
        component_names=overlay is not None and overlay.component_names,
        component_prices=overlay is not None and overlay.component_prices,
        port_names=overlay is None or overlay.port_names,
        interface_names=overlay is None or overlay.interface_names,
        prices=None if overlay is None else overlay.prices,
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
        if not overlay.draws(record.name):
            continue
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

        if overlay.select is not None:
            pc_logging.warning(
                "%s:%s: nothing to draw for %s: none of the ports asked for is one this object reports: %s"
                % (shape.project_name, shape.name, asked_for, ", ".join(sorted(overlay.select)))
            )
        elif isinstance(shape, Assembly) and not overlay.internals:
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


def price_text(price, currency=None) -> str:
    """A price as the log writes it: two decimal places and the currency's code.

    The code, because a log is text somebody greps and a supplier's
    configuration states the currency as one (see 'currency' in
    'examples/provider_store'). What a picture writes is 'price_label'.
    """
    text = "%.2f" % float(price)
    return "%s %s" % (text, currency) if currency else text


def price_label(price, currency=None) -> str:
    """A price as a callout on a picture writes it.

    In dollars it is written the way a reader expects to see dollars, '$1,234.50'
    - which is also how the IDE's 3D view and its Buy tab write it (see
    'formatPrice' in the extension's 'supply.ts'), so the 2D tab's picture and
    the 3D view beside it show one price one way. Any other currency is written
    as the log writes it, with its code: the picture's font ('stroke_text') has
    a '$' and no other currency symbol.
    """
    if currency is not None and str(currency).upper() == "USD":
        return "${:,.2f}".format(float(price))
    return price_text(price, currency)


async def component_prices_async(shape, ctx, overlay: Overlay) -> dict:
    """The price of every component of 'shape' there is one for, as callout text ('price_label').

    Keyed by the full name of each object ('<package>:<name>'), which is what
    every node of the tree a renderer is handed carries ('name'), so a part
    placed a hundred times is priced once. Empty when nothing has a price -
    nobody sells any of it, no supplier answered, or there is nowhere to ask -
    which is said in the log, because a picture with no prices on it cannot
    say why. Like the ports, failing must not cost the picture.
    """
    name = "%s:%s" % (shape.project_name, shape.name)
    if overlay.prices is None:
        pc_logging.warning(
            "%s: no prices to draw: only the PartCAD daemon asks the suppliers what the components cost" % name
        )
        return {}
    try:
        prices = await overlay.prices(ctx, shape) or {}
    except Exception as e:
        pc_logging.error("%s: failed to find what the components cost: %s" % (name, e))
        return {}
    priced = {
        object_name: entry
        for object_name, entry in prices.items()
        if isinstance(entry, dict) and entry.get("price") is not None
    }
    if not priced:
        pc_logging.warning("%s: no supplier quoted a price for any of its components" % name)
        return {}
    pc_logging.info(
        "%s: --with-component-prices: %d priced:\n%s"
        % (
            name,
            len(priced),
            "\n".join(
                "\t%s\t%s" % (key, price_text(priced[key]["price"], priced[key].get("currency")))
                for key in sorted(priced)
            ),
        )
    )
    return {key: price_label(entry["price"], entry.get("currency")) for key, entry in priced.items()}
