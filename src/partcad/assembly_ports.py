#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'map:' - the ports and interfaces an assembly externalizes.

An assembly is connected to other things the way a part is: by its ports, and
by the interfaces those ports belong to. What it does *not* have is a part's
way of getting them. A part is one solid and says where its ports are on it; an
assembly is made of parts that already carry ports, already placed - and the
whole point of an assembly's port is that it is one of those, seen from
outside.

So an assembly does not declare a port at a coordinate somebody worked out by
hand. It says which one it means::

    assemblies:
      motor-mount:
        type: assy
        map:
          # a port of a node, under a name of this assembly's choosing
          output: [bracket, TR-thru-3-opening-m3]
          # an instance of an interface a node implements, under a new instance
          # name; the interface itself is what it is
          mount: [bracket, nema-17-motor-bracket-3, outer]

The key is the new name and the value names what is being externalized: two
elements are a node and one of its ports, three are a node, an interface it
implements and the instance of it. The interface *type* is never restated - it
is read off the node - because an interface is a contract and an assembly is
not in a position to rename one. The instance name is the assembly's to choose,
because an instance is a place rather than a kind: the bracket calls it
'outer', and the mount it is part of calls it 'mount'.

The first element is the **node name from the ASSY file** - the 'name:' of a
link, or the part/assembly name where the link has none - and not the name of
the part. An assembly places the same part six times; five of those are not the
one being externalized.

What is *not* reachable is what another object externalizes nothing of: the
path walks through the anonymous 'links:' containers an ASSY file is built out
of, because those are this assembly's own structure, and stops at a
sub-assembly that some package declares. That sub-assembly is an object with a
boundary of its own; to reach a port inside it, it externalizes that port and
this one maps *that*. A node inside a named container is reached through it
('frame/bracket'), which is the only place a path has more than one element.

Resolution needs the assembly's tree, which is not in its declaration: it is
the result of instantiating it (the tree, not the geometry - no CAD kernel is
involved, and none of this reaches a sandbox). That is why it is asynchronous
and why it happens before the 'ports:' and 'implements:' sections are read:
those are declarations about this assembly, and they are entitled to refer to
what the map has already produced.
"""

from . import logging as pc_logging
from . import shape_ports
from .geom import Location
from .interface import InterfacePort, port_location
from .interface_inherit import InterfaceInherits

# The section this module is about.
MAP = "map"

# What separates the elements of a node path. Neither ':' (which separates a
# package from an object) nor ';' (which introduces parameters) can be one, and
# '/' is the only separator a port name and an interface instance name are
# already allowed to contain - so a mapped name never needs a spelling its own
# schema rejects.
NODE_SEPARATOR = "/"


class MappedPorts:
    """What a 'map:' section came out to.

    'ports' are ports of this assembly, ready to be used as if it had declared
    them. 'inherits' are the interfaces it implements because a node does, each
    an 'InterfaceInherits' exactly like the ones 'implements:' produces - so
    that everything downstream (the names the ports get, the ancestors that are
    walked, the freedom of movement that is merged in) happens once, in
    'Interface.adopt_inherit', for both.
    """

    def __init__(self):
        self.ports = {}
        self.inherits = {}


def mapped_interface_names(config: dict) -> list:
    """The interfaces a 'map:' section names, read from the text alone.

    No node is resolved and nothing is instantiated: the three-element form
    states the interface, which is what makes an assembly findable by
    'pc search --interface' at the price of reading its declaration.
    """
    names = []
    for spec in (config.get(MAP) or {}).values():
        if isinstance(spec, (list, tuple)) and len(spec) == 3 and isinstance(spec[1], str):
            names.append(spec[1])
    return names


def node_index(assembly, prefix: str = "", placement: Location = None, index: dict = None) -> dict:
    """{node path -> (item, where this assembly put it)}.

    The nodes a 'map:' may name. An anonymous 'links:' container contributes no
    path element - it is a grouping in the file rather than a thing - so the
    nodes of an ASSY file are named exactly as the file names them however
    deeply the file nests them. A named container contributes its name and is
    itself addressable. A sub-assembly that a package declares is addressable
    and is not descended into: see this module's docstring.
    """
    from .assembly import Assembly

    index = {} if index is None else index
    placement = Location() if placement is None else placement

    for child in assembly.children:
        child_placement = placement
        if child.location is not None:
            child_placement = placement * shape_ports.as_location(child.location)

        item = child.item
        container = isinstance(item, Assembly) and item.config.get("child", False)
        path = NODE_SEPARATOR.join([part for part in (prefix, child.name) if part])

        if path and path != prefix:
            if path in index:
                pc_logging.warning(
                    "%s: more than one node is called '%s'; the first one is what 'map:' reaches"
                    % (assembly.name, path)
                )
            else:
                index[path] = (item, child_placement)

        if container:
            node_index(item, path, child_placement, index)

    return index


def _item_placement(item, placement: Location) -> Location:
    """Where an item's *ports* are, given where the assembly put the item.

    A sub-assembly carries a placement of its own on the envelope it renders as
    (its 'location:'), and its ports move with its geometry, so that placement
    is part of the answer. A part has none.
    """
    root = item._root_location() if hasattr(item, "_root_location") else None
    return placement if root is None else placement * root


def _instance_location(ctx, item, interface_name: str, instance_name: str) -> Location:
    """Where 'item' carries that instance of that interface, in 'item''s own frame.

    Read from the declaration where the item declares it directly, which is
    exact and cheap. Derived from a port otherwise - an instance of an
    *inherited* interface is not written down anywhere, it is what the ports it
    produced imply. Either way it is the location an 'implements:' would have
    had to state to put the interface where it is, which is what this assembly
    now states on its own behalf.
    """
    with_ports = item.with_ports

    inherit = (with_ports.get_parents() or {}).get(interface_name)
    if inherit is not None and instance_name in inherit.instances:
        return inherit.instances[instance_name]

    instance = (with_ports.get_interfaces().get(interface_name) or {}).get(instance_name) or {}
    interface = ctx.get_interface(interface_name)
    interface_ports = interface.get_ports() if interface is not None else {}
    own_ports = with_ports.get_ports()
    # Sorted, so that an interface with several ports resolves to the same frame
    # every time rather than to whichever one a dictionary happened to yield.
    for interface_port_name in sorted(instance.keys()):
        own_port = own_ports.get(instance[interface_port_name])
        interface_port = interface_ports.get(interface_port_name)
        if own_port is None or interface_port is None:
            continue
        return port_location(own_port) * port_location(interface_port).inverse()

    pc_logging.warning(
        "%s: where the instance '%s' of '%s' is cannot be worked out; taking it to be at the origin"
        % (item.name, instance_name, interface_name)
    )
    return Location()


def _match_interface(available: dict, interface_name: str, item) -> str:
    """'interface_name' as the object spells it, or None if it does not implement it."""
    if interface_name in available:
        return interface_name

    project_name = getattr(item, "project_name", None)
    if project_name is not None:
        qualified = project_name + ":" + interface_name
        if qualified in available:
            return qualified

    short = shape_ports.short_interface_name(interface_name)
    matched = [name for name in available if shape_ports.short_interface_name(name) == short]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        pc_logging.error("More than one interface is called '%s': %s" % (interface_name, sorted(matched)))
    return None


def _merge_inherit(mapped: MappedPorts, inherit: InterfaceInherits, where: str) -> None:
    """Add an externalized instance to the interface it belongs to.

    Two entries mapping two instances of one interface are two instances of one
    interface here as well, and not two declarations of it.
    """
    existing = mapped.inherits.get(inherit.name)
    if existing is None:
        mapped.inherits[inherit.name] = inherit
        return
    for instance_name, location in inherit.instances.items():
        if instance_name in existing.instances:
            pc_logging.error("%s: '%s' is mapped more than once" % (where, instance_name))
            continue
        existing.instances[instance_name] = location


def _resolve_port(shape, mapped: MappedPorts, name: str, item, placement: Location, port_name: str, where: str) -> None:
    ports = item.with_ports.get_ports()
    port = ports.get(port_name)
    if port is None:
        if _match_interface(item.with_ports.get_interfaces(), port_name, item) is not None:
            pc_logging.error(
                "%s: '%s' is an interface of '%s' rather than a port of it; "
                "name the instance too to map an interface" % (where, port_name, item.name)
            )
        else:
            pc_logging.error(
                "%s: '%s' has no port called '%s': %s" % (where, item.name, port_name, sorted(ports.keys()))
            )
        return

    mapped.ports[name] = InterfacePort(
        name,
        shape.with_ports.project,
        sketch=port.sketch,
        location=placement * port_location(port),
        sketch_params=port.sketch_params,
    )


def _resolve_instance(
    ctx,
    shape,
    mapped: MappedPorts,
    name: str,
    item,
    placement: Location,
    interface_name: str,
    instance_name: str,
    where: str,
) -> None:
    interfaces = item.with_ports.get_interfaces() or {}
    matched = _match_interface(interfaces, interface_name, item)
    if matched is None:
        pc_logging.error(
            "%s: '%s' does not implement '%s': %s" % (where, item.name, interface_name, sorted(interfaces.keys()))
        )
        return

    instances = interfaces.get(matched) or {}
    if instance_name not in instances:
        pc_logging.error(
            "%s: '%s' has no instance '%s' of '%s': %s"
            % (where, item.name, instance_name, matched, sorted(instances.keys()))
        )
        return

    location = placement * _instance_location(ctx, item, matched, instance_name)
    try:
        inherit = InterfaceInherits(matched, shape.with_ports.project, {name: location.as_packed()})
    except Exception as e:
        pc_logging.error("%s: failed to externalize the interface '%s': %s" % (where, matched, e))
        return
    if inherit.interface is None:
        pc_logging.error("%s: failed to externalize the interface '%s'" % (where, matched))
        return
    _merge_inherit(mapped, inherit, where)


async def _resolve_entry(ctx, shape, mapped: MappedPorts, nodes: dict, name: str, spec, where: str) -> None:
    if isinstance(spec, str):
        # One string is not a tuple of two, and reading it as a list of
        # characters is the kind of help nobody asked for.
        pc_logging.error(
            "%s: '%s' must name a node and a port, or a node, an interface and an instance" % (where, name)
        )
        return
    if not isinstance(spec, (list, tuple)) or len(spec) not in (2, 3) or not all(isinstance(x, str) for x in spec):
        pc_logging.error("%s: '%s' must be [node, port] or [node, interface, instance], got: %r" % (where, name, spec))
        return

    node_name = spec[0]
    node = nodes.get(node_name)
    if node is None:
        pc_logging.error("%s: there is no node '%s' in this assembly: %s" % (where, node_name, sorted(nodes.keys())))
        return

    item, placement = node
    if getattr(item, "with_ports", None) is None:
        pc_logging.error("%s: the node '%s' has no ports at all" % (where, node_name))
        return

    # The node may be an assembly that externalizes ports of its own, and this
    # one is entitled to map those: its map has to be resolved first.
    await shape_ports.prepare_async(item, ctx)
    placement = _item_placement(item, placement)

    if len(spec) == 2:
        _resolve_port(shape, mapped, name, item, placement, spec[1], where)
    else:
        _resolve_instance(ctx, shape, mapped, name, item, placement, spec[1], spec[2], where)


async def resolve_async(shape, ctx) -> None:
    """Work out what this assembly's 'map:' externalizes, and hand it its ports.

    Idempotent and safe to call on anything: an object with no 'map:' is left
    alone, and one that has been resolved already is not resolved again (see
    'shape_ports.prepare_async', which is what callers use).
    """
    from .assembly import Assembly

    with_ports = shape.with_ports
    where = "%s:%s: 'map:'" % (shape.project_name, shape.name)
    mapped = MappedPorts()

    declared = with_ports.config.get(MAP) or {}
    if not isinstance(declared, dict):
        pc_logging.error("%s: must be a mapping of new names to what they name" % where)
        with_ports.set_mapped(mapped)
        return

    if not isinstance(shape, Assembly):
        pc_logging.error("%s: only an assembly has anything inside it to externalize" % where)
        with_ports.set_mapped(mapped)
        return

    with pc_logging.Action("Map", shape.project_name, shape.name):
        try:
            await shape.do_instantiate()
            nodes = node_index(shape)
        except Exception as e:
            pc_logging.error("%s: failed to walk the assembly: %s" % (where, e))
            with_ports.set_mapped(mapped)
            return

        for name, spec in declared.items():
            try:
                await _resolve_entry(ctx, shape, mapped, nodes, name, spec, where)
            except Exception as e:
                # One unusable entry costs the user that port, not the assembly.
                pc_logging.error("%s: failed to map '%s': %s" % (where, name, e))

    with_ports.set_mapped(mapped)
