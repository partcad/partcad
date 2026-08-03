#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

"""Rigid-body transforms, stored as pure-Python data.

'Location' used to wrap an OCCT 'TopLoc_Location' and do all its math with
'gp_Trsf'. It sits on PartCAD's import path (partcad/__init__.py imports it), so
that pulled OCP into every process that so much as imported partcad.

The transform is now held as a unit quaternion plus a translation, and every
operation - construction, composition, inversion, repr - is pure Python. OCP is
touched only when a caller actually needs the live OCCT object: '.wrapped'
(a 'TopLoc_Location') and 'trsf_from_coords()' (a 'gp_Trsf') build it on demand
through a lazy import, and constructing 'Location(gp_Trsf)' / 'Location(TopLoc)'
reads one back. So importing partcad, and composing/inverting locations, no
longer requires OCP; only the assembly/interface code that hands a location to
OCCT geometry does, and that is the next thing to move into a sandbox.
"""

import math
from typing import Sequence

# Identity: unit (no-op) rotation quaternion and zero translation.
_IDENTITY_Q = (1.0, 0.0, 0.0, 0.0)
_IDENTITY_T = (0.0, 0.0, 0.0)


def _axis_angle_to_quat(ax: Sequence[float], angle_deg: float):
    """Unit quaternion (w, x, y, z) for a rotation of 'angle_deg' about 'ax'.

    The axis is normalized, exactly as OCCT's gp_Dir does; a zero-length axis is
    rejected (gp_Dir would raise on it too).
    """
    x, y, z = float(ax[0]), float(ax[1]), float(ax[2])
    norm = math.sqrt(x * x + y * y + z * z)
    if norm == 0.0:
        raise ValueError("geom.Location: the rotation axis must have a non-zero length")
    x, y, z = x / norm, y / norm, z / norm
    half = math.radians(angle_deg) / 2.0
    s = math.sin(half)
    return (math.cos(half), x * s, y * s, z * s)


def _quat_mul(a, b):
    """Hamilton product; R(a * b) == R(a) . R(b)."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def _quat_conj(q):
    """Conjugate = inverse for a unit quaternion."""
    w, x, y, z = q
    return (w, -x, -y, -z)


def _rotate_vec(q, v):
    """Apply the rotation 'q' to the vector 'v'."""
    w, x, y, z = q
    vx, vy, vz = v
    return (
        (1.0 - 2.0 * (y * y + z * z)) * vx + 2.0 * (x * y - w * z) * vy + 2.0 * (x * z + w * y) * vz,
        2.0 * (x * y + w * z) * vx + (1.0 - 2.0 * (x * x + z * z)) * vy + 2.0 * (y * z - w * x) * vz,
        2.0 * (x * z - w * y) * vx + 2.0 * (y * z + w * x) * vy + (1.0 - 2.0 * (x * x + y * y)) * vz,
    )


def _quat_to_axis_angle(q):
    """Inverse of _axis_angle_to_quat, for repr(). Axis is arbitrary at angle 0."""
    w = max(-1.0, min(1.0, q[0]))
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-12:
        return (0.0, 0.0, 1.0), 0.0
    return (q[1] / s, q[2] / s, q[3] / s), math.degrees(2.0 * math.acos(w))


def _build_trsf(q, t):
    """Build the OCCT gp_Trsf for quaternion 'q' and translation 't' (lazy OCP)."""
    from OCP.gp import gp_Trsf, gp_Quaternion, gp_Vec

    w, x, y, z = q
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Quaternion(x, y, z, w))
    trsf.SetTranslationPart(gp_Vec(t[0], t[1], t[2]))
    return trsf


def _from_ocp(arg):
    """(t, q) extracted from a gp_Trsf / TopLoc_Location, or None if 'arg' is neither.

    OCP is imported lazily and its absence is treated as "not an OCP object": a
    process without OCP installed cannot be holding one anyway.
    """
    try:
        from OCP.gp import gp_Trsf
        from OCP.TopLoc import TopLoc_Location
    except ImportError:
        return None

    if isinstance(arg, gp_Trsf):
        trsf = arg
    elif isinstance(arg, TopLoc_Location):
        trsf = arg.Transformation()
    else:
        return None

    quat = trsf.GetRotation()
    trans = trsf.TranslationPart()
    return (trans.X(), trans.Y(), trans.Z()), (quat.W(), quat.X(), quat.Y(), quat.Z())


class Location:
    """A rigid body transform: a rotation about an axis through the origin followed by a translation.

    The accepted constructor forms are:
      Location()                                  the identity location
      Location(gp_Trsf)                           wrap an existing OCCT transformation
      Location(TopLoc_Location)                   wrap an existing OCCT location
      Location(Location)                          copy of another location
      Location([t, axis, angle])                  the packed form used by PartCAD config files,
                                                  e.g. [[0, 0, 0], [0, 0, 1], 0]
      Location(t, axis, angle)                    the same, spelled as three arguments

    Internally the transform is a unit quaternion '_q' plus a translation '_t';
    the OCCT 'TopLoc_Location' is derived on demand via the 'wrapped' property.
    """

    def __init__(self, arg=None, axis=None, angle=None):
        if axis is not None or angle is not None:
            # The three-argument form: Location((x, y, z), (ax, ay, az), angle).
            if arg is None or axis is None or angle is None:
                raise ValueError("geom.Location: the three-argument form needs a translation, an axis and an angle")
            self._t = (float(arg[0]), float(arg[1]), float(arg[2]))
            self._q = _axis_angle_to_quat(axis, angle)
        elif arg is None:
            self._t, self._q = _IDENTITY_T, _IDENTITY_Q
        elif isinstance(arg, Location):
            # Copy. _t/_q are immutable tuples, so sharing them cannot alias.
            self._t, self._q = arg._t, arg._q
        elif isinstance(arg, (list, tuple)):
            if len(arg) != 3:
                raise ValueError(
                    "geom.Location: the packed form needs exactly 3 elements "
                    "([x, y, z], [ax, ay, az], angle), got %d" % len(arg)
                )
            self._t = (float(arg[0][0]), float(arg[0][1]), float(arg[0][2]))
            self._q = _axis_angle_to_quat(arg[1], arg[2])
        else:
            # A gp_Trsf or TopLoc_Location - or, if it is neither, an error.
            extracted = _from_ocp(arg)
            if extracted is None:
                raise ValueError("geom.Location: Invalid argument type")
            self._t, self._q = extracted

    @classmethod
    def _from_qt(cls, q, t) -> "Location":
        """Build a Location straight from a quaternion and a translation."""
        loc = cls.__new__(cls)
        loc._q = q
        loc._t = t
        return loc

    @property
    def wrapped(self):
        """The OCCT 'TopLoc_Location' for this transform, built fresh on each access.

        Building it fresh keeps the pure-Python '_q'/'_t' the single source of
        truth and means two Locations never share (and so cannot alias through)
        one mutable OCCT object.
        """
        from OCP.TopLoc import TopLoc_Location

        return TopLoc_Location(_build_trsf(self._q, self._t))

    def as_packed(self):
        """This location as the packed [[tx,ty,tz], [ax,ay,az], angle] form.

        The inverse of Location([t, axis, angle]); used to carry a location as
        plain data in the BREP envelope (see Assembly), where the geometry-side
        codec turns it back into a TopLoc_Location.
        """
        axis, angle = _quat_to_axis_angle(self._q)
        return [list(self._t), list(axis), angle]

    def inverse(self) -> "Location":
        """Return the location that undoes this one."""
        q_inv = _quat_conj(self._q)
        rt = _rotate_vec(q_inv, self._t)
        return Location._from_qt(q_inv, (-rt[0], -rt[1], -rt[2]))

    def __mul__(self, other: "Location") -> "Location":
        """Compose two locations: (a * b) applies b first and then a."""
        if not isinstance(other, Location):
            return NotImplemented
        q = _quat_mul(self._q, other._q)
        rt = _rotate_vec(self._q, other._t)
        t = (rt[0] + self._t[0], rt[1] + self._t[1], rt[2] + self._t[2])
        return Location._from_qt(q, t)

    def __repr__(self):
        axis, angle = _quat_to_axis_angle(self._q)
        return f"Location({[self._t[0], self._t[1], self._t[2]]}, {[axis[0], axis[1], axis[2]]}, {angle})"

    @classmethod
    def trsf_from_coords(cls, t: Sequence[float], ax: Sequence[float], angle: float):
        """The OCCT gp_Trsf for the packed (translation, axis, angle) form."""
        return _build_trsf(_axis_angle_to_quat(ax, angle), (float(t[0]), float(t[1]), float(t[2])))
