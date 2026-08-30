#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""SDFormat (Gazebo) conventions: poses, geometry, and the vocabulary tables.

Shared by the world reader (wrapper_import_world) and the world exporter
(builtin/export/export_world.py), and dependency-free -- no OCP, no XML schema,
nothing but the standard library and 'urdf_common' -- so it can be imported and
unit-tested on its own.

"SDF" is overloaded in PartCAD and the two meanings are unrelated. The 'sdf'
*part* type is a signed distance function, evaluated by 'wrapper_sdf.py'. This
module is about **SDFormat**, the XML dialect Gazebo describes simulation
worlds in, and PartCAD calls that one ``world`` after the ``.world`` files it
lives in -- which is also the identifier a scene is exported to it under. Where
this module says "SDF" it always means SDFormat.

SDFormat states a pose exactly as URDF states an ``<origin>``: a translation
and a fixed-axis roll-pitch-yaw triple, in metres and radians. So the pose
maths is 'urdf_common''s, unchanged, and only the spelling differs -- six
numbers in one element rather than two attributes. Two SDF-only spellings are
handled here because they appear in real files: ``degrees="true"`` and
``rotation_format="quat_xyzw"``.
"""

import math
import os

import urdf_common

# Millimetres per metre. SDFormat is metres by definition, PartCAD is
# millimetres throughout; the same constant URDF is read and written with.
MM_PER_M = urdf_common.MM_PER_M

# The SDFormat version PartCAD writes. 1.9 is what Gazebo (Ionic/Harmonic)
# reads, and every element written here has been in the format for far longer;
# a reader of an older version accepts the file, since nothing below is new.
SDF_VERSION = "1.9"

# Mesh formats a world may name, mapped to the PartCAD part type that reads
# them. COLLADA (.dae) is deliberately absent for the reason it is absent from
# the URDF reader: it is common in Gazebo models and PartCAD has no reader for
# it, so it is reported as skipped rather than silently ignored.
MESH_PART_TYPES = {
    ".stl": "stl",
    ".obj": "obj",
    ".step": "step",
    ".stp": "step",
    ".brep": "brep",
    ".3mf": "3mf",
}

IDENTITY = (urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T)


def parse_pose(element, warnings=None):
    """One ``<pose>`` element as a ``(q, t)`` pose with 't' in millimetres.

    None -- a missing ``<pose>`` -- is the identity, which is what SDFormat
    says a missing pose means. Anything unreadable is reported and treated the
    same way: a model in the wrong place is easier to see and to correct than a
    world that refuses to load.
    """
    if element is None:
        return IDENTITY
    text = (element.text or "").strip()
    if not text:
        return IDENTITY

    relative_to = element.get("relative_to") or element.get("@relative_to")
    if relative_to and warnings is not None:
        # PartCAD places every object in the frame of the one that holds it.
        # A pose stated relative to some other frame would need the frame graph
        # SDFormat has and PartCAD does not.
        warnings.append(
            "A pose stated relative to the frame '%s' is read as relative to its parent instead" % relative_to
        )

    values = []
    for token in text.split():
        try:
            values.append(float(token))
        except ValueError:
            if warnings is not None:
                warnings.append("Unreadable pose %r; using the identity instead" % text)
            return IDENTITY

    rotation_format = (element.get("rotation_format") or "").strip()
    if rotation_format == "quat_xyzw":
        if len(values) != 7:
            if warnings is not None:
                warnings.append("A quat_xyzw pose needs seven numbers, found %d; using the identity" % len(values))
            return IDENTITY
        x, y, z, qx, qy, qz, qw = values
        return (
            urdf_common.normalize((qw, qx, qy, qz)),
            (x * MM_PER_M, y * MM_PER_M, z * MM_PER_M),
        )

    if len(values) != 6:
        if warnings is not None:
            warnings.append("A pose needs six numbers, found %d; using the identity" % len(values))
        return IDENTITY

    x, y, z, roll, pitch, yaw = values
    if _is_true(element.get("degrees")):
        roll, pitch, yaw = (math.radians(v) for v in (roll, pitch, yaw))
    return (
        urdf_common.rpy_to_quat((roll, pitch, yaw)),
        (x * MM_PER_M, y * MM_PER_M, z * MM_PER_M),
    )


def _is_true(text):
    return str(text).strip().lower() in ("1", "true")


def format_pose(pose, precision=12):
    """A ``(q, t)`` pose (millimetres) as the six numbers ``<pose>`` carries.

    Twelve significant digits, not the six a pose is usually written with: an
    angle is stated here in radians, so six digits of "1.5708" is four digits of
    a right angle and a round trip through the file would move a model by
    two ten-thousandths of a degree. Twelve keeps the round trip below what any
    geometry notices while staying a number a person can read.
    """
    xyz, rpy = urdf_common.to_urdf_origin(pose)
    return " ".join(_number(v, precision) for v in list(xyz) + list(rpy))


def _number(value, precision):
    text = ("%." + str(precision) + "g") % (value + 0.0)
    return "0" if text in ("-0", "-0.0") else text


def resolve_uri(uri, world_dir, model_paths):
    """Resolve an SDFormat ``<uri>`` to a path on disk, or None.

    SDFormat names files in three ways and all three appear in the wild:
    ``model://<name>/<rest>`` (resolved against the model path, which outside a
    Gazebo installation is whatever the caller configured plus the directories
    around the world file), ``file://<abs>``, and a plain relative path. This
    is the same search a standalone SDF viewer ends up doing, and the same one
    'wrapper_import_urdf.resolve_mesh_path' does for ``package://``.
    """
    uri = (uri or "").strip()
    if not uri:
        return None

    if uri.startswith("file://"):
        path = uri[len("file://") :]
        return path if os.path.isabs(path) else os.path.join(world_dir, path)

    if uri.startswith("model://"):
        model, _, rest = uri[len("model://") :].partition("/")
        candidates = []
        for root in model_paths:
            candidates.append(os.path.join(root, model, rest) if rest else os.path.join(root, model))
            if rest:
                candidates.append(os.path.join(root, rest))
        directory = world_dir
        while True:
            candidates.append(os.path.join(directory, model, rest) if rest else os.path.join(directory, model))
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent
        if rest:
            candidates.append(os.path.join(world_dir, rest))
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return None

    if os.path.isabs(uri):
        return uri
    return os.path.join(world_dir, uri)


def mesh_scale_factor(scale_text, warnings):
    """The uniform scale, in PartCAD's millimetres, of an SDF ``<mesh><scale>``.

    SDFormat reads mesh coordinates as metres after applying ``scale``, so a
    mesh written in millimetres carries ``0.001 0.001 0.001`` -- which is what
    PartCAD's own exporter writes, and what makes this come back as 1.0. A
    non-uniform scale has no equivalent in a PartCAD part configuration, so it
    is reported and the X component is used.
    """
    if not scale_text or not scale_text.strip():
        return MM_PER_M
    try:
        values = [float(v) for v in scale_text.split()]
    except ValueError:
        # Reported and defaulted rather than raised, the way 'parse_pose'
        # treats an unreadable pose: a mesh at the wrong size is easier to see
        # and to correct than a world that refuses to load at all.
        warnings.append("Unreadable mesh scale '%s'; reading the mesh as millimetres instead" % scale_text.strip())
        return MM_PER_M
    if not values:
        return MM_PER_M
    if len(values) < 3:
        values = values * 3
    if max(values[:3]) - min(values[:3]) > 1e-12:
        warnings.append(
            "Non-uniform mesh scale %s is not representable in PartCAD; using the X component %g"
            % (values[:3], values[0])
        )
    return values[0] * MM_PER_M
