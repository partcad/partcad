#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import math
import re

from .geom import Location
from .interface_inherit import InterfaceInherits
from .sketch import Sketch
from . import logging as pc_logging
from .utils import resolve_resource_path

from OCP.gp import (
    gp_Trsf,
    gp_Ax1,
    gp_Pnt,
    gp_Dir,
    gp_Vec,
)


class InterfacePort:
    """One of the ports provided by the interface,
    either explicitly (inside "ports:")
    or implicitly (inherited from "inherits:")."""

    name: str
    location: Location = None
    source_project_name: str
    source_sketch_name: str
    source_sketch_spec: str
    sketch: Sketch = None

    def __init__(
        self,
        name,
        project,
        config: dict = {},
        sketch: Sketch = None,
        location: Location = None,
    ):
        self.name = name

        if location is not None:
            self.location = location
        elif config.get("location", None) is not None:
            self.location = Location(config["location"])

        if sketch is not None:
            self.sketch = sketch
        elif "sketch" in config:
            if "project" in config:
                self.source_project_name = config["project"]
                if (
                    self.source_project_name == "this"
                    or self.source_project_name == ""
                ):
                    self.source_project_name = project.name
            else:
                self.source_project_name = project.name

            self.source_sketch_name = config["sketch"]
            if ":" in self.source_sketch_name:
                self.source_project_name, self.source_sketch_name = (
                    resolve_resource_path(
                        self.source_project_name,
                        self.source_sketch_name,
                    )
                )
                self.source_sketch_spec = (
                    self.source_project_name + ":" + self.source_sketch_name
                )
                self.sketch = project.ctx.get_sketch(self.source_sketch_spec)
            else:
                self.source_project_name = project.name
                self.source_sketch_spec = (
                    self.source_project_name + ":" + self.source_sketch_name
                )
                self.sketch = project.get_sketch(self.source_sketch_name)

    def __repr__(self):
        return f"<Port: {self.name}, location:{str(self.location)}>"


PARAM_MOVE = "move"
PARAM_TURN = "turn"


class InterfaceParameter:
    """One of the parameters provided by the interface,
    either explicitly (inside "parameters:")
    or implicitly (inherited from "inherits:")."""

    name: str
    dir: list[float]
    type: int = PARAM_MOVE
    min: float
    max: float
    default: float

    def __init__(self, config: dict = {}):
        self.name = config.get("name", "param")
        self.type = config.get("type", PARAM_MOVE)
        self.dir = config.get("dir", [1.0, 0.0, 0.0])
        self.min = config.get("min", 0.0)
        self.max = config.get("max", 0.0)
        self.default = config.get("default", 0.0)

    def __repr__(self):
        return f"<Parameter: {self.name}, default: {self.default}, min:{self.min}, max:{self.max}, dir:{self.dir}, type:{self.type}>"

    @staticmethod
    def config_normalize(config):
        if isinstance(config, (int, float)):
            config = {
                "min": config,
                "max": config,
                "default": config,
            }
        elif isinstance(config, list):
            new_config = {}
            new_config["min"] = config[0]
            if len(config) > 1:
                new_config["max"] = config[1]
                if len(config) > 2:
                    new_config["default"] = config[2]
            config = new_config

        elif not isinstance(config, dict):
            raise Exception("Invalid parameter configuration")

        if "default" in config:
            if "min" not in config:
                config["min"] = config["default"]
            if "max" not in config:
                config["max"] = config["default"]
        else:
            if "min" not in config:
                config["min"] = 0.0
            if "max" not in config:
                config["max"] = 0.0

            if config["min"] * config["max"] <= 0:
                config["default"] = 0.0
            else:
                config["default"] = (config["min"] + config["max"]) / 2.0

        return config

    @staticmethod
    def config_finalize(config):
        name = config.get("name", None)

        if name == "moveX":
            config["type"] = PARAM_MOVE
            config["dir"] = [1.0, 0.0, 0.0]
        elif name == "moveY":
            config["type"] = PARAM_MOVE
            config["dir"] = [0.0, 1.0, 0.0]
        elif name == "moveZ":
            config["type"] = PARAM_MOVE
            config["dir"] = [0.0, 0.0, 1.0]
        elif name == "turnX":
            config["type"] = PARAM_TURN
            config["dir"] = [1.0, 0.0, 0.0]
        elif name == "turnY":
            config["type"] = PARAM_TURN
            config["dir"] = [0.0, 1.0, 0.0]
        elif name == "turnZ":
            config["type"] = PARAM_TURN
            config["dir"] = [0.0, 0.0, 1.0]

        if not "type" in config:
            config["type"] = PARAM_MOVE

        return config

    def get_offsets(self, value):
        if self.min is not None and value < self.min:
            pc_logging.warning(
                "Parameter %s: value below minimum: %f" % (self.name, value)
            )
        if self.max is not None and value > self.max:
            pc_logging.warning(
                "Parameter %s: value above maximum: %f" % (self.name, value)
            )

        trsf = gp_Trsf()
        if self.type == PARAM_MOVE:
            if value != 0:
                trsf.SetTranslationPart(
                    gp_Vec(
                        self.dir[0] * value,
                        self.dir[1] * value,
                        self.dir[2] * value,
                    )
                )
                return [trsf]
        elif self.type == PARAM_TURN:
            if value != 0:
                trsf.SetRotation(
                    gp_Ax1(
                        gp_Pnt(),
                        gp_Dir(
                            self.dir[0],
                            self.dir[1],
                            self.dir[2],
                        ),
                    ),
                    value * math.pi / 180.0,
                )
                return [trsf]
        return []


# TODO(clairbee): introduce "Entity" as a shared parent to Shape and Interface
#                 to share "show()"
class Interface:
    """Stored as a singleton in the package and defines the interface.
    Explicitly contains all inherited ports and instances of sub-interfaces.
    """

    config: str
    config_section: str
    name: str
    full_name: str  # including project name
    desc: str
    abstract: bool
    lead_port: int

    ports: dict[str, InterfacePort]  # both own and inherited
    inherits: dict[str, InterfaceInherits] | None  # not set until instantiate()
    compatible_with: list[
        str
    ]  # list of ancestor interfaces with the same ports

    params: dict[str, InterfaceParameter]

    count: int

    def __init__(
        self,
        name: str,
        project,
        config: dict = {},
        config_section: str = "inherits",
    ):
        # TODO(clairbee): remove this circular dependency
        self.project = project

        self.config = config
        self.config_section = config_section
        self.name = name
        self.full_name = project.name + ":" + name
        self.desc = config.get("desc", "")
        self.desc = self.desc.strip() if self.desc is not None else ""
        self.abstract = config.get("abstract", False)
        self.lead_port = config.get("leadPort", None)

        self.ports = None
        self.inherits = None
        self.compatible_with = set()

        self.count = 0

        # pc_logging.debug("Initializing interface: %s" % name)

        # Initialize parameters space and freedom of movement
        # Not to be confused with specific parameter values.
        # See InterfaceInherits for values specific to a particular instance.
        self.params = {}
        params_config = config.get("parameters", None)
        if params_config is not None:
            if isinstance(params_config, list):
                params_config = {param: {} for param in params_config}
            elif not isinstance(params_config, dict):
                raise Exception(
                    "Invalid 'parameters' section in the interface '%s'"
                    % self.name
                )

            for param_name, param_config in params_config.items():
                param_config = InterfaceParameter.config_normalize(param_config)
                param_config["name"] = param_name
                param_config = InterfaceParameter.config_finalize(param_config)
                self.params[param_name] = InterfaceParameter(param_config)

        self.project.ctx.stats_interfaces += 1

    def get_ports(self):
        if self.ports is None:
            self.instantiate_ports()  # Fill in own ports
            self.instantiate()  # Get ports from parents
        return self.ports

    def instantiate_ports(self):
        self.ports = {}

        if self.config.get("ports", None) is not None:
            ports_config = self.config["ports"]
            if isinstance(ports_config, list):
                ports_config = {port_name: {} for port_name in ports_config}
            elif isinstance(ports_config, str):
                ports_config = {ports_config: {}}
            elif not isinstance(ports_config, dict):
                raise Exception(
                    "Invalid 'ports' section in the interface '%s'" % self.name
                )

            for port_name, port_config in ports_config.items():
                if isinstance(port_config, list):
                    port_config = {"location": port_config}
                self.ports[port_name] = InterfacePort(
                    port_name, self.project, port_config
                )

    def get_parents(self):
        if self.inherits is None:
            self.instantiate()
        return self.inherits

    def instantiate(self):
        self.project.ctx.stats_interfaces_instantiated += 1
        self.inherits = {}
        self.get_ports()  # Make sure self.ports is initialized

        # Initialize inheritance ("inherits" or "implements")
        inherits_config = self.config.get(self.config_section, None)
        if inherits_config is not None:
            if isinstance(inherits_config, str):
                inherits_config = {inherits_config: ""}  # {}???

            if len(inherits_config.keys()) == 1 and (
                isinstance(list(inherits_config.values())[0], str)
                or len(list(inherits_config.values())[0]) == 1
            ):
                compatible_with_parents = True
            else:
                compatible_with_parents = False

            for interface_name, interface_config in inherits_config.items():
                # Resolve the parameter values in the interface name
                def interface_template_resolve(m):
                    tmpl = m.group(1)
                    param_name = tmpl[0 : tmpl.index(":")]
                    value = self.params[param_name].default
                    if ":" in tmpl:
                        expr = tmpl[tmpl.index(":") + 1 :]
                        globals = {"__builtins__": {}}
                        locals = {"value": value}
                        value = eval(expr, globals, locals)

                    return value

                interface_name = re.sub(
                    "%([^%*]+)%",
                    interface_template_resolve,
                    interface_name,
                )

                inherit = InterfaceInherits(
                    interface_name, self.project, interface_config
                )
                if inherit.interface is None:
                    pc_logging.error(
                        "Failed to inherit interface: %s" % interface_name
                    )
                    continue
                self.inherits[inherit.name] = inherit

                if compatible_with_parents:
                    self.compatible_with.add(inherit.name)
                    self.compatible_with = self.compatible_with.union(
                        inherit.interface.compatible_with
                    )

                for (
                    instance_name,
                    instance_location,
                ) in inherit.instances.items():
                    # pc_logging.debug(
                    #     "Inherited ports: %s"
                    #     % str(inherit.interface.get_ports())
                    # )
                    for (
                        port_name,
                        port,
                    ) in inherit.interface.get_ports().items():
                        if instance_name != "":
                            inherited_port_name = (
                                instance_name + "-" + port_name
                            )
                        else:
                            inherited_port_name = port_name

                        if port.location is None:
                            port_location = instance_location
                        else:
                            trsf = port.location.wrapped.Transformation()
                            # pc_logging.debug(
                            #     "Instance location: %s" % instance_location
                            # )
                            trsf.PreMultiply(
                                instance_location.wrapped.Transformation()
                            )
                            port_location = Location(trsf)
                            # pc_logging.debug(
                            #     "Result location: %s" % port_location
                            # )
                        # pc_logging.debug(
                        #     "Inherited port from %s to %s at %s: %s"
                        #     % (
                        #         interface_name,
                        #         instance_name,
                        #         self.name,
                        #         inherited_port_name,
                        #     )
                        # )
                        self.ports[inherited_port_name] = InterfacePort(
                            inherited_port_name,
                            self.project,
                            sketch=port.sketch,
                            location=port_location,
                        )

                    # TODO(clairbee): prepend the instance name to the param name
                    # TODO(clairbee): prepend only if it's not the only instance?
                    # pc_logging.debug(
                    #     "Inherited parameters: %s"
                    #     % str(inherit.interface.params)
                    # )
                    for (
                        param_name,
                        param,
                    ) in inherit.interface.params.items():
                        self.params[param_name] = param
                    # pc_logging.debug("Result parameters: %s" % str(self.params))

        # Enrich mating information
        mates = self.config.get("mates", None)
        if not mates is None:
            if self.abstract:
                pc_logging.error(
                    "Abstract interfaces cannot have mates: %s" % self.name
                )
                return

            if isinstance(mates, str):
                mates = {mates: {}}
            elif isinstance(mates, list):
                mates = {x: {} for x in mates}
            elif not isinstance(mates, dict):
                raise Exception(
                    "Invalid 'mates' section in the interface '%s'" % self.name
                )

            self.add_mates(self.project, mates)

    def add_mates(self, project, mates: dict):
        """Handles the "mates" sub-section of this interface's config,
        or the references to this interface in top level "mates" config sections
        of any project."""
        for target_interface_name, mate_target_config in mates.items():
            if not ":" in target_interface_name:
                target_interface_name = (
                    project.name + ":" + target_interface_name
                )
            target_package_name, short_target_interface_name = (
                resolve_resource_path(project.name, target_interface_name)
            )

            if target_package_name == project.name:
                target_project = project
            else:
                target_project = project.ctx.get_project(target_package_name)
            if target_project is None:
                pc_logging.error(
                    "Failed to find the target package for %s: %s"
                    % (target_interface_name, target_package_name)
                )
                continue
            target_interface = target_project.get_interface(
                short_target_interface_name
            )
            if target_interface is None:
                pc_logging.error(
                    "Failed to find the target interface: %s"
                    % target_interface_name
                )
                continue
            if target_interface.abstract:
                pc_logging.error(
                    "Cannot mate with an abstract interface: %s"
                    % target_interface_name
                )
                continue
            project.ctx.add_mate(self, target_interface, mate_target_config)

    async def test_async(self):
        return self.test()

    def test(self):
        _ = self.get_ports()

    def info(self):
        info = {
            "name": self.name,
            "desc": self.desc,
            "ports": list(self.get_ports().values()),
            "parameters": list(self.params.values()),
            "inherits": self.get_parents(),
        }
        if self.abstract:
            info["abstract"] = True
        if self.lead_port is not None:
            info["leadPort"] = self.lead_port
        return info

    async def get_components(self):
        components = []
        for port in self.get_ports().values():
            components.append(port.location)
            if port.sketch is not None:
                sketch_components = list(await port.sketch.get_components())

                def move_component(component, move_components):
                    nonlocal port
                    if isinstance(component, list):
                        component = move_components(component)
                    else:
                        component = component.Located(port.location.wrapped)
                    return component

                def move_components(components):
                    components = list(
                        map(
                            lambda x: move_component(x, move_components),
                            components,
                        )
                    )
                    return components

                sketch_components = move_components(sketch_components)
                components.append(sketch_components)
        return components

    async def show_async(self):
        components = []
        try:
            components = await self.get_components()
        except Exception as e:
            pc_logging.error(e)

        if len(components) != 0:
            import importlib

            ocp_vscode = importlib.import_module("ocp_vscode")
            if ocp_vscode is None:
                pc_logging.warning(
                    'Failed to load "ocp_vscode". Giving up on connection to VS Code.'
                )
            else:
                try:
                    pc_logging.info('Visualizing in "OCP CAD Viewer"...')
                    ocp_vscode.show(
                        *components,
                        progress=None,
                        # TODO(clairbee): make showing (and the connection
                        # to ocp_vscode) a part of the context, and memorize
                        # which part was displayed last. Keep the camera
                        # if the part has not changed.
                        # reset_camera=ocp_vscode.Camera.KEEP,
                    )
                except Exception as e:
                    pc_logging.warning(e)
                    pc_logging.warning(
                        'No VS Code or "OCP CAD Viewer" extension detected.'
                    )

    def show(self):
        asyncio.run(self.show_async())
