#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a 'motion:' declaration says: which degrees of freedom a connection keeps.

A connection between two interfaces is a composition of rigid transforms (see
'AssemblyFactoryAssy' and 'partcad.joint'), and every freedom-of-movement
parameter of either interface - 'moveX', 'turnZ', a custom one with a 'dir' -
is one factor of it. What a parameter does not say is whether it stays free
once the connection is made. A slotted hole's 'moveX' is an *adjustment*: the
screw is tightened and it is fixed. A bearing's 'turnZ' is a *degree of
freedom*: it stays free while the machine runs. 'motion:' is where that bit is
stated, in one of two ways:

  * **explicitly**, by naming the parameters that stay free ('dof: [turnZ]').
    The parameter already says its kind, its direction and its range, so
    nothing is restated;
  * **implicitly**, by naming a kind of joint ('type: revolute', or the short
    form 'motion: revolute'), which implies its degrees of freedom - about the
    port's Z axis unless 'axis:' says otherwise, between 'limits:' where those
    apply. 'KINDS' below is the list, and 'Motion.implied()' what each implies.

This module only *reads* a declaration: it turns one into the freedoms it states
and reports what is wrong with it. Matching those freedoms to the parameters of
the two interfaces of a connection, combining both sides and building the joint
out of them is 'partcad.joint', because that is the half that needs a
connection to have happened.

Angles are degrees and lengths millimetres, as everywhere in PartCAD. Nothing
here imports OCP.
"""

import math

TURN = "turn"
MOVE = "move"

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

# Every kind of joint 'motion.type' may name. The first eight are what URDF and
# the converter have always written; 'cylindrical' and 'universal' are the two
# a pairing of ordinary interfaces needs that URDF has no word for - a shaft in
# a plain bore, and a cardan joint.
KINDS = (
    FIXED,
    REVOLUTE,
    CONTINUOUS,
    PRISMATIC,
    CYLINDRICAL,
    SCREW,
    UNIVERSAL,
    BALL,
    PLANAR,
    FLOATING,
)

# The kinds 'limits:' bounds, and which of their freedoms it bounds. A screw's
# limits are the turn's: the move follows the turn by the thread. Every other
# kind has more than one freedom and no way to say which of them one 'lower'
# and one 'upper' are about, so a range there is stated on each parameter and
# the parameter named in 'dof:' instead.
LIMITED_KINDS = (REVOLUTE, PRISMATIC, SCREW)

# The fields a 'motion:' section may state. Everything but 'dof' and
# 'softLimits'/'mimic' describes the freedoms; those two describe the joint.
FIELDS = ("type", "dof", "axis", "limits", "softLimits", "mimic")

# The six parameters whose axis is in their name, and what that axis is. A
# degree of freedom implied along a principal axis is named after the one that
# would have that axis, which is what makes it addressable as 'turnZ' from a
# connection's 'toParams' whether or not anybody declared one.
PREDEFINED = {
    "moveX": (MOVE, (1.0, 0.0, 0.0)),
    "moveY": (MOVE, (0.0, 1.0, 0.0)),
    "moveZ": (MOVE, (0.0, 0.0, 1.0)),
    "turnX": (TURN, (1.0, 0.0, 0.0)),
    "turnY": (TURN, (0.0, 1.0, 0.0)),
    "turnZ": (TURN, (0.0, 0.0, 1.0)),
}

# How close two directions have to be to be called one (the sine of the angle
# between them), and two lines (millimetres apart). Directions here are made of
# numbers somebody wrote - '[0.5, 0.866, 0]' for a 60 degree axis - and of the
# half turn that makes two ports face each other applied to them, so two axes a
# micro-radian apart are one axis that was written twice.
TOLERANCE = 1e-6

X_AXIS = (1.0, 0.0, 0.0)
Y_AXIS = (0.0, 1.0, 0.0)
Z_AXIS = (0.0, 0.0, 1.0)


def unit(vector):
    """'vector' scaled to length one, or None when it has no length (or is not a vector)."""
    try:
        x, y, z = (float(v) for v in vector)
    except (TypeError, ValueError):
        return None
    norm = math.sqrt(x * x + y * y + z * z)
    if norm == 0.0 or not math.isfinite(norm):
        return None
    return (x / norm, y / norm, z / norm)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def parallel(a, b) -> int:
    """+1 when two unit vectors point the same way, -1 when opposite, 0 otherwise."""
    across = cross(a, b)
    if math.sqrt(dot(across, across)) > TOLERANCE:
        return 0
    return 1 if dot(a, b) > 0 else -1


def principal_name(kind: str, axis):
    """The predefined parameter along 'axis', and the sign 'axis' has against it, or (None, 0)."""
    for name, (named_kind, named_axis) in PREDEFINED.items():
        if named_kind != kind:
            continue
        sign = parallel(axis, named_axis)
        if sign:
            return name, sign
    return None, 0


def _across(axis):
    """Two unit vectors that, with 'axis', make a right-handed frame.

    For a principal axis they are the other two principal axes in cyclic order,
    so that 'planar' about Z moves along X and Y - the names a reader expects,
    and the predefined parameters an interface already declares. For any other
    axis they are built from the principal axis least aligned with it, which is
    the one that makes the cross product best conditioned.
    """
    for first, second, third in ((X_AXIS, Y_AXIS, Z_AXIS), (Y_AXIS, Z_AXIS, X_AXIS), (Z_AXIS, X_AXIS, Y_AXIS)):
        sign = parallel(axis, third)
        if sign:
            return (first, second) if sign > 0 else (second, first)
    least = min((X_AXIS, Y_AXIS, Z_AXIS), key=lambda e: abs(dot(axis, e)))
    u = unit(cross(least, axis))
    return u, cross(axis, u)


class Freedom:
    """One degree of freedom a 'motion:' implies, before it is matched to a parameter.

    'axis' is a unit vector in the frame the declaration is stated in - the
    port's, for an interface - and 'lower'/'upper' are in its sense: degrees
    about it, or millimetres along it. Both are None unless 'limits:' gave them,
    in which case 'limited' says so; 'unlimited' is the other definite answer,
    which 'continuous' gives. Neither means the range is whatever the parameter
    the freedom is matched to says.

    'follows' is the index of another freedom of the same declaration that this
    one is coupled to: a screw's move follows its turn by the thread.
    """

    def __init__(self, kind, axis, lower=None, upper=None, limited=False, unlimited=False, follows=None):
        self.kind = kind
        self.axis = axis
        self.lower = lower
        self.upper = upper
        self.limited = limited
        self.unlimited = unlimited
        self.follows = follows

    def __repr__(self):
        return "<Freedom %s %s [%s, %s]>" % (self.kind, self.axis, self.lower, self.upper)


class Motion:
    """One 'motion:' as written: on an interface, on a mating, or on a connection.

    Read leniently, the way the rest of a connection is: whatever is wrong is
    added to 'problems' and replaced by what it most plausibly meant, so that an
    assembly always builds. 'pc test''s 'connect' check is what looks past that
    (see 'Assembly.get_connect_problems').
    """

    def __init__(self, config, where: str = "motion"):
        self.where = where
        self.problems = []
        self.config = config
        self.type = None
        self.dof = None
        self.axis = None
        self.lower = None
        self.upper = None
        self.has_limits = False
        self.soft_limits = None
        self.mimic = None

        if config is None:
            return
        if isinstance(config, str):
            # 'motion: revolute' is 'motion: {type: revolute}'.
            config = {"type": config}
        if not isinstance(config, dict):
            self._problem("must be the name of a kind of joint or a section, ignoring: %r" % (config,))
            return
        for field in config:
            if field not in FIELDS:
                self._problem("has no field '%s'; ignoring it" % field)

        self._read_type(config.get("type"))
        self._read_dof(config.get("dof"))
        self._read_axis(config.get("axis"))
        self._read_limits(config.get("limits"))
        self.soft_limits = self._section(config, "softLimits")
        self.mimic = self._section(config, "mimic")
        self._check_consistency()

    def _problem(self, message):
        self.problems.append("%s: %s" % (self.where, message))

    def _section(self, config, field):
        value = config.get(field)
        if value is None:
            return None
        if not isinstance(value, dict):
            self._problem("'%s' must be a section, ignoring it" % field)
            return None
        return dict(value)

    def _read_type(self, value):
        if value is None:
            return
        if value not in KINDS:
            self._problem("'%s' is not a kind of joint (%s); ignoring it" % (value, ", ".join(KINDS)))
            return
        self.type = value

    def _read_dof(self, value):
        if value is None:
            return
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, (list, tuple)) or not all(isinstance(name, str) and name for name in value):
            self._problem("'dof' must list the names of freedom-of-movement parameters, ignoring: %r" % (value,))
            return
        names = []
        for name in value:
            if name in names:
                self._problem("'dof' names '%s' twice" % name)
                continue
            names.append(name)
        self.dof = names

    def _read_axis(self, value):
        if value is None:
            return
        axis = unit(value) if isinstance(value, (list, tuple)) and len(value) == 3 else None
        if axis is None:
            self._problem("'axis' must be three numbers that are not all zero, using the port's Z axis: %r" % (value,))
            return
        self.axis = axis

    def _read_limits(self, value):
        if value is None:
            return
        if not isinstance(value, dict):
            self._problem("'limits' must be a section with 'lower' and 'upper', ignoring it")
            return
        bounds = {}
        for field in ("lower", "upper"):
            bound = value.get(field)
            if bound is None:
                continue
            if isinstance(bound, bool) or not isinstance(bound, (int, float)) or not math.isfinite(bound):
                # An expression that did not resolve arrives here as its text.
                self._problem("'limits.%s' must be a number, ignoring it: %r" % (field, bound))
                continue
            bounds[field] = float(bound)
        if "lower" in bounds and "upper" in bounds and bounds["lower"] > bounds["upper"]:
            self._problem("'limits' run backwards, from %s to %s: ignoring them" % (bounds["lower"], bounds["upper"]))
            return
        self.has_limits = bool(bounds)
        self.lower = bounds.get("lower")
        self.upper = bounds.get("upper")

    def _check_consistency(self):
        """What a declaration says that the kind it names cannot mean."""
        if self.type is None:
            if self.has_limits:
                self._problem("'limits' bound nothing without a 'type'; state a range on each parameter in 'dof'")
            if self.axis is not None:
                self._problem("'axis' says nothing without a 'type': each parameter in 'dof' has its own")
            return
        if self.type == FIXED:
            if self.dof:
                self._problem("a fixed motion keeps no degree of freedom, yet 'dof' names %s" % ", ".join(self.dof))
            if self.has_limits:
                self._problem("a fixed motion has no limits")
        elif self.type == CONTINUOUS and self.has_limits:
            self._problem("a continuous motion turns without limits, yet 'limits' bound it; ignoring them")
            self.has_limits, self.lower, self.upper = False, None, None
        elif self.has_limits and self.type not in LIMITED_KINDS:
            self._problem(
                "'limits' do not say which of a %s motion's degrees of freedom they bound; "
                "state a range on each parameter and name them in 'dof' instead" % self.type
            )
            self.has_limits, self.lower, self.upper = False, None, None

    @property
    def declared(self) -> bool:
        """Whether this declaration says anything about the freedoms at all."""
        return self.type is not None or self.dof is not None

    @property
    def is_fixed(self) -> bool:
        return self.type == FIXED and not self.dof

    def implied(self) -> list:
        """The freedoms 'type' implies, in the declaration's own frame; empty without a type.

        See the table in docs/source/config_geometry.rst ('Joints').
        """
        if self.type is None or self.type == FIXED:
            return []
        axis = self.axis or Z_AXIS
        limits = dict(lower=self.lower, upper=self.upper, limited=self.has_limits)

        if self.type == REVOLUTE:
            return [Freedom(TURN, axis, **limits)]
        if self.type == CONTINUOUS:
            return [Freedom(TURN, axis, unlimited=True)]
        if self.type == PRISMATIC:
            return [Freedom(MOVE, axis, **limits)]
        if self.type == CYLINDRICAL:
            return [Freedom(TURN, axis), Freedom(MOVE, axis)]
        if self.type == SCREW:
            return [Freedom(TURN, axis, **limits), Freedom(MOVE, axis, follows=0)]
        if self.type == UNIVERSAL:
            second = X_AXIS
            if parallel(axis, X_AXIS):
                # The port's X axis is the second turn, and it is the first one
                # here: both turns would be one, which is no universal joint.
                self._problem("a universal motion about the port's X axis turns twice about one axis; using Y")
                second = Y_AXIS
            return [Freedom(TURN, axis), Freedom(TURN, second)]
        if self.type == BALL:
            return [Freedom(TURN, X_AXIS), Freedom(TURN, Y_AXIS), Freedom(TURN, Z_AXIS)]
        if self.type == PLANAR:
            u, v = _across(axis)
            return [Freedom(MOVE, u), Freedom(MOVE, v), Freedom(TURN, axis)]
        if self.type == FLOATING:
            return [
                Freedom(MOVE, X_AXIS),
                Freedom(MOVE, Y_AXIS),
                Freedom(MOVE, Z_AXIS),
                Freedom(TURN, X_AXIS),
                Freedom(TURN, Y_AXIS),
                Freedom(TURN, Z_AXIS),
            ]
        return []

    def joint_record(self) -> dict:
        """What this declaration says about the joint rather than about its freedoms."""
        record = {}
        if self.soft_limits:
            record["softLimits"] = dict(self.soft_limits)
        if self.mimic:
            record["mimic"] = dict(self.mimic)
        return record
