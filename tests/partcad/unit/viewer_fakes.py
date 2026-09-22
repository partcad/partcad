#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Parts, assemblies, interfaces and ports for the shape-tree tests, without a kernel.

What a shape tree holds is 'geom.Location' algebra over BREP payloads nothing here
opens, plus what the declarations say about ports (see 'partcad.shape_envelope'),
so a test of it needs objects that carry ports and placements and nothing else.
Building the real ones would mean a package, a sandbox and a tessellation per
assertion, and would test none of that.

The fakes stand in for the factory and the cache, and for those only: the layer
that stamps a node's name, its placement and its connections is the real one
('Shape.get_cache_metadata'), and an assembly's hierarchy is built by the real
'_get_shape_real()'. A fake that produced the tree itself would be a second
implementation of the thing under test.

The BREP payloads are not valid BREP and are not meant to be: nothing in the core
decodes one, and every test that uses these stops short of the sandbox.
"""

import threading

from partcad import shape_envelope
from partcad.geom import Location


def fake_port(location=None, sketch=None):
    """One 'InterfacePort', with a placement and optionally a boundary sketch."""
    from partcad.interface import InterfacePort

    port = InterfacePort.__new__(InterfacePort)
    port.name = "port"
    port.location = location
    port.sketch = sketch
    return port


def fake_sketch(name="sketch", project="//pkg", envelope=None):
    """A sketch that answers for itself as a node, standing in for a port's boundary."""

    class FakeSketch:
        def __init__(self):
            self.name = name
            self.project_name = project
            self.node = (
                {"name": "%s:%s" % (project, name), "label": name, "brep": "..."} if envelope is None else envelope
            )

        async def get_representation(self, ctx, form=shape_envelope.FORM_BREP):
            return self.node

        async def get_components(self, ctx):
            return [self.node]

    return FakeSketch()


class FakeWithPorts:
    """What 'shape.with_ports' answers: the ports, and which interface claims each.

    'interfaces' is keyed the way 'WithPorts.get_interfaces()' keys it - interface,
    then instance, then {port name of the interface: port name of the object} -
    because that is what 'shape_ports.interface_of_port()' reads.
    """

    def __init__(self, ports=None, interfaces=None):
        self._ports = dict(ports or {})
        self._interfaces = dict(interfaces or {})

    def get_ports(self):
        return self._ports

    def get_interfaces(self):
        return self._interfaces


def fake_part(name, envelope=None, ports=None, interfaces=None, project="//pkg"):
    """A 'Shape' that is built already: one payload, and the ports it declares.

    'get_wrapped()' stands in for the factory and the cache, and does the one thing
    the real one does on the way out: stamps this shape's own layer - its name, its
    label, its properties and its connections - around the payload. That layer is
    the real 'get_cache_metadata()', because that is what is being tested.
    """
    from partcad.shape import Shape

    shape = Shape.__new__(Shape)
    shape.name = name
    shape.kind = "part"
    shape.project_name = project
    shape.config = {}
    shape.with_ports = FakeWithPorts(ports, interfaces) if (ports or interfaces) else None
    payload = {"brep": "..."} if envelope is None else envelope

    async def get_wrapped(ctx):
        return shape_envelope.apply_metadata(payload, shape.get_cache_metadata())

    shape.get_wrapped = get_wrapped
    return shape


def fake_assembly(name, children=(), location=None, ports=None, interfaces=None, project="//pkg", child=False):
    """An 'Assembly' that is instantiated already: the children it placed.

    A real one instantiates itself on demand, under two locks and a thread pool;
    here the children are simply there, which is the state every caller of
    'do_instantiate()' is after. Everything else is the real thing: the tree comes
    out of '_get_shape_real()' and the layer around each node out of
    'get_cache_metadata()'. 'child' marks an assembly that an ASSY file's 'links:'
    embedded.
    """
    from partcad.assembly import Assembly

    assembly = Assembly.__new__(Assembly)
    assembly.name = name
    assembly.kind = "assembly"
    assembly.project_name = project
    assembly.config = {"child": True} if child else {}
    assembly.location = location
    assembly.children = list(children)
    assembly.lock = threading.RLock()
    assembly.with_ports = FakeWithPorts(ports, interfaces) if (ports or interfaces) else None

    async def do_instantiate():
        return None

    async def get_wrapped(ctx):
        return await assembly._get_shape_real(ctx)

    assembly.do_instantiate = do_instantiate
    assembly.get_wrapped = get_wrapped
    return assembly


def fake_interface(name, ports=None, parents=None, project="//pkg"):
    """An 'Interface' with its ports and its inherited interfaces already resolved.

    'parents' is {interface name: (interface, {instance name: location})}, which is
    what 'get_parents()' answers with.
    """
    from partcad.interface import Interface
    from partcad.interface_inherit import InterfaceInherits

    class FakePackage:
        pass

    FakePackage.name = project

    interface = Interface.__new__(Interface)
    interface.name = name
    interface.full_name = "%s:%s" % (project, name)
    interface.project = FakePackage()
    interface.lock = threading.RLock()
    interface.ports = dict(ports or {})
    interface.inherits = {}
    for parent_name, (parent, instances) in (parents or {}).items():
        inherit = InterfaceInherits.__new__(InterfaceInherits)
        inherit.interface = parent
        inherit.instances = dict(instances)
        interface.inherits[parent_name] = inherit
    return interface


def placed(item, name=None, location=None):
    """One 'AssemblyChild': an object, the node name it was placed under, and where."""
    from partcad.assembly import AssemblyChild

    return AssemblyChild(item, name=name, location=None if location is None else Location(location))
