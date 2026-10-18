#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in URDF exporter (see '//builtin/export' in partcad.yaml).

Writes a PartCAD shape, assembly or scene as a URDF file plus its mesh files:
one ``<link>`` per rigid body and one ``<joint>`` per pair of bodies, so that a
mechanism goes out as the mechanism it is.

Unlike the other exporters, this one is handed the assembly *tree* itself
rather than the geometry it decodes to - which is what 'decode: false' on this
format's declaration asks for, see wrapper_export.DECODE_KEY. Which nodes of it
are one rigid body, and how the joints between bodies move, is not decided here:
it is PartCAD's body rule, 'kinematics.bodies()', and its classification of a
joint's free steps, 'kinematics.classify()' - one copy shared with the MJCF and
SDFormat exporters, so that the three cannot come to disagree about what falls
apart (docs/design/simulation.md, sections 7 and 8.8).

**Links.** Every body is a link, named after the link that placed it, and every
part welded into it is a ``<visual>`` and a ``<collision>`` of its own, at its
place in the link: a link of several parts is a link of several shapes, which
is how a URDF link of several shapes was read in. The body's mass, centre of
mass and inertia - its parts' combined, or what a measured link states about
itself - are its ``<inertial>``. An assembly's root body takes the name of the
one part it is made of when it is made of one (a robot's base link), and the
assembly's name otherwise.

**Joints**, by what 'kinematics.classify()' says the free steps are
(docs/design/simulation.md, section 8.13.4):

  * a ``revolute`` is URDF's ``revolute``, or its ``continuous`` where both of
    its bounds are open, and a ``prismatic`` is URDF's own;
  * a ``planar`` is URDF's own, its ``<axis>`` the normal of the plane (its
    turn's, whether the moves come first or the turn does), and so is a
    ``floating`` -- the child of which is a free body of its own, read
    against the body it was connected to, which a URDF ``floating`` joint
    between their links says;
  * a cylindrical, screw, universal, ball or composite joint has no URDF type,
    and the export **refuses** it ('Refused'), naming the joint, its type and
    the ways on: simulate the mechanism in MuJoCo, which writes every type;
    model the body the joint abstracts and join it by native joints; or, for a
    URDF read only for its kinematics, ask for ``composites: massless``. That
    writes the joint as a chain of single-axis joints through links with no
    ``<inertial>`` -- URDF's own idiom for a frame, which ROS's kinematics
    tools read and every simulator drops -- one per freedom past the first,
    named after the joint. A screw is then a revolute joint and a prismatic one
    that 'mimic's it by the lead.

Nothing is written with a mass PartCAD did not derive: the 1 g dummy links
this exporter used to write stood in for bodies a mechanism really has
('dummyMass' and 'dummyInertia' are gone, and reported where they are passed).
Every chain and every default is reported, never left to be found.

**Frames.** A child link's frame is the joint's *moving* frame: what the joint
puts the child at, with every freedom at zero and the last of them applied. So
``<axis>`` is the freedom's axis verbatim, in that frame, and every part sits in
its link where 'kinematics' puts the body against the joint ('tail'), times its
place in the body. A free root body is the URDF's root link, its frame the
tree's own origin, so that every shape is where the tree put it. A body welded
to the world hangs off a link named ``world`` by a fixed joint, which is what a
URDF bolted down says; and since a URDF has one root, the free bodies of a scene
of several hang off it by ``floating`` joints.

**What a URDF cannot state** is reported, and the file says the rest:

  * the **starting value** of a joint ('toParams'): URDF has no starting
    position, and what reads one -- ROS's tools, a robot's drivers -- takes a
    joint's zero to be where its hardware reads zero, so the robot is written
    at PartCAD's zero of every joint and not re-zeroed at its start, which an
    engine plugin does for a file that is its own (section 8.13.9, decision 2);
  * an open bound, which URDF's ``revolute`` and ``prismatic`` cannot leave
    open: written as 'OPEN_BOUND' away;
  * ``<limit effort velocity>``, which URDF requires: a joint's 'maxEffort' and
    'maxVelocity' where it states them, and the declaration's 'effort' and
    'velocity' (see partcad.yaml) where it does not.

Units convert at the boundary and nowhere else: PartCAD's millimetres and
degrees to URDF's metres and radians (``<dynamics>`` is per radian or per metre
in SI already, as PartCAD states it). Meshes are written in millimetres and
referenced with ``scale="0.001 0.001 0.001"``, which is how URDF says "these
coordinates are millimetres"; a shape used more than once is written once.

The URDF is built with ROS's own 'urdf_parser_py' and serialized by it, so what
lands on disk is what the ROS toolchain itself would write and reads back
through the very same parser. Everything up to that is plain data ('Planner'),
which is what the tests check frame by frame against 'kinematics'.

What a part states about itself wins over anything computed here: mass, centre
of mass, inertia, friction and the contact parameters are named PartCAD
properties, and this writes each of them back into the URDF element that states
it - or, for a part that states none, what PartCAD worked out from its solid and
the density of what it is made of (see 'partcad.physics'). A property PartCAD
has and URDF has no spelling for is reported rather than dropped in silence -
see URDF_STATED and JOINT_STATED.
"""

import math
import os
import re
import sys

# Pinned before anything that may pull OCP - see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import appearance  # noqa: E402
import kinematics  # noqa: E402
import mass_properties  # noqa: E402
import naming  # noqa: E402
import ocp_serialize  # noqa: E402
import urdf_common  # noqa: E402

# What this implementation reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again. 2: a link per body and a joint per pair (step 11).
# 3: native joint types; no dummy links, a refusal or 'composites: massless'.
CACHE_VERSION = 3

# Metres per millimetre, for the mesh 'scale' attribute: the meshes are written
# in millimetres and URDF reads mesh coordinates as metres after scaling.
MESH_SCALE = 1.0 / urdf_common.MM_PER_M

# What a URDF name may be, declared here because it is URDF's (see 'naming').
# The specification itself restricts nothing: urdfdom requires every link, every
# joint and every robot-level material to be unique among its own kind -- three
# namespaces -- and compares them as written. What reads a URDF restricts more,
# and a URDF is written to be read: Gazebo converts one to SDFormat first
# (sdformat's 'parser_urdf'), where '::' is a scope separator and 'world' and
# every '__*__' are reserved; Gazebo, ROS and MoveIt all take a link called
# 'world' to be the world itself, which is what this exporter's own 'world'
# link is; and a link's name is a ROS TF frame id, which may not begin with
# '/'. So the alphabet is the one every consumer reads verbatim, ASCII letters,
# digits, '_', '.' and '-', and the reserved names are SDFormat's.
URDF_NAMES = naming.Rules(
    "URDF",
    allowed=re.compile(r"[A-Za-z0-9_.-]"),
    reserved=("world",),
    reserved_patterns=(r"__.*__",),
)

TURN = kinematics.TURN
MOVE = kinematics.MOVE
IDENTITY = kinematics.IDENTITY

# What '<limit effort velocity>' says where a joint states no 'maxEffort' or
# 'maxVelocity' of its own: N.m or N, and rad/s or m/s. URDF requires both on a
# revolute and a prismatic joint. These are the declaration's defaults (see
# partcad.yaml), chosen to limit nothing a passive mechanism does while staying
# finite, since some readers refuse an infinite one; a package sets its own with
# 'effort:' and 'velocity:'. Every joint that gets them is reported.
DEFAULT_EFFORT = 1000.0
DEFAULT_VELOCITY = 100.0

# The kinds a URDF joint states as they are. Every other kind is refused, or
# written through massless links where 'composites: massless' asks for it.
NATIVE_KINDS = (kinematics.REVOLUTE, kinematics.PRISMATIC, kinematics.PLANAR, kinematics.FLOATING)

# What 'composites' may say: refuse a joint URDF has no type for (the default),
# or write it as a chain through links with no '<inertial>'.
COMPOSITES_REFUSE = "refuse"
COMPOSITES_MASSLESS = "massless"
COMPOSITES = (COMPOSITES_REFUSE, COMPOSITES_MASSLESS)

# The options this exporter had and does not: what a link of a mass nobody
# measured weighed. Reported where a package still passes one.
RETIRED_OPTIONS = ("dummyMass", "dummyInertia")

# How far away a bound URDF cannot leave open is written, in PartCAD's units
# (degrees, millimetres). URDF's 'lower' and 'upper' default to nought and are
# required on a revolute and a prismatic joint, so one side open - a door that
# stops only one way - has no spelling but a bound too far away to reach; the
# one place a sentinel stays (section 8.13.6), and reported.
OPEN_BOUND = 1.0e6


def _bool_text(value):
    return "true" if value else "false"


# PartCAD property -> the Gazebo tag that states it, and how to write the text.
# The mirror image of wrapper_import_urdf.GAZEBO_LINK_PHYSICS, and to be kept
# that way: contact and friction are PartCAD properties, and '<gazebo>' is where
# a URDF states them. 'turnGravityOff' has no entry here because 'gravity' says
# the same thing and is not deprecated.
GAZEBO_LINK_PHYSICS = {
    "friction": ("mu1", repr),
    "friction2": ("mu2", repr),
    "frictionDirection": ("fdir1", lambda v: " ".join(repr(float(x)) for x in v)),
    "contactStiffness": ("kp", repr),
    "contactDamping": ("kd", repr),
    "minContactDepth": ("minDepth", lambda v: repr(v / urdf_common.MM_PER_M)),
    "maxContactVelocity": ("maxVel", lambda v: repr(v / urdf_common.MM_PER_M)),
    "restitution": ("bounce", repr),
    "maxContacts": ("maxContacts", lambda v: str(int(v))),
    "velocityDamping": ("dampingFactor", repr),
    "selfCollide": ("selfCollide", _bool_text),
    "gravity": ("gravity", _bool_text),
}

# The same for a joint: the mirror image of the reader's GAZEBO_JOINT_PHYSICS,
# which carries each of these as it is written.
GAZEBO_JOINT_PHYSICS = {
    "springStiffness": ("springStiffness", repr),
    "springReference": ("springReference", repr),
    "stopCfm": ("stopCfm", repr),
    "stopErp": ("stopErp", repr),
    "fudgeFactor": ("fudgeFactor", repr),
    "implicitSpringDamper": ("implicitSpringDamper", _bool_text),
    "provideFeedback": ("provideFeedback", _bool_text),
}

# Every part property this exporter has a URDF spelling for. A 'physics'
# property outside this set is one PartCAD supports and URDF does not: it is
# reported through the response and logged at info level, which is the mirror
# image of the import refusing URDF that PartCAD has no property for. When
# PartCAD grows a physical property, either give it a spelling above or let it
# be reported here - do not let it disappear quietly.
#
# 'density' is here although URDF has no element for one, because it is not
# lost: it is what the mass, the centre of mass and the inertia of a part that
# states no mass were worked out from, so the file states it the only way URDF
# can - as the '<inertial>' it comes to.
#
# 'volume' and 'centerOfVolume' are here for the opposite reason: they are not
# properties of the part at all but what PartCAD measured its solid to enclose
# and where, handed to every exporter for the one that buoys a body in a fluid.
# A URDF has no world to fill with one, so there is nothing it could lose.
URDF_STATED = frozenset(
    ("mass", "centerOfMass", "inertiaOrientation", "inertia", "density", "volume", "centerOfVolume")
) | frozenset(GAZEBO_LINK_PHYSICS)

# Every joint physics property this exporter has a URDF spelling for: the
# '<limit>', the '<dynamics>' and the joint's '<gazebo>' block.
JOINT_STATED = frozenset(("maxEffort", "maxVelocity", "damping", "friction")) | frozenset(GAZEBO_JOINT_PHYSICS)


def sanitize_name(name, fallback):
    """A URDF-safe name derived from a PartCAD name, uniqueness aside.

    PartCAD names carry package paths and ':' separators ("//pub/examples:logo"),
    none of which belong in a ROS name.
    """
    return naming.transcode(URDF_NAMES, name, fallback)


def per_si(kind) -> float:
    """PartCAD units per SI unit of a freedom: degrees a radian, or millimetres a metre."""
    return math.degrees(1.0) if kind == TURN else urdf_common.MM_PER_M


def to_si(kind, value):
    """A value of a freedom in URDF's units, or None for None."""
    return None if value is None else float(value) / per_si(kind)


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _shown(value, kind) -> str:
    return "%g %s" % (value, "deg" if kind == TURN else "mm")


class Refused(ValueError):
    """The joints a URDF has no type for, which the export will not write as something they are not.

    'joints' is '(name, kind)' for each. The message names them, says why,
    and gives the ways on.
    """

    def __init__(self, joints):
        self.joints = list(joints)
        super().__init__(refusal(self.joints))


def refusal(joints) -> str:
    """Why a URDF of these joints is not written, and what to do instead (docs/design/simulation.md, 8.13.4)."""
    named = ", ".join("the %s joint '%s'" % (kind, name) for name, kind in joints)
    return (
        "URDF has no type for %s: its joints are revolute, continuous, prismatic, planar and floating, and the only "
        "way to write another is through links of a mass nobody measured, which this export does not invent. "
        "Either simulate the mechanism in MuJoCo (partcad-sim-mujoco), which writes every type; or model the body "
        "the joint stands for - for a cylindrical pair a sleeve and its carriage, for a universal joint the cross "
        "- and join it by native joints; or, for a URDF that is read only for its kinematics (robot_state_publisher, "
        "MoveIt), export with 'composites: massless', which writes each such joint as a chain through links with no "
        "<inertial> that every simulator drops" % named
    )


#
# The plan: links and joints as plain data
#


class LinkPlan:
    """One URDF link: a body, or a massless link between two freedoms of one joint.

    'frame' is the link's frame in the body's own: the identity for a body that
    is a root under 'world', the inverse of where the tree placed a free root
    (so that its link frame is the tree's origin), and the inverse of the
    joint's 'tail' for a body a joint moves (so that its link frame is the
    joint's moving frame). Its shapes and its inertia are restated in it.

    A 'massless' link is a frame of a chain URDF writes for a joint it has no
    type for, under 'composites: massless': no shape, and no '<inertial>'.
    """

    def __init__(self, name, body=None, frame=IDENTITY, massless=False):
        self.name = name
        self.body = body
        self.frame = frame
        self.massless = massless

    def shapes(self) -> list:
        """(part, its pose in the link) for every part of the body."""
        if self.body is None:
            return []
        undo = kinematics.inverse(self.frame)
        return [(part, kinematics.compose(undo, part.placement)) for part in self.body.parts]

    def inertial(self, options=None):
        """The physics '<inertial>' states, in the link's frame, or None."""
        if self.massless:
            return None
        physics = None if self.body is None else self.body.physics
        if not physics or urdf_common.is_identity(self.frame):
            return physics
        return mass_properties.placed(physics, kinematics.packed_of(kinematics.inverse(self.frame)))

    def __repr__(self):
        return "<LinkPlan %s%s>" % (self.name, " (massless)" if self.massless else "")


class JointPlan:
    """One URDF joint, in URDF's units: metres, radians, and SI per unit of motion."""

    def __init__(self, name, joint_type, parent, child, origin):
        self.name = name
        self.type = joint_type
        self.parent = parent
        self.child = child
        # The joint frame in the parent link's frame, millimetres (converted
        # where the pose is written, as every other pose is).
        self.origin = origin
        self.axis = None
        # The kind of freedom it is, for the units of what follows.
        self.kind = None
        self.lower = None
        self.upper = None
        self.effort = None
        self.velocity = None
        self.damping = None
        self.friction = None
        # (k_velocity, k_position, soft lower, soft upper), SI.
        self.safety = None
        # (joint name, multiplier, offset), SI.
        self.mimic = None
        # What the joint's '<gazebo>' block states, as PartCAD properties.
        self.gazebo = {}

    def motion(self, value):
        """Where the child link is against the joint frame at 'value' (URDF units): for checking a plan."""
        if self.type in ("revolute", "continuous"):
            return (urdf_common.axis_angle_to_quat(self.axis, math.degrees(value)), (0.0, 0.0, 0.0))
        if self.type == "prismatic":
            metres = value * urdf_common.MM_PER_M
            return kinematics.translation(tuple(a * metres for a in self.axis))
        return IDENTITY

    def __repr__(self):
        return "<JointPlan %s %s %s -> %s>" % (self.name, self.type, self.parent, self.child)


def _subtree(node, into):
    into.add(id(node))
    for child in node.get(kinematics.KEY_ASSEMBLY) or []:
        if isinstance(child, dict):
            _subtree(child, into)
    return into


def sole_child_label(body):
    """The label of the one child of a root assembly that every part of its body is in, or None.

    What a robot's base link is when the robot is an assembly: the part the rest
    hangs off, placed at the assembly's root. A root body made of several such
    children has no better name than the assembly's own.
    """
    if not body.parts or kinematics.is_geometry(body.node):
        return None
    for child in body.node.get(kinematics.KEY_ASSEMBLY) or []:
        if not isinstance(child, dict) or not child.get("label"):
            continue
        inside = _subtree(child, set())
        if all(id(part.node) in inside for part in body.parts):
            return child["label"]
    return None


class Planner:
    """The links and joints of a URDF for the bodies 'kinematics.bodies()' found.

    Plain data, and nothing written: 'process()' turns it into the URDF, and
    the tests check it against the joints it came from, frame by frame.
    """

    def __init__(self, found, options=None, warnings=None):
        self.found = found
        self.warnings = warnings if warnings is not None else []
        options = {key: value for key, value in (options or {}).items() if value is not None}
        retired = [key for key in RETIRED_OPTIONS if key in options]
        if retired:
            self.warnings.append(
                "The URDF export has no %s any more: it writes no link of a mass nobody measured, and refuses a "
                "joint URDF has no type for unless 'composites: massless' asks for one through links with no "
                "<inertial>; ignoring %s" % (" or ".join("'%s'" % key for key in retired), ", ".join(retired))
            )
        composites = options.get("composites", COMPOSITES_REFUSE)
        if composites not in COMPOSITES:
            self.warnings.append(
                "'composites' is '%s' or '%s', not %r: refusing what URDF has no type for"
                % (COMPOSITES_REFUSE, COMPOSITES_MASSLESS, composites)
            )
            composites = COMPOSITES_REFUSE
        self.options = {
            "effort": options.get("effort", DEFAULT_EFFORT),
            "velocity": options.get("velocity", DEFAULT_VELOCITY),
            "composites": composites,
        }
        # Links and joints are two namespaces, as urdfdom checks them, and
        # "<parent>_to_<child>" collides on its own: "a" -> "b_to_c" and
        # "a_to_b" -> "c" both spell "a_to_b_to_c". Every body's link and every
        # joint is claimed before anything is derived (see 'plan'), so that a
        # massless link yields its name to a body somebody called that.
        self.names = naming.Transcoder(URDF_NAMES)
        self.joint_names = naming.Transcoder(URDF_NAMES)
        self.links = []
        self.joints = []
        self.unsupported = set()
        # Body -> its LinkPlan; PartCAD joint name -> the URDF joints it became,
        # as (name, kind of freedom) - what a 'mimic' looks its leader up in.
        self._link_of = {}
        self._written = {}
        self._mimics = []
        # What is reported once, grouped, at the end; and what is refused.
        self._started = []
        self._defaults = []
        self._open = []
        self.refused = []

    def plan(self):
        """Plan every link and joint; raises 'Refused' for the joints a URDF has no type for."""
        # A floating body is free, as a root is, but a URDF says so with a
        # 'floating' joint to the link of the body it was connected to.
        roots = [body for body in self.found if body.is_root and not body.is_floating]
        for body in self.found:
            self.names.claim(body.name, "body", "link", preferred=self.link_label(body))
            if body.joint is not None:
                self.joint_names.claim(body.joint.name, "joint", "joint")
        world = None
        if not (len(roots) == 1 and roots[0].parent is None):
            # The world itself, under the name URDF's readers know it by, which
            # no body can have (URDF_NAMES reserves it).
            world = LinkPlan(self.names.reserve(kinematics.WORLD))
            self.links.append(world)
            free = [body.name for body in roots if body.parent is None]
            if free:
                self.warnings.append(
                    "A URDF has one root link, so the free bodies %s are each joined to 'world' by a 'floating' "
                    "joint" % ", ".join(free)
                )

        for body in self.found:
            name = self.names.claim(body.name, "body")
            if isinstance(body.parent, kinematics.Body) or body.is_floating:
                self.jointed(body, name)
            elif world is None:
                self.add_link(LinkPlan(name, body, kinematics.inverse(body.world)))
            else:
                self.add_link(LinkPlan(name, body))
                joint = JointPlan(
                    self.joint_names.derive("%s_to_%s" % (world.name, name), "joint"),
                    "fixed" if body.parent == kinematics.WORLD else "floating",
                    world.name,
                    name,
                    body.world,
                )
                self.joints.append(joint)

        if self.refused:
            raise Refused(self.refused)
        self._resolve_mimics()
        self._report()
        renamed = naming.renamed_warning(URDF_NAMES, self.names, self.joint_names)
        if renamed:
            self.warnings.append(renamed)
        return self

    def link_label(self, body) -> str:
        if body.is_root and body.kind == kinematics.ASSEMBLY:
            return sole_child_label(body) or body.name
        return body.name

    def add_link(self, link):
        self.links.append(link)
        if link.body is not None:
            self._link_of[id(link.body)] = link

    def jointed(self, body, name):
        """The joint (or chain of joints) of 'body' to its parent, and its link."""
        joint = body.joint
        classification = joint.classification
        kind = classification.kind
        if kind not in NATIVE_KINDS and self.options["composites"] != COMPOSITES_MASSLESS:
            self.refused.append((joint.name, kind))
            # Planned as a link of its own all the same, so that what hangs off
            # it has a parent to be refused or planned against.
            self.add_link(LinkPlan(name, body, kinematics.inverse(joint.tail)))
            return
        parent = self._link_of[id(body.joint_parent)]
        undo = kinematics.inverse(parent.frame)
        for freedom in joint.freedoms:
            if freedom.value:
                self._started.append("'%s' at %s" % (joint.name, _shown(freedom.value, freedom.kind)))
        self.unsupported.update(set(joint.physics) - JOINT_STATED)

        if kind in (kinematics.REVOLUTE, kinematics.PRISMATIC):
            (freedom,) = joint.freedoms
            self.add_link(LinkPlan(name, body, kinematics.inverse(joint.tail)))
            plan = self.single(joint.name, joint, freedom, parent.name, name, kinematics.compose(undo, joint.origin))
            self.joint_record(plan, joint, freedom)
            self._written[joint.name] = [(plan.name, freedom.kind)]
            return

        if kind in (kinematics.PLANAR, kinematics.FLOATING):
            self.add_link(LinkPlan(name, body, kinematics.inverse(classification.tail)))
            plan = JointPlan(
                self.joint_names.claim(joint.name, "joint", "joint"),
                kind,
                parent.name,
                name,
                kinematics.compose(undo, classification.origin),
            )
            if kind == kinematics.PLANAR:
                # The normal of the plane: the turn's axis, which is the first
                # freedom or the third, as the joint's order has it.
                turn = next(freedom.index for freedom in joint.freedoms if freedom.kind == TURN)
                plan.axis = classification.axes[turn]
            plan.damping = _number(joint.physics.get("damping"))
            plan.friction = _number(joint.physics.get("friction"))
            plan.gazebo = dict(joint.physics)
            self.joints.append(plan)
            bounded = [freedom for freedom in joint.freedoms if freedom.limited]
            if bounded:
                self.warnings.append(
                    "The %s joint '%s' has bounds on %d of its freedoms, and a URDF %s joint has none: they are not "
                    "written" % (kind, joint.name, len(bounded), kind)
                )
            if joint.turn_limit is not None:
                self.warnings.append(
                    "The %s joint '%s' states how far it turns, and a URDF %s joint cannot: not written"
                    % (kind, joint.name, kind)
                )
            if joint.soft_limits or joint.mimic:
                self.warnings.append(
                    "The %s joint '%s' states soft limits or a mimic, which a URDF %s joint cannot: not written"
                    % (kind, joint.name, kind)
                )
            self._written[joint.name] = [(plan.name, None)]
            return

        self.chain(body, name, parent, undo)

    def chain(self, body, name, parent, undo):
        """A joint URDF has no type for, as one single-axis joint per freedom through massless links.

        Only where 'composites: massless' asks for it: each link between two
        freedoms is a frame, with no shape and no '<inertial>', which is what
        ROS's kinematics tools read a link of a chain as and what every
        simulator that reads a URDF drops - so this is a URDF for kinematics,
        and the warning says so.
        """
        joint = body.joint
        freedoms = joint.freedoms
        names = self.chain_names(joint)
        previous = parent.name
        written = []
        frames = []
        for index, freedom in enumerate(freedoms):
            if index == len(freedoms) - 1:
                child = name
                self.add_link(LinkPlan(name, body, kinematics.inverse(joint.tail)))
            else:
                child = self.names.derive("%s_link%d" % (joint.name, index + 1), "link")
                frames.append(child)
                self.add_link(LinkPlan(child, massless=True))
            origin = kinematics.compose(undo, joint.origins[0]) if index == 0 else joint.origins[index]
            plan = self.single(names[index], joint, freedom, previous, child, origin, derived=index > 0)
            if freedom.follows is not None:
                leader_name, leader = written[freedom.follows], freedoms[freedom.follows]
                plan.mimic = (
                    leader_name,
                    freedom.ratio * per_si(leader.kind) / per_si(freedom.kind),
                    to_si(freedom.kind, freedom.offset or 0.0),
                )
                # What moving it costs is the leader's to pay: it is not a
                # freedom of its own.
                plan.damping = plan.friction = None
                plan.gazebo = {}
            written.append(plan.name)
            previous = child
        self._written[joint.name] = [(written[i], freedoms[i].kind) for i in range(len(freedoms))]

        kind = joint.kind
        self.warnings.append(
            "The %s joint '%s' has no URDF type: as 'composites: massless' asks, it is written as the joints %s "
            "through the links %s, which have no <inertial> - a URDF for kinematics, whose chain every simulator "
            "drops" % (kind, joint.name, ", ".join(written), ", ".join(frames))
        )
        if kind == kinematics.SCREW:
            self.warnings.append(
                "The screw '%s' is approximate in URDF: its move follows its turn by a <mimic>, which kinematics "
                "tools honour and few simulators do" % joint.name
            )
        if joint.soft_limits:
            self.warnings.append(
                "The joint '%s' states soft limits for a joint URDF writes as several: not written" % joint.name
            )
        if joint.mimic:
            self.warnings.append("The joint '%s' mimics another, and is written as several: not written" % joint.name)
        if joint.turn_limit is not None:
            self.warnings.append(
                "The ball '%s' is bounded by how far it turns, which its three URDF joints cannot state: not written"
                % joint.name
            )

    def chain_names(self, joint) -> list:
        """What each joint of a chain is called: the first after the joint, the rest after what they are.

        The first keeps the joint's own name, so that reading the URDF back
        names the joint the chain composes into as it was. Each one after it is
        named after the URDF joint its freedom was read from, where it was read
        from one, and after its parameter otherwise.
        """
        names = [joint.name]
        for index, freedom in enumerate(joint.freedoms[1:], start=1):
            read_from = {source.get("joint") for source in freedom.source if source.get("joint")}
            if len(read_from) == 1 and next(iter(read_from)) not in names:
                names.append(next(iter(read_from)))
                continue
            names.append("%s_%s" % (joint.name, freedom.parameter or index + 1))
        return names

    def single(self, name, joint, freedom, parent, child, origin, derived=False):
        """One single-axis URDF joint for one freedom, with its limits and dynamics.

        'derived' for a joint of a chain past its first, which is not named by
        PartCAD and yields its name to one that is.
        """
        if freedom.kind == TURN:
            joint_type = "revolute" if freedom.limited else "continuous"
        else:
            joint_type = "prismatic"
        names = self.joint_names
        plan = JointPlan(
            names.derive(name, "joint") if derived else names.claim(name, "joint", "joint"),
            joint_type,
            parent,
            child,
            origin,
        )
        plan.kind = freedom.kind
        plan.axis = freedom.axis
        physics = joint.physics
        effort = _number(physics.get("maxEffort"))
        velocity = to_si(freedom.kind, _number(physics.get("maxVelocity")))

        if joint_type != "continuous":
            lower, upper = freedom.lower, freedom.upper
            if lower is None or upper is None:
                self._open.append(plan.name)
                lower = -OPEN_BOUND if lower is None else lower
                upper = OPEN_BOUND if upper is None else upper
            plan.lower, plan.upper = to_si(freedom.kind, lower), to_si(freedom.kind, upper)
        if joint_type != "continuous" or effort is not None or velocity is not None:
            # URDF requires both wherever there is a '<limit>' at all.
            if effort is None or velocity is None:
                self._defaults.append(plan.name)
            plan.effort = self.options["effort"] if effort is None else effort
            plan.velocity = self.options["velocity"] if velocity is None else velocity
        plan.damping = _number(physics.get("damping"))
        plan.friction = _number(physics.get("friction"))
        plan.gazebo = dict(physics)
        self.joints.append(plan)
        return plan

    def joint_record(self, plan, joint, freedom):
        """What a joint of one freedom says about itself: its soft limits, and what it mimics."""
        soft = joint.soft_limits
        if isinstance(soft, dict) and soft:
            plan.safety = (
                _number(soft.get("kVelocity")) or 0.0,
                _number(soft.get("kPosition")),
                to_si(freedom.kind, _number(soft.get("lower"))),
                to_si(freedom.kind, _number(soft.get("upper"))),
            )
            if soft.get("kVelocity") is None:
                self.warnings.append(
                    "The joint '%s' states soft limits and no 'kVelocity', which URDF requires: written as 0"
                    % joint.name
                )
        if isinstance(joint.mimic, dict) and joint.mimic.get("joint"):
            self._mimics.append((plan, joint.name, dict(joint.mimic)))

    def _resolve_mimics(self):
        for plan, name, mimic in self._mimics:
            leader = self._written.get(str(mimic["joint"]))
            if not leader or len(leader) != 1 or leader[0][1] is None:
                self.warnings.append(
                    "The joint '%s' mimics '%s', and URDF can say that only of a joint of one freedom following "
                    "another: it is not written" % (name, mimic["joint"])
                )
                continue
            leader_name, leader_kind = leader[0]
            multiplier = _number(mimic.get("multiplier"))
            multiplier = 1.0 if multiplier is None else multiplier
            plan.mimic = (
                leader_name,
                multiplier * per_si(leader_kind) / per_si(plan.kind),
                to_si(plan.kind, _number(mimic.get("offset")) or 0.0),
            )

    def _report(self):
        if self._started:
            self.warnings.append(
                "A URDF states no starting position, so every joint is written at zero; these start elsewhere in "
                "the assembly: %s" % ", ".join(self._started)
            )
        if self._defaults:
            self.warnings.append(
                "URDF requires an effort and a velocity limit, and the joints %s state no 'maxEffort' or "
                "'maxVelocity': written as effort=%g, velocity=%g (the export's 'effort' and 'velocity')"
                % (", ".join(self._defaults), self.options["effort"], self.options["velocity"])
            )
        if self._open:
            self.warnings.append(
                "A URDF revolute or prismatic joint is bounded on both sides, and %s are open on one: the open "
                "side is written %g degrees or millimetres away" % (", ".join(self._open), OPEN_BOUND)
            )


#
# Writing it
#


def node_geometry(node):
    """The node's own shape as a live TopoDS_Shape, in its own frame, or None.

    Decoded already: 'shape_tree' carries it on the node. The placement carried
    by the node is deliberately left off: where the part sits in its link is the
    visual's origin, not part of the geometry.
    """
    if not ocp_serialize.is_shape_object(node):
        return None
    return node[ocp_serialize.KEY_SHAPE]


def write_mesh(shape, path, options):
    """Triangulate 'shape' and write it out as an STL file."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer

    BRepMesh_IncrementalMesh(
        shape,
        theLinDeflection=options["tolerance"],
        isRelative=True,
        theAngDeflection=options["angularTolerance"],
        isInParallel=True,
    )
    writer = StlAPI_Writer()
    writer.ASCIIMode = options["ascii"]
    if not writer.Write(shape, path) or not os.path.exists(path) or os.path.getsize(path) == 0:
        raise Exception("Failed to write the mesh file: %s" % path)


def carried_inertial(physics):
    """The ``<inertial>`` a physics dict states, or None if it states none.

    Mass, centre of mass and inertia are named PartCAD properties (see
    wrapper_import_urdf's tables for the full list and the units), whether the
    part stated them - a measurement, or the number a simulation was tuned
    against - or PartCAD worked them out from its solid and its density. This
    restates them in URDF's units and frame and decides nothing.
    """
    from urdf_parser_py.urdf import Inertia, Inertial, Pose

    physics = physics or {}
    if "mass" not in physics and "inertia" not in physics:
        return None

    xyz = [v / urdf_common.MM_PER_M for v in physics.get("centerOfMass") or (0.0, 0.0, 0.0)]
    rpy = [math.radians(v) for v in physics.get("inertiaOrientation") or (0.0, 0.0, 0.0)]
    inertia = physics.get("inertia") or {}
    return Inertial(
        mass=float(physics.get("mass", 0.0)),
        origin=Pose(xyz=xyz, rpy=rpy),
        inertia=Inertia(**{key: float(inertia.get(key, 0.0)) for key in Inertia.KEYS}) if inertia else None,
    )


def carried_material(properties, state):
    """The ``<material>`` a part's own 'material'/'color' properties state."""
    from urdf_parser_py.urdf import Color, LinkMaterial

    name, color = properties.get("material"), properties.get("color")
    if not name and not color:
        return None
    built = LinkMaterial(name=sanitize_name(name or color, "material"))
    rgba = color_rgba(color, state) if color else None
    if rgba is not None:
        # 'Color' takes the components positionally, not by keyword.
        built.color = Color(rgba)
    return built


def color_rgba(text, state):
    """A PartCAD colour string as URDF's ``rgba``, or None if it is not one.

    Read by 'appearance.parse', which is what reads it for every drawing of the
    part as well: a colour the URDF takes is a colour the part is drawn in.
    """
    parsed = appearance.parse(str(text))
    if parsed is None:
        state["warnings"].append("Ignoring the colour '%s', which is not #RRGGBB or #RRGGBBAA" % text)
        return None
    red, green, blue, alpha = parsed
    return [round(channel / 255.0, 6) for channel in (red, green, blue)] + [round(alpha, 6)]


def gazebo_element(reference, physics, table=None):
    """The ``<gazebo reference="...">`` block a link's or a joint's physics needs, or None.

    The reverse of wrapper_import_urdf's GAZEBO_LINK_PHYSICS and
    GAZEBO_JOINT_PHYSICS: contact, friction and a joint's solver settings are
    PartCAD properties, and Gazebo is where a URDF states them.
    """
    from xml.etree import ElementTree

    element = None
    for name, (tag, write) in (GAZEBO_LINK_PHYSICS if table is None else table).items():
        if name not in physics:
            continue
        if element is None:
            element = ElementTree.Element("gazebo", {"reference": reference})
        child = ElementTree.SubElement(element, tag)
        child.text = write(physics[name])
    return element


def mesh_reference(shape, node, link_name, state):
    """Write 'shape' out as a mesh (or reuse one) and return the URDF reference.

    An identical shape used twice - the two bones of the PartCAD logo, a
    repeated fastener - shares one mesh file, the way a URDF written by hand
    would.
    """
    key = node.get(ocp_serialize.KEY_BREP)
    mesh_file = state["meshes"].get(key)
    if mesh_file is None:
        mesh_name = state["mesh_names"].derive(node.get("label") or link_name, "mesh")
        mesh_file = "%s/%s.stl" % (state["mesh_dir_name"], mesh_name)
        write_mesh(shape, os.path.join(state["mesh_dir"], "%s.stl" % mesh_name), state["options"])
        state["meshes"][key] = mesh_file
    return state["mesh_prefix"] + mesh_file


def physics_of(node, state):
    """What the object behind one node of the tree states about its physics.

    Looked up by 'kinematics.properties_of()' rather than by the node's full
    name, which a part and an assembly may share: the assembly 'nut' holding the
    part 'nut' would otherwise state, for the body it is the root of, the
    part's friction.
    """
    return (kinematics.properties_of(state["properties"], node) or {}).get("physics") or {}


def link_physics(body, state):
    """What a body's '<gazebo>' block states: the body's own, else what its parts agree on.

    A body rooted at a part says it of itself. One rooted at an assembly - a
    robot's base, welded out of its parts - says what its parts say, and two
    parts that say different things are reported, the first one's being used.
    """
    own = physics_of(body.node, state)
    stated = {}
    for key in GAZEBO_LINK_PHYSICS:
        if key in own:
            stated[key] = own[key]
            continue
        values = [part.physics[key] for part in body.parts if key in (part.physics or {})]
        if not values:
            continue
        stated[key] = values[0]
        if any(value != values[0] for value in values[1:]):
            state["warnings"].append(
                "The parts of the link '%s' state different '%s' (%s), and a URDF link has one: '%s' is used"
                % (body.name, key, ", ".join(str(value) for value in values), values[0])
            )
    return stated


def pose(xyz_rpy_source):
    from urdf_parser_py.urdf import Pose

    xyz, rpy = urdf_common.to_urdf_origin(xyz_rpy_source)
    return Pose(xyz=xyz, rpy=rpy)


def build_link(plan, state):
    """The URDF ``<link>`` for one planned link."""
    from urdf_parser_py.urdf import Collision, Link, Mesh, Visual

    link = Link(name=plan.name)
    shapes = [(part, where, node_geometry(part.node)) for part, where in plan.shapes()]
    shapes = [entry for entry in shapes if entry[2] is not None]
    # A link of several shapes names each after the part it is, which is what
    # reading it back names the part '<assembly>/<link>/<name>' by - so a part
    # labelled under its link ('wrist/1', read from such a link) is named after
    # what it is within it.
    names = naming.Transcoder(URDF_NAMES, "_", 1) if len(shapes) > 1 else None
    placed = 0
    for part, where, shape in shapes:
        reference = mesh_reference(shape, part.node, plan.name, state)
        geometry = Mesh(filename=reference, scale=[MESH_SCALE, MESH_SCALE, MESH_SCALE])
        origin = None if urdf_common.is_identity(where) else pose(where)
        name = None if names is None else names.derive(str(part.label or part.name or "").rpartition("/")[2], "shape")
        # The appearance belongs to the shape, not to the link: a link built
        # from several parts may well have a colour per part.
        material = carried_material(state["properties"].get(part.node.get("name")) or {}, state)
        link.add_aggregate("visual", Visual(geometry=geometry, origin=origin, material=material, name=name))
        link.add_aggregate("collision", Collision(geometry=geometry, origin=origin, name=name))
        state["unsupported"].update(set(part.physics or {}) - URDF_STATED)
        placed += 1

    if plan.massless:
        # A frame of a chain: no '<inertial>', which is the point of it.
        return link
    if not placed:
        # A link with no geometry of its own - the 'world', or a body that holds
        # nothing but what moves against it. A body still states what it says
        # about itself: a measured mass, a Gazebo setting. There is nothing to
        # weigh, though, so having no mass is not worth a warning here.
        if plan.body is not None:
            if state["options"]["inertial"]:
                link.inertial = carried_inertial(plan.inertial(state["planner"].options))
            gazebo = gazebo_element(plan.name, link_physics(plan.body, state))
            if gazebo is not None:
                state["gazebo"].append(gazebo)
            state["unsupported"].update(set(physics_of(plan.body.node, state)) - URDF_STATED)
        return link

    if state["options"]["inertial"]:
        link.inertial = carried_inertial(plan.inertial(state["planner"].options))
        if link.inertial is None:
            state["warnings"].append(
                "Link '%s' has no mass: it states none and has no solid to weigh (an open shell or a mesh), "
                "so it carries no <inertial>" % plan.name
            )
    gazebo = gazebo_element(plan.name, link_physics(plan.body, state))
    if gazebo is not None:
        state["gazebo"].append(gazebo)
    state["unsupported"].update(set(physics_of(plan.body.node, state)) - URDF_STATED)
    return link


def build_joint(plan, state):
    """The URDF ``<joint>`` for one planned joint."""
    from urdf_parser_py.urdf import Joint, JointDynamics, JointLimit, JointMimic, SafetyController

    joint = Joint(
        name=plan.name,
        parent=plan.parent,
        child=plan.child,
        joint_type=plan.type,
        origin=None if urdf_common.is_identity(plan.origin) else pose(plan.origin),
    )
    if plan.axis is not None and plan.type != "fixed":
        joint.axis = [round(float(v), 15) for v in plan.axis]
    if plan.effort is not None:
        joint.limit = JointLimit(effort=plan.effort, velocity=plan.velocity, lower=plan.lower, upper=plan.upper)
    if plan.damping is not None or plan.friction is not None:
        joint.dynamics = JointDynamics(damping=plan.damping, friction=plan.friction)
    if plan.safety is not None:
        k_velocity, k_position, lower, upper = plan.safety
        joint.safety_controller = SafetyController(velocity=k_velocity, position=k_position, lower=lower, upper=upper)
    if plan.mimic is not None:
        leader, multiplier, offset = plan.mimic
        joint.mimic = JointMimic(joint_name=leader, multiplier=multiplier, offset=offset)
    gazebo = gazebo_element(plan.name, plan.gazebo, GAZEBO_JOINT_PHYSICS)
    if gazebo is not None:
        state["gazebo"].append(gazebo)
    return joint


def process(path, request):
    from urdf_parser_py.urdf import URDF

    root = request.get("shape_tree")
    if not isinstance(root, dict) or not (
        ocp_serialize.is_shape_object(root) or ocp_serialize.is_assembly_object(root)
    ):
        raise ValueError("The URDF exporter needs a shape or an assembly to export")

    urdf_dir = os.path.dirname(os.path.abspath(path)) or "."
    stem = os.path.splitext(os.path.basename(path))[0] or "robot"
    robot_name = sanitize_name(request.get("robot_name") or root.get("label") or stem, stem)
    mesh_dir_name = request.get("mesh_dir") or "%s_meshes" % stem
    mesh_dir = os.path.join(urdf_dir, mesh_dir_name)

    warnings = []
    # Shape full name -> the properties its part declares ('physics',
    # 'material', 'color'), and what PartCAD resolved for it. A part that came
    # from a URDF states the link's mass, inertia and friction here, and they go
    # back out rather than being recomputed.
    properties = request.get("properties") or {}
    found = kinematics.bodies(root, properties)
    warnings.extend(found.problems)
    options = {key: _number(request.get(key)) for key in ("effort", "velocity")}
    options["composites"] = request.get("composites")
    for key in RETIRED_OPTIONS:
        options[key] = request.get(key)
    # Planned before anything is written: a refusal ('Refused') leaves nothing
    # behind, not even an empty directory for the meshes.
    planner = Planner(found, options, warnings).plan()
    os.makedirs(mesh_dir, exist_ok=True)

    state = {
        "planner": planner,
        # A mesh's name is a file's, and a file's rules are the filesystem's.
        "mesh_names": naming.Transcoder(naming.FILE_NAMES, "_", 1),
        "meshes": {},
        "mesh_dir": mesh_dir,
        "mesh_dir_name": mesh_dir_name,
        # Empty by default, which makes the reference relative to the URDF file
        # itself - what a standalone URDF wants. A ROS package sets this to
        # "package://<pkg>/" so the meshes resolve through the ROS package path.
        "mesh_prefix": request.get("mesh_prefix") or "",
        "properties": properties,
        "gazebo": [],
        # PartCAD properties URDF has no spelling for, reported once at the end.
        "unsupported": set(planner.unsupported),
        "options": {
            "tolerance": request.get("tolerance", 0.1),
            "angularTolerance": request.get("angularTolerance", 0.1),
            "ascii": request.get("ascii", False),
            "inertial": request.get("inertial", True),
        },
        "warnings": warnings,
    }

    robot = URDF(name=robot_name)
    for link in planner.links:
        robot.add_link(build_link(link, state))
    for joint in planner.joints:
        robot.add_joint(build_joint(joint, state))

    with open(path, "w", encoding="utf-8") as f:
        f.write(with_gazebo(robot.to_xml_string(), state["gazebo"]))

    return {
        "success": True,
        "exception": None,
        "robot_name": robot_name,
        "mesh_dir": mesh_dir,
        "meshes": sorted(set(state["meshes"].values())),
        "warnings": warnings,
        # Properties PartCAD holds and URDF cannot state. Reported at info
        # level by the caller: nothing is wrong with the file, it just says
        # less than the package does.
        "unsupported": sorted(state["unsupported"]),
    }


def with_gazebo(xml, blocks):
    """Add the ``<gazebo>`` blocks to the serialized robot.

    They are inserted as text because urdf_parser_py serializes what it parsed,
    and it keeps ``<gazebo>`` as an opaque element it will not build. Each block
    here was *built* from named PartCAD properties, not carried through, so what
    lands in the file is a statement of what PartCAD holds.
    """
    if not blocks:
        return xml

    from xml.etree import ElementTree

    rendered = [ElementTree.tostring(block, encoding="unicode").rstrip() for block in blocks]
    closing = xml.rindex("</robot>")
    return xml[:closing] + "\n".join("  %s" % line for line in rendered) + "\n" + xml[closing:]
