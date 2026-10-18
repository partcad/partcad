#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which nodes of a tree are rigid bodies, and how the joints between them move.

PartCAD's one copy of the body rule and of joint classification, for every
exporter that writes bodies and joints: the MJCF and SDFormat ones the
simulation plugins carry and the URDF one in '//builtin/export'. A plugin runs
in a sandbox with this directory on its path, so it imports this module the way
it imports 'mass_properties' and 'urdf_common'. Three exporters deciding for
themselves which parts are one body is three answers to what falls apart.

**The body rule** (docs/design/simulation.md, section 7) is what PartCAD already
says the two kinds of arrangement mean: an assembly is a product that was put
together, and a scene only states where things are.

  * Every element of a scene is a body of its own, recursively: the elements of
    a scene placed in a scene are bodies too. A scene's 'connect:' places one
    object against another; it attaches nothing.
  * Everything inside an assembly is attached. A child placed by 'location:' is
    welded to its container, a 'connect:' that keeps no degree of freedom is
    welded to its target, and one that keeps any is a joint to it. There are no
    fixed joints: what is welded together is *one* body, its mass, centre of mass
    and inertia those of its parts combined ('mass_properties.of_body()').
  * An assembly placed in a scene is one articulated tree of bodies, whose root
    body is free.
  * An element of a scene marked 'fixed: true' is welded to the world; fixing a
    scene fixes every element in it. Free is the default.

The tree says everything the rule reads: each node's "kind" ("part", "assembly"
or "scene"), a scene element's "fixed", a connected child's "joint", and the
sibling a rigid connection welds a child to ("attached") -- all stamped by the
core as the tree is built (see 'partcad.shape_envelope'). A joint naming no
sibling is to the container itself, and a child attached to a sibling that
moves is welded into that sibling's body rather than its container's. A node
with no kind is read by what it carries, children making it an assembly and
geometry a part, which is what a lone part always was. One convention is kept
from before the rule: a node whose shapes are labelled under its own label
("wrist" holding "wrist/1" and "wrist/2") is one body of several shapes wherever
it is, which is how every reader of a robot description writes a link of
several shapes, and how every exporter has always read one.

**The API.** Everything here is plain Python over plain data: a *pose* is
'urdf_common''s ``(quaternion, translation)`` pair, ``(w, x, y, z)`` and
millimetres; an angle is degrees. Each exporter converts at its own boundary --
URDF and SDFormat to metres and radians, MJCF to metres and its own angles.

``bodies(tree, properties=None) -> Bodies``
    The rigid bodies of a shape tree - the 'shape_tree' every implementation is
    handed - parents before children, as a list with a 'problems' attribute
    (what the tree said that the rule ignores: a 'fixed' inside an assembly, a
    joint inside a scene). 'properties' is the request's properties index
    ('request["properties"]'), which every body's physics is read from.

``properties_of(properties, node) -> dict or None``
    A node's entry in that index. Keyed by full name, except that an assembly
    or a scene sharing its full name with a part has its own entry under its
    kind and name ('properties_key()') - the full name is the part's - so an
    exporter reading what a body's own node states asks this rather than
    'properties.get(node["name"])'.

``Body``
    'name' (unique in the list: the label of the node that placed it, then
    "-2", "-3" ... in list order, as joint names are made unique); 'label';
    'path' (the labels from the root down to it); 'node' (the envelope node it
    is rooted at); 'kind'; 'world' (its frame, a pose in the tree's frame);
    'parts' (each a 'BodyPart' with 'node', 'name', 'label', 'physics',
    'placement' in the body's frame and 'world', which is
    'compose(body.world, placement)'); 'parent' (a Body, 'WORLD', or None for a
    free body); 'fixed_to_world'; 'joint' (a 'Joint', or None for a root);
    'children'; 'physics' (the combined physics dict, or None when nothing in it
    weighs anything); 'displacement' ('mass_properties.displacement_of()' of its
    parts, or None); and 'mass_parts()', the (physics, packed placement) pairs
    'physics' was combined from.

    **A floating body.** The child of a FLOATING joint is held by nothing: its
    'parent' is None, as a free root's is, and it is in no body's 'children'.
    It keeps its 'joint', whose 'parent' is the body it was connected to
    ('joint_parent'), because that is what its pose is read against: a
    reading of the joint is the child's pose in that body ('reading').
    'is_floating' says which bodies these are. Every engine writes one as a
    free body of its own -- MJCF a body directly in the '<worldbody>' with a
    '<freejoint>', SDFormat a link with no joint in a model of its own -- and
    the URDF exporter as a 'floating' joint from that body's link, URDF's
    spelling of the same thing.

``Joint``
    The joint of a body to its parent, re-expressed for that pair: its 'steps'
    are the node's joint steps with, in front of them, the target node's frame
    in the parent body (a fixed step of role 'parentFrame', left out where it is
    the identity), so that the child body's frame is the parent body's times
    their product. 'name', 'physics', 'soft_limits', 'mimic', 'turn_limit' (a
    ball's one bound, degrees from its zero, or None) and 'record' (the node's
    joint as the tree stated it) come with it, and 'freedoms' is the free
    steps as 'Freedom's: 'kind' (TURN or MOVE), 'axis' (a unit vector, in the
    frame the steps before it leave), 'lower'/'upper' (degrees, or millimetres
    along the axis; None where open), 'value' (the starting value, same
    units), 'follows'/'ratio'/'offset' (a coupling: 'value = ratio * leader +
    offset', in those units), 'step' (its index in 'steps'), 'parameter' and
    'source' (what declared it). 'parameter_names()' is what each freedom is
    called in a reading, unique within the joint. The frames an exporter
    needs, every one a pose or a vector in millimetres:

      origin                 the first freedom's frame in the parent body
      origins                each freedom's frame relative to the frame the one
                             before it leaves (the first's: the parent body) --
                             a URDF chain, one link per freedom
      tail                   the child body's frame relative to the frame the
                             last freedom leaves: where the child body sits in
                             the *moving* joint frame
      location(values)       the child body's frame in the parent body's
      frame(i, values)       freedom i's frame in the parent body's
      axis_in_parent(i, values), anchor_in_parent(i, values)
      axis_in_child(i, values), anchor_in_child(i, values)
                             freedom i's line in either body; in the child body
                             at the starting values it is an MJCF joint's 'axis'
                             and 'pos'
      origin_in_child(values)
                             the native joint's frame (see 'classify') in the
                             child body: an MJCF ball's 'pos'

    'values' is the freedoms' values, by index (a list, or a dict overriding
    some of them); the default is their starting values, the configuration the
    assembly shows. At those, 'location()' is the child body's placement against
    its parent's -- the joint model's invariant, carried over to the body pair.

``classify(joint) -> Classification``
    What the free steps of a joint (a 'Joint', a node's joint as the tree states
    it, or a list of steps) are: exactly one of the canonical set of section
    8.13.3 of the design record --

      REVOLUTE     one turn, bounded on either side or on neither
      PRISMATIC    one move, likewise
      CYLINDRICAL  a turn and a move on one line, uncoupled, in either order
      SCREW        the same, the move following the turn
      UNIVERSAL    two turns whose lines cross; the first is fixed in the parent
      BALL         three independent turns through one point, in any order, none
                   bounded on its own: a ball is bounded by one angle, the
                   joint's 'turn_limit'
      PLANAR       two moves and the turn about their normal, the moves first or
                   the turn first
      FLOATING     three independent moves one after another, and three
                   independent turns through one point, in any order
      COMPOSITE    anything else: the chain of bodies a declaration leaves out
                   (an XY stage's carriage, a gimbal's ring)

    -- and FIXED for steps with nothing free, which a body's joint never is.
    Beside the kind: 'freedoms'; 'origin', the native joint's frame in the
    frame the steps start in, with every freedom at zero; per freedom its
    'axes' (unit vectors) and 'points' in that frame; and 'tail', the child's
    frame relative to it, so that the location at any values is

        origin . M_1(v_1) . M_2(v_2) ... M_n(v_n) . tail

    where M_i turns about, or moves along, axis i through point i, each in the
    frame the ones before it moved -- MJCF's joints-in-one-body, and URDF's and
    SDFormat's single-axis joints. For every kind but COMPOSITE the points are
    the origin, so a native joint sits at 'origin': a ball's centre, a
    universal joint's crossing, a screw's or a planar joint's axis. See
    section 8.13.4 of the design record for which format writes what, and
    which refuses what.

``rezeroed(joint) -> Rezeroed``
    The joint re-expressed so that an engine's zero is PartCAD's start, for an
    engine that has no starting value of its own (SDFormat; an MJCF ball):
    the child is written where the assembly shows it, and every quantity
    stated about a position shifts by the start, 'e = v - s' (section 8.13.5).
    In series ('origins', 'tail', 'location(values)'), as one native joint of
    several freedoms ('origin', 'native_tail', 'native_location(values)'), as
    a ball ('origin', 'rotation' -- R_s --, 'ball_location(rotation)'), and as
    a free body, written at its start. 'freedoms' are the freedoms with their
    bounds, value and coupling offsets shifted; 'spring_reference(i)',
    'soft_limits(i)' and 'rezeroed_offset()' (a 'mimic''s, between two joints)
    shift the rest. See 'Rezeroed'. URDF is not re-zeroed: what reads one takes
    joint zero to be the hardware's, so the URDF exporter keeps PartCAD's.

``joint_map(joint, freedoms=None, start=True, frame=None, followers=None) -> dict``
    What one engine joint written for 'joint' is -- which PartCAD joint and
    parameters, the kind, the unit factor, the start 's' or 'R_s', and a free
    body's parent -- as plain data for the names sidecar's joint entry
    ('"map"', 'naming.write_sidecar'), which is how a run reads the engine's
    values back without knowing how the exporter wrote anything.

``reading(entries, positions, velocities=None) -> dict``
    One PartCAD joint's reading, from the maps of the engine joints it was
    written as and the engine's values of each: keyed by PartCAD's joint
    name, in PartCAD's units -- a number for a joint of one freedom, an object
    keyed by parameter for several, 'quat' too for a ball or a free body.
    'turns_of(rotation, axes)' is the decomposition of a rotation into three
    turns it uses, and 'per_si(kind)' the unit factor.

The classification table is the design record's, and the order of the freedoms
is part of it only where it changes what the joint is: a planar joint is its
two moves and its turn in either order, the same pair in other coordinates, and
a floating one its six in any order that keeps its three moves together. A coupling makes a pair a screw when
the two lie on one axis and a composite otherwise; a 'mimic' is between joints
and is the exporter's to write.

Placements. A part's 'world' is defined as its body's frame times its placement
in the body, so the two always multiply to it exactly; what the tree states,
composed node by node from the root, agrees with it to rounding -- and to the
bit for a part that is its body's own node, which every element of a scene of
parts is: such a body sits exactly where an exporter writing every geometry node
as a body of its own ('flatten') always put it. The joint invariant holds to
rounding, not to the bit, because the tree carries placements as axis and angle
('[[x, y, z], [ax, ay, az], angle]'), whose round trip is exact to a few units
in the last place; bit for bit is the core's promise, where the placement is the
product of its steps as one 'geom.Location' ('partcad.joint').

Deliberately free of every dependency but 'mass_properties' and 'urdf_common':
no OCP, nothing from 'partcad'.
"""

import math

import mass_properties
import urdf_common

# The envelope keys this reads. Spelled out rather than imported, for the reason
# 'wrapper_export' spells its own: their twins are in 'partcad.shape_envelope',
# and a wrapper cannot import 'partcad'.
KEY_ASSEMBLY = "assembly"
KEY_BREP = "brep"
KEY_GLTF = "gltf"
KEY_GLTF_REF = "gltfRef"
KEY_LOCATION = "location"
KEY_PROPERTIES = "properties"
KEY_JOINT = "joint"
KEY_ATTACHED = "attached"
KEY_KIND = "kind"
KEY_FIXED = "fixed"

# What a node holds.
PART = "part"
ASSEMBLY = "assembly"
SCENE = "scene"
KINDS = (PART, ASSEMBLY, SCENE)

# The parent of a body welded to the world. A free root's parent is None.
WORLD = "world"

# The two kinds of freedom, as a joint's steps spell them.
TURN = "turn"
MOVE = "move"

# What a joint's free steps are (see 'classify'): one native type per physical
# joint (docs/design/simulation.md, section 8.13.3), which are 'motion.type''s,
# plus the two that only describe a result -- 'fixed', steps with nothing free,
# and 'composite', a set of freedoms no native joint has.
FIXED = "fixed"
REVOLUTE = "revolute"
PRISMATIC = "prismatic"
CYLINDRICAL = "cylindrical"
SCREW = "screw"
UNIVERSAL = "universal"
BALL = "ball"
PLANAR = "planar"
FLOATING = "floating"
COMPOSITE = "composite"
NATIVE = (REVOLUTE, PRISMATIC, CYLINDRICAL, SCREW, UNIVERSAL, BALL, PLANAR, FLOATING)

# Kept only until partcad-sim-mujoco and partcad-sim-gazebo stop using them, and
# to be removed then: both plugins import this module, and their CI installs
# PartCAD from 'devel'. 'classify()' never returns CONTINUOUS -- one turn is a
# REVOLUTE whatever its bounds -- and CHAIN is COMPOSITE under its old name.
CONTINUOUS = "continuous"
CHAIN = COMPOSITE

# The role of the fixed step a body's joint starts with: where the node it is
# connected to sits in the parent body (see 'Joint').
ROLE_PARENT_FRAME = "parentFrame"

# How close two directions have to be to be one (the sine of the angle between
# them), and two lines (millimetres apart): 'partcad.motion''s tolerance, which
# is the one the core merged freedoms with, so that two axes it took for one are
# one here too.
TOLERANCE = 1e-6

IDENTITY = (urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T)
_ORIGIN = (0.0, 0.0, 0.0)


#
# Poses
#


def pose_of(packed):
    """PartCAD's packed '[[t], [axis], angle]' as a pose; None is the identity."""
    return urdf_common.from_packed(packed)


def packed_of(pose):
    """A pose as PartCAD's packed form, or None for the exact identity."""
    if pose == IDENTITY:
        return None
    return urdf_common.to_packed(pose)


def compose(first, second):
    """'second' applied within the frame of 'first'."""
    return urdf_common.compose(first, second)


def inverse(pose):
    """The pose that undoes 'pose' - 'geom.Location.inverse()', in the same arithmetic."""
    q, t = pose
    conjugate = (q[0], -q[1], -q[2], -q[3])
    moved = urdf_common.rotate_vec(conjugate, t)
    return (conjugate, (-moved[0], -moved[1], -moved[2]))


def rotate(pose, vector):
    """A direction turned by a pose, and not moved: an axis is not a point."""
    return urdf_common.rotate_vec(pose[0], vector)


def transform_point(pose, point):
    """A point taken from the frame 'pose' places into the frame it is stated in."""
    moved = urdf_common.rotate_vec(pose[0], point)
    return (moved[0] + pose[1][0], moved[1] + pose[1][1], moved[2] + pose[1][2])


def translation(vector):
    return (urdf_common.IDENTITY_Q, (float(vector[0]), float(vector[1]), float(vector[2])))


def motion(kind, axis, value):
    """What one freedom at 'value' is: a turn of that many degrees about 'axis', or a move along it.

    'axis' is a unit vector through the origin of the frame it is stated in, and
    a move is 'value' millimetres along it. None at zero, which composes as
    nothing - the way the core's placement skips a parameter at zero.
    """
    if not value:
        return None
    if kind == TURN:
        return (urdf_common.axis_angle_to_quat(axis, value), (0.0, 0.0, 0.0))
    return translation((axis[0] * value, axis[1] * value, axis[2] * value))


#
# Nodes
#


def is_geometry(node) -> bool:
    """Whether a node carries a shape of its own, in either form."""
    return isinstance(node, dict) and (KEY_BREP in node or KEY_GLTF in node or KEY_GLTF_REF in node)


def is_node(node) -> bool:
    return isinstance(node, dict) and (is_geometry(node) or KEY_ASSEMBLY in node)


def kind_of(node) -> str:
    """What a node holds: its "kind", or - where it states none - what it carries."""
    kind = node.get(KEY_KIND) if isinstance(node, dict) else None
    if kind in KINDS:
        return kind
    return ASSEMBLY if isinstance(node, dict) and KEY_ASSEMBLY in node else PART


def properties_key(node):
    """The key a node's own entry is under where its full name may be another node's too.

    A part and an assembly may share a name within a package - a part 'nut' and
    the assembly 'nut' that holds it - and so share a full name, which is all
    the properties index and the physics the core resolves were ever keyed by.
    Whichever of the two came last took the entry, so an assembly exported with
    its namesake part inside was handed that part's physics: it weighed what the
    part weighs, and with a joint below it was reported as stating its own mass.

    So this is the full name for a part, which keeps the key every reader has
    always looked a part up by, and the kind and the full name for an assembly
    or a scene: 'assembly://pkg:nut'. None for a node with no name, which
    nothing can look up.

    A string, and not a (kind, name) pair, because the core sends the physics
    keyed by it to the sandbox as JSON, whose keys are strings and nothing else.
    It cannot be a part's full name: a full name is '<package>:<name>', and a
    package's name is a path from the root, '//' (see 'partcad.consts.ROOT'), so
    every full name begins with '/' and none begins with a kind.
    """
    name = node.get("name") if isinstance(node, dict) else None
    if not name:
        return None
    kind = kind_of(node)
    return name if kind == PART else "%s:%s" % (kind, name)


def properties_of(properties, node):
    """A node's entry in a properties index ('request["properties"]'), or None.

    Under 'properties_key()' where the index has an entry there - which it
    does for every assembly and scene whose full name another node in the
    request also carries (see 'wrapper_export.properties_index()') - and under
    the full name otherwise, which is where every other node's entry has always
    been, and where an index made by hand keeps it.
    """
    if not isinstance(properties, dict):
        return None
    key = properties_key(node)
    if key is not None and key in properties:
        return properties[key]
    return properties.get(node.get("name")) if isinstance(node, dict) else None


def _children(node) -> list:
    return [child for child in (node.get(KEY_ASSEMBLY) or []) if isinstance(child, dict)]


def _own_shapes(node):
    """The shapes a node is made of by the slash convention, and its other children.

    'shape_elements()' of the exporters, which every one of them applies: a node
    labelled "wrist" whose shapes are labelled "wrist/1" and "wrist/2" is one
    thing of several shapes - a link of a robot description - and not a frame
    holding three things.
    """
    children = _children(node)
    prefix = (node.get("label") or "") + "/"
    if not prefix.strip("/"):
        return [], children
    own = [child for child in children if is_geometry(child) and (child.get("label") or "").startswith(prefix)]
    return own, [child for child in children if not any(child is shape for shape in own)]


def _has_joint_below(node) -> bool:
    for child in _children(node):
        if isinstance(child.get(KEY_JOINT), dict) or _has_joint_below(child):
            return True
    return False


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _length(vector) -> float:
    return math.sqrt(sum(float(v) * float(v) for v in vector))


def _unit(vector):
    length = _length(vector)
    if length == 0.0:
        return None
    return tuple(float(v) / length for v in vector)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _minus(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


#
# Joints
#


class Step:
    """One factor of a joint: fixed (a pose) or free (one degree of freedom).

    As the tree states it (see 'partcad.joint.FreeStep.to_envelope'): a free
    step's 'axis' is the parameter's own direction, not necessarily of unit
    length, and its 'value', 'lower' and 'upper' are the parameter's - degrees
    for a turn, and for a move millimetres per unit of that direction.
    'Freedom' is the same step in units an exporter can write.
    """

    def __init__(self, free=False, location=None, role=None, kind=None, axis=None, lower=None, upper=None):
        self.free = free
        self.location = IDENTITY if location is None else location
        self.role = role
        self.kind = kind
        self.axis = axis
        self.lower = lower
        self.upper = upper
        self.value = 0.0
        self.source = []
        self.coupling = None
        self.entry = None

    @classmethod
    def from_envelope(cls, entry):
        if not isinstance(entry, dict):
            return cls(role="unknown")
        if entry.get("type") != "free":
            step = cls(location=pose_of(entry.get("location")), role=entry.get("role"))
            step.source = entry.get("source")
            step.entry = entry
            return step
        step = cls(
            free=True,
            kind=TURN if entry.get("kind") == TURN else MOVE,
            axis=[float(v) for v in (entry.get("axis") or (0.0, 0.0, 1.0))],
            lower=_number(entry.get("lower")),
            upper=_number(entry.get("upper")),
        )
        step.value = _number(entry.get("value")) or 0.0
        step.source = [dict(source) for source in entry.get("source") or [] if isinstance(source, dict)]
        coupling = entry.get("coupling")
        step.coupling = dict(coupling) if isinstance(coupling, dict) else None
        step.entry = entry
        return step

    def __repr__(self):
        if self.free:
            return "<free %s %s [%s, %s] = %s>" % (self.kind, self.axis, self.lower, self.upper, self.value)
        return "<fixed %s>" % self.role


class Freedom:
    """One free step of a joint, in the units every exporter writes.

    'axis' is a unit vector in the frame the steps before it leave. For a move
    the step's own direction need not be of unit length, and its value is in
    millimetres per unit of it; here the value, the bounds and the coupling are
    all millimetres along 'axis', and 'scale' is the length that was factored
    out. A turn's are degrees, and its 'scale' is 1.
    """

    def __init__(self, index, step_index, step):
        self.index = index
        self.step = step_index
        self.kind = step.kind
        axis = _unit(step.axis)
        self.axis = axis if axis is not None else (0.0, 0.0, 1.0)
        self.scale = _length(step.axis) if (step.kind == MOVE and axis is not None) else 1.0
        self.lower = None if step.lower is None else step.lower * self.scale
        self.upper = None if step.upper is None else step.upper * self.scale
        self.value = step.value * self.scale
        self.source = step.source
        names = [entry.get("parameter") for entry in step.source if entry.get("parameter")]
        self.parameter = "+".join(str(name) for name in names) or None
        # A coupling to another freedom of the same joint: 'value = ratio *
        # leader + offset', the leader by its index among the freedoms.
        self.follows = None
        self.ratio = None
        self.offset = None

    @property
    def limited(self) -> bool:
        """Whether a bound is stated on either side - which a joint kind needs to be a revolute."""
        return self.lower is not None or self.upper is not None

    def motion(self, value=None):
        return motion(self.kind, self.axis, self.value if value is None else value)

    def __repr__(self):
        return "<Freedom %d %s %s [%s, %s] = %s>" % (
            self.index,
            self.kind,
            self.axis,
            self.lower,
            self.upper,
            self.value,
        )


class Joint:
    """A joint as the steps that relate one frame to another.

    Built by 'bodies()' for a body and its parent, with the target node's frame
    in the parent body in front of the node's own steps ('parent_frame'); or
    from a node's joint alone, when it relates the node the joint is connected
    to and the node it moves. See the module docstring for the frames.
    """

    def __init__(self, record, parent=None, child=None, parent_frame=None):
        record = record if isinstance(record, dict) else {}
        self.record = record
        self.name = record.get("name")
        self.parent = parent
        self.child = child
        # The two links the joint was declared between, by label: the node it
        # is connected to and the node it moves, siblings in one 'links:' list.
        self.parent_link = record.get("parent")
        self.child_link = record.get("child")
        self.physics = dict(record.get("physics") or {})
        self.soft_limits = record.get("softLimits")
        self.mimic = record.get("mimic")
        # A ball's one bound, in degrees: how far it turns from its zero.
        self.turn_limit = _number(record.get("turnLimit"))

        steps = []
        if parent_frame is not None and parent_frame != IDENTITY:
            steps.append(Step(location=parent_frame, role=ROLE_PARENT_FRAME))
        shift = len(steps)
        steps.extend(Step.from_envelope(entry) for entry in record.get("steps") or [])
        self.steps = steps

        self.freedoms = []
        self._by_step = {}
        for index, step in enumerate(steps):
            if step.free:
                freedom = Freedom(len(self.freedoms), index, step)
                self.freedoms.append(freedom)
                self._by_step[index] = freedom
        for freedom in self.freedoms:
            coupling = steps[freedom.step].coupling
            if not coupling:
                continue
            leader = self._by_step.get(int(_number(coupling.get("step")) or 0) + shift)
            ratio = _number(coupling.get("ratio"))
            if leader is None or leader is freedom or ratio is None:
                continue
            freedom.follows = leader.index
            freedom.ratio = ratio * freedom.scale / leader.scale
            freedom.offset = (_number(coupling.get("offset")) or 0.0) * freedom.scale

        self.origins = []
        current = IDENTITY
        for step in steps:
            if step.free:
                self.origins.append(current)
                current = IDENTITY
            else:
                current = compose(current, step.location)
        self.tail = current
        self._classification = None

    @property
    def origin(self):
        """The first freedom's frame in the frame the steps start in, or None with nothing free."""
        return self.origins[0] if self.origins else None

    def parameter_names(self) -> list:
        """What each freedom is called in a reading of the joint, by index: unique within the joint.

        Its parameter ('turnZ', or 'turnZ+turnZ' for two summed into one), or
        its kind and index where no parameter declared it ('turn0'); a name a
        freedom before it took is told apart as names are elsewhere ('-2', ...).
        """
        names = []
        for freedom in self.freedoms:
            base = freedom.parameter or "%s%d" % (freedom.kind, freedom.index)
            name, suffix = base, 2
            while name in names:
                name = "%s-%d" % (base, suffix)
                suffix += 1
            names.append(name)
        return names

    def values(self, values=None) -> list:
        """The freedoms' values: the starting ones, with 'values' laid over them."""
        result = [freedom.value for freedom in self.freedoms]
        if values is None:
            return result
        if isinstance(values, dict):
            for index, value in values.items():
                result[index] = float(value)
            return result
        values = list(values)
        if len(values) != len(result):
            raise ValueError("%d values for a joint of %d freedoms" % (len(values), len(result)))
        return [float(value) for value in values]

    def _product(self, values, stop=None):
        values = self.values(values)
        pose = IDENTITY
        for index, step in enumerate(self.steps):
            if stop is not None and index == stop:
                break
            if step.free:
                moved = self._by_step[index].motion(values[self._by_step[index].index])
                if moved is not None:
                    pose = compose(pose, moved)
            else:
                pose = compose(pose, step.location)
        return pose

    def location(self, values=None):
        """The frame the steps lead to - the child body's - in the frame they start in."""
        return self._product(values)

    def frame(self, index, values=None):
        """Freedom 'index''s frame, before it is applied, in the frame the steps start in."""
        return self._product(values, stop=self.freedoms[index].step)

    def axis_in_parent(self, index, values=None):
        return rotate(self.frame(index, values), self.freedoms[index].axis)

    def anchor_in_parent(self, index, values=None):
        return self.frame(index, values)[1]

    def _in_child(self, index, values):
        return compose(inverse(self.location(values)), self.frame(index, values))

    def axis_in_child(self, index, values=None):
        """Freedom 'index''s axis in the child body's frame: an MJCF joint's 'axis'."""
        return rotate(self._in_child(index, values), self.freedoms[index].axis)

    def anchor_in_child(self, index, values=None):
        """A point of freedom 'index''s axis in the child body's frame: an MJCF joint's 'pos'."""
        return self._in_child(index, values)[1]

    def origin_in_child(self, values=None):
        """The native joint's frame ('classification.origin') in the child body's frame.

        Where a joint of several freedoms that a format writes as one sits in
        the body it moves: an MJCF 'ball''s 'pos' is this frame's origin, the
        centre all three turns go through.
        """
        origin = self.classification.origin
        if origin is None:
            return None
        return compose(inverse(self.location(values)), origin)

    @property
    def classification(self):
        if self._classification is None:
            self._classification = _classify(self)
        return self._classification

    @property
    def kind(self) -> str:
        return self.classification.kind

    def __repr__(self):
        return "<Joint %s: %s, %s>" % (self.name, self.kind, self.freedoms)


class Classification:
    """What a joint's free steps are, and the one frame a native joint of that kind sits in.

    See 'classify()'. 'location(values)' is the decomposition multiplied back
    out, which is the joint's own 'location(values)' to rounding.
    """

    def __init__(self, kind, freedoms, origin, axes, points, tail):
        self.kind = kind
        self.freedoms = freedoms
        self.origin = origin
        self.axes = axes
        self.points = points
        self.tail = tail

    def location(self, values=None):
        values = [freedom.value for freedom in self.freedoms] if values is None else list(values)
        pose = self.origin if self.origin is not None else IDENTITY
        for freedom, axis, point, value in zip(self.freedoms, self.axes, self.points, values):
            moved = motion(freedom.kind, axis, value)
            if moved is None:
                continue
            if freedom.kind == TURN and any(point):
                moved = compose(compose(translation(point), moved), translation((-point[0], -point[1], -point[2])))
            pose = compose(pose, moved)
        return compose(pose, self.tail)

    def __repr__(self):
        return "<Classification %s>" % self.kind


def classify(joint) -> Classification:
    """What the free steps of a joint are; see the module docstring.

    'joint' is a 'Joint', a node's joint as the tree states it, or the list of
    its steps.
    """
    if isinstance(joint, Joint):
        return joint.classification
    if isinstance(joint, (list, tuple)):
        joint = {"steps": list(joint)}
    return Joint(joint).classification


def _parallel(a, b) -> int:
    if _length(_cross(a, b)) > TOLERANCE:
        return 0
    return 1 if _dot(a, b) > 0 else -1


def _closest_to_origin(point, axis):
    """The point of a line nearest the origin of the frame it is stated in."""
    along = _dot(point, axis)
    return (point[0] - along * axis[0], point[1] - along * axis[1], point[2] - along * axis[2])


def _on_line(point, line_point, axis) -> bool:
    return _length(_cross(_minus(point, line_point), axis)) <= TOLERANCE


def _meet(point_a, axis_a, point_b, axis_b):
    """Where two lines that are not parallel cross, or None where they pass apart."""
    b = _dot(axis_a, axis_b)
    denominator = 1.0 - b * b
    if denominator <= TOLERANCE * TOLERANCE:
        return None
    w = _minus(point_a, point_b)
    d = _dot(axis_a, w)
    e = _dot(axis_b, w)
    s = (b * e - d) / denominator
    t = (e - b * d) / denominator
    on_a = tuple(point_a[i] + s * axis_a[i] for i in range(3))
    on_b = tuple(point_b[i] + t * axis_b[i] for i in range(3))
    if _length(_minus(on_a, on_b)) > TOLERANCE:
        return None
    return on_a


def _independent(axes) -> bool:
    """Whether three directions span space - no two parallel and not all in one plane."""
    return abs(_dot(axes[0], _cross(axes[1], axes[2]))) > TOLERANCE


def _moves_across(moves, normal) -> bool:
    """Whether two moves span the plane across 'normal': not parallel, and each square to it."""
    return (
        not _parallel(moves[0], moves[1])
        and abs(_dot(moves[0], normal)) <= TOLERANCE
        and abs(_dot(moves[1], normal)) <= TOLERANCE
    )


def _kind(freedoms, axes, points):
    """The kind of a set of freedoms, and the point a native joint of it is centred on (or None)."""
    kinds = [freedom.kind for freedom in freedoms]
    coupled = [freedom for freedom in freedoms if freedom.follows is not None]
    count = len(freedoms)
    if count == 1:
        # One turn is a revolute whatever its bounds: a bound on either side,
        # or on neither, is a property of the hinge and not a second kind.
        return (REVOLUTE if kinds[0] == TURN else PRISMATIC), None
    if count == 2 and sorted(kinds) == [MOVE, TURN]:
        turn = 0 if kinds[0] == TURN else 1
        if not _parallel(axes[0], axes[1]):
            return COMPOSITE, None
        centre = _closest_to_origin(points[turn], axes[turn])
        if not coupled:
            return CYLINDRICAL, centre
        if len(coupled) == 1 and coupled[0].follows == freedoms[1 - coupled[0].index].index:
            return SCREW, centre
        return COMPOSITE, None
    if coupled:
        # A coupled freedom is not a freedom of its own, and only a screw is a
        # native joint with one in it.
        return COMPOSITE, None
    if count == 2 and kinds == [TURN, TURN]:
        centre = _meet(points[0], axes[0], points[1], axes[1])
        return (UNIVERSAL, centre) if centre is not None else (COMPOSITE, None)
    if count == 3 and kinds == [TURN, TURN, TURN] and _independent(axes):
        centre = _meet(points[0], axes[0], points[1], axes[1])
        if centre is None or not _on_line(centre, points[2], axes[2]):
            return COMPOSITE, None
        if any(freedom.limited for freedom in freedoms):
            # A ball is bounded by one angle, how far it turns from its zero
            # (the joint's 'turn_limit'), and not turn by turn: three turns
            # through a point each bounded on its own are the gimbal a ball
            # has not got, which is what a composite is.
            return COMPOSITE, None
        return BALL, centre
    if count == 3 and kinds == [MOVE, MOVE, TURN] and _moves_across(axes[:2], axes[2]):
        # A planar joint, the moves first: its turn is about the line it is on.
        return PLANAR, _closest_to_origin(points[2], axes[2])
    if count == 3 and kinds == [TURN, MOVE, MOVE] and _moves_across(axes[1:], axes[0]):
        # The same pair in the other order, the turn first: the moves are then
        # across the plane in the frame the turn left, which is the same plane.
        return PLANAR, _closest_to_origin(points[0], axes[0])
    if count == 6 and sorted(kinds) == [MOVE] * 3 + [TURN] * 3:
        # Six freedoms that hold nothing, in whatever order they were declared
        # (a 'dof' list may name the turns first, and a reader of another
        # format may state them so): three moves one after another, so that no
        # turn between two of them can turn one onto the other, and three
        # turns about lines through one point. Anything else is a composite.
        moves = [index for index, kind in enumerate(kinds) if kind == MOVE]
        turns = [index for index, kind in enumerate(kinds) if kind == TURN]
        if (
            moves == list(range(moves[0], moves[0] + 3))
            and _independent([axes[i] for i in moves])
            and _independent([axes[i] for i in turns])
        ):
            centre = _meet(points[turns[0]], axes[turns[0]], points[turns[1]], axes[turns[1]])
            if centre is not None and _on_line(centre, points[turns[2]], axes[turns[2]]):
                return FLOATING, centre
    return COMPOSITE, None


def _classify(joint) -> Classification:
    freedoms = joint.freedoms
    if not freedoms:
        return Classification(FIXED, [], None, [], [], joint.tail)
    # Every freedom's line in the first one's frame, with all of them at zero
    # and every fixed step at its value: what the core merged two freedoms by,
    # and what a native joint has to be stated in.
    axes, points = [], []
    prefix = IDENTITY
    for index in range(freedoms[0].step, len(joint.steps)):
        step = joint.steps[index]
        if step.free:
            freedom = joint._by_step[index]
            axes.append(_unit(rotate(prefix, freedom.axis)) or (0.0, 0.0, 1.0))
            points.append(prefix[1])
        else:
            prefix = compose(prefix, step.location)
    kind, centre = _kind(freedoms, axes, points)
    centre = _ORIGIN if centre is None else centre
    origin = compose(joint.origins[0], translation(centre))
    if kind == COMPOSITE:
        # Each turn's line by its point nearest the origin; a move has no line,
        # only a direction.
        points = [
            _closest_to_origin(point, axis) if freedom.kind == TURN else _ORIGIN
            for freedom, point, axis in zip(freedoms, points, axes)
        ]
    else:
        # Every line of a native joint goes through its centre, which is what
        # finding the kind checked: they are through the origin of its frame.
        points = [_ORIGIN] * len(freedoms)
    tail = compose(translation((-centre[0], -centre[1], -centre[2])), prefix)
    return Classification(kind, freedoms, origin, axes, points, tail)


#
# Starting values: re-zeroing, the joint map, and readings
#

# PartCAD units per SI unit of a freedom: degrees a radian, millimetres a metre.
# What every engine's joint coordinates are in (MuJoCo's 'qpos' is radians
# whatever '<compiler angle>' says, which converts only what the file states).
DEGREES_PER_RADIAN = math.degrees(1.0)
MILLIMETRES_PER_METRE = urdf_common.MM_PER_M

# The frame an engine may state a ball's rotation in, for 'joint_map': the child
# body's own, which is MuJoCo's (a ball's frame there is its body's).
CHILD_FRAME = "child"


def per_si(kind) -> float:
    """PartCAD units per SI unit of a freedom of 'kind': degrees a radian, or millimetres a metre."""
    return DEGREES_PER_RADIAN if kind == TURN else MILLIMETRES_PER_METRE


def _shifted(bound, start):
    return None if bound is None else bound - start


def _conjugate(q):
    return (q[0], -q[1], -q[2], -q[3])


def _turned(q, by):
    """'q' seen from a frame turned by 'by': by . q . by^-1."""
    return urdf_common.quat_mul(urdf_common.quat_mul(by, q), _conjugate(by))


def _product(kinds, axes, values):
    """The motions of freedoms about or along axes through the origin, one after another."""
    pose = IDENTITY
    for kind, axis, value in zip(kinds, axes, values):
        moved = motion(kind, axis, value)
        if moved is not None:
            pose = compose(pose, moved)
    return pose


def _commute(kind_a, axis_a, kind_b, axis_b) -> bool:
    """Whether two freedoms about or along lines through one point move the same way in either order."""
    if kind_a == MOVE and kind_b == MOVE:
        return True
    return bool(_parallel(axis_a, axis_b))


def _split(kinds, axes):
    """How many leading freedoms of a native joint take their start into its frame, or None.

    The starts of the freedoms before the split go into the joint frame and
    those after it into the child's, which is right where each side is a set of
    freedoms that commute with one another: a start in front has to move past
    the engine's motions of the freedoms before it, and one behind past those
    after it. The most that can go in front, so that a screw's or a
    cylindrical's two starts are both in the joint frame, a universal joint's
    first is and its second is not, and a planar joint's turn is wherever its
    order puts it -- never in front of moves it does not commute with.
    """
    count = len(kinds)

    def commuting(indices):
        return all(_commute(kinds[i], axes[i], kinds[j], axes[j]) for i in indices for j in indices if i < j)

    for split in range(count, -1, -1):
        if commuting(range(split)) and commuting(range(split, count)):
            return split
    return None


class RezeroedFreedom:
    """One freedom of a joint as an engine whose zero is PartCAD's start states it.

    The same fields as a 'Freedom' -- 'index', 'step', 'kind', 'axis',
    'parameter', 'source', 'follows' and 'ratio' -- with every quantity that is
    a position of the freedom shifted by 'start', its starting value: 'value'
    (nought, where it starts), 'lower' and 'upper' (an open side stays open)
    and the coupling's 'offset', which keeps 'value = ratio * leader + offset'
    true in the engine's terms.
    """

    def __init__(self, freedom, starts):
        self.index = freedom.index
        self.step = freedom.step
        self.kind = freedom.kind
        self.axis = freedom.axis
        self.scale = freedom.scale
        self.parameter = freedom.parameter
        self.source = freedom.source
        self.start = freedom.value
        self.value = 0.0
        self.lower = _shifted(freedom.lower, freedom.value)
        self.upper = _shifted(freedom.upper, freedom.value)
        self.follows = freedom.follows
        self.ratio = freedom.ratio
        self.offset = None
        if freedom.follows is not None:
            self.offset = rezeroed_offset(freedom.offset or 0.0, freedom.ratio, starts[freedom.follows], freedom.value)

    @property
    def limited(self) -> bool:
        return self.lower is not None or self.upper is not None

    def motion(self, value=None):
        return motion(self.kind, self.axis, self.value if value is None else value)

    def __repr__(self):
        return "<RezeroedFreedom %d %s from %s [%s, %s]>" % (self.index, self.kind, self.start, self.lower, self.upper)


def rezeroed_offset(offset, multiplier, leader_start, follower_start) -> float:
    """A coupling's offset in the terms of an engine whose zero is PartCAD's start.

    'value_f = multiplier * value_l + offset' in PartCAD's values is
    'e_f = multiplier * e_l + (offset + multiplier * s_l - s_f)' in the
    engine's, 'e = value - s' (section 8.13.5). For a screw's move within one
    joint, and for a 'mimic' between two, whose starts are each joint's.
    """
    return float(offset) + float(multiplier) * float(leader_start) - float(follower_start)


class Rezeroed:
    """A joint re-expressed so that an engine's zero is PartCAD's start (docs/design/simulation.md, 8.13.5).

    Where an engine has no starting value of its own -- SDFormat, an MJCF ball
    -- the joint is written so that the engine's zero *is* where the assembly
    shows it: the child at its start, and every axis where that configuration
    puts it. The engine's value of a freedom is then 'e = v - s', 's' its
    start, and everything stated about a position shifts with it. Two ways to
    write the same joint, and both are here:

    **Joints in series** -- one single-axis joint per freedom, MJCF's joints in
    one body or a chain of URDF or SDFormat joints. Each absorbs its own start:
    'origins[i]' is 'joint.origins[i] . M_i(s_i)', freedom i's frame against
    the one before at the engine's zero, and 'tail' is the joint's own. Every
    axis keeps its components in its frame. 'location(values)' multiplies
    them back out.

    **One native joint** -- a joint of several freedoms written as one (an
    SDFormat universal or screw, a URDF planar). 'origin' is the native joint's
    frame ('classification.origin') with the starts of the freedoms that
    commute with every freedom before them absorbed in front, and
    'native_tail' the child's frame in its moving frame with the rest absorbed
    behind: a universal joint's first turn in front and its second behind; a
    planar joint's moves in front of its turn, or its turn in front of its
    moves, as its order has them, and never a turn in front of moves it does
    not commute with -- which would turn the engine's moves against PartCAD's.
    The axes are 'classification.axes', unchanged. 'native_location(values)'
    multiplies it back out. For a joint of one freedom the two ways agree.

    **A ball** is a rotation, not three turns: 'origin' is its frame turned by
    'rotation', the starting rotation R_s (a quaternion, 'w x y z'), so that
    the engine's rotation R_e is the turn away from the start and PartCAD's is
    R_s . R_e. 'native_tail' is the classification's. 'ball_location(R_e)'
    multiplies it back out.

    **A free body** (FLOATING) is written at its start, and its pose is the
    engine's coordinates: 'origin' is the native frame moved and turned to the
    start (so 'origin . native_tail' is where the child starts), and
    'rotation' the turns' start. A reading of it is its pose against its
    parent's ('reading').

    'freedoms' are 'RezeroedFreedom's: bounds, value and couplings shifted.
    'starts' are the starting values themselves, by index.
    """

    def __init__(self, joint):
        self.joint = joint
        classification = joint.classification
        self.kind = classification.kind
        freedoms = joint.freedoms
        self.starts = [freedom.value for freedom in freedoms]
        self.freedoms = [RezeroedFreedom(freedom, self.starts) for freedom in freedoms]

        # In series: each freedom's frame absorbs its own start.
        self.origins = [
            compose(origin, freedom.motion() or IDENTITY) for origin, freedom in zip(joint.origins, freedoms)
        ]
        self.tail = joint.tail

        self.rotation = None
        self.split = None
        kinds = [freedom.kind for freedom in freedoms]
        axes = classification.axes
        if not freedoms:
            self.origin, self.native_tail = None, joint.tail
        elif self.kind == BALL:
            self.rotation = _product(kinds, axes, self.starts)[0]
            self.origin = compose(classification.origin, (self.rotation, urdf_common.IDENTITY_T))
            self.native_tail = classification.tail
        elif self.kind == FLOATING:
            turns = [index for index, kind in enumerate(kinds) if kind == TURN]
            self.rotation = _product([TURN] * len(turns), [axes[i] for i in turns], [self.starts[i] for i in turns])[0]
            self.origin = compose(classification.origin, _product(kinds, axes, self.starts))
            self.native_tail = classification.tail
        elif self.kind == COMPOSITE:
            # No native joint: the series is the only way to write it.
            self.origin, self.native_tail = self.origins[0], self.tail
        else:
            self.split = _split(kinds, axes)
            front, back = range(self.split), range(self.split, len(freedoms))
            self.origin = compose(
                classification.origin, _product([kinds[i] for i in front], [axes[i] for i in front], self.starts)
            )
            self.native_tail = compose(
                _product([kinds[i] for i in back], [axes[i] for i in back], [self.starts[i] for i in back]),
                classification.tail,
            )

    def _values(self, values):
        if values is None:
            return [0.0] * len(self.freedoms)
        if isinstance(values, dict):
            result = [0.0] * len(self.freedoms)
            for index, value in values.items():
                result[index] = float(value)
            return result
        return [float(value) for value in values]

    def location(self, values=None):
        """The child's frame in the frame the steps start in, at the engine's values in series (PartCAD units)."""
        pose = IDENTITY
        for origin, freedom, value in zip(self.origins, self.freedoms, self._values(values)):
            pose = compose(compose(pose, origin), freedom.motion(value) or IDENTITY)
        return compose(pose, self.tail)

    def native_location(self, values=None):
        """The same, written as one native joint about 'classification.axes' from 'origin'.

        None for a ball and a free body, whose engine coordinates are a
        rotation and a pose ('ball_location'); a composite, which is no native
        joint, is its series.
        """
        if self.kind in (BALL, FLOATING, COMPOSITE):
            return self.location(values) if self.kind == COMPOSITE else None
        kinds = [freedom.kind for freedom in self.freedoms]
        moved = _product(kinds, self.joint.classification.axes, self._values(values))
        return compose(compose(self.origin, moved), self.native_tail)

    def ball_location(self, rotation):
        """A ball's child frame at the engine's rotation 'rotation' (a quaternion: the turn away from its start)."""
        return compose(compose(self.origin, (tuple(rotation), urdf_common.IDENTITY_T)), self.native_tail)

    def spring_reference(self, index):
        """The joint's 'springReference', for freedom 'index', in the engine's terms; None where it states none."""
        reference = _number(self.joint.physics.get("springReference"))
        return None if reference is None else reference - self.starts[index]

    def soft_limits(self, index):
        """The joint's 'softLimits' for freedom 'index' in the engine's terms, or None: the bounds shifted."""
        soft = self.joint.soft_limits
        if not isinstance(soft, dict) or not soft:
            return None
        shifted = dict(soft)
        for side in ("lower", "upper"):
            value = _number(soft.get(side))
            if value is not None:
                shifted[side] = value - self.starts[index]
        return shifted

    def __repr__(self):
        return "<Rezeroed %s from %s>" % (self.kind, self.starts)


def rezeroed(joint) -> Rezeroed:
    """'joint' (a 'Joint', a node's joint as the tree states it, or its steps) re-zeroed at its start."""
    if not isinstance(joint, Joint):
        joint = Joint({"steps": list(joint)} if isinstance(joint, (list, tuple)) else joint)
    return Rezeroed(joint)


def _pose_data(pose):
    return [list(pose[0]), list(pose[1])]


def _pose_of_data(data):
    return (tuple(float(v) for v in data[0]), tuple(float(v) for v in data[1]))


def joint_map(joint, freedoms=None, start=True, frame=None, followers=None) -> dict:
    """What one engine joint written for 'joint' is, for a run to read it back by: a sidecar's 'map'.

    The exporter that writes a joint knows which engine joint holds which of
    its freedoms and whether the engine's zero is PartCAD's start; the run that
    reads the engine's values knows neither. This is what it needs, as plain
    data, so that it travels in the names sidecar beside the joint's names
    ('naming.write_sidecar', each joint entry's "map"; section 8.13.5 of
    docs/design/simulation.md) and 'reading()' turns the engine's values into
    PartCAD's. Computed here, once, so that no plugin carries a copy.

    'freedoms' are the indices of the joint's freedoms the engine joint has as
    its coordinates, in its own order: one for a hinge or a slide, two for an
    SDFormat universal. None means one native joint for the whole, whose
    coordinates are its freedoms that follow nothing -- but a screw's, which
    is its turn whichever of its two leads (8.13.3: a screw is read by its
    turn, as SDFormat's screw is). 'followers' are the indices of the
    freedoms that move with those coordinates and are no coordinate of any
    engine joint -- an SDFormat screw's move; by default, where 'freedoms' is
    None, every freedom that follows a coordinate or that a coordinate
    follows, and none otherwise. A follower is written as what it is in terms
    of the coordinate it moves with: the coupling as it stands where it
    follows the coordinate, and turned round ('value = (coordinate - offset)
    / ratio') where the coordinate follows it. Indices that name no freedom,
    and a follower coupled to no coordinate, raise ValueError.

    'start' says whether the engine's zero is PartCAD's start -- a joint
    re-zeroed ('rezeroed()'), as SDFormat's and an MJCF ball are -- or
    PartCAD's zero, as an MJCF hinge's is, whose 'ref' makes MuJoCo's value
    PartCAD's. 'frame' is, for a ball, the frame the engine states its rotation
    in: None for the ball's own joint frame, CHILD_FRAME for the child body's
    (MuJoCo's), or a quaternion turning the joint frame into it.

    The entry, every quantity in PartCAD's units unless it says otherwise::

        {"joint": "<PartCAD joint>", "kind": "<classify() kind>", "freedoms": <how many it has>,
         "coordinates": [{"parameter", "freedom": "turn"|"move", "factor", "start"}, ...],
         "followers":   [{"parameter", "freedom", "follows": "<parameter>", "ratio", "offset"}, ...]}

    'factor' is PartCAD units per engine unit (degrees a radian, millimetres a
    metre) and 'start' what to add after it: the freedom's start where the
    engine was re-zeroed, nought where it was not. A follower is 'ratio *
    leader + offset' in PartCAD's values. A ball adds
    ``"rotation": [w, x, y, z]`` (R_s, or the identity where it was not
    re-zeroed), ``"frame": [w, x, y, z]`` and ``"turns": [{"parameter",
    "axis", "start"}, ...]``, its three turns' axes in its joint frame, which
    its rotation is reported in. A free body adds ``"parent": "<PartCAD
    body>"``, ``"origin"`` and ``"tail"`` (the native joint's frame in the
    parent body at PartCAD's zero, and the child's in its moving frame, as
    '[[w, x, y, z], [x, y, z]]' in millimetres), ``"length": 1000.0``
    (millimetres per engine unit of a pose), and ``"sequence": [{"parameter",
    "freedom", "axis", "start"}, ...]``, its six freedoms in the order they
    apply, its three moves one after another.
    """
    if not isinstance(joint, Joint):
        joint = Joint(joint)
    classification = joint.classification
    kind = classification.kind
    names = joint.parameter_names()
    entry = {"joint": joint.name, "kind": kind, "freedoms": len(joint.freedoms)}
    shifted = rezeroed(joint)

    def axes_of(indices):
        return [
            {
                "parameter": names[i],
                "axis": list(classification.axes[i]),
                "start": joint.freedoms[i].value,
            }
            for i in indices
        ]

    if kind == BALL:
        if frame == CHILD_FRAME:
            frame = shifted.native_tail[0]
        entry["rotation"] = list(shifted.rotation if start else urdf_common.IDENTITY_Q)
        entry["frame"] = list(frame if frame is not None else urdf_common.IDENTITY_Q)
        entry["turns"] = axes_of(range(3))
        return entry
    if kind == FLOATING:
        parent = joint.parent
        entry["parent"] = parent.name if isinstance(parent, Body) else parent
        entry["origin"] = _pose_data(classification.origin)
        entry["tail"] = _pose_data(classification.tail)
        entry["length"] = MILLIMETRES_PER_METRE
        entry["sequence"] = [
            dict(axis, freedom=joint.freedoms[index].kind) for index, axis in enumerate(axes_of(range(6)))
        ]
        return entry

    count = len(joint.freedoms)
    if freedoms is None:
        if kind == SCREW:
            indices = [freedom.index for freedom in joint.freedoms if freedom.kind == TURN]
        else:
            indices = [freedom.index for freedom in joint.freedoms if freedom.follows is None]
        if followers is None:
            followers = [
                freedom.index
                for freedom in joint.freedoms
                if freedom.index not in indices
                and (freedom.follows in indices or any(joint.freedoms[i].follows == freedom.index for i in indices))
            ]
    else:
        indices = [int(index) for index in freedoms]
    followers = [int(index) for index in followers or []]
    for index in indices + followers:
        if not 0 <= index < count:
            raise ValueError("The joint '%s' has %d freedoms, and no freedom %d" % (joint.name, count, index))
    entry["coordinates"] = [
        {
            "parameter": names[i],
            "freedom": joint.freedoms[i].kind,
            "factor": per_si(joint.freedoms[i].kind),
            "start": joint.freedoms[i].value if start else 0.0,
        }
        for i in indices
    ]
    entry["followers"] = [_follower(joint, names, index, indices) for index in followers]
    return entry


def _follower(joint, names, index, coordinates):
    """A freedom that moves with one of an engine joint's coordinates, as that coordinate's function."""
    freedom = joint.freedoms[index]
    if freedom.follows is not None and freedom.follows in coordinates:
        return {
            "parameter": names[index],
            "freedom": freedom.kind,
            "follows": names[freedom.follows],
            "ratio": freedom.ratio,
            "offset": freedom.offset or 0.0,
        }
    # The coordinate follows this freedom ('c = r v + o'): this freedom is the
    # coupling turned round, 'v = c / r - o / r'.
    leader = next((joint.freedoms[i] for i in coordinates if joint.freedoms[i].follows == index), None)
    if leader is not None and leader.ratio:
        return {
            "parameter": names[index],
            "freedom": freedom.kind,
            "follows": names[leader.index],
            "ratio": 1.0 / leader.ratio,
            "offset": -(leader.offset or 0.0) / leader.ratio,
        }
    raise ValueError(
        "The freedom '%s' of the joint '%s' is no follower of the coordinates %s, nor followed by one: it is a "
        "coordinate of an engine joint of its own"
        % (names[index], joint.name, ", ".join(names[i] for i in coordinates))
    )


def _unwrapped(angle, near):
    """'angle' (degrees) plus the whole turns that bring it nearest 'near'."""
    return angle - 360.0 * round((angle - near) / 360.0)


def _about(axis, vector, onto):
    """The angle (degrees) a turn about the unit 'axis' takes 'vector' to 'onto' by."""
    across = _cross(vector, onto)
    along = _dot(vector, onto) - _dot(axis, vector) * _dot(axis, onto)
    return math.degrees(math.atan2(_dot(axis, across), along))


def turns_of(rotation, axes, near=None):
    """Three turns about 'axes', one after another, that make the rotation 'rotation', or None.

    'rotation' is a quaternion, 'w x y z'; each turn is about its axis in the
    frame the ones before it left, as a joint's freedoms are, so that
    'R = R_1(a_1) . R_2(a_2) . R_3(a_3)'. Davenport's generalisation of Euler
    angles: it needs each next pair of axes square to each other (the turnX,
    turnY, turnZ 'motion: ball' implies are), and returns None otherwise -- a
    rotation there has no three such turns to report. Of the two sets of turns
    that make every rotation, the one nearest 'near' (degrees; the starting
    values, so that a reading begins where the joint does) is returned, each
    turn unwrapped to the whole turns nearest it; at gimbal lock, where only a
    sum is determined, the third turn is 'near''s. Anything but three axes --
    a map that states none, as one written before its joint's turns were known
    -- has no three turns either, and is None too; so is a 'near' of any other
    length taken as none.
    """
    axes = list(axes or [])
    if len(axes) != 3:
        return None
    n1, n2, n3 = (_unit(axis) for axis in axes)
    if None in (n1, n2, n3) or abs(_dot(n1, n2)) > TOLERANCE or abs(_dot(n2, n3)) > TOLERANCE:
        return None
    near = list(near or [])
    near = [float(v) for v in near] if len(near) == 3 else [0.0, 0.0, 0.0]
    rotation = urdf_common.normalize(tuple(rotation))
    phi = math.degrees(math.atan2(_dot(n1, _cross(n2, n3)), _dot(n1, n3)))
    d = max(-1.0, min(1.0, _dot(n1, urdf_common.rotate_vec(rotation, n3))))
    spread = math.degrees(math.acos(d))
    w = urdf_common.rotate_vec(rotation, n3)
    y = urdf_common.rotate_vec(_conjugate(rotation), n1)
    candidates = []
    for second in (phi + spread, phi - spread):
        v = urdf_common.rotate_vec(urdf_common.axis_angle_to_quat(n2, second), n3)
        if _length(_cross(n1, v)) <= 1e-9:
            # Gimbal lock: the first and the third turn are about one line, and
            # only what they come to together is determined.
            third = near[2]
            rest = urdf_common.quat_mul(
                rotation,
                urdf_common.quat_mul(
                    urdf_common.axis_angle_to_quat(n3, -third), urdf_common.axis_angle_to_quat(n2, -second)
                ),
            )
            probe = _unit(_cross(n1, (1.0, 0.0, 0.0))) or _unit(_cross(n1, (0.0, 1.0, 0.0)))
            first = _about(n1, probe, urdf_common.rotate_vec(rest, probe))
        else:
            first = _about(n1, v, w)
            u = urdf_common.rotate_vec(urdf_common.axis_angle_to_quat(n2, -second), n1)
            third = -_about(n3, u, y)
        candidates.append([_unwrapped(angle, reference) for angle, reference in zip((first, second, third), near)])
    return min(candidates, key=lambda turns: sum(abs(a - b) for a, b in zip(turns, near)))


def _solve(columns, vector):
    """'x' with 'sum(x_i * columns[i]) == vector', for three independent columns (Cramer's rule)."""
    a, b, c = columns
    determinant = _dot(a, _cross(b, c))
    return [
        _dot(vector, _cross(b, c)) / determinant,
        _dot(a, _cross(vector, c)) / determinant,
        _dot(a, _cross(b, vector)) / determinant,
    ]


def _plus(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scaled(vector, factor):
    return tuple(float(v) * factor for v in vector)


def _solvable(columns) -> bool:
    return len(columns) == 3 and abs(_dot(columns[0], _cross(columns[1], columns[2]))) > TOLERANCE


def _free_body_rates(entry, child, parent, rates, local, found):
    """A free body's rates: each freedom's, by parameter, and its angular velocity in its moving joint frame.

    'child' and 'parent' are the two bodies' world poses in millimetres,
    'rates' their world twists as the engine states them -- '((linear),
    (angular))' each, m/s of the body frame's origin and rad/s, both in the
    world's axes -- 'local' the six freedoms' product 'M_1(v_1) ... M_6(v_6)'
    and 'found' the turns read off it (or None). Returns '(by parameter,
    angular)': mm/s and deg/s, the turns' only where their rates are
    determined (not at gimbal lock), the moves' where the turns before them
    are; and the angular velocity of the child against its parent, deg/s about
    the axes of the moving joint frame, as a ball's is reported.

    The velocity read is that of the native joint's moving origin relative to
    the parent: the point every turn of the joint is about, which is what the
    moves move. Its rate in the joint frame is 'd(B . A v)', B the turns before
    the moves and A their axes, so the moves' rates are 'A^-1 B^-1 (t' - W_B x
    t)', W_B being B's angular velocity, which is the turns' rates before the
    moves along their axes as the turns before each leave it.
    """
    length = float(entry.get("length", MILLIMETRES_PER_METRE))
    (child_linear, child_angular), (parent_linear, parent_angular) = (
        (_scaled(twist[0], length), _scaled(twist[1], 1.0)) for twist in rates
    )
    origin, tail = _pose_of_data(entry["origin"]), _pose_of_data(entry["tail"])
    # The moving origin, in the world, and its velocity against the parent's
    # frame, stated in the parent's axes.
    offset = rotate(child, inverse(tail)[1])
    point = _plus(child[1], offset)
    moving = _plus(child_linear, _cross(child_angular, offset))
    carried = _plus(parent_linear, _cross(parent_angular, _minus(point, parent[1])))
    to_parent = _conjugate(parent[0])
    velocity = urdf_common.rotate_vec(to_parent, _minus(moving, carried))
    spin = urdf_common.rotate_vec(to_parent, _minus(child_angular, parent_angular))
    # The same in the native joint's frame at PartCAD's zero.
    to_joint = _conjugate(origin[0])
    velocity = urdf_common.rotate_vec(to_joint, velocity)
    spin = urdf_common.rotate_vec(to_joint, spin)
    angular = [v * DEGREES_PER_RADIAN for v in urdf_common.rotate_vec(_conjugate(local[0]), spin)]

    by_parameter = {}
    sequence = entry.get("sequence") or []
    moves = [item for item in sequence if item["freedom"] == MOVE]
    turns = [item for item in sequence if item["freedom"] == TURN]
    first = next((index for index, item in enumerate(sequence) if item["freedom"] == MOVE), None)
    before = [item for item in sequence[: first or 0] if item["freedom"] == TURN]
    turn_rates = None
    if found is not None and len(turns) == 3:
        # Each turn's axis as the turns before it leave it, in the joint frame:
        # what the angular velocity is the sum of, turn rate by turn rate.
        columns, running = [], urdf_common.IDENTITY_Q
        for item, angle in zip(turns, found):
            columns.append(urdf_common.rotate_vec(running, item["axis"]))
            running = urdf_common.quat_mul(running, urdf_common.axis_angle_to_quat(item["axis"], angle))
        if _solvable(columns):
            turn_rates = _solve(columns, spin)
            for item, rate in zip(turns, turn_rates):
                by_parameter[item["parameter"]] = rate * DEGREES_PER_RADIAN
    if len(moves) == 3 and _solvable([move["axis"] for move in moves]) and (not before or turn_rates is not None):
        swept = (0.0, 0.0, 0.0)
        rotation = urdf_common.IDENTITY_Q
        for index, item in enumerate(before):
            axis = urdf_common.rotate_vec(rotation, item["axis"])
            swept = _plus(swept, _scaled(axis, turn_rates[index]))
            rotation = urdf_common.quat_mul(rotation, urdf_common.axis_angle_to_quat(item["axis"], found[index]))
        along = urdf_common.rotate_vec(_conjugate(rotation), _minus(velocity, _cross(swept, local[1])))
        by_parameter.update(zip([move["parameter"] for move in moves], _solve([m["axis"] for m in moves], along)))
    return by_parameter, angular


def _as_list(value):
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(v) for v in value]


def reading(entries, positions, velocities=None) -> dict:
    """What one PartCAD joint reads, from what the engine joints it was written as read.

    'entries' are the joint maps ('joint_map()') of every engine joint written
    for the joint -- each a sidecar joint entry or its "map" -- and
    'positions' the engine's position of each, in the same order, in the
    engine's own units: a number, or a list of one per coordinate, for an
    engine joint of scalar coordinates (radians, metres); a quaternion 'w x y
    z' for a ball; and for a free body the pair '(child pose, parent pose)',
    each '((w, x, y, z), (x, y, z))' in the world, metres. 'velocities' are the
    same for the rates, if any: a number or list per scalar engine joint (rad/s,
    m/s); a ball's angular velocity '[x, y, z]' in rad/s about the axes of
    the frame it states its rotation in, moving with it (MuJoCo's); and for a
    free body the pair '(child twist, parent twist)', each '((vx, vy, vz),
    (wx, wy, wz))': the linear velocity of the body frame's origin in m/s and
    the angular velocity in rad/s, both in the world's axes -- what MuJoCo's
    'mj_objectVelocity' gives in the world's orientation, linear and angular
    the other way round, and what Gazebo's link world velocities are.

    Returns the reading in PartCAD's terms (section 8.13.5 of
    docs/design/simulation.md), keyed by the joint's own names whatever the
    file had to call anything: ``{"type": <kind>, "pos": ..., "vel": ...}``.
    'pos' is a number for a joint of one freedom and an object keyed by
    parameter for one of several ('{"turnZ": 30.0, "moveZ": 0.83}'),
    degrees and millimetres; a ball and a free body add ``"quat"``, their
    rotation in their joint frame from PartCAD's zero, and give their turns
    only where three turns can make a rotation ('turns_of'). 'vel' is in deg/s
    and mm/s, keyed as 'pos' is, and for a ball its angular velocity
    '[x, y, z]' in deg/s about its moving joint frame. A free body's 'vel' is
    an object: each of its six freedoms' rates by parameter, mm/s and deg/s --
    a turn's only where its rate is determined (not at gimbal lock), and a
    move's only where the turns before it are -- and ``"angular": [x, y, z]``,
    the child's angular velocity against its parent in deg/s about the axes of
    its moving joint frame, as a ball's is.
    """
    maps = [entry.get("map", entry) if isinstance(entry, dict) else {} for entry in entries]
    if not maps:
        return {}
    kind = maps[0].get("kind")
    count = maps[0].get("freedoms")
    pos, vel = {}, {}
    result = {"type": kind}
    velocities = list(velocities) if velocities is not None else [None] * len(maps)
    angular = None
    free_vel = None
    for entry, position, rate in zip(maps, positions, velocities):
        if "rotation" in entry:
            frame = tuple(entry.get("frame") or urdf_common.IDENTITY_Q)
            engine = urdf_common.normalize(tuple(float(v) for v in position))
            rotation = urdf_common.quat_mul(tuple(entry["rotation"]), _turned(engine, frame))
            result["quat"] = [float(v) for v in rotation]
            turns = entry.get("turns") or []
            found = turns_of(rotation, [turn["axis"] for turn in turns], [turn.get("start", 0.0) for turn in turns])
            if found is not None:
                pos.update(zip([turn["parameter"] for turn in turns], found))
            if rate is not None:
                spun = urdf_common.rotate_vec(frame, [float(v) for v in rate])
                angular = [v * DEGREES_PER_RADIAN for v in spun]
            continue
        if "parent" in entry:
            length = float(entry.get("length", MILLIMETRES_PER_METRE))
            child, parent = (
                (tuple(float(v) for v in pose[0]), tuple(float(v) * length for v in pose[1])) for pose in position
            )
            relative = compose(inverse(parent), child)
            # The six freedoms' product, 'M_1(v_1) ... M_6(v_6)': its rotation
            # is the turns' alone, in their order, and its translation the
            # moves', turned by the turns before them (every turn is about a
            # line through the native joint's origin, which no turn moves).
            local = compose(
                compose(inverse(_pose_of_data(entry["origin"])), relative), inverse(_pose_of_data(entry["tail"]))
            )
            sequence = entry.get("sequence") or []
            turns = [item for item in sequence if item["freedom"] == TURN]
            moves = [item for item in sequence if item["freedom"] == MOVE]
            result["quat"] = [float(v) for v in local[0]]
            found = turns_of(local[0], [turn["axis"] for turn in turns], [turn.get("start", 0.0) for turn in turns])
            first = next((index for index, item in enumerate(sequence) if item["freedom"] == MOVE), None)
            movable = len(moves) == 3 and _solvable([move["axis"] for move in moves])
            if found is not None:
                pos.update(zip([turn["parameter"] for turn in turns], found))
            if movable and (found is not None or first == 0):
                # The moves, turned back by the turns before them -- which the
                # moves need no turn to be read where they come first.
                before = urdf_common.IDENTITY_Q
                for item in sequence[:first]:
                    before = urdf_common.quat_mul(
                        before, urdf_common.axis_angle_to_quat(item["axis"], pos[item["parameter"]])
                    )
                along = urdf_common.rotate_vec(_conjugate(before), local[1])
                pos.update(zip([move["parameter"] for move in moves], _solve([m["axis"] for m in moves], along)))
            if rate is not None:
                free_vel = _free_body_rates(entry, child, parent, rate, local, found)
            continue
        coordinates = entry.get("coordinates") or []
        values = _as_list(position)
        rates = None if rate is None else _as_list(rate)
        for index, coordinate in enumerate(coordinates):
            pos[coordinate["parameter"]] = values[index] * coordinate["factor"] + coordinate.get("start", 0.0)
            if rates is not None:
                vel[coordinate["parameter"]] = rates[index] * coordinate["factor"]
        for follower in entry.get("followers") or []:
            leader = follower["follows"]
            if leader in pos:
                pos[follower["parameter"]] = follower["ratio"] * pos[leader] + follower.get("offset", 0.0)
            if leader in vel:
                vel[follower["parameter"]] = follower["ratio"] * vel[leader]

    if pos:
        result["pos"] = next(iter(pos.values())) if count == 1 and len(pos) == 1 else pos
    if free_vel is not None:
        by_parameter, spin = free_vel
        result["vel"] = dict(by_parameter, angular=spin)
    elif angular is not None:
        result["vel"] = angular
    elif vel:
        result["vel"] = next(iter(vel.values())) if count == 1 and len(vel) == 1 else vel
    return result


#
# Bodies
#


class BodyPart:
    """One shape of a body: the node, its physics, and where it sits."""

    def __init__(self, node, placement, world, physics):
        self.node = node
        self.name = node.get("name")
        self.label = node.get("label")
        # In the body's frame, and in the tree's: 'world' is the body's frame
        # times 'placement', by definition, so the two always agree exactly.
        self.placement = placement
        self.world = world
        self.physics = physics

    def __repr__(self):
        return "<BodyPart %s>" % (self.label or self.name)


class Body:
    """One rigid body: the node it is rooted at, the shapes welded into it, and what holds it."""

    def __init__(self, node, name, path, world, parent, fixed_to_world):
        self.node = node
        self.name = name
        self.label = node.get("label")
        self.kind = kind_of(node)
        self.path = path
        self.world = world
        self.parent = parent
        self.fixed_to_world = fixed_to_world
        self.joint = None
        self.parts = []
        self.children = []
        self.physics = None
        self.displacement = None
        self._mass_parts = []
        # Assemblies inside this body that state their own physics: a measured
        # link of several shapes is taken at its word (see 'weigh').
        self._stated = []

    @property
    def is_root(self) -> bool:
        """Whether nothing in the tree holds this body: it is free, or welded to the world."""
        return not isinstance(self.parent, Body)

    @property
    def is_floating(self) -> bool:
        """Whether this is the child of a floating joint: a free body whose pose is read against another."""
        return self.joint is not None and self.parent is None

    @property
    def joint_parent(self):
        """The body this body's joint is to: its parent, or for a floating body the one it was connected to."""
        return None if self.joint is None else self.joint.parent

    def mass_parts(self) -> list:
        """The (physics, packed placement) pairs 'physics' was combined from, placements in this body."""
        return list(self._mass_parts)

    def __repr__(self):
        parent = self.parent.name if isinstance(self.parent, Body) else self.parent
        return "<Body %s (%s) parent=%s parts=%s>" % (self.name, self.kind, parent, [p.label for p in self.parts])


class Bodies(list):
    """The bodies of a tree, parents before children, with what the rule set aside in 'problems'."""

    def __init__(self, *args):
        super().__init__(*args)
        self.problems = []

    def by_name(self, name):
        return next((body for body in self if body.name == name), None)


def bodies(tree, properties=None) -> Bodies:
    """The rigid bodies of a shape tree ('shape_tree'), parents before children.

    'properties' is the request's properties index: full name -> what that
    shape reports about itself, its resolved physics among it (see
    'wrapper_export.properties_index()'). Without it, the properties each node
    carries are read, which are what it states and not what was derived for it.

    Raises:
        ValueError: 'tree' is not a node of a shape tree.
    """
    if not is_node(tree):
        raise ValueError("Bodies are found in a shape tree, and this is not one: %r" % (type(tree),))
    builder = _Builder(properties)
    builder.build(tree)
    return builder.bodies


class _Builder:
    def __init__(self, properties):
        self.properties = properties if isinstance(properties, dict) else None
        self.bodies = Bodies()
        self.taken = set()

    def problem(self, message):
        self.bodies.problems.append(message)

    def physics_of(self, node) -> dict:
        if self.properties is not None:
            entry = properties_of(self.properties, node)
        else:
            entry = node.get(KEY_PROPERTIES)
        physics = entry.get("physics") if isinstance(entry, dict) else None
        return dict(physics) if isinstance(physics, dict) else {}

    def new_body(self, node, world, path, parent, fixed):
        base = node.get("label") or str(node.get("name") or "").rpartition(":")[2] or "body"
        name, suffix = base, 2
        while name in self.taken:
            name = "%s-%d" % (base, suffix)
            suffix += 1
        self.taken.add(name)
        body = Body(node, name, path, world, WORLD if fixed else parent, fixed)
        if isinstance(parent, Body):
            parent.children.append(body)
        self.bodies.append(body)
        return body

    def build(self, root):
        world = pose_of(root.get(KEY_LOCATION))
        if kind_of(root) == SCENE:
            self.scene(root, world, (), False, root=True)
        else:
            # An assembly exported on its own is one articulated tree, as it is
            # in a scene; a part is one body. Either way the root is free.
            body = self.new_body(root, world, (), None, False)
            self.fill(body, root, IDENTITY, world, ())
        for body in self.bodies:
            self.weigh(body)

    def add_part(self, body, node, placement):
        body.parts.append(BodyPart(node, placement, compose(body.world, placement), self.physics_of(node)))

    def scene(self, node, world, path, fixed, root=False):
        """Every element of a scene, recursively, as a body of its own.

        Composed node by node from the root, exactly as an exporter writing
        every node with geometry as a free body ('flatten') always composed
        them, so that a scene of parts is where it always was, to the bit.
        """
        own, elements = ([], _children(node)) if root else _own_shapes(node)
        if own:
            body = self.new_body(node, world, path, None, fixed)
            for shape in own:
                self.add_part(body, shape, pose_of(shape.get(KEY_LOCATION)))
        for child in elements:
            child_world = compose(world, pose_of(child.get(KEY_LOCATION)))
            child_path = path + (child.get("label"),)
            child_fixed = fixed or child.get(KEY_FIXED) is True
            if isinstance(child.get(KEY_JOINT), dict):
                self.problem(
                    "'%s' carries a joint, and a scene attaches nothing: it is a body of its own"
                    % "/".join(str(label) for label in child_path)
                )
            if kind_of(child) == SCENE:
                self.scene(child, child_world, child_path, child_fixed)
                continue
            body = self.new_body(child, child_world, child_path, None, child_fixed)
            self.fill(body, child, IDENTITY, child_world, child_path)

    def fill(self, body, node, placement, world, path):
        """'node' and what it holds, welded into 'body' at 'placement' - but for what moves.

        'world' is the node's frame composed from the root, which is where a
        child that moves against its target starts a body of its own.
        """
        if is_geometry(node):
            self.add_part(body, node, placement)
        children = _children(node)
        if not children:
            return

        start = len(body.parts)
        stated = self.physics_of(node)
        states_mass = mass_properties.weighs(stated)
        if states_mass and _has_joint_below(node):
            # The mass of the whole mechanism, which is not the mass of any one
            # of its bodies; each of those is weighed from its parts instead.
            self.problem(
                "'%s' states its own mass, and moves: it is more than one body, so each is weighed from its "
                "parts" % ("/".join(str(label) for label in path) or node.get("label") or node.get("name"))
            )
            states_mass = False

        # (label, the body it is in, its frame in that body, its location in
        # this container) for every child placed so far: what a joint or an
        # attachment to a sibling looks its target up in.
        placed = []
        for child in children:
            location = pose_of(child.get(KEY_LOCATION))
            child_world = compose(world, location)
            label = child.get("label")
            child_path = path + (label,)
            where = "/".join(str(entry) for entry in child_path)
            if child.get(KEY_FIXED) is True:
                self.problem("'%s' is marked 'fixed', and everything in an assembly is attached to it: ignored" % where)
            if kind_of(child) == SCENE:
                self.problem("'%s' is a scene inside an assembly, which holds none: it is taken as attached" % where)
            record = child.get(KEY_JOINT)
            if isinstance(record, dict):
                # A joint is to a sibling placed before it: the first of that
                # name, as the connection that made it looked it up. One that
                # names no sibling at all is to the container itself: what a
                # robot description says of a link hanging off a root link
                # with no geometry, which is no node of its own.
                target = next((entry for entry in placed if entry[0] == record.get("parent")), None)
                if record.get("parent") is None:
                    target_body, target_frame = body, placement
                elif target is None:
                    self.problem(
                        "'%s' moves against '%s', which is not placed before it: it is jointed to its container"
                        % (where, record.get("parent"))
                    )
                    target_body, target_frame = body, placement
                else:
                    _, target_body, target_frame, _ = target
                joint = Joint(record, target_body, None, target_frame)
                # A floating joint holds nothing: the child is a body of its
                # own, free as a root is, and its joint stays only to say what
                # its pose is read against -- the body it was connected to
                # (section 8.13.2 of docs/design/simulation.md). Written as six
                # freedoms under that body, a loose part would be nested in
                # what it rests on and pass through it.
                floating = joint.kind == FLOATING
                moving = self.new_body(child, child_world, child_path, None if floating else target_body, False)
                joint.child = moving
                moving.joint = joint
                for problem in outside_bounds(joint, where):
                    self.problem(problem)
                self.fill(moving, child, IDENTITY, child_world, child_path)
                placed.append((label, moving, IDENTITY, location))
            else:
                # Welded: into the container's body, unless a rigid connection
                # says it is welded to a sibling that moves - then into that
                # sibling's body, where the two sit as the container holds them.
                target_body, child_placement = body, compose(placement, location)
                attached = child.get(KEY_ATTACHED)
                if attached is not None:
                    target = next((entry for entry in placed if entry[0] == attached), None)
                    if target is None:
                        self.problem(
                            "'%s' is attached to '%s', which is not placed before it: it is attached to its container"
                            % (where, attached)
                        )
                    elif target[1] is not body:
                        _, target_body, target_frame, target_location = target
                        child_placement = compose(compose(target_frame, inverse(target_location)), location)
                self.fill(target_body, child, child_placement, child_world, child_path)
                placed.append((label, target_body, child_placement, location))

        if states_mass:
            body._stated.append((placement, stated, start, len(body.parts)))

    def weigh(self, body):
        """A body's physics: its parts combined, each where the body holds it.

        An assembly welded whole into the body that states its own physics - a
        measured link of several shapes, read from a robot description - is
        taken at its word, its parts saying only how that mass is spread (see
        'mass_properties.of_body()'). The outermost such statement wins.
        """
        stated = []
        for entry in sorted(body._stated, key=lambda entry: (entry[2], -entry[3])):
            if not any(start <= entry[2] and entry[3] <= end for _, _, start, end in stated):
                stated.append(entry)
        covered = set(index for _, _, start, end in stated for index in range(start, end))

        def group(placement, own, start, end):
            # An assembly with no shapes that states what it weighs is still that
            # much mass, where it is: 'of_body()' of nothing is what it states.
            undo = inverse(placement)
            inner = [(member.physics, packed_of(compose(undo, member.placement))) for member in body.parts[start:end]]
            return (mass_properties.of_body(inner, own=own), packed_of(placement))

        entries = []
        for index in range(len(body.parts) + 1):
            entries.extend(group(*entry) for entry in stated if entry[2] == index)
            if index < len(body.parts) and index not in covered:
                part = body.parts[index]
                entries.append((part.physics, packed_of(part.placement)))
        body._mass_parts = entries
        body.physics = mass_properties.of_body(entries) if entries else None
        shapes = [(part.physics, packed_of(part.placement)) for part in body.parts]
        body.displacement = mass_properties.displacement_of(shapes) if shapes else None


def outside_bounds(joint, where=None) -> list:
    """What a joint says that starts it outside its own bounds: one sentence per freedom that does.

    The start is the freedom's value -- 'toParams', the parameter's own value
    -- and the bounds its range in the same terms, so an engine handed both
    starts the joint against its own stop (MuJoCo does, and pushes it back in
    with the first step). The core's 'connect' check fails such a connection
    ('partcad.joint.outside_bounds'); this says it of a tree, wherever the tree
    came from. Where the bounds were stated by 'limits:' about an axis that
    runs the other way to the parameter (a source marked "reversed"), that is
    said too: it is what turns '[-10, 30]' into '[-30, 10]'. A ball, whose
    turns have no bounds of their own, starts beyond its one bound
    ('turn_limit') where the rotation its turns make at the start turns
    further than that from its zero.
    """
    problems = []
    names = joint.parameter_names()
    for freedom in joint.freedoms:
        value, lower, upper = freedom.value, freedom.lower, freedom.upper
        tolerance = 1e-9 * max(1.0, abs(value))
        if not ((lower is not None and value < lower - tolerance) or (upper is not None and value > upper + tolerance)):
            continue
        unit = "deg" if freedom.kind == TURN else "mm"
        shown = "%s to %s %s" % (
            "-inf" if lower is None else "%g" % lower,
            "+inf" if upper is None else "%g" % upper,
            unit,
        )
        problem = "'%s' starts its joint '%s' with '%s' at %g %s, outside its bounds of %s" % (
            where or joint.child_link or "?",
            joint.name,
            names[freedom.index],
            value,
            unit,
            shown,
        )
        if any(isinstance(source, dict) and source.get("reversed") for source in freedom.source):
            problem += (
                ": its 'limits' are stated about the motion's axis, which runs the other way to '%s' (a target's "
                "port Z is the contact frame's -Z), so they bound it the other way round" % names[freedom.index]
            )
        problems.append(problem)
    if joint.kind == BALL and joint.turn_limit is not None:
        # A ball's bound is one angle, which none of its turns has ('Joint.turn_limit'):
        # what it bounds is the rotation the turns make together.
        rotation = rezeroed(joint).rotation
        angle = math.degrees(2.0 * math.acos(min(1.0, abs(rotation[0]))))
        if angle > joint.turn_limit + 1e-9 * max(1.0, joint.turn_limit):
            problems.append(
                "'%s' starts its ball '%s' turned %g deg from its zero, beyond its bound of %g deg"
                % (where or joint.child_link or "?", joint.name, angle, joint.turn_limit)
            )
    return problems


def summary(found) -> list:
    """The bodies as plain data, for a report or a test: what each is, holds, and hangs off."""
    rows = []
    for body in found:
        parent = body.parent.name if isinstance(body.parent, Body) else body.parent
        row = {
            "name": body.name,
            "kind": body.kind,
            "parent": parent,
            "fixed": body.fixed_to_world,
            "parts": [part.label for part in body.parts],
        }
        if body.joint is not None:
            row["joint"] = {"name": body.joint.name, "kind": body.joint.kind}
            if body.is_floating:
                row["joint"]["parent"] = body.joint_parent.name
        if body.physics:
            row["mass"] = body.physics.get("mass")
        rows.append(row)
    return rows
