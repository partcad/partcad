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

# What a URDF file may carry that the assembly representation cannot hold as
# geometry. The counters are reported rather than the loss being passed over in
# silence; what can be kept verbatim goes into the 'physics' section.
DROPPABLE = (
    "inertial",
    "material",
    "joint_kinematics",
    "joint_limits",
    "joint_dynamics",
    "collision",
    "visual",
    "transmission",
    "gazebo",
    "sensor",
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
            "Non-uniform mesh scale %s is not representable in PartCAD; using the X component %g"
            % (values, values[0])
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
# Descriptors, for the opaque 'physics' section
#


def element_to_string(element):
    """Serialize an XML element back to text.

    urdf_parser_py parses with lxml when it is importable and with the standard
    library's ElementTree otherwise, and hands raw elements straight through -
    so which of the two this gets is not ours to decide.
    """
    if (type(element).__module__ or "").startswith("lxml"):
        from lxml import etree

        return etree.tostring(element, encoding="unicode")

    from xml.etree import ElementTree

    return ElementTree.tostring(element, encoding="unicode")


def pose_descriptor(origin):
    return {
        "xyz": [float(v) for v in (getattr(origin, "xyz", None) or (0.0, 0.0, 0.0))],
        "rpy": [float(v) for v in (getattr(origin, "rpy", None) or (0.0, 0.0, 0.0))],
    }


def material_descriptor(material):
    descriptor = {"name": getattr(material, "name", None)}
    color = getattr(material, "color", None)
    if color is not None and getattr(color, "rgba", None) is not None:
        descriptor["rgba"] = [float(v) for v in color.rgba]
    texture = getattr(material, "texture", None)
    if texture is not None:
        descriptor["texture"] = texture.filename
    return descriptor


def geometry_descriptor(element):
    """A URDF ``<visual>``/``<collision>`` as plain data, kept verbatim.

    Both the geometry the shapes were built from and the geometry that was not
    are recorded, so that an export back to URDF can restore what PartCAD does
    not model rather than let it silently disappear.
    """
    geometry = getattr(element, "geometry", None)
    if geometry is None:
        return None

    descriptor = {"origin": pose_descriptor(getattr(element, "origin", None))}
    if getattr(element, "name", None):
        descriptor["name"] = element.name

    kind = type(geometry).__name__.lower()
    if kind == "mesh":
        descriptor["mesh"] = {
            "filename": geometry.filename,
            "scale": [float(v) for v in geometry.scale] if getattr(geometry, "scale", None) else None,
        }
    elif kind == "box":
        descriptor["box"] = {"size": [float(v) for v in geometry.size]}
    elif kind == "cylinder":
        descriptor["cylinder"] = {"radius": float(geometry.radius), "length": float(geometry.length)}
    elif kind == "sphere":
        descriptor["sphere"] = {"radius": float(geometry.radius)}
    else:
        descriptor["unknown"] = kind

    material = getattr(element, "material", None)
    if material is not None:
        descriptor["material"] = material_descriptor(material)
    return descriptor


def inertial_descriptor(inertial):
    inertia = getattr(inertial, "inertia", None)
    descriptor = {
        "origin": pose_descriptor(getattr(inertial, "origin", None)),
        "mass": float(getattr(inertial, "mass", 0.0) or 0.0),
    }
    if inertia is not None:
        descriptor["inertia"] = {key: float(getattr(inertia, key, 0.0) or 0.0) for key in inertia.KEYS}
    return descriptor


def joint_descriptor(joint):
    """A URDF joint as plain data - everything about it, for the ASSY conversion."""
    descriptor = {
        "name": joint.name,
        "type": joint.type,
        "parent": joint.parent,
        "child": joint.child,
        "origin": pose_descriptor(getattr(joint, "origin", None)),
    }
    if getattr(joint, "axis", None) is not None:
        descriptor["axis"] = [float(v) for v in joint.axis]
    for section, keys in (
        ("limit", ("lower", "upper", "effort", "velocity")),
        ("dynamics", ("damping", "friction")),
        ("mimic", ("joint", "multiplier", "offset")),
        ("safety_controller", ("soft_lower_limit", "soft_upper_limit", "k_position", "k_velocity")),
        ("calibration", ("rising", "falling")),
    ):
        value = getattr(joint, section, None)
        if value is None:
            continue
        contents = {}
        for key in keys:
            item = getattr(value, key, None)
            if item is not None:
                contents[key] = float(item) if isinstance(item, (int, float)) else item
        if contents:
            descriptor[section] = contents
    return descriptor


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


def link_geometry(link, parent, context):
    """(part nodes, physics) for a link's geometry."""
    chosen, other, kind = choose_geometry(link, context)
    context["dropped"].add("collision" if kind == "visual" else "visual", len(other))

    # Which URDF link these properties belong to, and which link it hung off.
    # PartCAD renames things - its own names carry package paths, and a link of
    # several shapes becomes a sub-assembly of parts named after its elements -
    # so the link's own name is worth keeping: the export uses it to tell a
    # link's shapes apart, a reader of the configuration can see where a part
    # came from, and 'parent' is what a future exporter would need to put the
    # joint tree back (see docs/source/simulation.rst).
    physics = {"link": link.name}
    if parent is not None:
        physics["parent"] = parent
    if getattr(link, "inertial", None) is not None:
        context["dropped"].add("inertial")
        physics["inertial"] = inertial_descriptor(link.inertial)
    used = [geometry_descriptor(element) for element in chosen]
    if any(used):
        physics[kind] = [descriptor for descriptor in used if descriptor is not None]
    if other:
        left = [geometry_descriptor(element) for element in other]
        physics["collision" if kind == "visual" else "visual"] = [d for d in left if d is not None]
    for element in chosen:
        if getattr(element, "material", None) is not None:
            context["dropped"].add("material")
    gazebo = context["gazebo"].get(link.name)
    if gazebo:
        physics["gazebo"] = gazebo

    nodes = []
    for index, element in enumerate(chosen):
        name = element_node_name(element, index, len(chosen), link.name)
        node = geometry_node(element, name, link.name, context)
        if node is not None:
            nodes.append(node)
    return nodes, {"urdf": physics}


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

    geometry, physics = link_geometry(link, ancestor, context)
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
        node["physics"] = physics
        context["nodes"].append(node)
    elif geometry:
        # Several shapes: the one grouping worth keeping. The sub-assembly's
        # frame is the link frame, so every element keeps the offset the URDF
        # gave it.
        shape_origin = urdf_common.to_packed(IDENTITY)
        context["nodes"].append(
            {
                "type": "assembly",
                "name": link_name,
                "link": link_name,
                "location": placement,
                "physics": physics,
                "links": geometry,
            }
        )

    if geometry:
        record_link(
            context,
            link_name,
            ancestor,
            urdf_common.round_packed(urdf_common.to_packed(relative), context["precision"]),
            shape_origin,
            physics,
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


def record_link(context, link_name, ancestor, placement, shape_origin, physics):
    """Note where a link ended up, for 'pc convert assembly -t assy'.

    'shape_origin' is where the link's *item* sits relative to the link frame:
    the identity for a sub-assembly, and the single element's own offset for a
    link that collapsed into one part. 'physics' travels here too: the
    conversion writes one part per link, and the link is what the properties
    belong to whether or not they also ended up on a part of the tree.
    """
    context["links"][link_name] = {
        "parent": ancestor,
        "origin": placement,
        "shape_origin": shape_origin,
        "physics": physics,
        "joints": list(context["joint_chain"]),
    }


def count_joint(joint, context):
    """Count what a joint says that the assembly geometry cannot hold."""
    dropped = context["dropped"]
    if joint.type != "fixed":
        # A movable joint is flattened to its zero position: the axis, the type
        # and everything that follows from them are gone from the geometry.
        dropped.add("joint_kinematics")
    if getattr(joint, "limit", None) is not None:
        dropped.add("joint_limits")
    if getattr(joint, "dynamics", None) is not None:
        dropped.add("joint_dynamics")


#
# Parsing
#


def parse_robot(text, warnings):
    """Parse URDF text, collecting the parser's own complaints as warnings.

    urdf_parser_py reports an unknown tag or attribute by writing to stderr and
    carrying on. The core treats anything a wrapper writes to stderr as a fatal
    error, and a '<gazebo>' block - which every simulation-ready URDF has - would
    trip that on every import. So the parser's error sink is redirected into the
    warning list the response carries back.
    """
    from urdf_parser_py import xml_reflection
    from urdf_parser_py.urdf import URDF

    previous = xml_reflection.core.on_error
    xml_reflection.core.on_error = warnings.append
    try:
        return URDF.from_xml_string(text)
    finally:
        xml_reflection.core.on_error = previous


def gazebo_blocks(robot, warnings):
    """``<gazebo>`` blocks as raw XML, keyed by the link or joint they reference.

    urdf_parser_py keeps them as raw elements, which is exactly what is wanted:
    PartCAD does not model Gazebo extensions, it carries them.
    """
    blocks = {}
    for element in getattr(robot, "gazebos", None) or []:
        reference = element.get("reference")
        try:
            xml = element_to_string(element).strip()
        except Exception as e:  # pragma: no cover - an element neither library produced
            warnings.append("Could not keep the Gazebo block for '%s': %s" % (reference, e))
            continue
        blocks.setdefault(reference, []).append(xml)
    return blocks


def process(request):
    urdf_file = request["urdf_file"]
    if not os.path.isfile(urdf_file):
        raise FileNotFoundError(urdf_file)

    warnings = []
    with open(urdf_file, "rb") as f:
        robot = parse_robot(f.read(), warnings)

    dropped = Dropped()
    dropped.add("transmission", len(getattr(robot, "transmissions", None) or []))
    dropped.add("gazebo", len(getattr(robot, "gazebos", None) or []))
    dropped.add("material", len(getattr(robot, "materials", None) or []))

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
        "gazebo": gazebo_blocks(robot, warnings),
        "warnings": warnings,
        "dropped": dropped,
        "primitives": {},
        "written": set(),
        "nodes": [],
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

    # The robot's root link is the assembly itself, and every link is one of its
    # children - see 'walk_link' for why the joint tree is not nesting. What the
    # root link said about itself belongs to the assembly, since there is no
    # node above it to hold it.
    root = {
        "type": "assembly",
        "name": root_name,
        "link": root_name,
        "location": urdf_common.to_packed(IDENTITY),
        "physics": (context["links"].get(root_name) or {}).get("physics") or {},
        "links": context["nodes"],
    }

    # A link no joint connects to the root is not part of the robot as far as
    # the kinematic tree is concerned, and is invisible in the result.
    orphaned = sorted(set(robot.link_map) - context["reached"])
    if orphaned:
        warnings.append("Ignoring links that no joint connects to '%s': %s" % (root_name, ", ".join(orphaned)))

    return {
        "root": root,
        "robot_name": robot.name,
        "root_link": root_name,
        "links": context["links"],
        "joints": {joint.name: joint_descriptor(joint) for joint in robot.joints},
        "warnings": warnings,
        "dropped": dropped.summary(),
        "movable_joints": [
            {"name": joint.name, "type": joint.type} for joint in robot.joints if joint.type != "fixed"
        ],
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
