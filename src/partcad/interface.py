#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import re

import threading

from .geom import Location
from .interface_inherit import InterfaceInherits
from .sketch import Sketch
from . import logging as pc_logging
from .utils import resolve_resource_path
from . import telemetry

# OCP is not imported at module scope: this module is on the 'import partcad'
# path, and only the two viewer/parameter paths below actually need OCCT, which
# import it lazily.


def _port_location(port) -> Location:
    """A port's placement, defaulting to the identity.

    'InterfacePort.location' is only set when the port declares one, so a port
    that sits at its interface's origin - which is most of them, and every port
    inherited without a placement - leaves it None.
    """
    return port.location if port.location is not None else Location()


def place_components(components, placement: Location):
    """The shape envelopes of 'components', moved by 'placement'.

    The envelopes stay envelopes: the placement is composed onto whatever
    placement each one already carries and travels on as plain data
    (KEY_LOCATION), exactly as an assembly places its children, so it becomes a
    real transform only once a sandbox decodes the envelope. That is what keeps
    this - and the core process - free of OCP.

    Shared by 'Interface.get_components()', which places an interface's port
    sketches onto its ports for the viewer, and by 'render_overlay', which
    places the same sketches for a projection.
    """
    from . import shape_envelope

    if isinstance(components, list):
        return [place_components(item, placement) for item in components]
    if not shape_envelope.is_shape_envelope(components):
        # Not geometry (a null a factory produced, say); nothing to place.
        return components
    own = components.get(shape_envelope.KEY_LOCATION)
    composed = placement if own is None else (placement * Location(own))
    moved = dict(components)
    moved[shape_envelope.KEY_LOCATION] = composed.as_packed()
    return moved


@telemetry.instrument()
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
            self.source_project_name = self.sketch.project_name
        elif "sketch" in config:
            if "project" in config:
                self.source_project_name = config["project"]
                if self.source_project_name == "this" or self.source_project_name == "":
                    self.source_project_name = project.name
                else:
                    self.source_project_name = project.relocate(self.source_project_name)
            else:
                self.source_project_name = project.name

            self.source_sketch_name = config["sketch"]
            if ":" in self.source_sketch_name:
                # The reference is resolved against the package named above,
                # but it was authored by 'project', so relocate it as such.
                self.source_project_name, self.source_sketch_name = resolve_resource_path(
                    self.source_project_name,
                    project.relocate(self.source_sketch_name),
                )
                self.source_sketch_spec = self.source_project_name + ":" + self.source_sketch_name
                self.sketch = project.ctx.get_sketch(self.source_sketch_spec)
            else:
                self.source_project_name = project.name
                self.source_sketch_spec = self.source_project_name + ":" + self.source_sketch_name
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
        """
        TODO: This logic should be part of the part normalization process to maintain
        consistency. Performing it separately doesn't make sense and may lead to
        inconsistencies.
        """
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
            pc_logging.warning("Parameter %s: value below minimum: %f" % (self.name, value))
        if self.max is not None and value > self.max:
            pc_logging.warning("Parameter %s: value above maximum: %f" % (self.name, value))

        # The freedom-of-movement offset is a rigid transform that the assembly
        # connection logic composes into the connection location. It is a
        # pc.Location built with pure-Python math - no OCP. A "move" is a pure
        # translation; a "turn" is a rotation about 'dir' through the origin.
        if self.type == PARAM_MOVE:
            if value != 0:
                return [
                    Location(
                        (self.dir[0] * value, self.dir[1] * value, self.dir[2] * value),
                        (0, 0, 1),
                        0,
                    )
                ]
        elif self.type == PARAM_TURN:
            if value != 0:
                return [Location((0, 0, 0), (self.dir[0], self.dir[1], self.dir[2]), value)]
        return []


# TODO(clairbee): introduce "Entity" as a shared parent to Shape and Interface
#                 to share "show()"
@telemetry.instrument()
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
    compatible_with: list[str]  # list of ancestor interfaces with the same ports

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

        # What this connection allows and what it costs. 'motion' states the
        # freedom of movement (type, axis, position and soft limits, mimic) and
        # 'physics' what moving it costs (effort and velocity limits, damping,
        # friction, spring and solver parameters). Both are closed sets of named
        # properties in PartCAD's own units - degrees and millimetres, SI for
        # the rest - defined in partcad_utils/schema/partcad.json; a format that states
        # something outside them fails the import rather than being carried
        # under a name of its own.
        #
        # 'parameters' below is the executable counterpart: where 'motion' is a
        # record, a parameter actually moves the parts when a connection names
        # it. A URDF import writes both, so the joint is described *and* usable.
        self.motion = config.get("motion", None)
        self.physics = config.get("physics", None)

        # How a connection made through this interface advances: the axial
        # distance per full turn, in mm, and whether the interface cuts its own
        # thread rather than matching one. Both are inherited from the parent
        # interfaces when this one does not declare them, so a thread only has
        # to be spelled out once, on the interface that introduces it.
        self.thread_step = config.get("threadStep", None)
        if self.thread_step is not None:
            if isinstance(self.thread_step, bool) or not isinstance(self.thread_step, (int, float)):
                pc_logging.error("Interface %s: 'threadStep' must be a number, ignoring: %s" % (name, self.thread_step))
                self.thread_step = None
            elif self.thread_step < 0.0:
                pc_logging.error("Interface %s: 'threadStep' must not be negative, ignoring" % name)
                self.thread_step = None
            else:
                self.thread_step = float(self.thread_step)
        self.self_screw = bool(config.get("selfScrew", False))

        self.ports = None
        self.inherits = None
        self.compatible_with = set()

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
                raise Exception("Invalid 'parameters' section in the interface '%s'" % self.name)

            for param_name, param_config in params_config.items():
                param_config = InterfaceParameter.config_normalize(param_config)
                param_config["name"] = param_name
                param_config = InterfaceParameter.config_finalize(param_config)
                self.params[param_name] = InterfaceParameter(param_config)

        self.project.ctx.stats_interfaces += 1
        self.lock = threading.RLock()

    def matches(self, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()

        if keyword in str(self.config).lower() or keyword in self.name.lower():
            return True
        return False

    def get_ports(self):
        # TODO(clairbee): make interface a Shape and switch to existing sync mechanisms
        with self.lock:
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
                raise Exception("Invalid 'ports' section in the interface '%s'" % self.name)

            for port_name, port_config in ports_config.items():
                if port_config is None:
                    # A port declared by name alone ("joint:"), which the schema
                    # allows: it sits at the interface origin and whatever
                    # implements the interface decides where that is.
                    port_config = {}
                elif isinstance(port_config, list):
                    port_config = {"location": port_config}
                self.ports[port_name] = InterfacePort(port_name, self.project, port_config)

    def get_parents(self):
        if self.inherits is None:
            self.instantiate()
        return self.inherits

    def get_thread_step(self):
        """This interface's thread step, its own or the one it inherits."""
        return self._inherited("thread_step")

    def get_self_screw(self):
        """Whether this interface cuts its own thread, its own setting or inherited."""
        return bool(self._inherited("self_screw"))

    def _inherited(self, attribute, seen=None):
        """The attribute as declared here, or the first one found among the parents."""
        value = getattr(self, attribute, None)
        if value is not None and value is not False:
            return value

        # An interface hierarchy is a DAG rather than a tree, so the same parent
        # can be reached twice; the 'seen' set keeps that from looping.
        if seen is None:
            seen = set()
        if self.full_name in seen:
            return value
        seen.add(self.full_name)

        for inherit in (self.get_parents() or {}).values():
            parent = getattr(inherit, "interface", None)
            if parent is None:
                continue
            inherited = parent._inherited(attribute, seen)
            if inherited is not None and inherited is not False:
                return inherited
        return value

    def instantiate(self):
        self.project.ctx.stats_interfaces_instantiated += 1
        self.inherits = {}
        self.get_ports()  # Make sure self.ports is initialized

        # Initialize inheritance ("inherits" or "implements")
        inherits_config = self.config.get(self.config_section, None)
        if inherits_config is not None:
            if isinstance(inherits_config, str):
                inherits_config = {inherits_config: ""}  # {}???

            # Inheriting exactly one interface, exactly once, makes this one a
            # drop-in for it. 'None' is that case spelled shortest: a single
            # unnamed instance at the origin ("implements: {m3-screw:}").
            values = list(inherits_config.values())
            only = values[0] if len(values) == 1 else None
            compatible_with_parents = len(inherits_config.keys()) == 1 and (
                only is None or isinstance(only, str) or len(only) == 1
            )

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

                inherit = InterfaceInherits(interface_name, self.project, interface_config)
                if inherit.interface is None:
                    pc_logging.error("Failed to inherit interface: %s" % interface_name)
                    continue
                self.inherits[inherit.name] = inherit

                if compatible_with_parents:
                    self.compatible_with.add(inherit.name)
                    self.compatible_with = self.compatible_with.union(inherit.interface.compatible_with)

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
                            inherited_port_name = instance_name + "-" + port_name
                        else:
                            inherited_port_name = port_name

                        if port.location is None:
                            port_location = instance_location
                        else:
                            # The inherited port sits at the instance's location
                            # composed with the port's own: apply the port first,
                            # then the instance. Pure-Python composition, no OCP.
                            port_location = instance_location * port.location
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
                pc_logging.error("Abstract interfaces cannot have mates: %s" % self.name)
                return

            if isinstance(mates, str):
                mates = {mates: {}}
            elif isinstance(mates, list):
                mates = {x: {} for x in mates}
            elif not isinstance(mates, dict):
                raise Exception("Invalid 'mates' section in the interface '%s'" % self.name)

            self.add_mates(self.project, mates)

    def add_mates(self, project, mates: dict):
        """Handles the "mates" sub-section of this interface's config,
        or the references to this interface in top level "mates" config sections
        of any project."""
        for target_interface_name, mate_target_config in mates.items():
            if not ":" in target_interface_name:
                target_interface_name = project.name + ":" + target_interface_name
            target_package_name, short_target_interface_name = project.resolve(target_interface_name)

            if target_package_name == project.name:
                target_project = project
            else:
                target_project = project.ctx.get_project(target_package_name)
            if target_project is None:
                pc_logging.error(
                    "Failed to find the target package for %s: %s" % (target_interface_name, target_package_name)
                )
                continue
            target_interface = target_project.get_interface(short_target_interface_name)
            if target_interface is None:
                pc_logging.error("Failed to find the target interface: %s" % target_interface_name)
                continue
            if target_interface.abstract:
                pc_logging.error("Cannot mate with an abstract interface: %s" % target_interface_name)
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
        if self.motion is not None:
            info["motion"] = self.motion
        if self.physics is not None:
            info["physics"] = self.physics
        return info

    async def get_components(self, ctx):
        """This interface's port sketches, each moved onto its port.

        This is a viewer-only path (Interface.show); 'render_overlay' does the
        same for a projection. The sketch components stay BREP envelopes - see
        'place_components()' above for why.
        """
        components = []
        for port in self.get_ports().values():
            if port.sketch is not None:
                sketch_components = list(await port.sketch.get_components(ctx))
                components.append(place_components(sketch_components, _port_location(port)))
        return components

    def get_markers(self):
        """The ports' coordinate frames, as packed locations.

        A port is a frame, and a frame has no geometry to tessellate - glTF has
        no primitive for one. They are sent to the viewer alongside the geometry
        so it can draw axes at each, which is what showing a bare 'port.location'
        used to produce.
        """
        return [{"name": name, "location": _port_location(port).as_packed()} for name, port in self.get_ports().items()]

    async def show_async(self, ctx=None):
        components = []
        try:
            components = await self.get_components(ctx)
        except Exception as e:
            pc_logging.error(e)

        markers = self.get_markers()
        if len(components) != 0 or len(markers) != 0:
            from . import viewer

            await viewer.show(
                ctx, components, name=self.name, kind="interface", package=self.project.name, markers=markers
            )

    def show(self, ctx=None):
        asyncio.run(self.show_async(ctx))
