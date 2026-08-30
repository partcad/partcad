#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in Gazebo world exporter (see '//builtin/export' in partcad.yaml).

Writes a PartCAD scene -- or any other shape -- as an SDFormat ``.world`` file
plus the mesh files it references. This is the format PartCAD calls ``world``,
after the files it lives in. "SDF" is overloaded and the two meanings are
unrelated: the ``sdf`` *part* type is a signed distance function, while this is
**SDFormat**, the XML dialect Gazebo describes a simulation world in.

Like the URDF exporter beside it, this one is handed the assembly *tree* itself
rather than the geometry it decodes to -- which is what ``decode: false`` on
this format's declaration asks for, see wrapper_export.DECODE_KEY. Decoding
would keep the tree's shape and nothing else about it: every node's ``name`` and
``label`` is dropped and its placement is baked into the geometry rather than
staying readable as data. This exporter needs all three, because that is what
the models, the links, the poses and the properties are built from.

The mapping is the reverse of the world reader's (wrapper_import_world):

  * the exported object is the ``<world>``,
  * anything placed in it is a ``<model>``, and a node with a subtree is a
    ``<model>`` wherever it sits -- SDFormat has no other container,
  * a node that is geometry is a ``<link>`` with a ``<visual>`` and a
    ``<collision>``, both referencing a mesh written next to the world file.

Two conventions are worth stating, because they are what makes the round trip
close, and both are the ones the URDF exporter already uses:

  * Meshes are written in millimetres -- the unit PartCAD uses everywhere --
    and referenced with ``<scale>0.001 0.001 0.001</scale>``, which is how
    SDFormat says "these coordinates are millimetres". Poses are in metres and
    radians, as SDFormat requires.
  * Geometry is written in its own frame and placed by the element that holds
    it, so a ``<visual>`` origin stays at identity. A shape that appears more
    than once is written once and referenced by every link that uses it.

What the part states about itself wins over anything computed here: mass,
centre of mass, inertia, friction, contact and colour are named PartCAD
properties, and this writes each of them into the SDFormat element that states
it. Only a part that says nothing gets computed inertial properties, from its
solid and the configured density. A property PartCAD has and SDFormat has no
spelling for is reported rather than dropped in silence -- see SDF_STATED.
"""

import math
import os
import re
import sys
from xml.etree import ElementTree

# Pinned before anything that may pull OCP - see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import gazebo_common  # noqa: E402
import ocp_serialize  # noqa: E402
import urdf_common  # noqa: E402

# Metres per millimetre, for the mesh '<scale>': the meshes are written in
# millimetres and SDFormat reads mesh coordinates as metres after scaling.
MESH_SCALE = 1.0 / urdf_common.MM_PER_M

# Density used to turn a volume into a mass when the caller does not name one,
# in kg/m^3. Aluminium, the same default the URDF exporter uses and for the
# same reason: a middle-of-the-road value for a machined part, whose provenance
# is obvious in the output rather than looking like a measurement.
DEFAULT_DENSITY = 2700.0

# mm^5 -> m^5. The second moment OCCT integrates has units of length^5, so this
# is what converts it once the density (kg/m^3) is applied.
MM5_TO_M5 = 1e-15
# mm^3 -> m^3.
MM3_TO_M3 = 1e-9

# SDFormat names end up as XML attributes and as scoped names joined by '::',
# so anything outside this set is replaced.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")

# PartCAD property -> where under '<link>' it is stated, and how to write it.
# The path is relative to the link; the writer creates whatever is missing.
LINK_PHYSICS = {
    "gravity": ("gravity", lambda v: _bool_text(v)),
    "selfCollide": ("self_collide", lambda v: _bool_text(v)),
    "velocityDamping": ("velocity_decay/linear", repr),
}

# PartCAD property -> where under '<collision><surface>' it is stated. The
# mirror image of wrapper_import_world.SURFACE_PHYSICS, and to be kept that way.
SURFACE_PHYSICS = {
    "friction": ("friction/ode/mu", repr),
    "friction2": ("friction/ode/mu2", repr),
    "frictionDirection": ("friction/ode/fdir1", lambda v: " ".join(repr(float(x)) for x in v)),
    "contactStiffness": ("contact/ode/kp", repr),
    "contactDamping": ("contact/ode/kd", repr),
    "minContactDepth": ("contact/ode/min_depth", lambda v: repr(v / urdf_common.MM_PER_M)),
    "maxContactVelocity": ("contact/ode/max_vel", lambda v: repr(v / urdf_common.MM_PER_M)),
    "maxContacts": ("contact/ode/max_contacts", lambda v: str(int(v))),
    "restitution": ("bounce/restitution_coefficient", repr),
}

# Every part property this exporter has an SDFormat spelling for. A 'physics'
# property outside this set is one PartCAD supports and SDFormat does not: it
# is reported through the response and logged at info level, which is the
# mirror image of the reader reporting what it cannot keep. When PartCAD grows
# a physical property, either give it a spelling above or let it be reported
# here - do not let it disappear quietly.
SDF_STATED = (
    frozenset(("mass", "centerOfMass", "inertiaOrientation", "inertia"))
    | frozenset(LINK_PHYSICS)
    | frozenset(SURFACE_PHYSICS)
)


def _bool_text(value):
    return "true" if value else "false"


def sanitize_name(name, fallback):
    """An SDFormat-safe name derived from a PartCAD name.

    PartCAD names carry package paths and ':' separators ("//pub/examples:logo")
    and the '/' that groups a link's own shapes, none of which belong in an
    SDFormat name -- '::' is its scope separator and a bare '/' has no meaning.
    """
    name = _UNSAFE_NAME.sub("_", str(name or "")).strip("_")
    return name or fallback


class NameAllocator:
    """Hands out unique names, since SDFormat requires them within a scope.

    Unique across the whole document rather than per scope: that satisfies the
    requirement everywhere at once, and it keeps the names readable in a
    simulator's entity tree, where they are shown scoped anyway.
    """

    def __init__(self):
        self.used = set()

    def take(self, name, fallback="model"):
        base = sanitize_name(name, fallback)
        candidate = base
        suffix = 1
        while candidate in self.used:
            candidate = "%s_%d" % (base, suffix)
            suffix += 1
        self.used.add(candidate)
        return candidate


def sub(parent, path, text=None):
    """The element at 'path' under 'parent', creating what is missing."""
    element = parent
    for step in path.split("/"):
        found = element.find(step)
        if found is None:
            found = ElementTree.SubElement(element, step)
        element = found
    if text is not None:
        element.text = text
    return element


def node_geometry(node):
    """The node's own shape as a live TopoDS_Shape, in its own frame, or None.

    The placement carried by the node is deliberately left off: it becomes the
    ``<pose>`` of the element above the geometry, not part of the geometry.
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


def mesh_reference(shape, node, link_name, state):
    """Write 'shape' out as a mesh (or reuse one) and return the SDFormat URI.

    An identical shape used twice - a repeated fastener, a row of pallets -
    shares one mesh file, the way a world written by hand would.
    """
    key = node.get(ocp_serialize.KEY_BREP)
    mesh_file = state["meshes"].get(key)
    if mesh_file is None:
        mesh_name = state["mesh_names"].take(node.get("label") or link_name, "mesh")
        mesh_file = "%s/%s.stl" % (state["mesh_dir_name"], mesh_name)
        write_mesh(shape, os.path.join(state["mesh_dir"], "%s.stl" % mesh_name), state["options"])
        state["meshes"][key] = mesh_file
    return state["mesh_prefix"] + mesh_file


def shape_elements(node):
    """The (shape node, placement) pairs one link is built from.

    Usually a node is one shape and that is the whole of it. A sub-assembly
    whose children are named *under* it - "wrist" holding "wrist/1" and
    "wrist/2" - is one thing made of several shapes, and goes back out as one
    link with several ``<visual>`` elements rather than as a model with a link
    per shape.

    The slash is the whole of the rule, and it is the only hierarchy PartCAD
    encodes in a name. It is the same rule the URDF exporter applies, and the
    same one both readers write, so a link that came in with several shapes
    goes back out as one.
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


def inertial_of(placed, density, warnings, link_name):
    """The ``<inertial>`` values for a link's solids, or None when they have none.

    'placed' is the (shape, packed placement) pairs the link is made of. Each is
    put where it belongs before the moments are taken, so the result is about
    the link as a whole. OCCT's GProp_GProps.MatrixOfInertia() is already the
    tensor about the centre of mass, which is the frame SDFormat's
    ``<inertia>`` is stated in too, so only the units and the density are
    applied.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    combined_shape = combined(placed)
    if combined_shape is None:
        return None

    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(combined_shape, properties)
    volume = properties.Mass()
    if volume <= 0.0:
        warnings.append("The link '%s' has no solid volume; it is written without an <inertial>" % link_name)
        return None

    mass = volume * MM3_TO_M3 * density
    centre = properties.CentreOfMass()
    matrix = properties.MatrixOfInertia()
    scale = MM5_TO_M5 * density
    return {
        "mass": mass,
        "centerOfMass": [centre.X(), centre.Y(), centre.Z()],
        "inertia": {
            "ixx": matrix.Value(1, 1) * scale,
            "ixy": matrix.Value(1, 2) * scale,
            "ixz": matrix.Value(1, 3) * scale,
            "iyy": matrix.Value(2, 2) * scale,
            "iyz": matrix.Value(2, 3) * scale,
            "izz": matrix.Value(3, 3) * scale,
        },
    }


def combined(placed):
    """The (shape, placement) pairs as one compound, each shape put in place."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.TopoDS import TopoDS_Compound

    shapes = []
    for shape, placement in placed:
        if placement is None:
            shapes.append(shape)
            continue
        shapes.append(BRepBuilderAPI_Transform(shape, _toploc(placement).Transformation(), True).Shape())

    if not shapes:
        return None
    if len(shapes) == 1:
        return shapes[0]

    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    return compound


def _toploc(packed):
    """A packed PartCAD location as an OCCT TopLoc_Location."""
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    translation, axis, angle = packed
    transform = gp_Trsf()
    if any(abs(v) > 0 for v in axis) and abs(angle) > 0:
        transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis)), math.radians(angle))
    transform.SetTranslationPart(gp_Vec(*translation))
    return TopLoc_Location(transform)


def carried_inertial(physics):
    """The ``<inertial>`` values a part states about itself, or None."""
    if "mass" not in physics:
        return None
    result = {"mass": float(physics["mass"])}
    if "centerOfMass" in physics:
        result["centerOfMass"] = [float(v) for v in physics["centerOfMass"]]
    if "inertiaOrientation" in physics:
        result["inertiaOrientation"] = [float(v) for v in physics["inertiaOrientation"]]
    if "inertia" in physics:
        result["inertia"] = {key: float(value) for key, value in physics["inertia"].items()}
    return result


def write_inertial(link, values):
    """Write one link's ``<inertial>`` block from the values above."""
    if values is None:
        return
    inertial = sub(link, "inertial")
    sub(inertial, "mass", repr(values["mass"]))
    centre = values.get("centerOfMass")
    orientation = values.get("inertiaOrientation")
    if centre or orientation:
        rotation = urdf_common.rpy_to_quat([math.radians(v) for v in (orientation or (0.0, 0.0, 0.0))])
        pose = (rotation, tuple(centre or (0.0, 0.0, 0.0)))
        sub(inertial, "pose", gazebo_common.format_pose(pose))
    inertia = values.get("inertia")
    if inertia:
        block = sub(inertial, "inertia")
        for key in ("ixx", "ixy", "ixz", "iyy", "iyz", "izz"):
            sub(block, key, repr(float(inertia.get(key, 0.0))))


def color_rgba(text):
    """A PartCAD colour string as SDFormat's ``r g b a``, or None."""
    value = str(text or "").strip().lstrip("#")
    if len(value) not in (6, 8):
        return None
    try:
        channels = [int(value[index : index + 2], 16) / 255.0 for index in range(0, len(value), 2)]
    except ValueError:
        return None
    while len(channels) < 4:
        channels.append(1.0)
    return " ".join("%.4g" % channel for channel in channels)


def write_material(visual, properties):
    """Write a ``<material>`` from what the shape says about its appearance."""
    rgba = color_rgba(properties.get("color"))
    if rgba is None:
        return
    material = sub(visual, "material")
    sub(material, "ambient", rgba)
    sub(material, "diffuse", rgba)


def emit_link(node, model, pose, elements, state):
    """Add one ``<link>``, with a visual and a collision per shape it holds."""
    link_name = state["link_names"].take(node.get("label") or node.get("name"), "link")
    # A new element every time, not 'sub()': a model holds one link per node,
    # and 'sub()' would find the link already there and pour the next node's
    # geometry into it.
    link = ElementTree.SubElement(model, "link")
    link.set("name", link_name)
    if not urdf_common.is_identity(pose):
        sub(link, "pose", gazebo_common.format_pose(pose))

    physics = (state["properties"].get(node.get("name")) or {}).get("physics") or {}

    placed = []
    for index, (shape_node, placement) in enumerate(elements):
        shape = node_geometry(shape_node)
        if shape is None:
            continue
        uri = mesh_reference(shape, shape_node, link_name, state)
        element_pose = None if placement is None else gazebo_common.format_pose(urdf_common.from_packed(placement))

        for kind in ("visual", "collision"):
            element = ElementTree.SubElement(link, kind)
            element.set("name", "%s_%s_%d" % (link_name, kind, index))
            if element_pose is not None:
                sub(element, "pose", element_pose)
            mesh = sub(element, "geometry/mesh")
            sub(mesh, "uri", uri)
            sub(mesh, "scale", "%s %s %s" % ((repr(MESH_SCALE),) * 3))
            if kind == "visual":
                # The appearance belongs to the shape, not to the link: a link
                # built from several parts may well have a colour per part.
                write_material(element, state["properties"].get(shape_node.get("name")) or {})
            else:
                write_surface(element, physics)
        placed.append((shape, placement))

    if not placed:
        # A frame that carries children, with no geometry of its own.
        return link

    for name, (path, render) in LINK_PHYSICS.items():
        if name in physics:
            sub(link, path, render(physics[name]))

    if state["options"]["inertial"]:
        write_inertial(
            link,
            carried_inertial(physics) or inertial_of(placed, state["options"]["density"], state["warnings"], link_name),
        )
    state["unsupported"].update(set(physics) - SDF_STATED)
    return link


def write_surface(collision, physics):
    """Write the ``<surface>`` of one collision from the link's properties."""
    for name, (path, render) in SURFACE_PHYSICS.items():
        if name in physics:
            sub(collision, "surface/" + path, render(physics[name]))


def emit(node, parent, pose, state):
    """Add 'node' and its subtree under 'parent' -- a ``<world>`` or a ``<model>``.

    Anything placed directly in a world is a model, and so is anything with a
    subtree: SDFormat has no other container, and a ``<link>`` cannot hold
    another. A leaf inside a model is a link.
    """
    elements, children = shape_elements(node)

    if parent.tag != "world" and not children:
        emit_link(node, parent, pose, elements, state)
        return

    model = ElementTree.SubElement(parent, "model")
    model.set("name", state["model_names"].take(node.get("label") or node.get("name"), "model"))
    if not urdf_common.is_identity(pose):
        sub(model, "pose", gazebo_common.format_pose(pose))
    if parent.tag == "world" and state["options"]["static"]:
        # A scene states where things are. Left dynamic, every model in it would
        # start falling the moment the world was loaded, which is not what the
        # scene says.
        sub(model, "static", "true")

    if elements:
        emit_link(node, model, gazebo_common.IDENTITY, elements, state)
    for child in children:
        emit(child, model, urdf_common.from_packed(child.get(ocp_serialize.KEY_LOCATION)), state)


def add_sun(world):
    """The directional light every Gazebo world needs to show anything."""
    light = ElementTree.SubElement(world, "light")
    light.set("name", "sun")
    light.set("type", "directional")
    sub(light, "cast_shadows", "true")
    sub(light, "pose", "0 0 10 0 0 0")
    sub(light, "diffuse", "0.8 0.8 0.8 1")
    sub(light, "specular", "0.2 0.2 0.2 1")
    sub(light, "direction", "-0.5 0.1 -0.9")


def add_ground_plane(world):
    """The ground every Gazebo world is normally loaded with."""
    model = ElementTree.SubElement(world, "model")
    model.set("name", "ground_plane")
    sub(model, "static", "true")
    link = ElementTree.SubElement(model, "link")
    link.set("name", "link")
    for kind in ("collision", "visual"):
        element = ElementTree.SubElement(link, kind)
        element.set("name", kind)
        plane = sub(element, "geometry/plane")
        sub(plane, "normal", "0 0 1")
        sub(plane, "size", "100 100")
    material = sub(link.find("visual"), "material")
    sub(material, "ambient", "0.8 0.8 0.8 1")
    sub(material, "diffuse", "0.8 0.8 0.8 1")


def process(path, request):
    root = request["wrapped"]
    if not isinstance(root, dict) or not (
        ocp_serialize.is_shape_object(root) or ocp_serialize.is_assembly_object(root)
    ):
        raise ValueError("The world exporter needs a shape or a scene to export")

    world_dir = os.path.dirname(os.path.abspath(path)) or "."
    stem = os.path.splitext(os.path.basename(path))[0] or "world"
    world_name = sanitize_name(request.get("world_name") or root.get("label") or stem, stem)
    mesh_dir_name = request.get("mesh_dir") or "%s_meshes" % stem
    mesh_dir = os.path.join(world_dir, mesh_dir_name)
    os.makedirs(mesh_dir, exist_ok=True)

    warnings = []
    state = {
        "model_names": NameAllocator(),
        "link_names": NameAllocator(),
        "mesh_names": NameAllocator(),
        "meshes": {},
        "mesh_dir": mesh_dir,
        "mesh_dir_name": mesh_dir_name,
        # Empty by default, which makes the reference relative to the world file
        # itself - what a standalone world wants. A Gazebo model database sets
        # this to "model://<name>/" so the meshes resolve through it.
        "mesh_prefix": request.get("mesh_prefix") or "",
        # Shape full name -> the properties its part declares ('physics',
        # 'material', 'color'). A part that came from a world states the link's
        # mass, inertia and friction here, and they go back out rather than
        # being recomputed.
        "properties": request.get("properties") or {},
        "unsupported": set(),
        "options": {
            "tolerance": request.get("tolerance", 0.1),
            "angularTolerance": request.get("angularTolerance", 0.1),
            "ascii": request.get("ascii", False),
            "inertial": request.get("inertial", True),
            "density": request.get("density") or DEFAULT_DENSITY,
            "static": request.get("static", True),
        },
        "warnings": warnings,
    }

    sdf = ElementTree.Element("sdf")
    sdf.set("version", str(request.get("version") or gazebo_common.SDF_VERSION))
    world = ElementTree.SubElement(sdf, "world")
    world.set("name", world_name)

    # Neither is part of what the scene says; both are what makes the file
    # usable. A world with no light renders black and a world with no ground
    # has nothing to stand on, so a simulator's own empty world ships with
    # both. Turn either off with 'sun: false' / 'ground_plane: false'.
    if request.get("sun", True):
        add_sun(world)
    if request.get("ground_plane", True):
        add_ground_plane(world)
        state["model_names"].take("ground_plane")

    root_pose = urdf_common.from_packed(root.get(ocp_serialize.KEY_LOCATION))
    if ocp_serialize.is_shape_object(root):
        # A single shape: one model holding one link.
        emit(root, world, root_pose, state)
    else:
        # The exported object *is* the world, so its children are its models,
        # each carrying the exported object's own placement on top of its own.
        for child in root.get(ocp_serialize.KEY_ASSEMBLY) or []:
            child_pose = urdf_common.compose(root_pose, urdf_common.from_packed(child.get(ocp_serialize.KEY_LOCATION)))
            emit(child, world, child_pose, state)

    ElementTree.indent(sdf, space="  ")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" ?>\n')
        f.write(ElementTree.tostring(sdf, encoding="unicode"))
        f.write("\n")

    return {
        "success": True,
        "exception": None,
        "world_name": world_name,
        "mesh_dir": mesh_dir,
        "meshes": sorted(set(state["meshes"].values())),
        "warnings": warnings,
        # Properties PartCAD holds and SDFormat cannot state. Reported at info
        # level by the caller: nothing is wrong with the file, it just says less
        # than the package does.
        "unsupported": sorted(state["unsupported"]),
    }
