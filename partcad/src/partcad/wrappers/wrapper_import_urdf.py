#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Read a URDF file and return the plain data PartCAD builds an assembly from.

This runs inside the python sandbox, for two reasons. The URDF parser is ROS's
own 'urdf_parser_py' rather than an XML reader written here, and PartCAD does
not carry the ROS stack as a dependency; and URDF's primitive shapes have to be
turned into geometry, which needs OCCT and which the core process never loads.
The core only receives plain data back.

**Nothing is rewritten that does not have to be.** A ``<mesh>`` becomes a part
that reads the very file the URDF named, at the path the URDF named it by; the
``<origin>`` that places it becomes a PartCAD location, not a transform baked
into new geometry. Only ``<box>``/``<cylinder>``/``<sphere>`` are generated,
because there is no file to point at. So a link with several visuals becomes a
*sub-assembly* of one part per visual, addressable as
``<assembly>/<link>/<name or index>``, and a link with one becomes the single
part ``<assembly>/<link>``.

**Nothing is stored in a container of its own either.** What the URDF says
about a link's physics is copied field by field into named PartCAD properties
with PartCAD units - see "The property tables" below - and URDF content nothing
there knows about stops the import instead of being tucked away under a
format-specific key. The link's *name* is the part's name and the joint tree is
this very file, so neither is recorded a second time.

The tree this returns has the same node shape wrapper_import_assy produces from
a STEP assembly, so both feed the same node handler and end up as the identical
in-memory representation an ASSY file produces:

    assembly node:  {"type": "assembly", "name", "location", "links": [...]}
    part node:      {"type": "part", "name", "location", "part_file",
                     "part_type", "scale"}

Alongside the tree, the response carries the flat ``links`` and ``joints``
tables that ``pc convert assembly -t assy`` needs to write an ASSY file, its
parts and the interfaces its joints turn into.
"""

import math
import os
import sys

# Pinned before anything that may pull OCP: VTK bundles its own older expat
# under the standard XML_* names, and once that is loaded the standard library's
# pyexpat binds to it and dies with an undefined-symbol ImportError. lxml (which
# urdf_parser_py may parse with) and OCP both reach it.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import urdf_common  # noqa: E402
import wrapper_common  # noqa: E402

# Mesh formats a URDF may name, mapped to the PartCAD part type that reads them.
# COLLADA (.dae) is deliberately absent: it is common in URDF and PartCAD has no
# reader for it, so it is reported as skipped rather than silently ignored.
MESH_PART_TYPES = {
    ".stl": "stl",
    ".obj": "obj",
    ".step": "step",
    ".stp": "step",
    ".brep": "brep",
    ".3mf": "3mf",
}

# What a URDF file may carry that PartCAD has no property for, or that its
# assembly cannot hold. The counters are reported rather than the loss being
# passed over in silence. Mass, inertia, friction, joint limits and joint
# dynamics are *not* here: they became named PartCAD properties, and the tables
# below are where they are read.
DROPPABLE = (
    "joint_kinematics",
    "collision",
    "visual",
    "transmission",
    "gazebo",
    "sensor",
    "calibration",
)

IDENTITY = (urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T)


class Dropped(dict):
    """Counters for the URDF content that does not survive as geometry."""

    def __init__(self):
        super().__init__({key: 0 for key in DROPPABLE})

    def add(self, key, count=1):
        self[key] = self.get(key, 0) + count

    def summary(self):
        return {key: value for key, value in self.items() if value}


#
# Path resolution
#


def resolve_mesh_path(filename, urdf_dir, package_paths):
    """Resolve a URDF mesh reference to a path on disk, or None.

    URDF names meshes in three ways and all three appear in the wild:
    ``package://<pkg>/<rest>`` (the ROS way, resolved against the ROS package
    path), ``file://<abs>``, and a plain path taken relative to the URDF file.
    Outside a ROS workspace there is no package path to consult, so a
    ``package://`` reference is resolved by looking for the package directory
    among the configured roots and then up from the URDF itself - which is what
    RViz, Gazebo and every standalone URDF viewer end up doing too.
    """
    if filename.startswith("file://"):
        path = filename[len("file://") :]
        return path if os.path.isabs(path) else os.path.join(urdf_dir, path)

    if filename.startswith("package://"):
        package, _, rest = filename[len("package://") :].partition("/")
        candidates = []
        for root in package_paths:
            candidates.append(os.path.join(root, package, rest))
            candidates.append(os.path.join(root, rest))
        # Then every ancestor of the URDF file, so a layout like
        # '<pkg>/urdf/robot.urdf' referring to '<pkg>/meshes/x.stl' resolves.
        directory = urdf_dir
        while True:
            candidates.append(os.path.join(directory, package, rest))
            if os.path.basename(directory) == package:
                candidates.append(os.path.join(directory, rest))
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent
        # Last resort: treat the remainder as relative to the URDF.
        candidates.append(os.path.join(urdf_dir, rest))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None

    if os.path.isabs(filename):
        return filename
    return os.path.join(urdf_dir, filename)


def mesh_scale_factor(mesh, warnings):
    """The uniform scale, in PartCAD's millimetres, of a URDF mesh reference.

    URDF reads mesh coordinates as metres after applying ``scale``, so a mesh
    written in millimetres carries ``scale="0.001 0.001 0.001"`` - which is what
    PartCAD's own exporter writes, and what makes this come back as 1.0.

    A non-uniform scale has no equivalent in PartCAD's part configuration (which
    scales a shape by a single factor), so it is reported and the X component is
    used.
    """
    scale = getattr(mesh, "scale", None)
    if scale is None:
        # No scale attribute: the mesh is already in metres.
        return urdf_common.MM_PER_M
    values = [float(v) for v in scale]
    if max(values) - min(values) > 1e-12:
        warnings.append(
            "Non-uniform mesh scale %s is not representable in PartCAD; using the X component %g" % (values, values[0])
        )
    return values[0] * urdf_common.MM_PER_M


#
# Primitives - the only geometry that has to be generated
#


def primitive_file(geometry, kind, name, context):
    """Write a URDF box/cylinder/sphere out as a STEP file and return its path.

    All three are centred on the link origin in URDF, which is not where OCCT's
    primitive builders put them, so each is re-centred here - and then it is the
    element's own ``<origin>`` that places it, exactly as it would place a mesh.
    Identical primitives share one file: a URDF that repeats a shape (wheels,
    bolts) should not produce a file per link.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    mm = urdf_common.MM_PER_M
    if kind == "box":
        size = tuple(round(float(v) * mm, 9) for v in geometry.size)
        key = ("box",) + size
    elif kind == "cylinder":
        radius, length = round(float(geometry.radius) * mm, 9), round(float(geometry.length) * mm, 9)
        key = ("cylinder", radius, length)
    else:
        radius = round(float(geometry.radius) * mm, 9)
        key = ("sphere", radius)

    cache = context["primitives"]
    if key in cache:
        return cache[key]

    if kind == "box":
        shape = BRepPrimAPI_MakeBox(gp_Pnt(-size[0] / 2.0, -size[1] / 2.0, -size[2] / 2.0), *size).Shape()
    elif kind == "cylinder":
        shape = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, -length / 2.0), gp_Dir(0, 0, 1)), radius, length).Shape()
    else:
        shape = BRepPrimAPI_MakeSphere(radius).Shape()

    os.makedirs(context["output_folder"], exist_ok=True)
    base = os.path.basename(name.replace("/", "_")) or kind
    path = os.path.join(context["output_folder"], "%s.step" % base)
    suffix = 1
    while path in context["written"]:
        path = os.path.join(context["output_folder"], "%s_%d.step" % (base, suffix))
        suffix += 1
    context["written"].add(path)

    writer = STEPControl_Writer()
    if writer.Transfer(shape, STEPControl_AsIs) != 1 or writer.Write(path) != 1:
        raise ValueError("Failed to write the STEP file for a URDF primitive: %s" % path)

    cache[key] = path
    return path


#
# The property tables
#
# Everything a URDF says that PartCAD keeps is copied field by field into a
# *named PartCAD property with a documented unit*, through the tables below.
# There is deliberately no format-specific container to hide values in: a
# property either has a PartCAD name and a PartCAD unit, or it is reported.
#
# Two rules follow from that, and both are on purpose:
#
#   * URDF content nothing here knows about stops the import with an error that
#     names it. When URDF grows a field, or one turns up in the wild, *extend
#     the table* - do not widen the error and do not add a passthrough.
#   * The export does the reverse: a PartCAD property URDF has no spelling for
#     is reported through the log rather than silently dropped. The list lives
#     in wrapper_render_urdf.URDF_STATED, and is to be extended the same way.
#
# The units are one rule: lengths are millimetres and angles are degrees, which
# is what PartCAD uses everywhere; everything else is SI, which is what URDF
# already states. So a mass stays kilograms and an inertia tensor stays kg.m^2,
# while a centre of mass becomes millimetres and a joint limit becomes degrees.
#

# What ``<gazebo reference="<link>">`` may say about a link's physics, as
# (PartCAD property, how to read the text). Gazebo is where URDF keeps contact
# and friction, so these are as much "URDF physics values" as <inertial> is.
GAZEBO_LINK_PHYSICS = {
    "mu1": ("friction", float),
    "mu2": ("friction2", float),
    "fdir1": ("frictionDirection", lambda text: [float(v) for v in text.split()]),
    "kp": ("contactStiffness", float),
    "kd": ("contactDamping", float),
    "minDepth": ("minContactDepth", lambda text: float(text) * urdf_common.MM_PER_M),
    "maxVel": ("maxContactVelocity", lambda text: float(text) * urdf_common.MM_PER_M),
    "bounce": ("restitution", float),
    "maxContacts": ("maxContacts", int),
    "dampingFactor": ("velocityDamping", float),
    "selfCollide": ("selfCollide", lambda text: text.strip().lower() in ("1", "true")),
    "gravity": ("gravity", lambda text: text.strip().lower() in ("1", "true")),
    "turnGravityOff": ("gravity", lambda text: text.strip().lower() not in ("1", "true")),
}

# What ``<gazebo reference="<joint>">`` may say about a joint's physics. These
# reach a PartCAD interface, not a part.
GAZEBO_JOINT_PHYSICS = {
    "springStiffness": ("springStiffness", float),
    "springReference": ("springReference", float),
    "stopCfm": ("stopCfm", float),
    "stopErp": ("stopErp", float),
    "fudgeFactor": ("fudgeFactor", float),
    "implicitSpringDamper": ("implicitSpringDamper", lambda text: text.strip().lower() in ("1", "true")),
    "provideFeedback": ("provideFeedback", lambda text: text.strip().lower() in ("1", "true")),
}

# Gazebo tags that are understood and deliberately have no PartCAD property:
# appearance, geometry PartCAD already holds, and the two - sensors and
# simulator plugins - that items 7 and 8 of docs/source/simulation.rst are
# about. They are counted as dropped rather than reported one by one. Anything
# else is reported, which is the point: this list is short on purpose.
GAZEBO_IGNORED = frozenset(("material", "visual", "collision", "sensor", "plugin"))


def color_hex(rgba):
    """A URDF ``rgba`` as PartCAD's colour string.

    Eight bits per channel, and the alpha only when the colour is not opaque -
    which is how a colour is written everywhere else in a PartCAD package.
    """
    values = [max(0.0, min(1.0, float(v))) for v in rgba]
    text = "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in values[:3])
    if len(values) > 3 and values[3] < 1.0:
        text += "%02X" % int(round(values[3] * 255))
    return text


def appearance(element, context):
    """The ``material``/``color`` a ``<visual>`` gives the part, as PartCAD names.

    A URDF material is either stated inline or named here and defined once at
    the robot level; both end up as the same two properties.
    """
    material = getattr(element, "material", None)
    if material is None:
        return {}

    name = getattr(material, "name", None)
    color = getattr(material, "color", None)
    texture = getattr(material, "texture", None)
    if color is None and texture is None and name:
        defined = context["materials"].get(name)
        if defined is None:
            unsupported(context, "The material '%s' is used but never defined" % name)
        else:
            color, texture = getattr(defined, "color", None), getattr(defined, "texture", None)

    result = {}
    if name:
        result["material"] = name
    if color is not None and getattr(color, "rgba", None) is not None:
        result["color"] = color_hex(color.rgba)
    if texture is not None:
        # A texture image has no PartCAD property; the material name that
        # selects it survives, the image does not.
        unsupported(context, "The material '%s' names a texture, which PartCAD does not carry" % name)
    return result


def link_physics(link, context):
    """A URDF link's physical properties, as named PartCAD properties.

    ``<inertial>`` plus whatever the link's ``<gazebo>`` block says about
    contact and friction. Nothing here is a copy of the URDF's own structure -
    each value is read out and restated in PartCAD's terms.
    """
    physics = {}

    inertial = getattr(link, "inertial", None)
    if inertial is not None:
        mass = getattr(inertial, "mass", None)
        if mass is not None:
            physics["mass"] = float(mass)  # kg, as URDF states it
        origin = getattr(inertial, "origin", None)
        if origin is not None:
            xyz = [float(v) for v in (getattr(origin, "xyz", None) or (0.0, 0.0, 0.0))]
            rpy = [float(v) for v in (getattr(origin, "rpy", None) or (0.0, 0.0, 0.0))]
            if any(xyz):
                physics["centerOfMass"] = [round(v * urdf_common.MM_PER_M, 9) for v in xyz]
            if any(rpy):
                # The inertia tensor is stated in a frame of its own; PartCAD
                # states that frame's orientation the way it states every other.
                physics["inertiaOrientation"] = [round(math.degrees(v), 9) for v in rpy]
        inertia = getattr(inertial, "inertia", None)
        if inertia is not None:
            # kg.m^2 about 'centerOfMass', which is the frame URDF uses too.
            physics["inertia"] = {key: float(getattr(inertia, key, 0.0) or 0.0) for key in inertia.KEYS}

    physics.update(gazebo_physics(link.name, GAZEBO_LINK_PHYSICS, context))
    return physics


def gazebo_physics(reference, table, context):
    """The physics a ``<gazebo reference="...">`` block states, as PartCAD names.

    Anything the table does not know is reported - or, with ``strict``, fatal.
    ``<gazebo>`` is URDF's open extension point, so an unknown child is a
    routine occurrence rather than a broken file, which is why it is not fatal
    by default the way unknown *core* URDF is.
    """
    physics = {}
    for element in context["gazebo"].get(reference) or []:
        for child in element:
            tag = getattr(child, "tag", None)
            if not isinstance(tag, str):
                # A comment or a processing instruction: lxml gives those a
                # callable tag, and they say nothing either way.
                continue
            if tag in GAZEBO_IGNORED:
                context["dropped"].add("gazebo")
                continue
            mapping = table.get(tag)
            if mapping is None:
                context["dropped"].add("gazebo")
                unsupported(
                    context,
                    "PartCAD has no property for the Gazebo setting '%s' of '%s'; it is not carried" % (tag, reference),
                )
                continue
            name, read = mapping
            try:
                physics[name] = read(child.text or "")
            except (TypeError, ValueError) as e:
                unsupported(context, "The Gazebo setting '%s' of '%s' is unreadable: %s" % (tag, reference, e))
    return physics


def joint_record(joint, context):
    """A URDF joint restated in PartCAD's terms.

    Returns ``{"motion": ..., "physics": ...}`` alongside the joint's identity:
    what the joint *can do* and what it *costs*, which is the same split a
    PartCAD interface makes. ``pc convert assembly -t assy`` writes these two
    dictionaries straight into the interface it generates, so the units are
    converted here and nowhere else.
    """
    angular = joint.type in ("revolute", "continuous")
    # A revolute joint's limits and velocity are angles; a prismatic joint's are
    # lengths. Nothing else in URDF has a unit that PartCAD restates.
    to_pc = math.degrees if angular else (lambda v: v * urdf_common.MM_PER_M)

    motion = {"type": joint.type}
    if getattr(joint, "axis", None) is not None:
        motion["axis"] = [float(v) for v in joint.axis]

    limit = getattr(joint, "limit", None)
    physics = {}
    if limit is not None:
        limits = {}
        for urdf_name, pc_name in (("lower", "lower"), ("upper", "upper")):
            value = getattr(limit, urdf_name, None)
            if value is not None:
                limits[pc_name] = round(to_pc(float(value)), 9)
        if limits:
            motion["limits"] = limits
        if getattr(limit, "effort", None) is not None:
            physics["maxEffort"] = float(limit.effort)  # N.m or N, as URDF states it
        if getattr(limit, "velocity", None) is not None:
            physics["maxVelocity"] = round(to_pc(float(limit.velocity)), 9)  # deg/s or mm/s

    safety = getattr(joint, "safety_controller", None)
    if safety is not None:
        soft = {}
        for urdf_name, pc_name, convert in (
            ("soft_lower_limit", "lower", to_pc),
            ("soft_upper_limit", "upper", to_pc),
            ("k_position", "kPosition", float),
            ("k_velocity", "kVelocity", float),
        ):
            value = getattr(safety, urdf_name, None)
            if value is not None:
                soft[pc_name] = round(convert(float(value)), 9)
        if soft:
            motion["softLimits"] = soft

    mimic = getattr(joint, "mimic", None)
    if mimic is not None and getattr(mimic, "joint", None):
        # A joint that follows another is kinematics, not physics.
        motion["mimic"] = {"joint": mimic.joint}
        if getattr(mimic, "multiplier", None) is not None:
            motion["mimic"]["multiplier"] = float(mimic.multiplier)
        if getattr(mimic, "offset", None) is not None:
            motion["mimic"]["offset"] = round(to_pc(float(mimic.offset)), 9)

    dynamics = getattr(joint, "dynamics", None)
    if dynamics is not None:
        for urdf_name, pc_name in (("damping", "damping"), ("friction", "friction")):
            value = getattr(dynamics, urdf_name, None)
            if value is not None:
                physics[pc_name] = float(value)

    if getattr(joint, "calibration", None) is not None:
        # A limit-switch reference used when a real robot is commissioned. It
        # says nothing about the model, so PartCAD has no property for it.
        context["dropped"].add("calibration")

    physics.update(gazebo_physics(joint.name, GAZEBO_JOINT_PHYSICS, context))

    return {
        "name": joint.name,
        "type": joint.type,
        "parent": joint.parent,
        "child": joint.child,
        "motion": motion,
        "physics": physics,
    }


#
# The walk
#


def choose_geometry(link, context):
    """The elements a link's shapes are built from, and the ones left over.

    Collision geometry wins by default: it is what a simulator resolves contact
    against, it is usually the cheaper shape, and a URDF that states both means
    the collision shape to be the physical one. ``ignoreCollision`` reverses
    that - ``true`` everywhere, or for the named links only.
    """
    ignore = context["ignore_collision"]
    prefer_visual = ignore is True or link.name in ignore
    if prefer_visual:
        chosen, other, kind = list(link.visuals), list(link.collisions), "visual"
    else:
        chosen, other, kind = list(link.collisions), list(link.visuals), "collision"

    if not chosen and other:
        # The link only has the other kind; using it beats dropping the link.
        chosen, other, kind = other, [], ("collision" if prefer_visual else "visual")
    return chosen, other, kind


def element_node_name(element, index, count, link_name):
    """What the part for one ``<visual>``/``<collision>`` is called.

    A link with one is simply the link. A link with several gets one part per
    element, under the link: by the element's own ``name`` when the URDF gave it
    one, and by its position otherwise.

    The slash is the whole of the hierarchy PartCAD keeps here. A URDF link name
    is a flat namespace and so is a PartCAD part name; what nests inside a link
    are its own shapes, and that is what the name says.
    """
    if count == 1:
        return link_name
    return "%s/%s" % (link_name, getattr(element, "name", None) or (index + 1))


def geometry_node(element, name, link_name, context):
    """The part node for one ``<visual>``/``<collision>``, or None if unreadable.

    A mesh is referenced where it lies: the part reads the file the URDF named,
    and the element's ``<origin>`` becomes the part's location rather than a
    transform applied to a copy of the geometry.
    """
    geometry = getattr(element, "geometry", None)
    if geometry is None:
        return None

    node = {
        "type": "part",
        "name": name,
        "link": link_name,
        "location": urdf_common.round_packed(
            urdf_common.to_packed(urdf_common.from_urdf_origin(getattr(element, "origin", None))),
            context["precision"],
        ),
        "scale": 1.0,
    }
    node.update(appearance(element, context))

    kind = type(geometry).__name__.lower()
    if kind == "mesh":
        path = resolve_mesh_path(geometry.filename, context["urdf_dir"], context["package_paths"])
        if path is None or not os.path.isfile(path):
            context["warnings"].append("Mesh file not found for link '%s': %s" % (link_name, geometry.filename))
            return None
        extension = os.path.splitext(path)[1].lower()
        part_type = MESH_PART_TYPES.get(extension)
        if part_type is None:
            context["warnings"].append(
                "Link '%s' uses the mesh format '%s', which PartCAD cannot read; skipping it"
                % (link_name, extension or "<none>")
            )
            return None
        node["part_file"] = os.path.abspath(path)
        node["part_type"] = part_type
        node["scale"] = mesh_scale_factor(geometry, context["warnings"])
        return node

    if kind in ("box", "cylinder", "sphere"):
        node["part_file"] = primitive_file(geometry, kind, name, context)
        node["part_type"] = "step"
        return node

    context["warnings"].append("Link '%s' uses an unsupported geometry type '%s'" % (link_name, kind))
    return None


def link_geometry(link, context):
    """(part nodes, physics) for a link's geometry.

    The geometry of the kind that was *not* chosen is not thrown away and is not
    stashed either: it becomes a part of its own, named
    ``<link>/<visual|collision>``, which is defined and exportable but not
    placed in the assembly. Only its ``<origin>`` within the link is lost, since
    a part that nothing places has nowhere to keep one.

    Nothing here records the link's name or its parent. The part *is* named
    after the link, and the joint tree is the URDF file (for an assembly read
    from one) or the ``connect:`` sections (for one converted to ASSY) - a
    second copy in a properties section would only be a second thing to keep
    right.
    """
    chosen, other, kind = choose_geometry(link, context)
    other_kind = "collision" if kind == "visual" else "visual"
    context["dropped"].add(other_kind, len(other))

    nodes = []
    for index, element in enumerate(chosen):
        name = element_node_name(element, index, len(chosen), link.name)
        node = geometry_node(element, name, link.name, context)
        if node is not None:
            nodes.append(node)

    for index, element in enumerate(other):
        name = "%s/%s" % (link.name, other_kind)
        if len(other) > 1:
            name = "%s/%s" % (name, getattr(element, "name", None) or (index + 1))
        node = geometry_node(element, name, link.name, context)
        if node is not None:
            node.pop("location", None)
            context["unplaced"].append(node)

    return nodes, link_physics(link, context)


def walk_link(robot, link_name, relative, absolute, context, visited, ancestor):
    """Add a link's node to the flat list, then walk the links below it.

    **The joint chain is not nesting.** A URDF's tree is its kinematics, and an
    assembly is one static configuration of it - every joint at zero - so a link
    hanging off another says nothing that the link's own placement does not
    already say. Nesting a sub-assembly per link would make an arm as deep as it
    has joints, for no information. So every link goes into one list at its
    *absolute* placement, and the only nesting left is the one that means
    something: a link of several shapes groups them.

    The relative placements are not lost - they are what URDF actually states,
    and 'pc convert assembly -t assy' turns them into joints - they are recorded
    in the link table rather than built into the tree.

    'relative' is the link's placement relative to the nearest ancestor that has
    geometry (not necessarily its URDF parent - a link with no geometry
    contributes nothing and its children compose straight through it), and
    'absolute' is its placement relative to the robot's root.
    """
    if link_name in visited:
        context["warnings"].append("Ignoring a cycle in the URDF joint tree at link '%s'" % link_name)
        return
    visited = visited | {link_name}

    link = robot.link_map.get(link_name)
    if link is None:
        context["warnings"].append("Joint refers to the unknown link '%s'" % link_name)
        return
    context["reached"].add(link_name)

    geometry, physics = link_geometry(link, context)
    placement = urdf_common.round_packed(urdf_common.to_packed(absolute), context["precision"])

    if len(geometry) == 1:
        # The link is one shape, so the part *is* the link: it takes the link's
        # placement, keeps its own offset within it, and carries what the link
        # said about itself.
        node = geometry[0]
        shape_origin = node["location"]
        node["location"] = urdf_common.round_packed(
            urdf_common.to_packed(urdf_common.compose(absolute, urdf_common.from_packed(shape_origin))),
            context["precision"],
        )
        if physics:
            node["physics"] = physics
        context["nodes"].append(node)
    elif geometry:
        # Several shapes: the one grouping worth keeping. The sub-assembly's
        # frame is the link frame, so every element keeps the offset the URDF
        # gave it.
        shape_origin = urdf_common.to_packed(IDENTITY)
        node = {
            "type": "assembly",
            "name": link_name,
            "link": link_name,
            "location": placement,
            "links": geometry,
        }
        if physics:
            node["physics"] = physics
        context["nodes"].append(node)

    if geometry:
        record_link(
            context,
            link_name,
            ancestor,
            urdf_common.round_packed(urdf_common.to_packed(relative), context["precision"]),
            shape_origin,
            physics,
            # A link of one shape has that shape's appearance; a link of several
            # has one per shape, and no single answer for the link as a whole.
            {key: geometry[0][key] for key in ("material", "color") if len(geometry) == 1 and key in geometry[0]},
        )
        # What is below this link is stated relative to it.
        child_ancestor, child_relative, chain = link_name, IDENTITY, []
    else:
        child_ancestor, child_relative, chain = ancestor, relative, list(context["joint_chain"])

    for joint_name, child_name in robot.child_map.get(link_name, []):
        joint = robot.joint_map[joint_name]
        count_joint(joint, context)
        origin = urdf_common.from_urdf_origin(joint.origin)
        saved = context["joint_chain"]
        context["joint_chain"] = chain + [joint_name]
        walk_link(
            robot,
            child_name,
            urdf_common.compose(child_relative, origin),
            urdf_common.compose(absolute, origin),
            context,
            visited,
            child_ancestor,
        )
        context["joint_chain"] = saved


def record_link(context, link_name, ancestor, placement, shape_origin, physics, appearance):
    """Note where a link ended up, for 'pc convert assembly -t assy'.

    This table is what comes back over the wire, not something that is written
    anywhere: the conversion reads it once to lay out the ASSY file, and after
    that the joint tree lives in that file's ``connect:`` sections.

    'shape_origin' is where the link's *item* sits relative to the link frame:
    the identity for a sub-assembly, and the single element's own offset for a
    link that collapsed into one part.
    """
    context["links"][link_name] = {
        "parent": ancestor,
        "origin": placement,
        "shape_origin": shape_origin,
        "physics": physics,
        "appearance": appearance,
        "joints": list(context["joint_chain"]),
    }


def count_joint(joint, context):
    """Count what a joint says that the assembly geometry cannot hold.

    Only the kinematics: an assembly is one static configuration, so a movable
    joint is shown at its zero position. The limits and the dynamics are *not*
    counted as lost - they become the ``motion:`` and ``physics:`` sections of
    the interface the joint turns into.
    """
    if joint.type != "fixed":
        context["dropped"].add("joint_kinematics")


#
# Parsing
#


def parse_robot(text, path):
    """Parse URDF text, refusing anything the parser does not recognize.

    urdf_parser_py reports an unknown tag or attribute by writing to its error
    sink and carrying on. That is exactly the case PartCAD wants to be loud
    about: an element it has never seen is a property that would be silently
    lost, so every one of them is collected and the import stops.

    ``<gazebo>`` does not come through here - the parser keeps those blocks as
    raw elements - so this only ever fires on *core* URDF, which is a closed
    vocabulary and can be treated as one. Gazebo's own vocabulary is open, and
    'gazebo_physics' handles it with its own rule.
    """
    from urdf_parser_py import xml_reflection
    from urdf_parser_py.urdf import URDF

    unknown = []
    previous = xml_reflection.core.on_error
    xml_reflection.core.on_error = unknown.append
    try:
        robot = URDF.from_xml_string(text)
    finally:
        xml_reflection.core.on_error = previous

    if unknown:
        raise ValueError(
            "%s contains URDF that PartCAD has no property for:\n  %s\n"
            "Every URDF value PartCAD keeps is copied into a named property; "
            "extend the tables in wrapper_import_urdf.py to support these." % (path, "\n  ".join(sorted(set(unknown))))
        )
    return robot


def gazebo_blocks(robot):
    """``<gazebo>`` elements keyed by the link or joint they reference.

    Kept as the parser's raw elements: their children are read one at a time
    into named PartCAD properties by 'gazebo_physics', not carried as XML.
    """
    blocks = {}
    for element in getattr(robot, "gazebos", None) or []:
        blocks.setdefault(element.get("reference"), []).append(element)
    return blocks


def unsupported(context, message):
    """Something in the URDF that PartCAD has no property for.

    Fatal under ``strict``, and reported otherwise. This is only reachable for
    ``<gazebo>`` content and for materials: core URDF is refused outright at
    parse time, because its vocabulary is closed and an unknown element there
    means PartCAD is out of date rather than the file being unusual.
    """
    if context["strict"]:
        raise ValueError(message)
    context["warnings"].append(message)


def process(request):
    urdf_file = request["urdf_file"]
    if not os.path.isfile(urdf_file):
        raise FileNotFoundError(urdf_file)

    warnings = []
    with open(urdf_file, "rb") as f:
        robot = parse_robot(f.read(), urdf_file)

    dropped = Dropped()
    dropped.add("transmission", len(getattr(robot, "transmissions", None) or []))

    # 'True' means "everywhere"; anything else is the set of link names for
    # which the visual geometry is preferred (an empty set by default).
    ignore_collision = request.get("ignoreCollision")
    if ignore_collision is not True:
        ignore_collision = frozenset(ignore_collision or ())

    context = {
        "urdf_dir": os.path.dirname(os.path.abspath(urdf_file)),
        "package_paths": list(request.get("package_paths") or []),
        "output_folder": request["output_folder"],
        "precision": request.get("precision", 6),
        "ignore_collision": ignore_collision,
        "strict": bool(request.get("strict", False)),
        "gazebo": gazebo_blocks(robot),
        "materials": {m.name: m for m in getattr(robot, "materials", None) or [] if getattr(m, "name", None)},
        "warnings": warnings,
        "dropped": dropped,
        "primitives": {},
        "written": set(),
        "nodes": [],
        "unplaced": [],
        "links": {},
        "reached": set(),
        "joint_chain": [],
    }

    try:
        root_name = robot.get_root()
    except AssertionError as e:
        # urdf_parser_py reports "no roots" and "multiple roots" as bare
        # assertions; both mean the joint tree is not a tree.
        raise ValueError("%s: %s" % (urdf_file, e)) from e

    walk_link(robot, root_name, IDENTITY, IDENTITY, context, frozenset(), None)
    if not context["nodes"]:
        raise ValueError("No geometry found in %s" % urdf_file)

    # Before the 'dropped' tally is taken: reading a joint is what notices the
    # Gazebo settings attached to it, and a calibration block.
    joints = {joint.name: joint_record(joint, context) for joint in robot.joints}

    # Every link is a child of the assembly, the robot's root link included -
    # see 'walk_link' for why the joint tree is not nesting. The assembly is the
    # container and holds nothing of its own: what a link says about itself is
    # carried by the part that link became, and is carried exactly once.
    root = {
        "type": "assembly",
        "name": root_name,
        "location": urdf_common.to_packed(IDENTITY),
        "links": context["nodes"],
        # Geometry that is defined but not placed: the visual shapes of a link
        # built from its collision geometry, and the other way round.
        "parts": context["unplaced"],
    }

    # A link no joint connects to the root is not part of the robot as far as
    # the kinematic tree is concerned, and is invisible in the result.
    orphaned = sorted(set(robot.link_map) - context["reached"])
    if orphaned:
        warnings.append("Ignoring links that no joint connects to '%s': %s" % (root_name, ", ".join(orphaned)))

    # A '<gazebo>' block that references neither a link nor a joint was never
    # looked at, so nothing above had the chance to report what it says. Most
    # often it is the robot-level block, which holds simulator plugins and the
    # settings of the model as a whole - and a PartCAD assembly has nowhere to
    # put those (see docs/source/simulation.rst, item 9).
    for reference, blocks in context["gazebo"].items():
        if reference in robot.link_map or reference in robot.joint_map:
            continue
        dropped.add("gazebo", len(blocks))
        unsupported(
            context,
            "The Gazebo block for '%s' is not attached to a link or a joint; PartCAD has nowhere to put it"
            % (reference or "the robot as a whole"),
        )

    return {
        "root": root,
        "robot_name": robot.name,
        "root_link": root_name,
        "links": context["links"],
        "joints": joints,
        "warnings": warnings,
        "dropped": dropped.summary(),
        "movable_joints": [{"name": joint.name, "type": joint.type} for joint in robot.joints if joint.type != "fixed"],
    }


if __name__ == "__main__":
    # argv[1] carries the operation name for readability in process listings; the
    # authoritative request travels via stdin.
    _, request = wrapper_common.handle_input()
    try:
        model = process(request)
        model["success"] = True
        model["exception"] = None
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "root": None}
    wrapper_common.handle_output(model)
