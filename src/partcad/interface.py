#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import threading

from . import config as pc_config
from . import expr, interface_config
from . import logging as pc_logging
from . import telemetry
from .geom import Location
from .interface_inherit import InterfaceInherits
from .sketch import Sketch
from .utils import resolve_resource_path

# OCP is not imported at module scope: this module is on the 'import partcad'
# path, and only the two viewer/parameter paths below actually need OCCT, which
# import it lazily.


def port_location(port) -> Location:
    """A port's placement, defaulting to the identity.

    'InterfacePort.location' is only set when the port declares one, so a port
    that sits at its interface's origin - which is most of them, and every port
    inherited without a placement - leaves it None. None is not a location, and
    a port declared by name alone ("grip:") is at the origin of the object that
    declares it rather than nowhere: every reader of a port's placement goes
    through here, so that "at the origin" is what they all see.
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
    # The parameter values this port asks its sketch for, if any. Kept so that
    # 'pc info' reports what the port was built from rather than only the name
    # it resolved to.
    sketch_params: dict

    def __init__(
        self,
        name,
        project,
        config: dict = {},
        sketch: Sketch = None,
        location: Location = None,
        sketch_params: dict = None,
    ):
        self.name = name
        self.sketch_params = dict(sketch_params) if sketch_params else {}

        if location is not None:
            self.location = location
        elif config.get("location", None) is not None:
            self.location = Location(config["location"])

        if sketch is not None:
            self.sketch = sketch
            self.source_project_name = self.sketch.project_name
        elif "sketch" in config:
            # The values to build the sketch with. Declared beside the sketch
            # ('params:') or spelled into its name ('m;size=3'); either way
            # they end up as the parameters of the instance the port gets,
            # which is what makes one sketch serve a whole family of ports
            # instead of one pre-generated sketch per size.
            declared_params = config.get("params") or {}
            # Formatted the way an expression writes a value, so that the
            # instance a port asks for is the instance somebody asking for it by
            # hand gets: a size of 4.0 is the sketch 'm;size=4', not a second
            # 'm;size=4.0' beside it.
            self.sketch_params = {
                **self.sketch_params,
                **{param_name: expr.format_value(value) for param_name, value in declared_params.items()},
            }

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
                self.sketch = project.ctx.get_sketch(self.source_sketch_spec, self.sketch_params or None)
            else:
                self.source_project_name = project.name
                self.source_sketch_spec = self.source_project_name + ":" + self.source_sketch_name
                self.sketch = project.get_sketch(self.source_sketch_name, self.sketch_params or None)

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

        if "type" not in config:
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
    # The ancestor interfaces this one is a drop-in for - same ports, same
    # names - which is what lets a connection made to one of them be made to
    # this one. Read through the 'compatible_with' property below, which is
    # what closes it over the ancestors' own.
    _compatible_with: set[str]

    params: dict[str, InterfaceParameter]

    # The construction half of 'parameters:' and the values this interface was
    # built with: what a reference such as 'm-thru;size=4,depth=3' sets, and
    # what a part or a sketch declares in the section of the same name. Empty
    # for an interface that declares only freedom of movement, which is every
    # interface written before this existed. See 'partcad.interface_config' for
    # how the two halves of one section are told apart.
    construction_params: dict
    construction_values: dict

    # The interface this one is another name for, if it is one.
    alias: str | None

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

        # The values this interface is built from, and the expressions that
        # read them, resolved before anything below looks at the declaration.
        # Everything after this point - the ports, their sketches, the
        # interfaces inherited, what this one mates with - reads a declaration
        # in which '%size%' is already the number it stands for.
        self.construction_params = self.declared_construction_params(config)
        self.construction_values = pc_config.parameter_values(self.construction_params)
        config = self._resolve_expressions(config, name, project)

        self.config = config
        self.config_section = config_section
        self.name = name
        self.full_name = project.name + ":" + name

        # 'alias: <interface>' - this interface *is* that one, under another
        # name. What it inherits is that one interface, exactly once, at the
        # origin, with no instance name - which is what makes the ports come
        # through under the names they already have rather than prefixed - and
        # what it does not declare for itself, it takes from it. See
        # 'instantiate()', where both halves of that happen.
        #
        # It is how a package that has published a name keeps publishing it
        # after the family behind it becomes parametric: 'm3-thru-3' is
        # 'm-thru;size=3,depth=3' spelled the way it always was.
        self.alias = config.get(interface_config.ALIAS, None)

        self._desc = config.get("desc", "")
        self._desc = self._desc.strip() if self._desc is not None else ""
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
        # option: "multiConnect"
        # description: whether more than one item may be connected to the same
        #              instance of this interface. False for a joint that is
        #              made once - a bolt in a hole, a stud under a brick -
        #              and true for one that is not, such as a shaft carrying
        #              several parts along its length, or a rail.
        # values: boolean
        # default: false
        # None when the option is absent, the boolean when it is given. The
        # difference matters: an interface that inherits 'multiConnect: true'
        # has to be able to say 'false' and be believed, and a stored False
        # that means "not set" cannot be told from one that means "no".
        self.multi_connect = bool(config["multiConnect"]) if "multiConnect" in config else None

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
        self._compatible_with = set()

        # pc_logging.debug("Initializing interface: %s" % name)

        # Initialize parameters space and freedom of movement
        # Not to be confused with specific parameter values.
        # See InterfaceInherits for values specific to a particular instance.
        #
        # The freedom-of-movement half of 'parameters:' only. The construction
        # half of the same section - 'size', 'depth' - is read above and is not
        # an offset to compose into a connection; 'partcad.interface_config'
        # says how the two are told apart.
        self.params = {}
        params_config = config.get(interface_config.PARAMETERS, None)
        if params_config is not None:
            # The list short form is expanded by 'InterfaceConfiguration.normalize',
            # which every reader of this config goes through first.
            if not isinstance(params_config, dict):
                raise Exception("Invalid 'parameters' section in the interface '%s'" % self.name)

            for param_name, param_config in self.declared_movement_params(config).items():
                param_config = InterfaceParameter.config_normalize(param_config)
                param_config["name"] = param_name
                param_config = InterfaceParameter.config_finalize(param_config)
                self._check_movement_range(param_name, param_config)
                self.params[param_name] = InterfaceParameter(param_config)

        self.lock = threading.RLock()

    def _check_movement_range(self, param_name, param_config) -> None:
        """A range that runs backwards is a mistake in the declaration, not a freedom.

        It is reachable because a bound may be computed: the published
        '//pub/std/metric/m' says a screw may be driven in 'length - 2', which
        for the 1mm screws in its own list is -1. A solver handed 0..-1 has no
        value to choose, so the range is reported and read as "no movement"
        - which is what the interface had before a child's own 'parameters:'
        took precedence over the inherited one.
        """
        try:
            low, high = float(param_config["min"]), float(param_config["max"])
        except (TypeError, ValueError):
            return
        if high >= low:
            return
        pc_logging.warning(
            "%s: '%s' may move from %s to %s, which is backwards: read as no movement"
            % (self.full_name, param_name, param_config["min"], param_config["max"])
        )
        param_config["max"] = param_config["min"]
        if float(param_config.get("default", low)) > low:
            param_config["default"] = param_config["min"]

    # The sections of a declaration that '%...%' expressions are resolved in.
    #
    # A list rather than "everything", because '%' is an ordinary character
    # elsewhere: a percent-encoded URL and a description that mentions a
    # percentage both contain pairs of them, and neither is an expression. What
    # is here is what describes the connection - where its ports are, what it is
    # built out of, what it mates with - which is what a parameter of an
    # interface has anything to say about.
    #
    # 'parameters' is here so that the freedom of movement may be stated in
    # terms of the values: an M4 screw 12mm long may be driven '%length - 2%'
    # in. The construction half is exempted inside '_resolve_expressions',
    # because that half is what the expressions are evaluated over.
    #
    # 'physics' is deliberately not here. It is a table of simulation constants
    # rather than a description of the connection's shape, and every one of its
    # two dozen numbers would have to accept an expression in the schema for
    # 'pc lint' to agree with what is accepted here.
    EXPRESSION_SECTIONS = (
        "desc",
        "ports",
        "inherits",
        "implements",
        "mates",
        interface_config.PARAMETERS,
        interface_config.ALIAS,
        "leadPort",
        "threadStep",
        "selfScrew",
        "multiConnect",
        "motion",
    )

    @property
    def compatible_with(self) -> set[str]:
        """Every interface this one is a drop-in for, all the way up.

        Closed over the ancestors rather than accumulated while inheriting,
        because inheriting only *creates* the parent - instantiating it is what
        fills in what it is in turn compatible with, and that had not happened
        yet. The chain therefore used to stop at the first parent, so an
        'm4-thru-3' reached 'm4-thru' and no further: a screw that mates with
        'm4-opening' did not find the hole in front of it.

        An interface hierarchy is a DAG rather than a tree, so 'seen' keeps the
        walk from going round.
        """
        return self._compatible_closure()

    def _compatible_closure(self, seen=None) -> set[str]:
        if self.inherits is None:
            self.instantiate()
        if seen is None:
            seen = set()
        if self.full_name in seen:
            return set()
        seen.add(self.full_name)

        closure = set(self._compatible_with)
        for name in list(self._compatible_with):
            inherit = (self.inherits or {}).get(name)
            parent = getattr(inherit, "interface", None)
            if parent is not None:
                closure |= parent._compatible_closure(seen)
        return closure

    @property
    def desc(self) -> str:
        """This interface's description, or the one it is an alias for.

        Resolved on the way out rather than in '__init__' because resolving it
        means resolving the alias target, and an interface is built without
        touching anything else it names - a package holds eleven thousand of
        them and a description is not a reason to instantiate them all.
        'pc list interfaces' reads this, so an alias that says nothing of its
        own still reads as what it is.
        """
        if self._desc or not self.alias:
            return self._desc
        for inherit in (self.get_parents() or {}).values():
            target = getattr(inherit, "interface", None)
            if target is not None and target.desc:
                return target.desc
        return self._desc

    @desc.setter
    def desc(self, value: str) -> None:
        self._desc = value

    def declared_construction_params(self, config: dict) -> dict:
        """The construction half of this object's 'parameters:' section.

        An interface's 'parameters:' holds two kinds and they are told apart by
        what each declares; see 'partcad.interface_config'. A part or an
        assembly declares only the one kind there - it is a shape, and a shape's
        'parameters:' are the values it is built from - so 'WithPorts' answers
        with the whole section; see 'WithPorts.declared_construction_params'.
        """
        return interface_config.construction_parameters(config.get(interface_config.PARAMETERS))

    def declared_movement_params(self, config: dict) -> dict:
        """The freedom-of-movement half of this object's 'parameters:' section."""
        return interface_config.movement_parameters(config.get(interface_config.PARAMETERS))

    def expression_values(self, config: dict = None) -> dict:
        """The names a '%...%' expression in this declaration may use.

        The object's own construction parameters - the same values
        'm-thru;size=4' sets and the same ones a CAD script is handed.

        'config' is passed while the object is still being built, before
        'self.config' exists: resolving the declaration is the first thing
        '__init__' does, because everything it reads afterwards has to be the
        resolved text.
        """
        return self.construction_values

    def _resolve_expressions(self, config: dict, name: str, project):
        """Substitute this interface's parameter values into its declaration.

        Only for an interface that declares parameters at all. An interface
        that does not is handed back untouched, expressions and all: a package
        written before any of this existed must not start reporting errors
        about a percent sign it has always had.
        """
        if not isinstance(config, dict):
            return config
        values = self.expression_values(config)
        if not values:
            return config

        where = "%s:%s" % (getattr(project, "name", "?"), name)
        resolved = dict(config)
        for key in self.EXPRESSION_SECTIONS:
            if key not in config:
                continue
            if key == interface_config.PARAMETERS:
                # The construction half is what the expressions are evaluated
                # over, so resolving it would be resolving a thing against
                # itself. The freedom-of-movement half beside it is resolved
                # like anything else.
                declared = config[key] or {}
                movement, construction = interface_config.split_parameters(declared)
                resolved[key] = {**construction, **expr.resolve(movement, values, where)}
                continue
            resolved[key] = expr.resolve(config[key], values, where)
        return resolved

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
        self.instantiate_declared_ports()

    def instantiate_declared_ports(self):
        """The ports this object's own 'ports:' section declares.

        Split from 'instantiate_ports' so that an object with ports from
        somewhere else - an assembly's 'map:' - fills those in first and then
        lets its own declaration have the last word on a name they both use.
        """
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
                if port_name in self.ports:
                    pc_logging.warning(
                        "%s: the port '%s' is both declared in 'ports:' and produced by 'map:'; "
                        "the declaration wins" % (self.full_name, port_name)
                    )
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

    def get_multi_connect(self):
        """Whether one instance of this interface may take more than one item.

        A stud takes one brick and a bolt hole takes one bolt, so two items
        connected to the same port is a mistake worth reporting. A shaft is the
        counter-example - several parts sit along it, all mated to the same
        interface - and says so with 'multiConnect: true'. Inherited, so that
        declaring it once on the interface a family derives from covers the
        family.
        """
        # Only None is silence here, so 'multiConnect: false' on a child
        # overrides a parent that allows many rather than being skipped over.
        return bool(self._inherited("multi_connect", unset=(None,)))

    def _inherited(self, attribute, seen=None, unset=(None, False)):
        """The attribute as declared here, or the first one found among the parents.

        'unset' says which stored values mean "nothing was declared here". It
        includes False by default because most of these attributes store False
        for an absent option and cannot tell that from an explicit one. An
        attribute that does keep the difference - storing None when absent -
        passes 'unset=(None,)' so that an explicit False overrides a parent
        rather than being read as silence.
        """
        value = getattr(self, attribute, None)
        if value not in unset:
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
            inherited = parent._inherited(attribute, seen, unset)
            if inherited not in unset:
                return inherited
        return value

    def instantiate(self):
        self.project.ctx.stats_interfaces_instantiated += 1
        self.inherits = {}
        if self.ports is None:
            # Make sure self.ports is initialized, without going through
            # 'get_ports()': that calls this method in turn, and the second pass
            # over the parents would adopt every one of them twice.
            self.instantiate_ports()

        # What this interface declares for itself, before anything is inherited
        # into it. Read now rather than tested against the configuration later,
        # because the parents are merged into the very dictionary being tested.
        own_param_names = set(self.params.keys())

        # Before the declared ones, so that an interface an assembly
        # externalizes is already among its parents while 'implements:' is read
        # and can be refined by it rather than colliding with it.
        for inherit in self.inherited_from_elsewhere().values():
            self.adopt_inherit(inherit, own_param_names)

        # Initialize inheritance ("inherits" or "implements")
        inherits_config = self.config.get(self.config_section, None)
        if self.alias is not None and inherits_config is not None:
            pc_logging.error(
                "The interface '%s' declares both an alias and a '%s' section; the alias is ignored"
                % (self.full_name, self.config_section)
            )
        if self.alias is not None and inherits_config is None:
            # An alias is that one interface, once, unnamed, at the origin -
            # which is the shape of inheritance that leaves the ports named
            # exactly as the target names them and marks this interface a
            # drop-in for it ('compatible_with' below). So it is spelled as
            # inheritance rather than implemented twice.
            inherits_config = {self.alias: None}
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

            # The names of the interfaces inherited may be expressions over this
            # interface's parameters. The freedom-of-movement parameters count
            # here as well as the construction ones: '%moveX%' and
            # '%moveX:value*2%' have named one since interfaces were introduced,
            # and those two spellings are what 'partcad.expr' keeps working.
            names = {
                **{param_name: param.default for param_name, param in self.params.items()},
                **self.expression_values(),
            }

            for interface_name, inherited_config in inherits_config.items():
                interface_name = expr.resolve(interface_name, names, self.full_name)

                inherit = InterfaceInherits(interface_name, self.project, inherited_config, ports=self.ports)
                if inherit.interface is None:
                    pc_logging.error("Failed to inherit interface: %s" % interface_name)
                    continue

                if compatible_with_parents:
                    # Only the parent itself. What *it* is a drop-in for is
                    # added by the property below, which reads it once this
                    # interface is asked - the parent has been created here but
                    # not instantiated, so its own set is still empty.
                    self._compatible_with.add(inherit.name)

                self.adopt_inherit(inherit, own_param_names)

        if self.alias is not None:
            self._adopt_alias_target()

        # Enrich mating information
        mates = self.config.get("mates", None)
        if mates is not None:
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

    def inherited_from_elsewhere(self) -> dict:
        """The interfaces this object gets from somewhere other than its own declaration.

        Empty for an interface: an interface inherits what its 'inherits:' says
        and nothing else. An assembly's 'map:' externalizes an instance of an
        interface that one of its children implements, and that instance has to
        arrive here - as an 'InterfaceInherits' like any other - so that it gets
        its ports named, its parameters merged and its ancestors walked by the
        very code that serves 'implements:'. See 'WithPorts'.
        """
        return {}

    def adopt_inherit(self, inherit, own_param_names: set) -> None:
        """Take one inherited (or externalized) interface into this object.

        Records it among the parents, creates a port of this object for every
        port of every instance, and merges in the freedom of movement it
        declares. Called once per entry of 'inherits:'/'implements:', and once
        per interface a 'map:' externalizes - there is one way an interface
        becomes part of an object, and this is it.

        An interface named twice - mapped and implemented, or written twice
        under two spellings of one name - merges rather than replaces: the
        instances of both are instances of this object.
        """
        existing = self.inherits.get(inherit.name)
        if existing is None:
            self.inherits[inherit.name] = inherit
        else:
            for instance_name, instance_location in inherit.instances.items():
                if instance_name in existing.instances:
                    pc_logging.error(
                        "%s: the instance '%s' of the interface '%s' is declared more than once"
                        % (self.full_name, instance_name, inherit.name)
                    )
                    continue
                existing.instances[instance_name] = instance_location
                if instance_name in inherit.sketches:
                    existing.sketches[instance_name] = inherit.sketches[instance_name]

        for instance_name, instance_location in inherit.instances.items():
            for port_name, port in inherit.interface.get_ports().items():
                if instance_name != "":
                    inherited_port_name = instance_name + "-" + port_name
                else:
                    inherited_port_name = port_name

                if port.location is None:
                    inherited_location = instance_location
                else:
                    # The inherited port sits at the instance's location
                    # composed with the port's own: apply the port first,
                    # then the instance. Pure-Python composition, no OCP.
                    inherited_location = instance_location * port.location

                # The boundary this instance draws with, where it restates it
                # ('sketch:' beside the instance), and the inherited one
                # otherwise. A slotted hole is a through hole with a slot for an
                # outline; see 'InterfaceInherits'.
                restated = inherit.sketches.get(instance_name)
                if restated is None:
                    port_sketch, port_sketch_params = port.sketch, port.sketch_params
                else:
                    restated_port = InterfacePort(
                        inherited_port_name,
                        self.project,
                        config={"sketch": restated},
                    )
                    port_sketch, port_sketch_params = (
                        restated_port.sketch,
                        restated_port.sketch_params,
                    )

                self.ports[inherited_port_name] = InterfacePort(
                    inherited_port_name,
                    self.project,
                    sketch=port_sketch,
                    location=inherited_location,
                    sketch_params=port_sketch_params,
                )

            # TODO(clairbee): prepend the instance name to the param name
            # TODO(clairbee): prepend only if it's not the only instance?
            for param_name, param in inherit.interface.params.items():
                # What this interface says about a parameter wins over what it
                # inherits about it. An M4 screw 12mm long narrows the 'moveZ'
                # it gets from the abstract 'm4' to how far *this* screw can
                # still be driven in, and taking the parent's back would put the
                # narrowing back to nothing - which is what used to happen,
                # silently, to every interface that refined an inherited
                # parameter.
                if param_name in own_param_names:
                    continue
                self.params[param_name] = param

    def _adopt_alias_target(self):
        """Take from the alias target whatever this interface does not state itself.

        Only what is not inherited some other way. 'threadStep', 'selfScrew'
        and 'multiConnect' already walk the parents ('_inherited'), and the
        ports and the parameters arrive through the inheritance an alias is
        spelled as. What is left is the handful of things an interface states
        rather than derives, and which a second name for one interface has no
        business answering differently: which port leads, whether it is
        abstract, and what kind of joint it is.
        """
        target = None
        for inherit in (self.inherits or {}).values():
            candidate = getattr(inherit, "interface", None)
            if candidate is not None:
                target = candidate
                break
        if target is None:
            return

        if self.lead_port is None:
            self.lead_port = target.lead_port
        if "abstract" not in self.config:
            self.abstract = target.abstract
        if self.motion is None:
            self.motion = target.motion
        if self.physics is None:
            self.physics = target.physics

    def add_mates(self, project, mates: dict):
        """Handles the "mates" sub-section of this interface's config,
        or the references to this interface in top level "mates" config sections
        of any project."""
        for target_interface_name, mate_target_config in mates.items():
            if ":" not in target_interface_name:
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
        if self.construction_params:
            # What this instance was built from, not what could be asked for:
            # 'pc info -i m-thru;size=4' has to show the 4 it resolved. Reported
            # apart from "parameters" above, which is the freedom of movement.
            info["values"] = dict(self.expression_values())
        if self.alias:
            info["alias"] = self.alias
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
                components.append(place_components(sketch_components, port_location(port)))
        return components

    def get_markers(self):
        """The ports' coordinate frames, as packed locations.

        A port is a frame, and a frame has no geometry to tessellate - glTF has
        no primitive for one. They are sent to the viewer alongside the geometry
        so it can draw axes at each, which is what showing a bare 'port.location'
        used to produce.
        """
        return [{"name": name, "location": port_location(port).as_packed()} for name, port in self.get_ports().items()]

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
