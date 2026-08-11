#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Read a URDF file and return the plain-data assembly tree PartCAD builds from.

This runs inside the python sandbox, for two reasons. The URDF parser is ROS's
own 'urdf_parser_py' rather than an XML reader written here, and PartCAD does
not carry the ROS stack as a dependency; and turning URDF's primitive shapes
(box/cylinder/sphere) into geometry needs OCCT, which the core process never
loads. The core only receives plain data back.

The tree this returns is deliberately the same shape as the one
wrapper_import_assy produces from a STEP assembly, so both feed the very same
node handler and end up as the identical in-memory representation an ASSY file
produces:

    assembly node:  {"type": "assembly", "name", "location", "links": [...]}
    part node:      {"type": "part", "name", "location", "part_file",
                     "part_type", "scale"}

The mapping from URDF is:

  * The robot's root link *is* the assembly. Its children become the assembly's
    children, so a round trip through URDF does not accumulate a wrapper level.
  * Every other link becomes an assembly node placed at its joint's origin - at
    the joint's zero position, since a PartCAD assembly is a single static
    configuration and a joint is not something it can hold (see 'dropped').
  * Each ``<visual>`` (or ``<collision>``, when asked) becomes a part node
    placed at the visual's own origin. A link carrying exactly one visual and no
    child links collapses into that part node, so the common "one link, one
    mesh" case does not grow an assembly level around every mesh.
  * Everything URDF says that PartCAD's assembly representation has nowhere to
    put - mass, inertia, joint kinematics and limits, materials, sensors, the
    Gazebo extensions - is counted in 'dropped' and reported by the caller.
"""

import os
import sys

# Pinned before anything that may pull OCP: VTK bundles its own older expat
# under the standard XML_* names, and once that is loaded the standard library's
# pyexpat binds to it and dies with an undefined-symbol ImportError. lxml (which
# urdf_parser_py parses with) and OCP both reach it.
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

# What a URDF file may carry that the assembly representation cannot hold. Used
# to report the loss in one place instead of warning per element.
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


class Dropped(dict):
    """Counters for the URDF content that does not survive the import."""

    def __init__(self):
        super().__init__({key: 0 for key in DROPPABLE})

    def add(self, key, count=1):
        self[key] = self.get(key, 0) + count

    def summary(self):
        return {key: value for key, value in self.items() if value}


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


def make_primitive(geometry, kind, output_folder, name, cache):
    """Write a URDF primitive out as a STEP file and return its path.

    URDF's box, cylinder and sphere are all centred on the link origin, which is
    not where OCCT's primitive builders put them, so each is re-centred here.
    Identical primitives share one file - a URDF that repeats a shape (wheels,
    bolts) should not produce a file per link.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    mm = urdf_common.MM_PER_M
    if kind == "box":
        size = [float(v) * mm for v in geometry.size]
        key = ("box", tuple(size))
    elif kind == "cylinder":
        radius, length = float(geometry.radius) * mm, float(geometry.length) * mm
        key = ("cylinder", radius, length)
    else:
        radius = float(geometry.radius) * mm
        key = ("sphere", radius)

    if key in cache:
        return cache[key]

    if kind == "box":
        shape = BRepPrimAPI_MakeBox(
            gp_Pnt(-size[0] / 2.0, -size[1] / 2.0, -size[2] / 2.0), size[0], size[1], size[2]
        ).Shape()
    elif kind == "cylinder":
        shape = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, -length / 2.0), gp_Dir(0, 0, 1)), radius, length).Shape()
    else:
        shape = BRepPrimAPI_MakeSphere(radius).Shape()

    os.makedirs(output_folder, exist_ok=True)
    path = os.path.join(output_folder, "%s.step" % name)
    suffix = 1
    while path in cache.values():
        path = os.path.join(output_folder, "%s_%d.step" % (name, suffix))
        suffix += 1

    writer = STEPControl_Writer()
    if writer.Transfer(shape, STEPControl_AsIs) != 1 or writer.Write(path) != 1:
        raise ValueError("Failed to write the STEP file for a URDF primitive: %s" % path)

    cache[key] = path
    return path


def geometry_node(element, name, context):
    """A part node for one ``<visual>``/``<collision>``, or None if unreadable."""
    geometry = getattr(element, "geometry", None)
    if geometry is None:
        return None

    kind = type(geometry).__name__.lower()
    location = urdf_common.to_packed(urdf_common.from_urdf_origin(getattr(element, "origin", None)))
    node = {
        "type": "part",
        "name": name,
        "location": urdf_common.round_packed(location, context["precision"]),
        "scale": 1.0,
    }

    if kind == "mesh":
        path = resolve_mesh_path(geometry.filename, context["urdf_dir"], context["package_paths"])
        if path is None or not os.path.isfile(path):
            context["warnings"].append("Mesh file not found for link '%s': %s" % (name, geometry.filename))
            return None
        extension = os.path.splitext(path)[1].lower()
        part_type = MESH_PART_TYPES.get(extension)
        if part_type is None:
            context["warnings"].append(
                "Link '%s' uses the mesh format '%s', which PartCAD cannot read; skipping it"
                % (name, extension or "<none>")
            )
            return None
        node["part_file"] = os.path.abspath(path)
        node["part_type"] = part_type
        node["scale"] = mesh_scale_factor(geometry, context["warnings"])
        return node

    if kind in ("box", "cylinder", "sphere"):
        node["part_file"] = make_primitive(
            geometry, kind, context["output_folder"], name, context["primitive_cache"]
        )
        node["part_type"] = "step"
        return node

    context["warnings"].append("Link '%s' uses an unsupported geometry type '%s'" % (name, kind))
    return None


def link_geometry_nodes(link, context):
    """Part nodes for a link's visuals (or collisions), named after the link.

    The other kind is counted as dropped: a URDF states visual and collision
    geometry separately and PartCAD's assembly holds one shape per part, so
    whichever kind was not chosen is lost.
    """
    preferred = context["geometry"]
    elements = list(link.visuals if preferred == "visual" else link.collisions)
    other = list(link.collisions if preferred == "visual" else link.visuals)
    if not elements and other:
        # The link only has the other kind. Using it beats dropping the link.
        context["warnings"].append(
            "Link '%s' has no %s geometry; using its %s geometry instead"
            % (link.name, preferred, "collision" if preferred == "visual" else "visual")
        )
        elements, other = other, []
    context["dropped"].add("collision" if preferred == "visual" else "visual", len(other))

    nodes = []
    for index, element in enumerate(elements):
        name = link.name if len(elements) == 1 else "%s_%s%d" % (link.name, preferred, index + 1)
        node = geometry_node(element, name, context)
        if node is not None:
            nodes.append(node)
        if getattr(element, "material", None) is not None:
            context["dropped"].add("material")
    return nodes


def link_node(robot, link_name, pose, context, visited, reached):
    """The node for a link and everything below it, placed at 'pose'.

    'pose' is the link's placement relative to its parent link, already in
    PartCAD's units. Returns None for a link that contributes nothing - no
    geometry anywhere beneath it - so an empty frame link does not become an
    empty assembly. 'reached' collects every link the walk visits, so the caller
    can report the ones no joint connects.
    """
    if link_name in visited:
        context["warnings"].append("Ignoring a cycle in the URDF joint tree at link '%s'" % link_name)
        return None
    visited = visited | {link_name}

    link = robot.link_map.get(link_name)
    if link is None:
        context["warnings"].append("Joint refers to the unknown link '%s'" % link_name)
        return None
    reached.add(link_name)

    if getattr(link, "inertial", None) is not None:
        context["dropped"].add("inertial")

    geometry_nodes = link_geometry_nodes(link, context)

    children = []
    for joint_name, child_name in robot.child_map.get(link_name, []):
        joint = robot.joint_map[joint_name]
        _count_joint(joint, context)
        child = link_node(
            robot, child_name, urdf_common.from_urdf_origin(joint.origin), context, visited, reached
        )
        if child is not None:
            children.append(child)

    if not geometry_nodes and not children:
        return None

    # A link that is one piece of geometry and nothing else becomes that part
    # directly: the part's location absorbs the link's own placement, so a round
    # trip through URDF reproduces the tree it started from.
    if len(geometry_nodes) == 1 and not children:
        node = geometry_nodes[0]
        node["location"] = urdf_common.round_packed(
            urdf_common.to_packed(urdf_common.compose(pose, urdf_common.from_packed(node["location"]))),
            context["precision"],
        )
        return node

    return {
        "type": "assembly",
        "name": link_name,
        "location": urdf_common.round_packed(urdf_common.to_packed(pose), context["precision"]),
        "links": geometry_nodes + children,
    }


def _count_joint(joint, context):
    """Count what a joint says that the assembly representation cannot hold."""
    dropped = context["dropped"]
    if joint.type != "fixed":
        # A movable joint is flattened to its zero position: the axis, the type
        # and everything that follows from them are gone.
        dropped.add("joint_kinematics")
        context["joints"].append({"name": joint.name, "type": joint.type})
    if getattr(joint, "limit", None) is not None:
        dropped.add("joint_limits")
    if getattr(joint, "dynamics", None) is not None:
        dropped.add("joint_dynamics")


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

    context = {
        "urdf_dir": os.path.dirname(os.path.abspath(urdf_file)),
        "package_paths": list(request.get("package_paths") or []),
        "output_folder": request["output_folder"],
        "precision": request.get("precision", 6),
        "geometry": "collision" if request.get("geometry") == "collision" else "visual",
        "primitive_cache": {},
        "warnings": warnings,
        "dropped": dropped,
        "joints": [],
    }

    try:
        root_name = robot.get_root()
    except AssertionError as e:
        # urdf_parser_py reports "no roots" and "multiple roots" as bare
        # assertions; both mean the joint tree is not a tree.
        raise ValueError("%s: %s" % (urdf_file, e)) from e

    reached = set()
    root = link_node(robot, root_name, (urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T), context, frozenset(), reached)
    if root is None:
        raise ValueError("No geometry found in %s" % urdf_file)

    # A link no joint connects to the root is not part of the robot as far as
    # the kinematic tree is concerned, and is invisible in the result.
    orphaned = sorted(set(robot.link_map) - reached)
    if orphaned:
        warnings.append("Ignoring links that no joint connects to '%s': %s" % (root_name, ", ".join(orphaned)))

    # The robot's root link is the assembly itself. When it collapsed into a
    # single part node (a one-link robot), wrap it so the caller always gets the
    # same "assembly with links" shape back.
    if root["type"] != "assembly":
        root = {
            "type": "assembly",
            "name": root_name,
            "location": urdf_common.to_packed((urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T)),
            "links": [root],
        }

    return {
        "root": root,
        "robot_name": robot.name,
        "root_link": root_name,
        "warnings": warnings,
        "dropped": dropped.summary(),
        "movable_joints": context["joints"],
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
