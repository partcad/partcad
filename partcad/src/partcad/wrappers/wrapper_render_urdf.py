#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Export a PartCAD shape or assembly as a URDF file plus its mesh files.

Unlike the other exporters, this one is handed the assembly *tree* rather than
the compound it decodes to (see wrapper_common.handle_input's 'decode' flag):
URDF is a tree of links joined by joints, and one link per node is exactly what
makes the export reversible. Each node becomes a link, each parent/child edge a
fixed joint carrying that child's placement, and each node that has geometry
gets a mesh written next to the URDF and referenced from its ``<visual>`` and
``<collision>``.

The URDF is built with ROS's own 'urdf_parser_py' and serialized by it, so what
lands on disk is what the ROS toolchain itself would write and reads back
through the very same parser.

Two conventions are worth stating, because they are what makes the round trip
close:

  * Meshes are written in millimetres - the unit PartCAD uses everywhere, and
    the unit its STL exporter already writes - and referenced with
    ``scale="0.001 0.001 0.001"``, which is how URDF says "these coordinates are
    millimetres". Joint origins are in metres and radians, as URDF requires.
  * Geometry is written in its own frame and placed by the joint above it, so
    the ``<visual>`` origin stays at identity. A shape that appears more than
    once in the assembly is written once and referenced by every link that uses
    it, the way a URDF written by hand would.

Inertial properties are computed from the solid where there is one, using the
configured density. They are a derived convenience, not something PartCAD
stores: see the URDF section of docs/source/design.rst.
"""

import os
import re
import sys

# Pinned before anything that may pull OCP - see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize  # noqa: E402
import urdf_common  # noqa: E402
import wrapper_common  # noqa: E402

# Metres per millimetre, for the mesh 'scale' attribute: the meshes are written
# in millimetres and URDF reads mesh coordinates as metres after scaling.
MESH_SCALE = 1.0 / urdf_common.MM_PER_M

# Density used to turn a volume into a mass when the caller does not name one,
# in kg/m^3. Aluminium: a middle-of-the-road value for a machined part, and one
# whose provenance is obvious in the output rather than looking like a
# measurement.
DEFAULT_DENSITY = 2700.0

# mm^5 -> m^5. The second moment OCCT integrates has units of length^5, so this
# is what converts it once the density (kg/m^3) is applied.
MM5_TO_M5 = 1e-15
# mm^3 -> m^3.
MM3_TO_M3 = 1e-9

# URDF link and joint names end up as XML attributes and as ROS graph names, so
# anything outside this set is replaced.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_name(name, fallback):
    """A URDF-safe name derived from a PartCAD name.

    PartCAD names carry package paths and ':' separators ("//pub/examples:logo"),
    none of which belong in a ROS name.
    """
    name = _UNSAFE_NAME.sub("_", str(name or "")).strip("_")
    return name or fallback


class NameAllocator:
    """Hands out unique link names, since URDF requires them to be unique."""

    def __init__(self):
        self.used = set()

    def take(self, name, fallback="link"):
        base = sanitize_name(name, fallback)
        candidate = base
        suffix = 1
        while candidate in self.used:
            candidate = "%s_%d" % (base, suffix)
            suffix += 1
        self.used.add(candidate)
        return candidate


def node_geometry(node):
    """The node's own shape as a live TopoDS_Shape, in its own frame, or None.

    The placement carried by the node is deliberately left off: it becomes the
    origin of the joint above the link, not part of the geometry.
    """
    if not ocp_serialize.is_shape_object(node):
        return None
    without_placement = {key: value for key, value in node.items() if key != ocp_serialize.KEY_LOCATION}
    return ocp_serialize.decode_shape(without_placement)


def write_mesh(shape, path, options):
    """Triangulate 'shape' and write it out as an STL file."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer

    BRepMesh_IncrementalMesh(
        shape,
        theLinDeflection=options["tolerance"],
        isRelative=True,
        theAngDeflection=options["angularTolerance"],
        isInParallel=True,
    )
    writer = StlAPI_Writer()
    writer.ASCIIMode = options["ascii"]
    if not writer.Write(shape, path) or not os.path.exists(path) or os.path.getsize(path) == 0:
        raise Exception("Failed to write the mesh file: %s" % path)


def inertial_of(shape, density, warnings, link_name):
    """The URDF ``<inertial>`` for a solid, or None when it has no volume.

    OCCT's GProp_GProps.MatrixOfInertia() is already the tensor about the centre
    of mass, which is the frame URDF's ``<inertia>`` is stated in, so no
    parallel-axis shift is needed - only the units and the density. GProp
    integrates at unit density in the shape's own (millimetre) units, so the
    volume becomes a mass and the second moment (length^5) becomes kg.m^2.

    A shape with no volume (a mesh imported as a shell, an empty compound) has
    no inertia to compute: it is reported and the link goes out without an
    ``<inertial>``, rather than carrying invented numbers.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from urdf_parser_py.urdf import Inertia, Inertial, Pose

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    volume = props.Mass()
    if volume <= 0.0:
        warnings.append(
            "Link '%s' has no computable volume (an open shell or a mesh), so it carries no <inertial>" % link_name
        )
        return None

    com = props.CentreOfMass()
    centre = (com.X(), com.Y(), com.Z())
    matrix = props.MatrixOfInertia()
    # Row/column indices in OCCT's gp_Mat are 1-based.
    inertia = [[matrix.Value(row, col) for col in (1, 2, 3)] for row in (1, 2, 3)]

    mass = volume * MM3_TO_M3 * density
    factor = density * MM5_TO_M5
    return Inertial(
        mass=mass,
        origin=Pose(xyz=[v * MESH_SCALE for v in centre], rpy=[0.0, 0.0, 0.0]),
        inertia=Inertia(
            ixx=inertia[0][0] * factor,
            ixy=inertia[0][1] * factor,
            ixz=inertia[0][2] * factor,
            iyy=inertia[1][1] * factor,
            iyz=inertia[1][2] * factor,
            izz=inertia[2][2] * factor,
        ),
    )


def build_link(node, link_name, state):
    """The URDF ``<link>`` for one node of the assembly tree."""
    from urdf_parser_py.urdf import Collision, Link, Mesh, Visual

    link = Link(name=link_name)

    shape = node_geometry(node)
    if shape is None:
        # A sub-assembly: a frame that carries children, with no geometry of its
        # own. URDF has no other way to express one.
        return link

    # An identical shape used twice (the two bones of the PartCAD logo, a
    # repeated fastener) shares one mesh file.
    key = node.get(ocp_serialize.KEY_BREP)
    mesh_file = state["meshes"].get(key)
    if mesh_file is None:
        mesh_name = state["mesh_names"].take(link_name, "mesh")
        mesh_file = "%s/%s.stl" % (state["mesh_dir_name"], mesh_name)
        write_mesh(shape, os.path.join(state["mesh_dir"], "%s.stl" % mesh_name), state["options"])
        state["meshes"][key] = mesh_file

    reference = state["mesh_prefix"] + mesh_file
    scale = [MESH_SCALE, MESH_SCALE, MESH_SCALE]
    link.visual = Visual(geometry=Mesh(filename=reference, scale=scale))
    link.collision = Collision(geometry=Mesh(filename=reference, scale=scale))
    if state["options"]["inertial"]:
        link.inertial = inertial_of(shape, state["options"]["density"], state["warnings"], link_name)
    return link


def emit(node, parent_link, pose, state):
    """Add 'node' and its subtree to the robot, joined to 'parent_link'."""
    from urdf_parser_py.urdf import Joint, Pose

    link_name = state["names"].take(node.get("label") or node.get("name"), "link")
    state["robot"].add_link(build_link(node, link_name, state))

    if parent_link is not None:
        xyz, rpy = urdf_common.to_urdf_origin(pose)
        state["robot"].add_joint(
            Joint(
                name="%s_to_%s" % (parent_link, link_name),
                parent=parent_link,
                child=link_name,
                joint_type="fixed",
                origin=Pose(xyz=xyz, rpy=rpy),
            )
        )

    for child in node.get(ocp_serialize.KEY_ASSEMBLY, []):
        emit(child, link_name, urdf_common.from_packed(child.get(ocp_serialize.KEY_LOCATION)), state)


def process(path, request):
    from urdf_parser_py.urdf import URDF

    root = request["wrapped"]
    if not isinstance(root, dict) or not (
        ocp_serialize.is_shape_object(root) or ocp_serialize.is_assembly_object(root)
    ):
        raise ValueError("The URDF exporter needs a shape or an assembly to export")

    urdf_dir = os.path.dirname(os.path.abspath(path)) or "."
    stem = os.path.splitext(os.path.basename(path))[0] or "robot"
    robot_name = sanitize_name(request.get("robot_name") or root.get("label") or stem, stem)
    mesh_dir_name = request.get("mesh_dir") or "%s_meshes" % stem
    mesh_dir = os.path.join(urdf_dir, mesh_dir_name)
    os.makedirs(mesh_dir, exist_ok=True)

    warnings = []
    state = {
        "robot": URDF(name=robot_name),
        "names": NameAllocator(),
        "mesh_names": NameAllocator(),
        "meshes": {},
        "mesh_dir": mesh_dir,
        "mesh_dir_name": mesh_dir_name,
        # Empty by default, which makes the reference relative to the URDF file
        # itself - what a standalone URDF wants. A ROS package sets this to
        # "package://<pkg>/" so the meshes resolve through the ROS package path.
        "mesh_prefix": request.get("mesh_prefix") or "",
        "options": {
            "tolerance": request.get("tolerance", 0.1),
            "angularTolerance": request.get("angularTolerance", 0.1),
            "ascii": request.get("ascii", False),
            "inertial": request.get("inertial", True),
            "density": request.get("density") or DEFAULT_DENSITY,
        },
        "warnings": warnings,
    }

    root_pose = urdf_common.from_packed(root.get(ocp_serialize.KEY_LOCATION))
    if urdf_common.is_identity(root_pose):
        emit(root, None, root_pose, state)
    else:
        # The exported object is itself placed somewhere. URDF has exactly one
        # root link and no way to put it anywhere but the origin, so the
        # placement becomes a joint from a 'world' link above it.
        world = _world_link(state)
        state["robot"].add_link(world)
        emit(root, world.name, root_pose, state)

    with open(path, "w", encoding="utf-8") as f:
        f.write(state["robot"].to_xml_string())

    return {
        "success": True,
        "exception": None,
        "robot_name": robot_name,
        "mesh_dir": mesh_dir,
        "meshes": sorted(set(state["meshes"].values())),
        "warnings": warnings,
    }


def _world_link(state):
    from urdf_parser_py.urdf import Link

    return Link(name=state["names"].take("world", "world"))


if __name__ == "__main__":
    # 'decode=False': the assembly tree is what is being exported, and decoding
    # would flatten it into a single compound.
    path, request = wrapper_common.handle_input(decode=False)
    try:
        response = process(path, request)
    except Exception as e:
        wrapper_common.handle_exception(e)
        response = {"success": False, "exception": str(e)}
    wrapper_common.handle_output(response)
