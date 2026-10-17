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

``Body``
    'name' (unique in the list: the label of the node that placed it, then
    "-2", "-3" ... in list order, as joint names are made unique); 'label';
    'path' (the labels from the root down to it); 'node' (the envelope node it
    is rooted at); 'kind'; 'world' (its frame, a pose in the tree's frame);
    'parts' (each a 'BodyPart' with 'node', 'name', 'label', 'physics',
    'placement' in the body's frame and 'world', which is
    'compose(body.world, placement)'); 'parent' (a Body, 'WORLD', or None for a
    free root); 'fixed_to_world'; 'joint' (a 'Joint', or None for a root);
    'children'; 'physics' (the combined physics dict, or None when nothing in it
    weighs anything); 'displacement' ('mass_properties.displacement_of()' of its
    parts, or None); and 'mass_parts()', the (physics, packed placement) pairs
    'physics' was combined from.

``Joint``
    The joint of a body to its parent, re-expressed for that pair: its 'steps'
    are the node's joint steps with, in front of them, the target node's frame
    in the parent body (a fixed step of role 'parentFrame', left out where it is
    the identity), so that the child body's frame is the parent body's times
    their product. 'name', 'physics', 'soft_limits', 'mimic' and 'record' (the
    node's joint as the tree stated it) come with it, and 'freedoms' is the free
    steps as 'Freedom's: 'kind' (TURN or MOVE), 'axis' (a unit vector, in the
    frame the steps before it leave), 'lower'/'upper' (degrees, or millimetres
    along the axis; None where unlimited), 'value' (the starting value, same
    units), 'follows'/'ratio'/'offset' (a coupling: 'value = ratio * leader +
    offset', in those units), 'step' (its index in 'steps'), 'parameter' and
    'source' (what declared it). The frames an exporter needs, every one a pose
    or a vector in millimetres:

      origin                 the first freedom's frame in the parent body
      origins                each freedom's frame relative to the frame the one
                             before it leaves (the first's: the parent body) --
                             a URDF chain through dummy links, one per freedom
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
    it, or a list of steps) are, as one of REVOLUTE (a turn with a bound on
    either side), CONTINUOUS (a turn with none), PRISMATIC, CYLINDRICAL, SCREW,
    UNIVERSAL, BALL, PLANAR, FLOATING, or CHAIN for anything else -- and FIXED
    for steps with nothing free, which a body's joint never is. Beside the kind:
    'freedoms'; 'origin', the native joint's frame in the frame the steps start
    in, with every freedom at zero; per freedom its 'axes' (unit vectors) and
    'points' in that frame; and 'tail', the child's frame relative to it, so
    that the location at any values is

        origin . M_1(v_1) . M_2(v_2) ... M_n(v_n) . tail

    where M_i turns about, or moves along, axis i through point i, each in the
    frame the ones before it moved -- MJCF's joints-in-one-body, and URDF's and
    SDFormat's single-axis joints. For every kind but CHAIN the points are the
    origin, so a native joint sits at 'origin': a ball's centre, a universal
    joint's crossing, a screw's or a planar joint's axis. See section 8.8 of the
    design record for which format writes what.

The classification table is the design record's, and the order of the freedoms
is part of it: a planar joint is two moves *then* the turn about their normal,
which is what 'motion: planar' implies and what a native planar joint means, and
the other order is a chain. A coupling makes a pair a screw when the two lie on
one axis and a chain otherwise; a 'mimic' is between joints and is the
exporter's to write.

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

# What a joint's free steps are (see 'classify'). The names are the design
# record's, which are 'motion.type''s, plus the two that only describe a result.
FIXED = "fixed"
REVOLUTE = "revolute"
CONTINUOUS = "continuous"
PRISMATIC = "prismatic"
CYLINDRICAL = "cylindrical"
SCREW = "screw"
UNIVERSAL = "universal"
BALL = "ball"
PLANAR = "planar"
FLOATING = "floating"
CHAIN = "chain"

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


def _kind(freedoms, axes, points):
    """The kind of a set of freedoms, and the point a native joint of it is centred on (or None)."""
    kinds = [freedom.kind for freedom in freedoms]
    coupled = [freedom for freedom in freedoms if freedom.follows is not None]
    count = len(freedoms)
    if count == 1:
        if kinds[0] == TURN:
            return (REVOLUTE if freedoms[0].limited else CONTINUOUS), None
        return PRISMATIC, None
    if count == 2 and sorted(kinds) == [MOVE, TURN]:
        turn = 0 if kinds[0] == TURN else 1
        if not _parallel(axes[0], axes[1]):
            return CHAIN, None
        centre = _closest_to_origin(points[turn], axes[turn])
        if not coupled:
            return CYLINDRICAL, centre
        if len(coupled) == 1 and coupled[0].follows == freedoms[1 - coupled[0].index].index:
            return SCREW, centre
        return CHAIN, None
    if coupled:
        # A coupled freedom is not a freedom of its own, and only a screw is a
        # native joint with one in it.
        return CHAIN, None
    if count == 2 and kinds == [TURN, TURN]:
        centre = _meet(points[0], axes[0], points[1], axes[1])
        return (UNIVERSAL, centre) if centre is not None else (CHAIN, None)
    if count == 3 and kinds == [TURN, TURN, TURN] and _independent(axes):
        centre = _meet(points[0], axes[0], points[1], axes[1])
        if centre is not None and _on_line(centre, points[2], axes[2]):
            return BALL, centre
        return CHAIN, None
    if count == 3 and kinds == [MOVE, MOVE, TURN]:
        normal = axes[2]
        if (
            not _parallel(axes[0], axes[1])
            and abs(_dot(axes[0], normal)) <= TOLERANCE
            and abs(_dot(axes[1], normal)) <= TOLERANCE
        ):
            return PLANAR, _closest_to_origin(points[2], normal)
        return CHAIN, None
    if count == 6 and kinds == [MOVE] * 3 + [TURN] * 3 and _independent(axes[:3]) and _independent(axes[3:]):
        centre = _meet(points[3], axes[3], points[4], axes[4])
        if centre is not None and _on_line(centre, points[5], axes[5]):
            return FLOATING, centre
    return CHAIN, None


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
    if kind == CHAIN:
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
            entry = self.properties.get(node.get("name"))
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
                moving = self.new_body(child, child_world, child_path, target_body, False)
                moving.joint = Joint(record, target_body, moving, target_frame)
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
        if body.physics:
            row["mass"] = body.physics.get("mass")
        rows.append(row)
    return rows
