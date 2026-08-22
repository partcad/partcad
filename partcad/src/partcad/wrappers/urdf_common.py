#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Conversions between URDF's pose convention and PartCAD's.

Shared by the two URDF wrappers (wrapper_import_urdf, wrapper_render_urdf) and
deliberately free of every dependency - no OCP, no urdf_parser_py - so it can be
imported and unit-tested on its own.

The two conventions differ in three ways, all handled here:

  * Rotation. URDF states a pose as ``xyz`` plus ``rpy``, fixed-axis
    roll-pitch-yaw applied in the order X, Y, Z (so the matrix is
    ``Rz(yaw) . Ry(pitch) . Rx(roll)``). PartCAD states it as the packed
    ``[[tx, ty, tz], [ax, ay, az], angle]`` form: a rotation of ``angle``
    degrees about an axis through the origin, then a translation.
  * Units. URDF is metres and radians; PartCAD is millimetres and degrees.
  * Handedness of composition, which is the same in both (parent then child),
    so composition is a plain quaternion product - see 'compose()'.

Internally a pose is a ``(quaternion, translation)`` pair, exactly as
partcad.geom.Location holds one, with the translation in whatever unit the
caller is working in. The unit conversion is explicit, at the boundary
functions 'from_urdf_origin()' and 'to_urdf_origin()'.
"""

import math

# Millimetres per metre. URDF is metres by definition (the spec fixes the unit,
# there is no unit attribute to read), PartCAD is millimetres throughout.
MM_PER_M = 1000.0

IDENTITY_Q = (1.0, 0.0, 0.0, 0.0)
IDENTITY_T = (0.0, 0.0, 0.0)

# Below this, an angle or an offset is treated as zero when deciding whether a
# pose is the identity. Chosen well above the double-rounding noise a
# quaternion round-trip leaves behind and well below anything a real model
# expresses.
EPSILON = 1e-9


def quat_mul(a, b):
    """Hamilton product; R(a * b) == R(a) . R(b)."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def rotate_vec(q, v):
    """Apply the rotation 'q' to the vector 'v'."""
    w, x, y, z = q
    vx, vy, vz = v
    return (
        (1.0 - 2.0 * (y * y + z * z)) * vx + 2.0 * (x * y - w * z) * vy + 2.0 * (x * z + w * y) * vz,
        2.0 * (x * y + w * z) * vx + (1.0 - 2.0 * (x * x + z * z)) * vy + 2.0 * (y * z - w * x) * vz,
        2.0 * (x * z - w * y) * vx + 2.0 * (y * z + w * x) * vy + (1.0 - 2.0 * (x * x + y * y)) * vz,
    )


def compose(parent, child):
    """Compose two ``(q, t)`` poses: apply 'child' within the frame of 'parent'."""
    pq, pt = parent
    cq, ct = child
    rt = rotate_vec(pq, ct)
    return (quat_mul(pq, cq), (pt[0] + rt[0], pt[1] + rt[1], pt[2] + rt[2]))


def rpy_to_quat(rpy):
    """The quaternion for URDF's fixed-axis roll-pitch-yaw triple (radians).

    URDF applies the three rotations about the *fixed* X, Y and Z axes in that
    order, which composes as Rz(yaw) . Ry(pitch) . Rx(roll).
    """
    roll, pitch, yaw = (float(v) for v in rpy)
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    return (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )


def quat_to_rpy(q):
    """The URDF roll-pitch-yaw triple (radians) for a quaternion.

    The inverse of 'rpy_to_quat()' up to the usual Euler-angle ambiguities. At
    the gimbal-lock poles (pitch = +-90 degrees) roll and yaw are not separable;
    the roll is put at zero there and the whole rotation is carried by the yaw,
    which is the same choice tf2 and urdfdom make.
    """
    w, x, y, z = q
    # The matrix entries the three angles are read from, expanded from the
    # quaternion rather than built as a full 3x3.
    m31 = 2.0 * (x * z - w * y)
    sin_pitch = max(-1.0, min(1.0, -m31))
    pitch = math.asin(sin_pitch)
    if abs(sin_pitch) > 1.0 - 1e-12:
        # Gimbal lock: only (yaw -+ roll) is determined, so pin roll at zero.
        # R[0][0] and R[1][0] are both zero here, so the yaw the general case
        # reads from them has to come from the first row's other two entries
        # instead - the same choice tf2 makes.
        m12 = 2.0 * (x * y - w * z)  # R[0][1]
        m13 = 2.0 * (x * z + w * y)  # R[0][2]
        if sin_pitch > 0.0:
            return (0.0, pitch, -math.atan2(m12, m13))
        return (0.0, pitch, math.atan2(-m12, -m13))
    roll = math.atan2(2.0 * (y * z + w * x), 1.0 - 2.0 * (x * x + y * y))
    yaw = math.atan2(2.0 * (x * y + w * z), 1.0 - 2.0 * (y * y + z * z))
    return (roll, pitch, yaw)


def axis_angle_to_quat(axis, angle_deg):
    """The quaternion for a rotation of 'angle_deg' about 'axis'.

    A zero-length axis means "no rotation" here rather than an error: it is what
    PartCAD's own packed identity carries when the angle is zero.
    """
    x, y, z = (float(v) for v in axis)
    norm = math.sqrt(x * x + y * y + z * z)
    if norm == 0.0:
        return IDENTITY_Q
    x, y, z = x / norm, y / norm, z / norm
    half = math.radians(float(angle_deg)) / 2.0
    s = math.sin(half)
    return (math.cos(half), x * s, y * s, z * s)


def quat_to_axis_angle(q):
    """The (axis, angle in degrees) pair for a quaternion. Axis is arbitrary at 0."""
    w = max(-1.0, min(1.0, q[0]))
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-12:
        return (0.0, 0.0, 1.0), 0.0
    return (q[1] / s, q[2] / s, q[3] / s), math.degrees(2.0 * math.acos(w))


def normalize(q):
    """Renormalize a quaternion that repeated composition has drifted."""
    w, x, y, z = q
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0.0:
        return IDENTITY_Q
    return (w / norm, x / norm, y / norm, z / norm)


def from_urdf_origin(origin):
    """A URDF ``<origin xyz rpy>`` as a ``(q, t)`` pose with 't' in millimetres.

    'origin' is anything with ``.xyz`` and ``.rpy`` attributes (what
    urdf_parser_py hands back), or None for the identity - URDF treats a missing
    origin as no offset.
    """
    if origin is None:
        return (IDENTITY_Q, IDENTITY_T)
    xyz = getattr(origin, "xyz", None) or (0.0, 0.0, 0.0)
    rpy = getattr(origin, "rpy", None) or (0.0, 0.0, 0.0)
    t = tuple(float(v) * MM_PER_M for v in xyz)
    return (rpy_to_quat(rpy), t)


def to_urdf_origin(pose):
    """A ``(q, t)`` pose (millimetres) as the URDF ``(xyz, rpy)`` pair (metres, radians)."""
    q, t = pose
    return ([v / MM_PER_M for v in t], list(quat_to_rpy(normalize(q))))


def from_packed(packed):
    """PartCAD's packed ``[[t], [axis], angle]`` location as a ``(q, t)`` pose."""
    if packed is None:
        return (IDENTITY_Q, IDENTITY_T)
    t, axis, angle = packed
    return (axis_angle_to_quat(axis, angle), (float(t[0]), float(t[1]), float(t[2])))


def to_packed(pose):
    """A ``(q, t)`` pose as PartCAD's packed ``[[t], [axis], angle]`` location."""
    q, t = pose
    axis, angle = quat_to_axis_angle(normalize(q))
    return [list(t), list(axis), angle]


def is_identity(pose):
    """Whether a pose is the identity, within EPSILON."""
    q, t = pose
    if any(abs(v) > EPSILON for v in t):
        return False
    _, angle = quat_to_axis_angle(normalize(q))
    return abs(angle) <= EPSILON or abs(abs(angle) - 360.0) <= EPSILON


def round_packed(packed, precision):
    """Round a packed location for readability, without changing what it means."""
    t, axis, angle = packed
    return [
        [round(v, precision) for v in t],
        [round(v, precision) for v in axis],
        round(angle, precision),
    ]
