#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-21
#
# Licensed under Apache License, Version 2.0.
#

from . import telemetry
from .geom import Location
from . import logging as pc_logging
from .utils import resolve_resource_path


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

    def __init__(self, name, project, config: dict = {}):
        self.instances = {}
        # Resolve the interface by name
        if ":" in name:
            self.source_project_name, self.source_interface_name = resolve_resource_path(
                project.name,
                name,
            )
        else:
            self.source_project_name = project.name
            self.source_interface_name = name

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
