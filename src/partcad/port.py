#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

from . import assembly_ports, interface_config, telemetry
from .interface import Interface, port_location


def port_info(port) -> dict:
    """What 'pc info' says about one port.

    The location as the packed form a configuration file spells it with - plain
    data, so that it survives the trip to a client over JSON-RPC - and the
    boundary sketch only where the port has one. A port may have neither: a port
    declared by name alone is a frame at the origin of whatever declares it, and
    nothing else.
    """
    info = {"location": port_location(port).as_packed()}
    if port.sketch is not None:
        info["sketch"] = f"{port.sketch.project_name}:{port.sketch.name}"
    return info


@telemetry.instrument(exclude=["info"])
class WithPorts(Interface):
    interfaces: dict[str, dict[str, dict[str, str]]]

    def __init__(
        self,
        name: str,
        project,
        config: dict = {},
    ):
        super().__init__(name, project, config, config_section="implements")
        self.interfaces = None
        # What this object's 'map:' externalizes, once somebody has resolved it.
        # None until then, and None forever for the objects that declare no
        # 'map:' at all - which is every part, every sketch, and every assembly
        # that states its ports itself. See 'partcad.assembly_ports'.
        self.mapped = None

    def map_resolved(self) -> bool:
        """Whether somebody has already worked out what this object's 'map:' names."""
        return self.mapped is not None

    def has_loose_ports(self) -> bool:
        """Whether this object has ports that belong to no interface it implements.

        Asked where a connection is being worked out from one end: an object
        that implements exactly one interface and nothing else is unambiguous,
        and one that also carries a port of its own is not. A mapped port is
        such a port - the map's two-element form externalizes a port rather than
        an interface - so it counts the same way a 'ports:' section does.
        """
        if "ports" in self.config:
            return True
        return bool(self.mapped.ports) if self.mapped is not None else False

    def set_mapped(self, mapped) -> None:
        """Take the resolved 'map:' and let the ports be built again with it.

        Resetting rather than merging: an object whose ports were read before
        its map was resolved read them without it, and those are the very
        dictionaries the map has to appear in. Rebuilding them is what
        'get_ports()' does for an object that has none yet, so this is the same
        work rather than a second way of doing it.
        """
        with self.lock:
            self.mapped = mapped
            self.ports = None
            self.interfaces = None
            self.inherits = None

    def inherited_from_elsewhere(self) -> dict:
        """The interfaces this object implements because something inside it does."""
        return self.mapped.inherits if self.mapped is not None else {}

    def instantiate_ports(self):
        """This object's ports: the ones it externalizes, then the ones it declares."""
        # Externalized first, declared second: 'ports:' and 'implements:' are
        # this object's own statements about itself and get the last word, and
        # they are entitled to name what the map has produced (an 'implements:'
        # instance may sit at a mapped port - see 'InterfaceInherits').
        self.ports = {}
        if self.mapped is not None:
            self.ports.update(self.mapped.ports)
        self.instantiate_declared_ports()

    # A shape's declaration is not an interface's: 'desc' is prose, 'fileUrl'
    # is a URL that may be percent-encoded, and neither has parameters
    # substituted into it. What a shape does declare about connections is where
    # its ports are, which interfaces it implements, and - for an assembly -
    # which of the ones inside it are its own; all three are worth writing in
    # terms of the shape's own parameters, since an assembly parametrized by how
    # many of something it holds names its nodes after them.
    EXPRESSION_SECTIONS = ("ports", "implements", assembly_ports.MAP)

    def declared_construction_params(self, config: dict) -> dict:
        """A shape's 'parameters:', all of it.

        The section is split in two on an *interface*, where it has always also
        meant the freedom of movement a connection keeps. On a shape it never
        did: 'parameters:' is what 'cube;width=20' sets and what a CAD script is
        handed, and that is the whole of it. So a part whose parameter happens
        to be called 'moveX' keeps it as the value it is.
        """
        return config.get(interface_config.PARAMETERS) or {}

    def declared_movement_params(self, config: dict) -> dict:
        """None: a shape states the freedom of movement in the interfaces it implements.

        What it gets is whatever those interfaces declare, merged in as they are
        inherited (see 'Interface.instantiate'). A shape's own 'parameters:' used
        to be read as freedom of movement as well, which turned every dimension a
        part was built from into an offset that composed into nothing.
        """
        return {}

    def get_interfaces(self):
        with self.lock:
            if self.interfaces is None:
                self.instantiate_interfaces()
            return self.interfaces

    def get_interface(self, interface_name: str):
        if interface_name.startswith("/") and not interface_name.startswith("//"):
            # Workaround the old syntax for absolute package paths
            interface_name = "/" + interface_name
        return self.get_interfaces()[interface_name]

    def instantiate_interfaces(self):
        self.interfaces = {}

        # Recursively merge the inherited interfaces
        @telemetry.start_as_current_span("WithPorts.instantiate_interfaces.merge_inherits")
        def merge_inherits(inherits, interface_state: str = "", top_level=False):
            if not top_level and len(inherits.keys()) == 1 and (len(list(inherits.values())[0].instances.keys()) == 1):
                compatible = True
            else:
                compatible = False

            for interface_name, inherit in inherits.items():
                interface = inherit.interface

                # Ignore abstract interfaces
                if interface.abstract:
                    continue

                if ":" not in interface_name:
                    interface_name = self.project.name + ":" + interface_name

                if not compatible and interface_name not in self.interfaces:
                    self.interfaces[interface_name] = {}

                for instance_name in inherit.instances.keys():
                    if instance_name != "" and interface_state != "":
                        instance_full_name = interface_state + "-" + instance_name
                    elif instance_name != "":
                        instance_full_name = instance_name
                    elif interface_state != "":
                        instance_full_name = interface_state
                    else:
                        instance_full_name = ""

                    if not compatible:
                        if instance_name not in self.interfaces[interface_name]:
                            self.interfaces[interface_name][instance_full_name] = {}

                        for port_name in interface.get_ports().keys():
                            if instance_full_name != "" and port_name != "":
                                port_full_name = instance_full_name + "-" + port_name
                            elif instance_full_name != "":
                                port_full_name = instance_full_name
                            elif port_name != "":
                                port_full_name = port_name
                            else:
                                port_full_name = ""

                            self.interfaces[interface_name][instance_full_name][port_name] = port_full_name

                    merge_inherits(interface.get_parents(), instance_full_name)

        merge_inherits(self.get_parents(), top_level=True)

    def info(self):
        return {
            "interfaces": dict(
                (
                    interface_name,
                    dict(
                        (
                            instance_name,
                            dict((port_name, port) for port_name, port in instance.items()),
                        )
                        for instance_name, instance in interface.items()
                    ),
                )
                for interface_name, interface in self.get_interfaces().items()
            ),
            "ports": dict((port_name, port_info(port)) for port_name, port in self.get_ports().items()),
        }
