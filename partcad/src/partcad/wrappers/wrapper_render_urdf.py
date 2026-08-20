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

What the part states about itself wins over anything computed here: mass,
centre of mass, inertia, friction and the contact parameters are named PartCAD
properties, and this writes each of them back into the URDF element that states
it. Only a part that says nothing gets computed inertial properties, from its
solid and the configured density. A property PartCAD has and URDF has no
spelling for is reported rather than dropped in silence - see URDF_STATED.
"""

import math
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


def _bool_text(value):
    return "true" if value else "false"


# PartCAD property -> the Gazebo tag that states it, and how to write the text.
# The mirror image of wrapper_import_urdf.GAZEBO_LINK_PHYSICS, and to be kept
# that way: contact and friction are PartCAD properties, and '<gazebo>' is where
# a URDF states them. 'turnGravityOff' has no entry here because 'gravity' says
# the same thing and is not deprecated.
GAZEBO_LINK_PHYSICS = {
    "friction": ("mu1", repr),
    "friction2": ("mu2", repr),
    "frictionDirection": ("fdir1", lambda v: " ".join(repr(float(x)) for x in v)),
    "contactStiffness": ("kp", repr),
    "contactDamping": ("kd", repr),
    "minContactDepth": ("minDepth", lambda v: repr(v / urdf_common.MM_PER_M)),
    "maxContactVelocity": ("maxVel", lambda v: repr(v / urdf_common.MM_PER_M)),
    "restitution": ("bounce", repr),
    "maxContacts": ("maxContacts", lambda v: str(int(v))),
    "velocityDamping": ("dampingFactor", repr),
    "selfCollide": ("selfCollide", _bool_text),
    "gravity": ("gravity", _bool_text),
}

# Every part property this exporter has a URDF spelling for. A 'physics'
# property outside this set is one PartCAD supports and URDF does not: it is
# reported through the response and logged at info level, which is the mirror
# image of the import refusing URDF that PartCAD has no property for. When
# PartCAD grows a physical property, either give it a spelling above or let it
# be reported here - do not let it disappear quietly.
URDF_STATED = frozenset(("mass", "centerOfMass", "inertiaOrientation", "inertia")) | frozenset(GAZEBO_LINK_PHYSICS)


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


def inertial_of(placed, density, warnings, link_name):
    """The URDF ``<inertial>`` for a link's solids, or None when they have none.

    'placed' is the (shape, packed placement) pairs the link is made of - one for
    an ordinary link, several for a URDF link with more than one ``<visual>``.
    Each is put where it belongs before the moments are taken, so the result is
    about the link as a whole.

    OCCT's GProp_GProps.MatrixOfInertia() is already the tensor about the centre
    of mass, which is the frame URDF's ``<inertia>`` is stated in, so no
    parallel-axis shift is needed - only the units and the density. GProp
    integrates at unit density in the shape's own (millimetre) units, so the
    volume becomes a mass and the second moment (length^5) becomes kg.m^2.

    A link with no volume (a mesh imported as a shell, an empty compound) has no
    inertia to compute: it is reported and the link goes out without an
    ``<inertial>``, rather than carrying invented numbers.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from urdf_parser_py.urdf import Inertia, Inertial, Pose

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(combined(placed), props)
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


def combined(placed):
    """The (shape, placement) pairs as one shape, each put where it belongs."""
    if len(placed) == 1 and placed[0][1] is None:
        return placed[0][0]

    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for shape, placement in placed:
        builder.Add(compound, shape if placement is None else shape.Located(_toploc(placement)))
    return compound


def _toploc(packed):
    """The OCCT location for PartCAD's packed [[t], [axis], angle] form."""
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    translation, axis, angle = packed
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(axis[0], axis[1], axis[2])), math.radians(angle))
    trsf.SetTranslationPart(gp_Vec(translation[0], translation[1], translation[2]))
    return TopLoc_Location(trsf)


def carried_inertial(physics):
    """The ``<inertial>`` a part's own properties state, if it has them.

    A part carries mass, centre of mass and inertia as named PartCAD properties
    (see wrapper_import_urdf's tables for the full list and the units). Those
    are what the model's author meant - a measurement, or the number a
    simulation was tuned against - so they win over anything recomputed from the
    geometry and a guessed density.
    """
    from urdf_parser_py.urdf import Inertia, Inertial, Pose

    physics = physics or {}
    if "mass" not in physics and "inertia" not in physics:
        return None

    xyz = [v / urdf_common.MM_PER_M for v in physics.get("centerOfMass") or (0.0, 0.0, 0.0)]
    rpy = [math.radians(v) for v in physics.get("inertiaOrientation") or (0.0, 0.0, 0.0)]
    inertia = physics.get("inertia") or {}
    return Inertial(
        mass=float(physics.get("mass", 0.0)),
        origin=Pose(xyz=xyz, rpy=rpy),
        inertia=Inertia(**{key: float(inertia.get(key, 0.0)) for key in Inertia.KEYS}) if inertia else None,
    )


def carried_material(properties, state):
    """The ``<material>`` a part's own 'material'/'color' properties state."""
    from urdf_parser_py.urdf import Color, LinkMaterial

    name, color = properties.get("material"), properties.get("color")
    if not name and not color:
        return None
    built = LinkMaterial(name=sanitize_name(name or color, "material"))
    rgba = color_rgba(color, state) if color else None
    if rgba is not None:
        # 'Color' takes the components positionally, not by keyword.
        built.color = Color(rgba)
    return built


def color_rgba(text, state):
    """A PartCAD colour string as URDF's ``rgba``, or None if it is not one."""
    digits = str(text).lstrip("#")
    if len(digits) not in (6, 8):
        state["warnings"].append("Ignoring the colour '%s', which is not #RRGGBB or #RRGGBBAA" % text)
        return None
    try:
        values = [int(digits[i : i + 2], 16) / 255.0 for i in range(0, len(digits), 2)]
    except ValueError:
        state["warnings"].append("Ignoring the colour '%s', which is not #RRGGBB or #RRGGBBAA" % text)
        return None
    return [round(v, 6) for v in values] + ([1.0] if len(values) == 3 else [])


def gazebo_element(link_name, physics, state):
    """The ``<gazebo reference="...">`` block a link's physics needs, or None.

    The reverse of wrapper_import_urdf.GAZEBO_LINK_PHYSICS: contact and friction
    are PartCAD properties, and Gazebo is where a URDF states them.

    A property with no URDF spelling is reported rather than dropped in silence
    - see UNSUPPORTED. When one of them grows a URDF spelling, move it into a
    table here; do not let it disappear quietly.
    """
    from xml.etree import ElementTree

    element = None
    for name, (tag, write) in GAZEBO_LINK_PHYSICS.items():
        if name not in physics:
            continue
        if element is None:
            element = ElementTree.Element("gazebo", {"reference": link_name})
        child = ElementTree.SubElement(element, tag)
        child.text = write(physics[name])
    return element


def mesh_reference(shape, node, link_name, state):
    """Write 'shape' out as a mesh (or reuse one) and return the URDF reference.

    An identical shape used twice - the two bones of the PartCAD logo, a
    repeated fastener - shares one mesh file, the way a URDF written by hand
    would.
    """
    key = node.get(ocp_serialize.KEY_BREP)
    mesh_file = state["meshes"].get(key)
    if mesh_file is None:
        mesh_name = state["mesh_names"].take(node.get("label") or link_name, "mesh")
        mesh_file = "%s/%s.stl" % (state["mesh_dir_name"], mesh_name)
        write_mesh(shape, os.path.join(state["mesh_dir"], "%s.stl" % mesh_name), state["options"])
        state["meshes"][key] = mesh_file
    return state["mesh_prefix"] + mesh_file


def shape_elements(node, state):
    """The (shape node, placement) pairs one URDF link is built from.

    Usually a node is one shape and that is the whole of it. A sub-assembly
    whose children are named *under* it - "wrist" holding "wrist/1" and
    "wrist/2" - is one thing made of several shapes, and goes back out as one
    link with several ``<visual>`` elements rather than as a frame link with a
    link per shape.

    The slash is the whole of the rule, and it is the only hierarchy PartCAD
    encodes in a name. It needs nothing recorded anywhere: a URDF link with
    several ``<visual>`` elements is imported under exactly this convention, and
    an assembly that was never a URDF but uses it means the same thing by it.
    """
    if ocp_serialize.is_shape_object(node):
        return [(node, None)], []

    children = node.get(ocp_serialize.KEY_ASSEMBLY, [])
    prefix = (node.get("label") or "") + "/"
    if not prefix.strip("/"):
        return [], children

    def belongs(child):
        return ocp_serialize.is_shape_object(child) and (child.get("label") or "").startswith(prefix)

    own = [(child, child.get(ocp_serialize.KEY_LOCATION)) for child in children if belongs(child)]
    return own, [child for child in children if not belongs(child)]


def build_link(node, link_name, elements, state):
    """The URDF ``<link>`` for one node of the assembly tree."""
    from urdf_parser_py.urdf import Collision, Link, Mesh, Pose, Visual

    link = Link(name=link_name)
    physics = (state["properties"].get(node.get("name")) or {}).get("physics") or {}

    placed = []
    for shape_node, placement in elements:
        shape = node_geometry(shape_node)
        if shape is None:
            continue
        reference = mesh_reference(shape, shape_node, link_name, state)
        geometry = Mesh(filename=reference, scale=[MESH_SCALE, MESH_SCALE, MESH_SCALE])
        if placement is None:
            origin = None
        else:
            xyz, rpy = urdf_common.to_urdf_origin(urdf_common.from_packed(placement))
            origin = Pose(xyz=xyz, rpy=rpy)
        # The appearance belongs to the shape, not to the link: a link built
        # from several parts may well have a colour per part.
        material = carried_material(state["properties"].get(shape_node.get("name")) or {}, state)
        link.add_aggregate("visual", Visual(geometry=geometry, origin=origin, material=material))
        link.add_aggregate("collision", Collision(geometry=geometry, origin=origin))
        placed.append((shape, placement))

    if not placed:
        # A frame that carries children, with no geometry of its own. URDF has
        # no other way to express one.
        return link

    if state["options"]["inertial"]:
        link.inertial = carried_inertial(physics) or inertial_of(
            placed, state["options"]["density"], state["warnings"], link_name
        )
    gazebo = gazebo_element(link_name, physics, state)
    if gazebo is not None:
        state["gazebo"].append(gazebo)
    state["unsupported"].update(set(physics) - URDF_STATED)
    return link


def emit(node, parent_link, pose, state):
    """Add 'node' and its subtree to the robot, joined to 'parent_link'."""
    from urdf_parser_py.urdf import Joint, Pose

    link_name = state["names"].take(node.get("label") or node.get("name"), "link")
    elements, children = shape_elements(node, state)
    state["robot"].add_link(build_link(node, link_name, elements, state))

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

    for child in children:
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
        # Shape full name -> the properties its part declares ('physics',
        # 'material', 'color'). A part that came from a URDF states the link's
        # mass, inertia and friction here, and they go back out rather than
        # being recomputed.
        "properties": request.get("properties") or {},
        "gazebo": [],
        # PartCAD properties URDF has no spelling for, reported once at the end.
        "unsupported": set(),
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
        f.write(with_gazebo(state["robot"].to_xml_string(), state["gazebo"]))

    return {
        "success": True,
        "exception": None,
        "robot_name": robot_name,
        "mesh_dir": mesh_dir,
        "meshes": sorted(set(state["meshes"].values())),
        "warnings": warnings,
        # Properties PartCAD holds and URDF cannot state. Reported at info
        # level by the caller: nothing is wrong with the file, it just says
        # less than the package does.
        "unsupported": sorted(state["unsupported"]),
    }


def _world_link(state):
    from urdf_parser_py.urdf import Link

    return Link(name=state["names"].take("world", "world"))


def with_gazebo(xml, blocks):
    """Add the ``<gazebo>`` blocks to the serialized robot.

    They are inserted as text because urdf_parser_py serializes what it parsed,
    and it keeps ``<gazebo>`` as an opaque element it will not build. Each block
    here was *built* from named PartCAD properties, not carried through, so what
    lands in the file is a statement of what PartCAD holds.
    """
    if not blocks:
        return xml

    from xml.etree import ElementTree

    rendered = [ElementTree.tostring(block, encoding="unicode").rstrip() for block in blocks]
    closing = xml.rindex("</robot>")
    return xml[:closing] + "\n".join("  %s" % line for line in rendered) + "\n" + xml[closing:]


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
