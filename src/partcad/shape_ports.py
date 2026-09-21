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


def interface_of_port(with_ports) -> dict:
    """port name -> (interface name, instance name), for one object's ports.

    'WithPorts.get_interfaces()' is keyed the other way round - interface, then
    instance, then the ports of that instance - and records an interface at
    every level of the inheritance it walks, most specific first. The first
    entry that claims a port is therefore the interface a user would name in a
    'connect:', which is the one worth reporting.
    """
    owner = {}
    for interface_name, instances in (with_ports.get_interfaces() or {}).items():
        for instance_name, ports in (instances or {}).items():
            for port_full_name in (ports or {}).values():
                owner.setdefault(port_full_name, (interface_name, instance_name))
    return owner


def own_ports(shape, placement: Location = None, owner: str = "") -> list:
    """The ports this object declares, moved by 'placement'.

    The object's own ports and nothing else: what a part implements, and what an
    assembly externalizes. Synchronous, and so it reports whatever has been
    resolved - call 'prepare_async' first for an assembly, which is what turns
    a 'map:' into ports.
    """
    with_ports = getattr(shape, "with_ports", None)
    if with_ports is None:
        return []

    from .interface import port_location

    placement = Location() if placement is None else placement
    interfaces = interface_of_port(with_ports)
    records = []
    for port_name, port in with_ports.get_ports().items():
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


def _child_owner(owner: str, child) -> str:
    """The node path of one child of an assembly.

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
    return qualify(owner, name) if name else owner


def as_location(location) -> Location:
    """A placement recorded by an assembly, as a Location whatever it was stored as."""
    return location if isinstance(location, Location) else Location(location)


async def _collect(shape, ctx, owner: str, placement: Location, deep: bool, out: list) -> None:
    """'shape' and, when the walk is a deep one and it is an assembly, what is inside it."""
    from .assembly import Assembly

    is_assembly = isinstance(shape, Assembly)
    if is_assembly:
        # Whatever the assembly externalizes is one of its own ports, so this
        # comes first - and it is what instantiates the assembly when there is a
        # 'map:' to resolve.
        await prepare_async(shape, ctx)
        # An assembly's own placement is carried on the envelope it renders as,
        # so the geometry moves by it and the ports have to move with it.
        root = shape._root_location()
        if root is not None:
            placement = placement * root

    out.extend(own_ports(shape, placement, owner))

    if not deep or not is_assembly:
        return

    await shape.do_instantiate()
    for child in shape.children:
        child_placement = placement
        if child.location is not None:
            child_placement = placement * as_location(child.location)
        await _collect(child.item, ctx, _child_owner(owner, child), child_placement, deep, out)


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
