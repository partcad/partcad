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

The same section renames what the object has of its own, which is what an
object that is not an assembly can do with it. Without a node, an entry names
a port or an interface instance the object would have without its 'map:' -- an
enrich's or an alias's are those of what it points at, anything else's are
the ones it declares -- and gives it another name::

    parts:
      leg:
        type: enrich
        source: //pub/std/imperial/dimensional-lumber:lumber
        with: {width: 4, height: 4, length: 29.25}
        map:
          top: [y1-x0-z1]            # one element: a port of its own
          rail:                      # the long form, which also moves and turns it
            port: x1-y1-z1
            moveZ: -12.7
            turnZ: 90

The long form spells out what the list form says by position -- 'node',
'port', or 'interface' and 'instance' -- and adds 'moveX'/'moveY'/'moveZ'
(millimetres) and 'turnX'/'turnY'/'turnZ' (degrees): an offset in the frame of
what is named, applied as the moves and then the turns in that order, the way
the freedom of movement of an interface is. It is the same mapping either way:
a node's port seen from outside the assembly, or the object's own port under a
name that says what it is for, and both may land somewhere near the original
rather than on it.

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

import copy

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


# The offsets an entry may carry, in the order they are applied: the moves,
# then the turns, as an interface's freedom of movement is.
MOVES = {"moveX": (1.0, 0.0, 0.0), "moveY": (0.0, 1.0, 0.0), "moveZ": (0.0, 0.0, 1.0)}
TURNS = {"turnX": (1.0, 0.0, 0.0), "turnY": (0.0, 1.0, 0.0), "turnZ": (0.0, 0.0, 1.0)}

# What the long form of an entry may say besides the offsets.
REFERENCE_KEYS = ("node", "port", "interface", "instance")


class MapEntry:
    """One entry of a 'map:' section, whichever way it was written.

    'node' is None for an entry that names something the object has of its
    own. Exactly one of 'port' and 'interface' is set; 'instance' goes with the
    interface. 'offset' is where the new name goes relative to what it names.
    """

    def __init__(self, node=None, port=None, interface=None, instance=None, offset=None):
        self.node = node
        self.port = port
        self.interface = interface
        self.instance = instance
        self.offset = offset if offset is not None else Location()


def parse_entry(name: str, spec, where: str):
    """A 'MapEntry' for one entry, or None after reporting what is wrong with it.

    The list form says by position what the long form says by key: '[port]',
    '[node, port]' and '[node, interface, instance]'. Only the long form can
    carry an offset, and only it can name an interface of the object's own,
    since '[interface, instance]' would read as '[node, port]'.
    """
    if isinstance(spec, (list, tuple)):
        if len(spec) not in (1, 2, 3) or not all(isinstance(x, str) for x in spec):
            pc_logging.error(
                "%s: '%s' must be [port], [node, port] or [node, interface, instance], got: %r" % (where, name, spec)
            )
            return None
        if len(spec) == 1:
            return MapEntry(port=spec[0])
        if len(spec) == 2:
            return MapEntry(node=spec[0], port=spec[1])
        return MapEntry(node=spec[0], interface=spec[1], instance=spec[2])

    if not isinstance(spec, dict):
        # One string is not a list of one, and reading it as a list of
        # characters is the kind of help nobody asked for.
        pc_logging.error(
            "%s: '%s' must be a list ([port], [node, port] or [node, interface, instance]) "
            "or a mapping with 'port' or 'interface'" % (where, name)
        )
        return None

    # As text: a key YAML read as a number ('1:') is reported, not raised on.
    unknown = sorted(str(key) for key in set(spec) - set(REFERENCE_KEYS) - set(MOVES) - set(TURNS))
    if unknown:
        pc_logging.error("%s: '%s' says %s, which a map entry does not take" % (where, name, ", ".join(unknown)))
        return None
    if ("port" in spec) == ("interface" in spec):
        pc_logging.error("%s: '%s' must name either a 'port' or an 'interface'" % (where, name))
        return None
    if "instance" in spec and "interface" not in spec:
        pc_logging.error("%s: '%s' names an 'instance' of no 'interface'" % (where, name))
        return None
    for key in REFERENCE_KEYS:
        if key in spec and not isinstance(spec[key], str):
            pc_logging.error("%s: '%s': '%s' must be a name, got: %r" % (where, name, key, spec[key]))
            return None

    offset = Location()
    for key, axis in list(MOVES.items()) + list(TURNS.items()):
        value = spec.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            pc_logging.error("%s: '%s': '%s' must be a number, got: %r" % (where, name, key, value))
            return None
        if value == 0:
            continue
        if key in MOVES:
            offset = offset * Location(tuple(v * value for v in axis), (0, 0, 1), 0)
        else:
            offset = offset * Location((0, 0, 0), axis, value)

    return MapEntry(
        node=spec.get("node"),
        port=spec.get("port"),
        interface=spec.get("interface"),
        instance=spec.get("instance", "") if "interface" in spec else None,
        offset=offset,
    )


def mapped_interface_names(config: dict) -> list:
    """The interfaces a 'map:' section names, read from the text alone.

    No node is resolved and nothing is instantiated: the three-element form and
    the long form state the interface, which is what makes an object findable by
    'pc search --interface' at the price of reading its declaration.
    """
    names = []
    for spec in (config.get(MAP) or {}).values():
        if isinstance(spec, (list, tuple)) and len(spec) == 3 and isinstance(spec[1], str):
            names.append(spec[1])
        elif isinstance(spec, dict) and isinstance(spec.get("interface"), str):
            names.append(spec["interface"])
    return names


def node_index(assembly, prefix: str = "", placement: Location = None, index: dict = None) -> dict:
    """{node path -> (item, where this assembly put it)}.

    The nodes a 'map:' may name. Every level of the tree is one, because every
    link has a name: its own, or - for a 'links:' that gives itself neither a
    'name:' nor an object to be named after - where it is written, as 'link#2'
    (see 'Assembly.link_name'). So a node is named by the path of links that
    reaches it, and 'frame/plate' and 'link#2/loose' are both paths of two.

    A container used to contribute nothing when it had no name of its own, on
    the grounds that it was a grouping in the file rather than a thing. That
    made two nodes in two such containers the same path, and there was no way
    to say which was meant. A sub-assembly that a package declares is
    addressable and is not descended into: see this module's docstring.
    """
    from .assembly import Assembly

    index = {} if index is None else index
    placement = Location() if placement is None else placement

    for index_of, child in enumerate(assembly.children):
        child_placement = placement
        if child.location is not None:
            child_placement = placement * shape_ports.as_location(child.location)

        item = child.item
        container = isinstance(item, Assembly) and item.config.get("child", False)
        path = NODE_SEPARATOR.join([part for part in (prefix, assembly.link_name(index_of)) if part])

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


def _resolve_port(
    shape, mapped: MappedPorts, name: str, item, placement: Location, port_name: str, where: str, offset=None
) -> None:
    """One port of one node - or of the object itself - under a name of this object's own.

    The port itself is not moved - a port of a part stays a port of that part.
    What this object gets is a port of its own at the place that one ended up,
    moved and turned by the entry's offset, and drawn with the same boundary.
    """
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
        location=placement * port_location(port) * (offset if offset is not None else Location()),
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
    offset=None,
) -> None:
    """One instance of one interface a node - or the object itself - implements.

    Spelled as the 'implements:' this assembly would have had to write for
    itself, so that everything downstream treats it as exactly that. The
    interface is the node's; only the instance name is this assembly's to
    choose.
    """
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
    if offset is not None:
        location = location * offset
    try:
        inherit = InterfaceInherits(matched, shape.with_ports.project, {name: location.as_packed()})
    except Exception as e:
        pc_logging.error("%s: failed to externalize the interface '%s': %s" % (where, matched, e))
        return
    if inherit.interface is None:
        pc_logging.error("%s: failed to externalize the interface '%s'" % (where, matched))
        return
    _merge_inherit(mapped, inherit, where)


class _Own:
    """What an entry with no node names things of: the object as it is without its map.

    For an enrich or an alias that is what it points at - the same geometry,
    with the same ports. For anything else it is what the object declares in
    'ports:' and 'implements:', read on their own: the object's own
    'with_ports' cannot be asked, because what it answers is about to include
    this very map.
    """

    def __init__(self, shape, with_ports):
        self.name = shape.name
        self.project_name = getattr(shape, "project_name", None)
        self.with_ports = with_ports


def _declaration(shape) -> dict:
    """The object's declaration as written.

    Not 'shape.config': an enrich reports the configuration of the instance it
    resolved to once it is prepared (see 'enrich.adopt_source_config'), type
    and all, while its 'with_ports' keeps what it was declared as.
    """
    with_ports = getattr(shape, "with_ports", None)
    return (getattr(with_ports, "config", None) or getattr(shape, "config", None)) or {}


def is_reference(shape) -> bool:
    """Whether this object is another one under a name of its own (an enrich or an alias)."""
    return _declaration(shape).get("type") in ("alias", "enrich")


async def _source_of(ctx, shape):
    """The object an enrich or an alias points at, prepared, or None."""
    from .assembly import Assembly

    config = shape.config or {}
    declaration = _declaration(shape)
    source_name = (
        config.get("source_resolved")
        or declaration.get("source_resolved")
        or config.get("source")
        or declaration.get("source")
    )
    if not source_name:
        return None
    if isinstance(shape, Assembly):
        source = ctx._get_assembly(source_name)
    else:
        source = await ctx._get_part_async(source_name)
    if source is None:
        return None
    await shape_ports.prepare_async(source, ctx)
    return source


async def _own(ctx, shape):
    """See '_Own'. None, after saying why, if an enrich's source cannot be found."""
    from .port import WithPorts

    if is_reference(shape):
        source = await _source_of(ctx, shape)
        if source is None or getattr(source, "with_ports", None) is None:
            return None
        return source

    config = {key: value for key, value in (shape.with_ports.config or {}).items() if key != MAP}
    return _Own(shape, WithPorts(shape.name, shape.with_ports.project, config))


def keeps_source_ports(shape) -> bool:
    """Whether this object has the ports of what it points at, besides what it maps.

    The rule an alias has always followed (see 'PartFactoryAlias'): a part that
    is another one under a new name has its ports, unless it declares ports or
    interfaces of its own or moves the geometry they sit on. A 'map:' adds names
    to those rather than replacing them - which is the point of giving a port of
    a standard part a name that says what it is for.
    """
    from .assembly import Assembly

    if isinstance(shape, Assembly) or not is_reference(shape):
        return False
    config = _declaration(shape)
    return not any(key in config for key in ("implements", "ports", "offset", "scale"))


def _own_placement(shape) -> Location:
    """Where what an entry with no node names is, in this object's frame.

    An enrich or an alias that declares 'offset:' moves the geometry of what it
    points at (see 'wrapper_transform'), and a port of that geometry moves with
    it. Anything else's own ports are its own and are where it declares them.
    """
    if not is_reference(shape):
        return Location()
    offset = _declaration(shape).get("offset")
    return Location() if offset is None else Location(offset)


def _adopt_all(shape, mapped: MappedPorts, source) -> None:
    """Every port and interface of 'source', as this object's own (see 'keeps_source_ports')."""
    carrier = source.with_ports
    for name, inherit in (carrier.get_parents() or {}).items():
        # A copy: an entry that maps another instance of the same interface
        # adds it here ('_merge_inherit'), and that is this object's instance,
        # not one of the source and of every other reference to it.
        adopted = copy.copy(inherit)
        adopted.instances = dict(inherit.instances)
        adopted.sketches = dict(inherit.sketches)
        mapped.inherits[name] = adopted
    owned = shape_ports.interface_of_port(carrier)
    for port_name, port in (carrier.get_ports() or {}).items():
        if port_name in owned:
            continue
        mapped.ports[port_name] = InterfacePort(
            port_name,
            shape.with_ports.project,
            sketch=port.sketch,
            location=port_location(port),
            sketch_params=port.sketch_params,
        )


async def _resolve_entry(ctx, shape, mapped: MappedPorts, nodes, own, name: str, spec, where: str) -> None:
    """One entry of a 'map:' section: what it names, if it names anything usable.

    Everything a declaration can get wrong is reported here and costs the user
    that one port rather than the object: a node this assembly does not have,
    a port that node does not have, an interface it does not implement, an
    instance of it that does not exist, and a value that is none of the forms.
    """
    entry = parse_entry(name, spec, where)
    if entry is None:
        return

    if entry.node is None:
        if own is None:
            pc_logging.error("%s: '%s': what this object points at cannot be found" % (where, name))
            return
        if is_reference(shape) and "scale" in _declaration(shape):
            pc_logging.error(
                "%s: '%s' names a port of what this object points at, which it scales: "
                "where that port is on the scaled geometry is not something a map can say" % (where, name)
            )
            return
        item, placement = own, _own_placement(shape)
    else:
        if nodes is None:
            pc_logging.error("%s: '%s' names the node '%s', and only an assembly has nodes" % (where, name, entry.node))
            return
        node = nodes.get(entry.node)
        if node is None:
            pc_logging.error(
                "%s: there is no node '%s' in this assembly: %s" % (where, entry.node, sorted(nodes.keys()))
            )
            return
        item, placement = node
        if getattr(item, "with_ports", None) is None:
            pc_logging.error("%s: the node '%s' has no ports at all" % (where, entry.node))
            return

        # The node may be an assembly that externalizes ports of its own, and
        # this one is entitled to map those: its map has to be resolved first.
        await shape_ports.prepare_async(item, ctx)
        placement = _item_placement(item, placement)

    if entry.port is not None:
        _resolve_port(shape, mapped, name, item, placement, entry.port, where, entry.offset)
    else:
        _resolve_instance(
            ctx, shape, mapped, name, item, placement, entry.interface, entry.instance, where, entry.offset
        )


async def resolve_async(shape, ctx) -> None:
    """Work out what this object's 'map:' names, and hand it its ports.

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

    with pc_logging.Action("Map", shape.project_name, shape.name):
        own = None
        if keeps_source_ports(shape) or any(_names_no_node(spec) for spec in declared.values()):
            try:
                own = await _own(ctx, shape)
            except Exception as e:
                pc_logging.error("%s: failed to find what this object points at: %s" % (where, e))

        if own is not None and keeps_source_ports(shape):
            _adopt_all(shape, mapped, own)

        nodes = None
        if isinstance(shape, Assembly) and any(not _names_no_node(spec) for spec in declared.values()):
            try:
                await shape.do_instantiate()
                nodes = node_index(shape)
            except Exception as e:
                pc_logging.error("%s: failed to walk the assembly: %s" % (where, e))
                with_ports.set_mapped(mapped)
                return

        for name, spec in declared.items():
            try:
                await _resolve_entry(ctx, shape, mapped, nodes, own, name, spec, where)
            except Exception as e:
                # One unusable entry costs the user that port, not the object.
                pc_logging.error("%s: failed to map '%s': %s" % (where, name, e))

    with_ports.set_mapped(mapped)


def _names_no_node(spec) -> bool:
    """Whether an entry, as written, names something of the object's own."""
    if isinstance(spec, (list, tuple)):
        return len(spec) == 1
    return isinstance(spec, dict) and "node" not in spec
