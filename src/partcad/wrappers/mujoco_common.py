#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""MJCF (MuJoCo) conventions: poses, geometry, defaults and the asset tables.

Shared by the MJCF reader (wrapper_import_mjcf), the MJCF exporter
(builtin/export/export_mjcf.py) and the MuJoCo simulation plugin
(builtin/simulate/simulate_mujoco.py), and dependency-free -- no OCP, no
mujoco, nothing but the standard library and 'urdf_common' -- so it can be
imported and unit-tested on its own.

MJCF is the third description of a placed arrangement PartCAD reads, after
URDF and SDFormat, and it is the one that states a pose most freely: a body may
name its orientation as a quaternion, as Euler angles in whichever sequence the
``<compiler>`` declared, as an axis and an angle, as two columns of the rotation
matrix, or as the direction its Z axis points in. All five appear in real
models, so all five are read here and reduced to the one ``(q, t)`` pair the
rest of PartCAD works in. Only the quaternion is ever written, because it is
the one spelling that needs no ``<compiler>`` to be read back.

Three conventions of MJCF's own are worth stating, because getting any of them
wrong moves geometry rather than failing:

  * **Angles are degrees by default.** ``<compiler angle="radian">`` says
    otherwise, and a file that omits the element is in degrees -- the opposite
    of URDF and SDFormat, which are radians with no way to say otherwise.
  * **A box's ``size`` is its half-extents**, a cylinder's and a capsule's is
    ``(radius, half-length)``. MuJoCo states half-sizes throughout, where
    SDFormat and URDF state full ones.
  * **Lengths have no unit in MJCF**, and the whole toolchain treats them as
    metres. PartCAD is millimetres, so the same MM_PER_M the other two readers
    use applies here too.
"""

import math
import os

import urdf_common

# Millimetres per metre. MJCF states no unit at all; MuJoCo's own documentation,
# its default gravity and every model in the wild treat a length as metres.
MM_PER_M = urdf_common.MM_PER_M

IDENTITY = (urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T)

# The attributes that state an orientation, in the order MuJoCo resolves them:
# the first one present wins.
ORIENTATION_ATTRIBUTES = ("quat", "axisangle", "euler", "xyaxes", "zaxis")

# Mesh formats an ``<asset><mesh>`` may name, mapped to the PartCAD part type
# that reads them. MuJoCo's own binary ``.msh`` is deliberately absent, as
# COLLADA is from the other two readers: PartCAD has no reader for it, so it is
# reported as skipped rather than silently ignored.
MESH_PART_TYPES = {
    ".stl": "stl",
    ".obj": "obj",
    ".step": "step",
    ".stp": "step",
    ".brep": "brep",
    ".3mf": "3mf",
}

# Geometry MJCF has and PartCAD builds no shape for. A ``plane`` is the usual
# one -- every floor in every model is a plane of (half-)infinite extent, which
# is not a shape that can be exported.
UNBUILDABLE_GEOMETRY = ("plane", "hfield", "sdf", "ellipsoid", "capsule")

# The geom attributes a ``<default>`` class may carry that this reader acts on.
# Everything else a class states is about the simulation rather than the shape.
DEFAULTED_GEOM_ATTRIBUTES = (
    "type",
    "size",
    "fromto",
    "rgba",
    "mesh",
    "density",
    "mass",
    "friction",
    "solref",
    "solimp",
    "margin",
    "contype",
    "conaffinity",
    "group",
    "material",
    "pos",
    "quat",
    "euler",
    "axisangle",
    "xyaxes",
    "zaxis",
)


class Compiler:
    """What ``<compiler>`` says about how the rest of the file is to be read.

    Only the three settings that change what the geometry *means* are kept:
    the angle unit, the Euler sequence, and where meshes are looked for. The
    rest of ``<compiler>`` configures MuJoCo's model compiler, which PartCAD is
    not.
    """

    def __init__(self, element=None, model_dir="."):
        self.model_dir = model_dir
        self.angle = "degree"
        self.eulerseq = "xyz"
        self.meshdir = None
        self.assetdir = None
        if element is not None:
            self.update(element)

    def update(self, element):
        self.angle = (element.get("angle") or self.angle).strip().lower()
        self.eulerseq = (element.get("eulerseq") or self.eulerseq).strip()
        self.meshdir = element.get("meshdir") or element.get("texturedir") or self.meshdir
        self.assetdir = element.get("assetdir") or self.assetdir

    @property
    def in_degrees(self) -> bool:
        return not self.angle.startswith("rad")

    def to_radians(self, value: float) -> float:
        return math.radians(value) if self.in_degrees else value

    def mesh_dirs(self):
        """The directories a mesh ``file`` is resolved against, in order."""
        dirs = []
        for candidate in (self.meshdir, self.assetdir):
            if candidate:
                dirs.append(candidate if os.path.isabs(candidate) else os.path.join(self.model_dir, candidate))
        dirs.append(self.model_dir)
        return dirs


def numbers(text, warnings=None, what=""):
    """The whitespace-separated numbers of an MJCF attribute, or []."""
    if text is None:
        return []
    values = []
    for token in str(text).split():
        try:
            values.append(float(token))
        except ValueError:
            if warnings is not None:
                warnings.append("Unreadable %s %r; ignoring it" % (what or "value", text))
            return []
    return values


def parse_orientation(element, compiler, warnings=None):
    """The quaternion an element's orientation attributes state.

    MuJoCo accepts five spellings and resolves them in the order of
    ORIENTATION_ATTRIBUTES; the first one present is the answer, and an element
    with none of them is unrotated. Anything unreadable is reported and treated
    as unrotated, the way the SDFormat reader treats an unreadable pose: a body
    facing the wrong way is easier to see and to correct than a model that
    refuses to load.
    """
    if element is None:
        return urdf_common.IDENTITY_Q

    quat = element.get("quat")
    if quat is not None:
        values = numbers(quat, warnings, "quat")
        if len(values) == 4:
            return urdf_common.normalize(tuple(values))
        if warnings is not None:
            warnings.append("A quat needs four numbers, found %d; leaving the body unrotated" % len(values))
        return urdf_common.IDENTITY_Q

    axisangle = element.get("axisangle")
    if axisangle is not None:
        values = numbers(axisangle, warnings, "axisangle")
        if len(values) == 4:
            return urdf_common.axis_angle_to_quat(values[:3], math.degrees(compiler.to_radians(values[3])))
        if warnings is not None:
            warnings.append("An axisangle needs four numbers, found %d; leaving the body unrotated" % len(values))
        return urdf_common.IDENTITY_Q

    euler = element.get("euler")
    if euler is not None:
        values = numbers(euler, warnings, "euler")
        if len(values) == 3:
            return euler_to_quat([compiler.to_radians(v) for v in values], compiler.eulerseq)
        if warnings is not None:
            warnings.append("An euler needs three numbers, found %d; leaving the body unrotated" % len(values))
        return urdf_common.IDENTITY_Q

    xyaxes = element.get("xyaxes")
    if xyaxes is not None:
        values = numbers(xyaxes, warnings, "xyaxes")
        if len(values) == 6:
            return _frame_to_quat(values[:3], values[3:6], warnings)
        if warnings is not None:
            warnings.append("An xyaxes needs six numbers, found %d; leaving the body unrotated" % len(values))
        return urdf_common.IDENTITY_Q

    zaxis = element.get("zaxis")
    if zaxis is not None:
        values = numbers(zaxis, warnings, "zaxis")
        if len(values) == 3:
            return _zaxis_to_quat(values, warnings)
        if warnings is not None:
            warnings.append("A zaxis needs three numbers, found %d; leaving the body unrotated" % len(values))
    return urdf_common.IDENTITY_Q


def parse_pose(element, compiler, warnings=None):
    """An element's ``pos`` and orientation as a ``(q, t)`` pose in millimetres."""
    if element is None:
        return IDENTITY
    position = numbers(element.get("pos"), warnings, "pos")
    if len(position) != 3:
        if position and warnings is not None:
            warnings.append("A pos needs three numbers, found %d; using the origin" % len(position))
        position = [0.0, 0.0, 0.0]
    return (
        parse_orientation(element, compiler, warnings),
        tuple(v * MM_PER_M for v in position),
    )


def euler_to_quat(angles, sequence="xyz"):
    """The quaternion for MuJoCo's Euler triple (radians) in 'sequence'.

    A lowercase letter is an intrinsic rotation (about the axes the previous
    rotations moved), an uppercase one extrinsic (about the fixed axes) -- which
    is what ``<compiler eulerseq>`` chooses between. Intrinsic composition is a
    left-to-right quaternion product; extrinsic is the same product right to
    left, which is the whole of the difference.
    """
    result = urdf_common.IDENTITY_Q
    for letter, angle in zip(sequence, angles):
        axis = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}.get(letter.lower())
        if axis is None:
            continue
        step = urdf_common.axis_angle_to_quat(axis, math.degrees(angle))
        result = urdf_common.quat_mul(result, step) if letter.islower() else urdf_common.quat_mul(step, result)
    return urdf_common.normalize(result)


def _normalized(vector):
    length = math.sqrt(sum(v * v for v in vector))
    if length < 1e-12:
        return None
    return tuple(v / length for v in vector)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _frame_to_quat(x_axis, y_axis, warnings=None):
    """The quaternion of the frame whose X and Y columns are given (``xyaxes``).

    The Y axis is re-orthogonalized against X, which is what MuJoCo does with
    the two vectors an ``xyaxes`` names rather than requiring them to be exactly
    perpendicular.
    """
    x = _normalized(x_axis)
    if x is None:
        if warnings is not None:
            warnings.append("An xyaxes states a zero-length X axis; leaving the body unrotated")
        return urdf_common.IDENTITY_Q
    z = _normalized(_cross(x, y_axis))
    if z is None:
        if warnings is not None:
            warnings.append("An xyaxes states parallel axes; leaving the body unrotated")
        return urdf_common.IDENTITY_Q
    y = _cross(z, x)
    return _matrix_to_quat((x, y, z))


def _zaxis_to_quat(zaxis, warnings=None):
    """The rotation that takes the frame's Z axis onto 'zaxis'.

    The minimal such rotation -- about the axis perpendicular to both -- which
    is what MuJoCo applies, leaving the roll about the new Z unspecified.
    """
    z = _normalized(zaxis)
    if z is None:
        if warnings is not None:
            warnings.append("A zaxis is zero-length; leaving the body unrotated")
        return urdf_common.IDENTITY_Q
    dot = max(-1.0, min(1.0, z[2]))
    if dot > 1.0 - 1e-12:
        return urdf_common.IDENTITY_Q
    if dot < -1.0 + 1e-12:
        # Antiparallel: any perpendicular axis will do, and X is one.
        return urdf_common.axis_angle_to_quat((1.0, 0.0, 0.0), 180.0)
    axis = _cross((0.0, 0.0, 1.0), z)
    return urdf_common.axis_angle_to_quat(axis, math.degrees(math.acos(dot)))


def _matrix_to_quat(columns):
    """The quaternion of a rotation matrix given as its three column vectors."""
    (m00, m10, m20), (m01, m11, m21), (m02, m12, m22) = columns
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        return urdf_common.normalize(((0.25 * s), (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s))
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return urdf_common.normalize(((m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s))
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return urdf_common.normalize(((m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s))
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return urdf_common.normalize(((m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s))


def format_numbers(values, precision=12):
    """Numbers as MJCF writes them: whitespace separated, no exponent surprises."""
    return " ".join(_number(value, precision) for value in values)


def _number(value, precision):
    text = ("%." + str(precision) + "g") % (float(value) + 0.0)
    return "0" if text in ("-0", "-0.0") else text


def format_pos(pose, precision=12):
    """The ``pos`` attribute of a ``(q, t)`` pose stated in millimetres."""
    _, translation = pose
    return format_numbers([v / MM_PER_M for v in translation], precision)


def format_quat(pose, precision=12):
    """The ``quat`` attribute (``w x y z``) of a ``(q, t)`` pose."""
    return format_numbers(urdf_common.normalize(pose[0]), precision)


def resolve_mesh_path(file_attribute, compiler):
    """Resolve an ``<asset><mesh file=...>`` to a path on disk, or None.

    MJCF names a mesh by a plain path, resolved against ``<compiler meshdir>``
    (or ``assetdir``) and, failing that, against the model file's own directory.
    That is the whole of the search MuJoCo itself does, and the counterpart of
    'gazebo_common.resolve_uri' and the URDF reader's ``package://`` lookup.
    """
    name = (file_attribute or "").strip()
    if not name:
        return None
    if os.path.isabs(name):
        return name if os.path.exists(name) else None
    for directory in compiler.mesh_dirs():
        candidate = os.path.join(directory, name)
        if os.path.exists(candidate):
            return candidate
    return None


def mesh_scale_factor(scale_text, warnings):
    """The uniform scale, in PartCAD's millimetres, of an ``<asset><mesh scale>``.

    MuJoCo multiplies a mesh's own coordinates by ``scale`` and reads the result
    as metres, so a mesh written in millimetres carries ``0.001 0.001 0.001`` --
    which is what PartCAD's own exporter writes, and what makes this come back
    as 1.0. A non-uniform scale has no equivalent in a PartCAD part
    configuration, so it is reported and the X component is used.
    """
    values = numbers(scale_text)
    if not values:
        if scale_text and scale_text.strip():
            warnings.append("Unreadable mesh scale '%s'; reading the mesh as millimetres instead" % scale_text.strip())
        return MM_PER_M
    if len(values) < 3:
        values = values * 3
    if max(values[:3]) - min(values[:3]) > 1e-12:
        warnings.append(
            "Non-uniform mesh scale %s is not representable in PartCAD; using the X component %g"
            % (values[:3], values[0])
        )
    return values[0] * MM_PER_M


def color_hex(text):
    """An MJCF ``rgba`` (four numbers, each 0..1) as PartCAD's colour string."""
    values = numbers(text)
    if len(values) < 3:
        return None
    values = [max(0.0, min(1.0, v)) for v in values]
    result = "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in values[:3])
    if len(values) > 3 and values[3] < 1.0:
        result += "%02X" % int(round(values[3] * 255))
    return result


def color_rgba(text, default_alpha=1.0):
    """A PartCAD colour string as MJCF's ``r g b a``, or None."""
    value = str(text or "").strip().lstrip("#")
    if len(value) not in (6, 8):
        return None
    try:
        channels = [int(value[index : index + 2], 16) / 255.0 for index in range(0, len(value), 2)]
    except ValueError:
        return None
    while len(channels) < 4:
        channels.append(default_alpha)
    return format_numbers(channels, 4)


def collect_defaults(root):
    """The ``<default>`` classes of a model, as class name -> geom attributes.

    MJCF's defaults are a tree: a class inherits every attribute of the class
    that encloses it, and the unnamed top-level ``<default>`` is the root every
    other class descends from. Only the ``<geom>`` attributes are collected --
    everything else a class states is about the simulation, not the shape -- and
    the root's are filed under the empty string, which is the class a geom that
    names none of them belongs to.
    """
    classes = {}

    def walk(element, inherited):
        attributes = dict(inherited)
        geom = element.find("geom")
        if geom is not None:
            for name in DEFAULTED_GEOM_ATTRIBUTES:
                value = geom.get(name)
                if value is not None:
                    attributes[name] = value
        name = element.get("class") or ""
        classes[name] = attributes
        for nested in element.findall("default"):
            walk(nested, attributes)

    for element in root.findall("default"):
        walk(element, {})
    classes.setdefault("", {})
    return classes


def geom_attributes(geom, classes, childclass):
    """One ``<geom>``'s attributes with its ``<default>`` class applied under them.

    The class is the geom's own ``class``, or the ``childclass`` the enclosing
    body set, or the root default -- the order MuJoCo resolves them in.
    """
    name = geom.get("class") or childclass or ""
    attributes = dict(classes.get(name) or classes.get("", {}))
    attributes.update({key: value for key, value in geom.attrib.items() if value is not None})
    return attributes
