#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-21
#
# Licensed under Apache License, Version 2.0.
#

from . import logging as pc_logging
from . import telemetry
from .geom import Location
from .utils import format_parameterized_name, parse_parameterized_name


@telemetry.instrument()
class InterfaceInherits:
    """One of the other interface types inherited by this interface.
    May include multiple instances of each inherited interface.

    This object is contained in the 'inherits' section of an interface
    or the 'implements' section of a part/assembly.
    It points at the interface object that already exists in the package."""

    source_project_name: str
    source_interface_name: str
    interface = None
    instances: dict[str, Location]
    # The boundary an instance draws its ports with, where it does not draw
    # them with the ones the inherited interface already has. Keyed by instance
    # name, and absent for every instance that says nothing about it - which is
    # nearly all of them.
    sketches: dict[str, str]

    def __init__(self, name, project, config: dict = {}, ports: dict = None):
        self.instances = {}
        self.sketches = {}
        # The ports of the object doing the inheriting, where it has any yet.
        # An instance may place itself at one of them ('port:') instead of
        # spelling out a location, which is how an assembly puts an interface
        # exactly where a port its 'map:' externalized ended up.
        self.owner_ports = ports or {}
        # Resolve the interface by name
        if ":" in name:
            self.source_project_name, self.source_interface_name = project.resolve(
                name,
            )
        else:
            self.source_project_name = project.name
            self.source_interface_name = name

        # A parametrized reference is canonicalized here rather than wherever it
        # was written: 'm-thru;depth=3,size=4' and 'm-thru;size=4,depth=3' name
        # one interface, and two spellings of it would be two keys in
        # 'Interface.inherits' and two entries in a part's 'implements' - the
        # same connection reported twice, and neither matching the other side.
        base_name, reference_params = parse_parameterized_name(self.source_interface_name)
        self.source_interface_name = format_parameterized_name(base_name, reference_params)

        self.name = self.source_project_name + ":" + self.source_interface_name
        pc_logging.debug("Fetching the interface %s" % self.name)

        if self.source_project_name == project.name:
            target_project = project
        else:
            target_project = project.ctx.get_project(self.source_project_name)
            if target_project is None:
                raise Exception(
                    "Failed to find the project to inherit the interface from: %s" % self.source_project_name
                )
        self.interface = target_project.get_interface(self.source_interface_name)

        if self.interface is None:
            raise Exception("Failed to find the interface to inherit: %s" % name)

        pc_logging.debug("Inherited config: %s: %s" % (name, str(config)))
        if config is None:
            config = {"": None}
        elif isinstance(config, str):
            config = {config: None}
        elif isinstance(config, list):
            if (
                len(config) == 3
                and isinstance(config[0], list)
                and len(config[0]) == 3
                and isinstance(config[1], list)
                and len(config[1]) == 3
                and (isinstance(config[2], int) or isinstance(config[2], float))
            ):
                # This is a single instance with a location
                config = {"": config}
            else:
                # This is a list of instances without locations
                # TODO(clairbee): is this practical at all?
                config = {instance_name: None for instance_name in config}
        elif not isinstance(config, dict):
            raise Exception("Invalid 'inherits' section in the interface '%s'" % self.name)
        pc_logging.debug("Normalized inherited config: %s: %s" % (name, str(config)))

        for instance_name, instance_config in config.items():
            offsets = []

            if isinstance(instance_config, dict):
                instance_location_config = instance_config.get("location", None)

                # 'port:' places this instance at a port of the object that is
                # inheriting - written instead of a location, not beside one.
                # The ports of an object are known before its 'implements:' is
                # read (see 'Interface.instantiate'), so what this names is its
                # own 'ports:' section or whatever its 'map:' externalized.
                port_name = instance_config.get("port", None)
                if port_name is not None:
                    if instance_location_config is not None:
                        pc_logging.error(
                            "%s: the instance '%s' states both a 'location' and a 'port'; the port wins"
                            % (self.name, instance_name)
                        )
                    port = self.owner_ports.get(port_name)
                    if port is None:
                        pc_logging.error(
                            "%s: the instance '%s' names the port '%s', which this object does not have"
                            % (self.name, instance_name, port_name)
                        )
                        instance_location_config = None
                    else:
                        # A port that declares no location of its own is at the
                        # origin of the object that declares it, which is what
                        # the 'is None' branch below reads it as.
                        instance_location_config = port.location

                # 'sketch:' restates the boundary of the ports this instance
                # brings in. The same opening drawn differently: a slotted hole
                # *is* a through hole - it inherits one, mates as one and keeps
                # its port - and what tells them apart is the outline, which is
                # a slot rather than a circle. Written as a reference like any
                # other, so the values go in the name:
                # 'sketch: "m-slotted;size=4,length=30"'.
                if instance_config.get("sketch", None) is not None:
                    self.sketches[instance_name] = instance_config["sketch"]

                params = instance_config.get("params", {})
                for param_name, param_value in params.items():
                    param = self.interface.params.get(param_name, None)
                    if param is not None:
                        # Extend the list of offsets to apply, if any
                        offsets.extend(param.get_offsets(param_value))
            else:
                instance_location_config = instance_config

            if instance_location_config is None:
                location = Location()
            else:
                location = Location(instance_location_config)

            # TODO(clairbee): consider resolving the parameters here: apply the offsets and drop the parameters
            # Do not apply the offsets yet?
            # if len(offsets) > 0:
            #     trsf = location.wrapped.Transformation()
            #     for offset in offsets:
            #         trsf.Multiply(offset)
            #         # trsf.Multiply(offset.Inverted())
            #     location = Location(trsf)

            self.instances[instance_name] = location
