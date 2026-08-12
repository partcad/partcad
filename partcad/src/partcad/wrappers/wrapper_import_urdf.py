#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Read a URDF file and return the plain data PartCAD builds an assembly from.

This runs inside the python sandbox, for two reasons. The URDF parser is ROS's
own 'urdf_parser_py' rather than an XML reader written here, and PartCAD does
not carry the ROS stack as a dependency; and turning URDF's geometry into shapes
needs OCCT, which the core process never loads. The core only receives plain
data back.

**One part per link.** Whatever geometry a link carries - one mesh, several
meshes, primitives, or a mix - becomes a single shape expressed in the *link
frame*, so the part PartCAD registers for a link is addressable as
``<assembly>/<link>`` and lines up with the link's own coordinate system. A link
that is one mesh at the identity origin references that mesh file directly;
anything else is combined here and written out as a BREP file.

The tree this returns has the same node shape wrapper_import_assy produces from
a STEP assembly, so both feed the same node handler and end up as the identical
in-memory representation an ASSY file produces:

    assembly node:  {"type": "assembly", "name", "location", "links": [...]}
    part node:      {"type": "part", "name", "location", "part_file",
                     "part_type", "scale", "physics"}

Alongside the tree, the response carries the flat ``links`` and ``joints``
tables that ``pc convert assembly -t assy`` needs to write an ASSY file, its
parts and the interfaces its joints turn into.
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
}

# What a URDF file may carry that the assembly representation cannot hold as
# geometry. The counters are reported rather than the loss being passed over in
# silence; what can be kept verbatim goes into the part's 'physics' section.
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
# Geometry
#


def _trsf(pose):
    """The gp_Trsf for a (quaternion, translation) pose."""
    from OCP.gp import gp_Quaternion, gp_Trsf, gp_Vec

    q, t = pose
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Quaternion(q[1], q[2], q[3], q[0]))
    trsf.SetTranslationPart(gp_Vec(t[0], t[1], t[2]))
    return trsf


def _transformed(shape, trsf):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def _scaled(shape, factor):
    from OCP.gp import gp_Pnt, gp_Trsf

    if abs(factor - 1.0) < 1e-12:
        return shape
    trsf = gp_Trsf()
    trsf.SetScale(gp_Pnt(), factor)
    return _transformed(shape, trsf)


def compound_of(shapes):
    from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound

    builder = TopoDS_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for shape in shapes:
        if shape is not None and not shape.IsNull():
            builder.Add(compound, shape)
    return compound


def primitive_shape(geometry, kind):
    """A URDF box/cylinder/sphere as a solid, in millimetres.

    All three are centred on the link origin in URDF, which is not where OCCT's
    primitive builders put them, so each is re-centred here.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    mm = urdf_common.MM_PER_M
    if kind == "box":
        x, y, z = (float(v) * mm for v in geometry.size)
        return BRepPrimAPI_MakeBox(gp_Pnt(-x / 2.0, -y / 2.0, -z / 2.0), x, y, z).Shape()
    if kind == "cylinder":
        radius, length = float(geometry.radius) * mm, float(geometry.length) * mm
        return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, -length / 2.0), gp_Dir(0, 0, 1)), radius, length).Shape()
    return BRepPrimAPI_MakeSphere(float(geometry.radius) * mm).Shape()


def read_mesh_file(path, part_type):
    """Read a mesh/CAD file into a TopoDS_Shape.

    Only reached when a link's geometry has to be combined into one shape; a
    link that is a single mesh at the identity origin references its file
    directly and never comes through here.
    """
    if part_type == "stl":
        # Read exactly the way the 'stl' part factory does, build123d's Mesher
        # first: it turns the triangles into real faces, while the OCCT reader
        # below yields one face that carries a triangulation and no surface.
        # That distinction matters downstream - a surface-less face takes the
        # SVG renderer down - so the fallback is only for a sandbox without
        # build123d.
        try:
            import build123d as b3d

            return b3d.Mesher().read(path)[0].wrapped
        except Exception:
            pass

        from OCP.BRep import BRep_Builder
        from OCP.RWStl import RWStl
        from OCP.TopoDS import TopoDS_Face, TopoDS_Shell, TopoDS_Solid

        triangulation = RWStl.ReadFile_s(os.fsdecode(path))
        if not triangulation:
            raise ValueError("Failed to read the STL file: %s" % path)
        builder = BRep_Builder()
        face = TopoDS_Face()
        builder.MakeFace(face, triangulation)
        shell = TopoDS_Shell()
        builder.MakeShell(shell)
        builder.Add(shell, face)
        solid = TopoDS_Solid()
        builder.MakeSolid(solid)
        builder.Add(solid, shell)
        return solid

    if part_type == "brep":
        from OCP.BRep import BRep_Builder
        from OCP.BRepTools import BRepTools
        from OCP.TopoDS import TopoDS_Shape

        shape = TopoDS_Shape()
        if not BRepTools.Read_s(shape, path, BRep_Builder()):
            raise ValueError("Failed to read the BREP file: %s" % path)
        return shape

    if part_type == "step":
        import OCP.IFSelect
        from OCP.STEPControl import STEPControl_Reader

        reader = STEPControl_Reader()
        if reader.ReadFile(path) != OCP.IFSelect.IFSelect_RetDone:
            raise ValueError("Failed to read the STEP file: %s" % path)
        for index in range(reader.NbRootsForTransfer()):
            reader.TransferRoot(index + 1)
        return compound_of(reader.Shape(index + 1) for index in range(reader.NbShapes()))

    if part_type == "obj":
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
        from OCP.gp import gp_Pnt

        vertices, faces = [], []
        with open(path, "r") as f:
            for line in f:
                if line.startswith("v "):
                    vertices.append(tuple(float(v) for v in line.split()[1:4]))
                elif line.startswith("f "):
                    faces.append([int(item.split("/")[0]) for item in line.split()[1:]])
        shapes = []
        for face in faces:
            polygon = BRepBuilderAPI_MakePolygon()
            for index in face:
                polygon.Add(gp_Pnt(*vertices[index - 1]))
            polygon.Close()
            shapes.append(BRepBuilderAPI_MakeFace(polygon.Wire()).Face())
        return compound_of(shapes)

    raise ValueError("No reader for the '%s' geometry of %s" % (part_type, path))


def write_brep(shape, path):
    from OCP.BRepTools import BRepTools

    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not BRepTools.Write_s(shape, path):
        raise ValueError("Failed to write the BREP file: %s" % path)
    return path


#
# Per-element descriptors, for the part's opaque 'physics' section
#


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

    Both the geometry the shape was built from and the geometry that was not are
    recorded, so that an export back to URDF can restore what PartCAD does not
    model rather than let it silently disappear.
    """
    geometry = getattr(element, "geometry", None)
    if geometry is None:
        return None

    origin = getattr(element, "origin", None)
    descriptor = {
        "origin": {
            "xyz": [float(v) for v in (getattr(origin, "xyz", None) or (0.0, 0.0, 0.0))],
            "rpy": [float(v) for v in (getattr(origin, "rpy", None) or (0.0, 0.0, 0.0))],
        }
    }
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
    origin = getattr(inertial, "origin", None)
    inertia = getattr(inertial, "inertia", None)
    descriptor = {
        "origin": {
            "xyz": [float(v) for v in (getattr(origin, "xyz", None) or (0.0, 0.0, 0.0))],
            "rpy": [float(v) for v in (getattr(origin, "rpy", None) or (0.0, 0.0, 0.0))],
        },
        "mass": float(getattr(inertial, "mass", 0.0) or 0.0),
    }
    if inertia is not None:
        descriptor["inertia"] = {key: float(getattr(inertia, key, 0.0) or 0.0) for key in inertia.KEYS}
    return descriptor


def joint_descriptor(joint):
    """A URDF joint as plain data - everything about it, for the ASSY conversion."""
    origin = getattr(joint, "origin", None)
    descriptor = {
        "name": joint.name,
        "type": joint.type,
        "parent": joint.parent,
        "child": joint.child,
        "origin": {
            "xyz": [float(v) for v in (getattr(origin, "xyz", None) or (0.0, 0.0, 0.0))],
            "rpy": [float(v) for v in (getattr(origin, "rpy", None) or (0.0, 0.0, 0.0))],
        },
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
    """The elements a link's shape is built from, and the ones left over.

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


def single_file_geometry(element, context):
    """(path, part_type, scale) when a lone element is a file PartCAD reads as is.

    Only when its origin is the identity: otherwise the shape would not be in
    the link frame, and the whole point of one-part-per-link is that it is.
    """
    geometry = getattr(element, "geometry", None)
    if type(geometry).__name__.lower() != "mesh":
        return None
    if not urdf_common.is_identity(urdf_common.from_urdf_origin(getattr(element, "origin", None))):
        return None

    path = resolve_mesh_path(geometry.filename, context["urdf_dir"], context["package_paths"])
    if path is None or not os.path.isfile(path):
        return None
    part_type = MESH_PART_TYPES.get(os.path.splitext(path)[1].lower())
    if part_type is None:
        return None
    return os.path.abspath(path), part_type, mesh_scale_factor(geometry, context["warnings"])


def element_shape(element, name, context):
    """One ``<visual>``/``<collision>`` as a shape placed in the link frame."""
    geometry = element.geometry
    kind = type(geometry).__name__.lower()

    if kind in ("box", "cylinder", "sphere"):
        shape = primitive_shape(geometry, kind)
    elif kind == "mesh":
        path = resolve_mesh_path(geometry.filename, context["urdf_dir"], context["package_paths"])
        if path is None or not os.path.isfile(path):
            context["warnings"].append("Mesh file not found for link '%s': %s" % (name, geometry.filename))
            return None
        part_type = MESH_PART_TYPES.get(os.path.splitext(path)[1].lower())
        if part_type is None:
            context["warnings"].append(
                "Link '%s' uses the mesh format '%s', which PartCAD cannot read; skipping it"
                % (name, os.path.splitext(path)[1] or "<none>")
            )
            return None
        shape = _scaled(read_mesh_file(path, part_type), mesh_scale_factor(geometry, context["warnings"]))
    else:
        context["warnings"].append("Link '%s' uses an unsupported geometry type '%s'" % (name, kind))
        return None

    return _transformed(shape, _trsf(urdf_common.from_urdf_origin(getattr(element, "origin", None))))


def combine_geometry(link, elements, context):
    """Build a link's geometry into one BREP file, returning (path, "brep")."""
    shapes = [element_shape(element, link.name, context) for element in elements]
    shapes = [shape for shape in shapes if shape is not None]
    if not shapes:
        return None
    base = os.path.basename(link.name) or "link"
    path = os.path.join(context["output_folder"], "%s.brep" % base)
    suffix = 1
    while path in context["written"]:
        path = os.path.join(context["output_folder"], "%s_%d.brep" % (base, suffix))
        suffix += 1
    context["written"].add(path)
    return write_brep(compound_of(shapes), path), "brep"


def link_part(link, context):
    """The part node for a link's geometry, or None if it has none.

    The shape is always expressed in the link frame. A link that is a single
    mesh sitting at the link origin references that mesh file as it is; anything
    else - several elements, a placed element, a primitive - is built here and
    written out as one BREP file, so that a link is always exactly one part.
    """
    chosen, other, kind = choose_geometry(link, context)
    context["dropped"].add("collision" if kind == "visual" else "visual", len(other))

    physics = {}
    if getattr(link, "inertial", None) is not None:
        context["dropped"].add("inertial")
        physics["inertial"] = inertial_descriptor(link.inertial)
    used = [geometry_descriptor(element) for element in chosen]
    used = [descriptor for descriptor in used if descriptor is not None]
    if used:
        physics[kind] = used
    if other:
        left = [geometry_descriptor(element) for element in other]
        physics["collision" if kind == "visual" else "visual"] = [d for d in left if d is not None]
    for element in chosen:
        if getattr(element, "material", None) is not None:
            context["dropped"].add("material")
    gazebo = context["gazebo"].get(link.name)
    if gazebo:
        physics["gazebo"] = gazebo

    if not chosen:
        return None

    node = {
        "type": "part",
        "name": link.name,
        "link": link.name,
        "location": urdf_common.to_packed((urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T)),
        "scale": 1.0,
        "physics": {"urdf": physics} if physics else {},
    }

    single = single_file_geometry(chosen[0], context) if len(chosen) == 1 else None
    if single is not None:
        node["part_file"], node["part_type"], node["scale"] = single
        return node

    combined = combine_geometry(link, chosen, context)
    if combined is None:
        return None
    node["part_file"], node["part_type"] = combined
    return node


def link_node(robot, link_name, pose, context, visited, ancestor):
    """The node for a link and everything below it, placed at 'pose'.

    'pose' is the link's placement relative to the *nearest ancestor that has
    geometry* - not necessarily its URDF parent, because a link with no geometry
    contributes no part and its children are composed straight through it.
    'ancestor' names that link, which is what the ASSY conversion connects to.

    Returns None for a link that contributes nothing - no geometry anywhere
    beneath it - so an empty frame link does not become an empty assembly.
    """
    if link_name in visited:
        context["warnings"].append("Ignoring a cycle in the URDF joint tree at link '%s'" % link_name)
        return None
    visited = visited | {link_name}

    link = robot.link_map.get(link_name)
    if link is None:
        context["warnings"].append("Joint refers to the unknown link '%s'" % link_name)
        return None
    context["reached"].add(link_name)

    part = link_part(link, context)
    if part is not None:
        context["links"][link_name] = {
            "part_file": part["part_file"],
            "part_type": part["part_type"],
            "scale": part["scale"],
            "physics": part["physics"],
            "parent": ancestor,
            "origin": urdf_common.round_packed(urdf_common.to_packed(pose), context["precision"]),
            "joints": list(context["joint_chain"]),
        }
        # Everything below this link is placed relative to it.
        ancestor = link_name
        pose_for_children = (urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T)
        chain = []
    else:
        pose_for_children = pose
        chain = list(context["joint_chain"])

    children = []
    for joint_name, child_name in robot.child_map.get(link_name, []):
        joint = robot.joint_map[joint_name]
        count_joint(joint, context)
        saved = context["joint_chain"]
        context["joint_chain"] = chain + [joint_name]
        child = link_node(
            robot,
            child_name,
            urdf_common.compose(pose_for_children, urdf_common.from_urdf_origin(joint.origin)),
            context,
            visited,
            ancestor,
        )
        context["joint_chain"] = saved
        if child is not None:
            children.append(child)

    if part is None and not children:
        return None

    placement = urdf_common.round_packed(urdf_common.to_packed(pose), context["precision"])
    if part is not None and not children:
        # A link that is one piece of geometry and nothing else becomes that
        # part directly, so a round trip reproduces the tree it started from.
        part["location"] = placement
        return part
    if part is not None:
        # The link's geometry sits at the link frame and its children hang off
        # the same frame, so the assembly node carries the link's placement.
        children = [part] + children

    return {
        "type": "assembly",
        "name": link_name,
        "link": link_name,
        "location": placement,
        "links": children,
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


def element_to_string(element):
    """Serialize an XML element back to text.

    urdf_parser_py parses with lxml when it is importable and with the standard
    library's ElementTree otherwise, and hands the raw element straight through
    - so which of the two this gets is not ours to decide.
    """
    module = type(element).__module__ or ""
    if module.startswith("lxml"):
        from lxml import etree

        return etree.tostring(element, encoding="unicode")

    from xml.etree import ElementTree

    return ElementTree.tostring(element, encoding="unicode")


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
        "written": set(),
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

    root = link_node(robot, root_name, (urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T), context, frozenset(), None)
    if root is None:
        raise ValueError("No geometry found in %s" % urdf_file)

    # The robot's root link is the assembly itself. When it collapsed into a
    # single part node (a one-link robot), wrap it so the caller always gets the
    # same "assembly with links" shape back.
    if root["type"] != "assembly":
        root = {
            "type": "assembly",
            "name": root_name,
            "link": root_name,
            "location": urdf_common.to_packed((urdf_common.IDENTITY_Q, urdf_common.IDENTITY_T)),
            "links": [root],
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
