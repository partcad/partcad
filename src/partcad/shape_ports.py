#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where an object's ports are, which interface each belongs to, and who has one.

A port is a coordinate frame and an interface is a named set of them. Neither is
geometry, so neither is something a caller can find by looking at a shape: it
has to be read out of what the package declares, and - for an assembly - out of
where that assembly put the things it is made of.

This module is the one place that answers those questions, for every caller that
asks one:

* ``pc render --with-ports`` / ``--with-interfaces``, which draw them
  (see ``render_overlay``, which is now only the drawing half);
* an assembly's ``map:``, which externalizes a port of something inside it and
  therefore has to know where that port ended up (see ``assembly_ports``);
* ``pc info`` and the viewer, which list them;
* ``pc search --interface``, which asks the opposite question - not "where are
  this object's ports" but "which objects have a port of this kind".

The first four are per object and the last is per package, and they are here
together because they are the same fact read from two directions. Nothing here
builds geometry or needs a CAD kernel: a port's placement is
``geom.Location`` algebra over what the declaration says and what an assembly
recorded when it placed a child, and both are plain data.

**Cost.** Everything is lazy and nothing is precomputed while a package loads,
because a package that is only being listed must not pay for this: ``pc list``
never asks. Listing an object's own ports resolves the interfaces it implements
and nothing else; walking an assembly instantiates it (its tree, not its
geometry) and only when the walk is asked to go deep or the assembly has a
``map:`` to resolve. The search index is built on the first search that needs
it and kept on the package, from the *declarations* - so finding every part
that implements an interface costs the interfaces named in those declarations
rather than an instantiation of everything in the package.
"""

from . import logging as pc_logging
from . import shape_envelope
from .geom import Location
from .utils import format_parameterized_name, parse_parameterized_name

# 'interface' is imported where it is used rather than here: it reaches
# 'sketch', which reaches 'shape', which is one of this module's own callers.

# How a port of something inside an assembly is named when the whole tree is
# enumerated: the node path, then the port. Only for display and for the
# deep walk - an externalized port ('map:') is named by the assembly and
# carries no path at all, which is the point of externalizing it.
OWNER_SEPARATOR = ":"

# The kinds of object that can carry ports, and the attribute of a package that
# holds them. Sketches are here because a sketch is a shape like any other and
# 'ShapeFactory' gives every shape its ports; scenes because a scene is built
# out of the same ASSY files an assembly is.
OBJECT_KINDS = {
    "part": "parts",
    "assembly": "assemblies",
    "sketch": "sketches",
    "scene": "scenes",
}


class PortRecord:
    """One port, as somebody outside the object sees it.

    'name' is what the port is called ('TL-m3'), qualified with the path of the
    node it came from when an assembly is walked in full. 'location' is where it
    is, in the coordinate system of the object the enumeration started from.
    'interface'/'instance' name the interface instance it belongs to, or are
    None for a port that belongs to none. 'port' is the 'InterfacePort' itself,
    for a caller that needs what it draws with.
    """

    __slots__ = ("name", "port", "location", "interface", "instance", "owner")

    def __init__(self, name, port, location, interface=None, instance=None, owner=""):
        self.name = name
        self.port = port
        self.location = location
        self.interface = interface
        self.instance = instance
        self.owner = owner

    def __repr__(self):
        return "PortRecord(%r, interface=%r, instance=%r, location=%r)" % (
            self.name,
            self.interface,
            self.instance,
            self.location,
        )


def qualify(owner: str, name: str) -> str:
    """How a port of an assembly's child is named: the node path, then the port."""
    return ("%s%s%s" % (owner, OWNER_SEPARATOR, name)) if owner else name


def short_interface_name(name: str) -> str:
    """An interface's name without the package it lives in."""
    return name.rsplit(":", 1)[-1] if name else name


def port_carrier(obj):
    """The thing that answers for an object's ports, or None if nothing does.

    A shape's ports are its 'with_ports'; an interface's are its own. The two are
    the same class of question and are asked of one object or the other depending
    on which kind this is, so every reader here goes through this rather than
    reaching for an attribute that one of them does not have.
    """
    with_ports = getattr(obj, "with_ports", None)
    if with_ports is not None:
        return with_ports
    return obj if hasattr(obj, "get_ports") else None


def interface_of_port(carrier) -> dict:
    """port name -> (interface name, instance name), for one object's ports.

    'WithPorts.get_interfaces()' is keyed the other way round - interface, then
    instance, then the ports of that instance - and records an interface at
    every level of the inheritance it walks, most specific first. The first
    entry that claims a port is therefore the interface a user would name in a
    'connect:', which is the one worth reporting.

    An *interface* answers nothing here, and that is the right answer rather than
    a gap: its ports are its own, and reporting an interface as the interface of
    its own ports would say nothing. What it inherits is a node of its tree (see
    'Interface.get_representation').
    """
    if not hasattr(carrier, "get_interfaces"):
        return {}
    owner = {}
    for interface_name, instances in (carrier.get_interfaces() or {}).items():
        for instance_name, ports in (instances or {}).items():
            for port_full_name in (ports or {}).values():
                owner.setdefault(port_full_name, (interface_name, instance_name))
    return owner


def own_ports(shape, placement: Location = None, owner: str = "") -> list:
    """The ports this object declares, moved by 'placement'.

    The object's own ports and nothing else: what a part implements, what an
    assembly externalizes, and - for an interface, which answers for its own
    ports - what it declares. Synchronous, and so it reports whatever has been
    resolved: call 'prepare_async' first for an assembly, which is what turns a
    'map:' into ports.
    """
    carrier = port_carrier(shape)
    if carrier is None:
        return []

    from .interface import port_location

    placement = Location() if placement is None else placement
    interfaces = interface_of_port(carrier)
    records = []
    for port_name, port in carrier.get_ports().items():
        interface_name, instance_name = interfaces.get(port_name, (None, None))
        records.append(
            PortRecord(
                name=qualify(owner, port_name),
                port=port,
                location=placement * port_location(port),
                interface=interface_name,
                instance=instance_name,
                owner=owner,
            )
        )
    return records


# What a node of a shape tree carries about connections.
#
# Every node does, whatever it is - a part, one node of an assembly, an
# interface - and it is plain data derived from the declaration, so it is
# synchronous and costs a lookup. It is stamped by the object itself, in
# 'Shape.get_cache_metadata()', which is the layer re-applied every time a
# payload is materialized: a cache entry is keyed on geometry and shared by every
# object whose geometry is identical, so anything *declared* has to be re-stamped
# rather than stored inside (the same reason 'properties:' is).
#
# The two lists are derived from one walk and cannot disagree: a port names the
# interface instance it belongs to, and an instance names the ports it is made
# of, so the ports are partitioned - each belongs to exactly one instance, or to
# none.


def port_record(record: PortRecord) -> dict:
    """One port, as a node carries it.

    'location' is in the coordinate system of the object that declares the port,
    not of whatever is drawing it: a node's own 'location' places its ports along
    with its geometry, so a port is stated once, where it was declared. 'sketch'
    is the reference to the boundary the port draws with, where it has one - the
    reference and not the geometry, because reading this is a lookup and building
    a sketch is not.
    """
    entry = {"name": record.name, shape_envelope.KEY_LOCATION: record.location.as_packed()}
    if record.interface is not None:
        entry["interface"] = record.interface
        entry["instance"] = record.instance
    sketch = record.port.sketch
    if sketch is not None:
        entry["sketch"] = "%s:%s" % (sketch.project_name, sketch.name)
    return entry


def connection_metadata(shape) -> dict:
    """The connection layer of one object's node: its ports and its interfaces.

    Both keys are left out when there is nothing to put in them, so a shape with
    no ports - which is most of them - adds nothing to its envelope at all.

    Synchronous, and so it reports whatever has been resolved: an assembly's
    'map:' is what turns a declaration into ports, and 'prepare_async()' is what
    resolves it. Every caller of this calls that first.
    """
    records = own_ports(shape)
    if not records:
        return {}

    # Insertion-ordered, so the interfaces are listed in the order this object's
    # ports mention them rather than in whatever order a dictionary yields.
    instances = {}
    for record in records:
        if record.interface is None:
            continue
        instances.setdefault((record.interface, record.instance), []).append(record.name)

    metadata = {shape_envelope.KEY_PORTS: [port_record(record) for record in records]}
    if instances:
        metadata[shape_envelope.KEY_INTERFACES] = [
            {"name": name, "instance": instance, "ports": ports} for (name, instance), ports in instances.items()
        ]
    return metadata


async def prepare_async(shape, ctx) -> None:
    """Resolve what this object's ports depend on but its declaration does not hold.

    Which is one thing: an assembly's 'map:', whose answers are where the
    assembly put its children. Everything else is in the declaration and is
    resolved on first use, so this is a no-op - and has to stay cheap, because
    every caller that is about to read an object's ports calls it first without
    knowing whether the object is an assembly at all.

    The declaration is what decides, rather than the kind of object or anything
    'with_ports' is asked: a shape that declares no 'map:' is every shape but a
    few, and answering for one must not mean reaching into it. A 'map:' on
    something that is not an assembly still gets here, and is reported there
    rather than passed over in silence.
    """
    from . import assembly_ports

    if not (getattr(shape, "config", None) or {}).get(assembly_ports.MAP):
        return
    with_ports = getattr(shape, "with_ports", None)
    if with_ports is None or with_ports.map_resolved():
        return

    await assembly_ports.resolve_async(shape, ctx)


def embeds(child) -> bool:
    """Whether this child's contents belong to the assembly holding it.

    An ASSY file's 'links:' becomes an assembly of its own inside the object the
    file defines, and so does every nested 'links:' - assemblies that are no
    object of any package and that nobody names in a 'connect:'. They are passed
    over for exactly the reason 'Assembly.connected_children()' passes over them:
    what they hold belongs to the assembly that embeds them. So such a child
    contributes no node path of its own, and what is inside it is named as though
    the embedding assembly held it directly.
    """
    return bool(getattr(child.item, "config", {}).get("child", False))


def child_label(child) -> str:
    """What one child of an assembly is called: the node's name, or the object's.

    The node's name first, which is what an ASSY file's 'links:' writes and what
    a 'connect:' names: an assembly is mostly repeats of a few objects, so the
    object's name says which part it is and not which of them this is.
    """
    name = child.name if child.name is not None else getattr(child.item, "name", None)
    return name or ""


def child_owner(owner: str, child) -> str:
    """The node path of one child of an assembly."""
    if embeds(child):
        return owner
    label = child_label(child)
    return qualify(owner, label) if label else owner


def as_location(location) -> Location:
    """A placement recorded by an assembly, as a Location whatever it was stored as."""
    return location if isinstance(location, Location) else Location(location)


# Both of the composers below take - and return - 'None' for "nothing has moved
# this yet", and hand back what they were given when there is nothing to compose.
# A caller that only needs the arithmetic may pass 'Location()' and never see one;
# one that has to tell "not moved" from "moved to the identity" needs the
# distinction, and the viewer is such a caller: it re-stamps an envelope's
# location only where something actually placed it (see 'shape_envelope.placed').


def own_placement(shape, placement: Location = None) -> Location:
    """'placement' with the object's own location composed onto it.

    An assembly's own placement is carried on the envelope it renders as, so the
    geometry moves by it and everything drawn against that geometry - its ports,
    the children it holds - has to move with it. Anything that is not an assembly
    carries no such location, and 'placement' is what it is placed at.
    """
    root = shape._root_location() if hasattr(shape, "_root_location") else None
    if root is None:
        return placement
    return root if placement is None else placement * root


def child_placement(placement: Location, child) -> Location:
    """Where one child of an assembly sits, in the frame 'placement' is expressed in."""
    if child.location is None:
        return placement
    location = as_location(child.location)
    return location if placement is None else placement * location


async def _collect(shape, ctx, owner: str, placement: Location, deep: bool, out: list) -> None:
    """'shape' and, when the walk is a deep one and it is an assembly, what is inside it."""
    from .assembly import Assembly

    is_assembly = isinstance(shape, Assembly)
    if is_assembly:
        # Whatever the assembly externalizes is one of its own ports, so this
        # comes first - and it is what instantiates the assembly when there is a
        # 'map:' to resolve.
        await prepare_async(shape, ctx)
        placement = own_placement(shape, placement)

    out.extend(own_ports(shape, placement, owner))

    if not deep or not is_assembly:
        return

    await shape.do_instantiate()
    for child in shape.children:
        await _collect(child.item, ctx, child_owner(owner, child), child_placement(placement, child), deep, out)


async def ports_async(shape, ctx, deep: bool = False) -> list:
    """Every port of 'shape', in the coordinate system 'shape' is drawn in.

    'deep' decides whether an assembly is walked or taken at its word. By
    default it is taken at its word: an assembly's ports are the ones it
    declares and the ones its 'map:' externalizes, and what is inside it is its
    own business - the same answer 'pc info' gives, and the same boundary a
    'connect:' can reach across. 'deep' is for looking *inside* one anyway, to
    find the connection that went wrong: every child contributes its ports,
    named by the node that holds them and moved by where the assembly put it.
    """
    records = []
    await _collect(shape, ctx, "", Location(), deep, records)
    return records


# The other direction: not "where are this object's ports" but "who has one".


def qualified_interface_name(project, name: str) -> str:
    """'name' as the package and interface it resolves to from within 'project'.

    The same canonicalization an inherited interface goes through
    ('InterfaceInherits'), so that a declaration, a search and an index all
    spell one interface one way: the package made explicit, and a parametrized
    reference in its canonical order ('m-thru;depth=3,size=4').
    """
    if ":" in name:
        project_name, interface_name = project.resolve(name)
    else:
        project_name, interface_name = project.name, name
    base_name, params = parse_parameterized_name(interface_name)
    return project_name + ":" + format_parameterized_name(base_name, params)


def declared_interfaces(shape) -> list:
    """The interfaces this object's *declaration* names, without resolving any of them.

    Configuration only: the keys of 'implements:', plus the interface of every
    instance an assembly's 'map:' externalizes. That is what makes the search
    index affordable - the answer is in the text of the package, and reading it
    neither instantiates the object nor builds anything.
    """
    with_ports = getattr(shape, "with_ports", None)
    if with_ports is None:
        return []

    config = with_ports.config or {}
    names = []

    implements = config.get(with_ports.config_section)
    if isinstance(implements, str):
        names.append(implements)
    elif isinstance(implements, dict):
        names.extend(implements.keys())
    elif isinstance(implements, list):
        names.extend([name for name in implements if isinstance(name, str)])

    alias = config.get("alias")
    if isinstance(alias, str):
        names.append(alias)

    from .assembly_ports import mapped_interface_names

    names.extend(mapped_interface_names(config))

    project = with_ports.project
    qualified = []
    for name in names:
        if not isinstance(name, str) or not name:
            continue
        try:
            qualified.append(qualified_interface_name(project, name))
        except Exception as e:
            pc_logging.debug("Failed to resolve the interface name '%s': %s" % (name, e))
    return qualified


def interface_closure(ctx, name: str, cache: dict = None) -> set:
    """'name' and every interface it inherits from, however far up.

    What "this object implements X" means to a search: a part that implements
    'm4-thru-3' is a part with an M4 through hole, and somebody looking for
    'm4' or for 'm4-opening' is looking for that part. The abstract ones are
    kept, unlike in 'WithPorts.get_interfaces()' - an abstract interface is
    exactly the name a family is searched by.
    """
    if cache is not None and name in cache:
        return cache[name]

    closure = {name}
    interface = None
    try:
        interface = ctx.get_interface(name)
    except Exception as e:
        pc_logging.debug("Failed to resolve the interface '%s': %s" % (name, e))
    if interface is not None:
        pending = [interface]
        seen = {interface.full_name}
        while pending:
            current = pending.pop()
            closure.add(current.full_name)
            for inherit in (current.get_parents() or {}).values():
                parent = getattr(inherit, "interface", None)
                if parent is None or parent.full_name in seen:
                    continue
                seen.add(parent.full_name)
                pending.append(parent)

    if cache is not None:
        cache[name] = closure
    return closure


def _index_names(closure: set) -> set:
    """Every spelling a search may use for the interfaces in 'closure'.

    The full name, and the short one: a user searching for 'm3-thru' means the
    one in the package they are working in, and just as often the one in
    whatever package the part came from. Both are keys, so neither needs the
    other's spelling.
    """
    names = set(closure)
    names.update([short_interface_name(name) for name in closure])
    return names


def interface_index(ctx, project, kind: str) -> dict:
    """{interface name -> [objects of 'kind' in 'project' that implement it]}.

    Built once per package and kind, on the first search that asks for it, and
    kept on the package afterwards. Nothing builds it while a package loads:
    'pc list' does not ask, and must not pay for an index it does not read.
    """
    if kind not in OBJECT_KINDS:
        pc_logging.error("There is no kind of object called '%s' to search by interface" % kind)
        return {}

    cached = project.interface_indexes.get(kind)
    if cached is not None:
        return cached

    index = {}
    closures = {}
    for shape in getattr(project, OBJECT_KINDS[kind], {}).values():
        if shape is None:
            continue
        names = set()
        for declared in declared_interfaces(shape):
            names |= _index_names(interface_closure(ctx, declared, closures))
        for name in names:
            index.setdefault(name, []).append(shape)

    project.interface_indexes[kind] = index
    return index


def implementers(ctx, project, kind: str, interface: str) -> list:
    """The objects of 'kind' in 'project' that implement 'interface'.

    'interface' is taken as written: a bare name is resolved against this
    package first and matched by its short name otherwise, which is how one
    search reaches the parts of a package that gets its interfaces from
    somewhere else entirely.
    """
    index = interface_index(ctx, project, kind)
    try:
        qualified = qualified_interface_name(project, interface)
    except Exception:
        qualified = None
    if qualified is not None and qualified in index:
        return index[qualified]
    return index.get(short_interface_name(interface), [])
