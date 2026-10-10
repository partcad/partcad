#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

from . import logging as pc_logging
from .interface import Interface


class Mating:
    """A mating between two interfaces."""

    source: Interface
    target: Interface
    desc: str
    count: int
    self_screw: bool
    snap_in: bool

    source_port_selector: str
    target_port_selector: str

    def __init__(
        self,
        source: Interface,
        target: Interface,
        config: dict = {},
        reverse: bool = False,
    ):
        if config is None:
            config = {}
        elif isinstance(config, str):
            config = {config: None}
        elif isinstance(config, list):
            config = {c: None for c in config}
        elif not isinstance(config, dict):
            raise ValueError("Invalid mating configuration")

        self.source = source
        self.target = target
        # As declared, and which way round: what an assembly that connects
        # through this mating is keyed on (see 'AssemblyFactoryAssy').
        self.config = config
        self.reverse = reverse
        self.desc = config["desc"] if "desc" in config else ""
        # Whether a thread gets *cut* by making this connection rather than
        # matched, which is what lets the two ends carry different threads - or
        # one of them none at all. Declared here rather than on either
        # interface because it is true of the pairing and not of the part: a
        # self-tapping screw cuts its thread in the pilot hole it is driven
        # into, and cuts nothing on its way through a clearance hole.
        self.self_screw = bool(config.get("selfScrew", False)) if isinstance(config, dict) else False

        # option: "selfScrew"
        # description: whether joining these two interfaces cuts a thread that
        #              neither of them has. An interface can say this of itself
        #              when it is true wherever the interface is used - a
        #              self-tapping screw - but the common case is a pairing:
        #              an M8 screw in an M8 tapped hole cuts nothing, and the
        #              same screw in a plain M8 opening cuts its own thread.
        #              Only the mating knows that, so it is said here.
        #              A connection's 'how' overrides it for one joint.
        # values: boolean
        # default: false
        self.self_screw = bool(config.get("selfScrew", False))

        # Whether joining these two is done by pushing one past the other
        # rather than by screwing it in: the bore of a part pushed onto a thread
        # it is not cut to match, a clip over a barb. Getting past means passing
        # through, and a model that holds no springs holds them overlapping, so
        # the two are expected to share that space. Said here for the same
        # reason 'selfScrew' is: it is a fact about the pairing and not about
        # either part on its own.
        self.snap_in = bool(config.get("snapIn", False)) if isinstance(config, dict) else False

        # option: "how"
        # description: how every connection that joins these two interfaces is
        #              made, unless the connection says otherwise: the motion
        #              half of a connection's own 'how' ('HOW_MOTION_FIELDS' in
        #              'assembly_connect') - pushed with how much force, turned
        #              which way and how hard, along what thread, snapped or
        #              self-screwed. It is the pairing that knows it - an M3
        #              screw goes into an M3 tapped hole the same way in every
        #              assembly - so it is said once, here, and an ASSY file
        #              states only what is different about one joint: any field
        #              of its 'how' overrides the same field here, and only that
        #              field. 'stage' and the 'hold*' fields are not here: when a
        #              step is done, and by what each object is held, are facts
        #              about the assembly and the object respectively.
        # values: a section
        # default: none
        self.how = self._how(config.get("how"))

        # option: "motion"
        # description: which degrees of freedom every connection that joins
        #              these two interfaces keeps, whatever each interface would
        #              do with another partner: a 6 mm pin turns in an H7 bore
        #              and is fixed in a press-fit one. The same 'motion:' an
        #              interface states (see 'partcad.motion'); 'axis' is in the
        #              frame of the port of the interface that declares the
        #              mating, and a 'dof' name means that parameter on either
        #              interface. A connection's own 'motion' outranks it, and it
        #              outranks the two interfaces'. See 'partcad.joint'.
        # values: the name of a kind of joint, or a section
        # default: none
        self.motion = config.get("motion")
        # option: "physics"
        # description: what moving such a connection costs - its damping,
        #              friction, effort and velocity limits - when it is a joint.
        #              Outranks the two interfaces', which is how a pairing
        #              whose interfaces disagree says what the pair really does.
        # values: a section
        # default: none
        self.physics = config.get("physics")
        if self.physics is not None and not isinstance(self.physics, dict):
            pc_logging.error(
                "%s -> %s: a mating's 'physics' must be a section, ignoring it"
                % (getattr(source, "full_name", "?"), getattr(target, "full_name", "?"))
            )
            self.physics = None

        if "sourcePortSelector" in config:
            if reverse:
                self.target_port_selector = config["sourcePortSelector"]
            else:
                self.source_port_selector = config["sourcePortSelector"]
        else:
            self.source_port_selector = None

        if "targetPortSelector" in config:
            if reverse:
                self.source_port_selector = config["targetPortSelector"]
            else:
                self.target_port_selector = config["targetPortSelector"]
        else:
            self.target_port_selector = None

    def _how(self, how) -> dict:
        """The 'how' section of this mating, keeping only what it may say."""
        from .assembly_connect import HOW_MOTION_FIELDS

        if how is None:
            return {}
        where = "%s -> %s" % (getattr(self.source, "full_name", "?"), getattr(self.target, "full_name", "?"))
        if not isinstance(how, dict):
            pc_logging.error("%s: a mating's 'how' must be a section, ignoring: %s" % (where, how))
            return {}
        kept = {}
        for field, value in how.items():
            if field in HOW_MOTION_FIELDS:
                kept[field] = value
            else:
                pc_logging.error(
                    "%s: a mating's 'how' says how the two go together (%s), ignoring: %s"
                    % (where, ", ".join(HOW_MOTION_FIELDS), field)
                )
        return kept
