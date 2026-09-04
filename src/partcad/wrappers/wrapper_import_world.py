#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Sandbox entry point for reading a Gazebo world (SDFormat) as a PartCAD scene.

A ``.world`` file describes a simulation world: models placed in it, each made
of links, each link made of visual and collision shapes. A PartCAD scene is a
tree of placed shapes, which is the very same thing minus the simulation - so
the two meet at the world's initial state. Every model is placed where its
``<pose>`` puts it, every link where its own ``<pose>`` puts it inside the
model, and the result is the tree an ASSY scene produces, so everything
downstream (rendering, export, bill of materials, inspection, caching) treats a
world scene and an ASSY scene identically.

What comes back is plain data: nodes naming the file each shape is read from,
and the placements between them. The only geometry generated here is the
primitives -- a ``<box>``, a ``<cylinder>``, a ``<sphere>`` -- which have no
file of their own and are written out as STEP (see 'primitive_shapes'). A mesh
is referenced where it lies and read by the part factory for its format.

**This is a best-effort reader**, and deliberately so: SDFormat describes a
running simulation and PartCAD's scene describes where things are. What a
static arrangement cannot hold -- joints, lights, sensors, plugins, actors,
physics settings, the ground plane -- is counted and reported rather than
passed over in silence, exactly as the URDF reader reports what it cannot keep.
See docs/source/simulation.rst.
"""

import math
import os
import sys
import xml.etree.ElementTree as ElementTree

# Pinned before anything that may pull OCP - see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import gazebo_common  # noqa: E402
import primitive_shapes  # noqa: E402
import urdf_common  # noqa: E402
import wrapper_common  # noqa: E402

# What a world may carry that a PartCAD scene has nowhere to put. Counted and
# reported; see 'DROPPED_LABELS' in scene_factory_world.py for the wording.
DROPPABLE = (
    "joint",
    "light",
    "sensor",
    "plugin",
    "actor",
    "physics",
    "collision",
    "visual",
    "geometry",
    "include",
)

# Geometry SDFormat has and PartCAD does not build. A plane is the usual one --
# every ground plane in every world is a <plane> of infinite extent, which is
# not a shape that can be exported.
UNBUILDABLE_GEOMETRY = ("plane", "heightmap", "polyline", "empty", "capsule", "ellipsoid")

# What ``<surface>`` says about a link's contact, as
# (path under <surface>, PartCAD property, how to read the text). The property
# names and units are URDF's -- they are PartCAD's, and the URDF reader states
# the same values under the same names (see wrapper_import_urdf).
SURFACE_PHYSICS = (
    ("friction/ode/mu", "friction", float),
    ("friction/ode/mu2", "friction2", float),
    ("friction/ode/fdir1", "frictionDirection", lambda text: [float(v) for v in text.split()]),
    ("contact/ode/kp", "contactStiffness", float),
    ("contact/ode/kd", "contactDamping", float),
    ("contact/ode/min_depth", "minContactDepth", lambda text: float(text) * gazebo_common.MM_PER_M),
    ("contact/ode/max_vel", "maxContactVelocity", lambda text: float(text) * gazebo_common.MM_PER_M),
    ("contact/ode/max_contacts", "maxContacts", int),
    ("bounce/restitution_coefficient", "restitution", float),
)

# What a ``<link>`` says about itself outside ``<inertial>``.
LINK_PHYSICS = (
    ("gravity", "gravity", lambda text: text.strip().lower() in ("1", "true")),
    ("self_collide", "selfCollide", lambda text: text.strip().lower() in ("1", "true")),
)

INERTIA_KEYS = ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")


class Dropped(dict):
    """Counters for the world content that does not survive as a scene."""

    def __init__(self):
        super().__init__({key: 0 for key in DROPPABLE})

    def add(self, key, count=1):
        self[key] = self.get(key, 0) + count

    def summary(self):
        return {key: value for key, value in self.items() if value}


def text_of(element, path, default=None):
    """The text of a descendant element, or 'default'."""
    if element is None:
        return default
    found = element.find(path)
    if found is None or found.text is None:
        return default
    text = found.text.strip()
    return text if text else default


def name_of(element, fallback):
    return (element.get("name") or "").strip() or fallback


def color_hex(text):
    """An SDFormat colour (``r g b a``, each 0..1) as PartCAD's colour string."""
    try:
        values = [max(0.0, min(1.0, float(v))) for v in (text or "").split()]
    except ValueError:
        return None
    if len(values) < 3:
        return None
    result = "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in values[:3])
    if len(values) > 3 and values[3] < 1.0:
        result += "%02X" % int(round(values[3] * 255))
    return result


def appearance(element):
    """The ``color`` a ``<visual>``'s ``<material>`` gives the part.

    The diffuse colour if there is one, the ambient otherwise. A PBR block, a
    script or a texture has no PartCAD property; the colour beside it survives.
    """
    material = element.find("material")
    if material is None:
        return {}
    for source in ("diffuse", "ambient"):
        color = color_hex(text_of(material, source))
        if color:
            return {"color": color}
    return {}


def link_physics(link, warnings):
    """A link's physical properties, as named PartCAD properties.

    ``<inertial>`` plus whatever the first ``<collision><surface>`` says about
    contact and friction. Nothing here is a copy of SDFormat's own structure:
    each value is read out and restated in PartCAD's terms and units, the same
    ones the URDF reader states them in.
    """
    physics = {}

    inertial = link.find("inertial")
    if inertial is not None:
        mass = text_of(inertial, "mass")
        if mass is not None:
            physics["mass"] = float(mass)  # kg, as SDFormat states it
        rotation, translation = gazebo_common.parse_pose(inertial.find("pose"), warnings)
        if any(abs(v) > urdf_common.EPSILON for v in translation):
            physics["centerOfMass"] = [round(v, 9) for v in translation]
        rpy = urdf_common.quat_to_rpy(rotation)
        if any(abs(v) > urdf_common.EPSILON for v in rpy):
            # The inertia tensor is stated in a frame of its own; PartCAD
            # states that frame's orientation the way it states every other.
            physics["inertiaOrientation"] = [round(math.degrees(v), 9) for v in rpy]
        inertia = inertial.find("inertia")
        if inertia is not None:
            # kg.m^2 about 'centerOfMass', which is the frame SDFormat uses too.
            physics["inertia"] = {key: float(text_of(inertia, key, "0") or 0.0) for key in INERTIA_KEYS}

    for path, name, read in LINK_PHYSICS:
        value = text_of(link, path)
        if value is not None:
            physics[name] = read(value)

    surface = None
    for collision in link.findall("collision"):
        surface = collision.find("surface")
        if surface is not None:
            break
    if surface is not None:
        for path, name, read in SURFACE_PHYSICS:
            value = text_of(surface, path)
            if value is None:
                continue
            try:
                physics[name] = read(value)
            except ValueError:
                warnings.append("Unreadable <surface> value for '%s': %r" % (name, value))

    return physics


def geometry_node(element, name, context, model_name, link_name):
    """The part node for one ``<visual>``/``<collision>``, or None if unreadable.

    A mesh is referenced where it lies: the part reads the file the world
    named, and the element's own ``<pose>`` becomes the part's location rather
    than a transform applied to a copy of the geometry.
    """
    geometry = element.find("geometry")
    if geometry is None:
        return None

    node = {
        "type": "part",
        "name": name,
        "model": model_name,
        "link": link_name,
        "location": urdf_common.round_packed(
            urdf_common.to_packed(gazebo_common.parse_pose(element.find("pose"), context["warnings"])),
            context["precision"],
        ),
        "scale": 1.0,
    }
    node.update(appearance(element))

    mesh = geometry.find("mesh")
    if mesh is not None:
        uri = text_of(mesh, "uri")
        path = gazebo_common.resolve_uri(uri, context["world_dir"], context["model_paths"])
        if path is None or not os.path.isfile(path):
            context["warnings"].append("Mesh file not found for '%s': %s" % (name, uri))
            context["dropped"].add("geometry")
            return None
        extension = os.path.splitext(path)[1].lower()
        part_type = gazebo_common.MESH_PART_TYPES.get(extension)
        if part_type is None:
            context["warnings"].append(
                "'%s' uses the mesh format '%s', which PartCAD cannot read; skipping it" % (name, extension or "<none>")
            )
            context["dropped"].add("geometry")
            return None
        node["part_file"] = os.path.abspath(path)
        node["part_type"] = part_type
        node["scale"] = gazebo_common.mesh_scale_factor(text_of(mesh, "scale"), context["warnings"])
        return node

    mm = gazebo_common.MM_PER_M
    box = geometry.find("box")
    if box is not None:
        size = [float(v) * mm for v in (text_of(box, "size") or "1 1 1").split()]
        if len(size) != 3:
            context["warnings"].append("A <box> needs three sizes, found %d; skipping '%s'" % (len(size), name))
            context["dropped"].add("geometry")
            return None
        node["part_file"] = primitive_shapes.write_primitive_step("box", size, name, context)
        node["part_type"] = "step"
        return node

    cylinder = geometry.find("cylinder")
    if cylinder is not None:
        dimensions = (
            float(text_of(cylinder, "radius", "0.5")) * mm,
            float(text_of(cylinder, "length", "1")) * mm,
        )
        node["part_file"] = primitive_shapes.write_primitive_step("cylinder", dimensions, name, context)
        node["part_type"] = "step"
        return node

    sphere = geometry.find("sphere")
    if sphere is not None:
        dimensions = (float(text_of(sphere, "radius", "0.5")) * mm,)
        node["part_file"] = primitive_shapes.write_primitive_step("sphere", dimensions, name, context)
        node["part_type"] = "step"
        return node

    for kind in UNBUILDABLE_GEOMETRY:
        if geometry.find(kind) is not None:
            context["warnings"].append(
                "'%s' is a <%s>, which a PartCAD scene has no shape for; skipping it" % (name, kind)
            )
            context["dropped"].add("geometry")
            return None

    context["warnings"].append("'%s' has no geometry PartCAD can read; skipping it" % name)
    context["dropped"].add("geometry")
    return None


def choose_geometry(link, context, link_name):
    """The elements a link's shapes are built from, and the ones left over.

    Collision geometry wins by default, for the reason it wins in the URDF
    reader: it is what a simulator resolves contact against and it is usually
    the cheaper shape. ``ignoreCollision`` reverses that -- ``true``
    everywhere, or for the named links only.
    """
    ignore = context["ignore_collision"]
    prefer_visual = ignore is True or link_name in ignore
    if prefer_visual:
        chosen, other, kind = link.findall("visual"), link.findall("collision"), "visual"
    else:
        chosen, other, kind = link.findall("collision"), link.findall("visual"), "collision"

    if not chosen and other:
        # The link only has the other kind; using it beats dropping the link.
        chosen, other, kind = other, [], ("collision" if prefer_visual else "visual")
    return list(chosen), list(other), kind


def link_node(link, model_name, path_name, context):
    """One ``<link>`` as a node of the scene tree, or None if it has no geometry.

    A link with one shape *is* that shape, named after the link. A link with
    several becomes a node holding one part per shape, each named under the
    link -- the same ``<thing>/<piece>`` convention the URDF reader uses, and
    the one the exporters read back (see 'export_urdf.shape_elements').
    """
    link_name = name_of(link, "link")
    chosen, other, kind = choose_geometry(link, context, link_name)
    other_kind = "collision" if kind == "visual" else "visual"
    context["dropped"].add(other_kind, len(other))
    context["dropped"].add("sensor", len(link.findall("sensor")))
    context["dropped"].add("light", len(link.findall("light")))

    physics = link_physics(link, context["warnings"])
    pose = gazebo_common.parse_pose(link.find("pose"), context["warnings"])

    nodes = []
    for index, element in enumerate(chosen):
        name = path_name if len(chosen) == 1 else "%s/%s" % (path_name, name_of(element, str(index + 1)))
        node = geometry_node(element, name, context, model_name, link_name)
        if node is not None:
            if physics:
                node["physics"] = physics
            nodes.append(node)

    # Geometry the scene does not place: the visual shapes of a link built from
    # its collision geometry, and the other way round. They are parts like any
    # other - inspectable and exportable - they are simply not in this
    # arrangement.
    for index, element in enumerate(other):
        name = "%s/%s" % (path_name, other_kind)
        if len(other) > 1:
            name = "%s/%s" % (name, name_of(element, str(index + 1)))
        node = geometry_node(element, name, context, model_name, link_name)
        if node is not None:
            node.pop("location", None)
            context["unplaced"].append(node)

    if not nodes:
        return None
    if len(nodes) == 1:
        node = nodes[0]
        node["location"] = urdf_common.round_packed(
            urdf_common.to_packed(urdf_common.compose(pose, urdf_common.from_packed(node["location"]))),
            context["precision"],
        )
        return node

    group = {
        "type": "assembly",
        "name": path_name,
        "link": link_name,
        "location": urdf_common.round_packed(urdf_common.to_packed(pose), context["precision"]),
        "links": nodes,
    }
    if physics:
        group["physics"] = physics
    return group


def model_node(model, prefix, context, depth=0):
    """One ``<model>`` as a node of the scene tree, or None if it holds nothing.

    A model is a container: its links, and the models nested in it, are placed
    inside it and it is placed inside whatever holds it. That is exactly a
    PartCAD sub-assembly, so this is the one place where SDFormat's nesting and
    PartCAD's agree and nothing has to be flattened.
    """
    if depth > context["max_depth"]:
        context["warnings"].append("Refusing to descend past %d nested models" % context["max_depth"])
        return None

    model_name = name_of(model, "model")
    path_name = "%s/%s" % (prefix, model_name) if prefix else model_name
    if path_name in context["seen"]:
        # SDFormat requires names to be unique among siblings, not globally.
        suffix = 1
        while "%s_%d" % (path_name, suffix) in context["seen"]:
            suffix += 1
        path_name = "%s_%d" % (path_name, suffix)
    context["seen"].add(path_name)

    context["dropped"].add("joint", len(model.findall("joint")))
    context["dropped"].add("plugin", len(model.findall("plugin")))

    children = []
    for link in model.findall("link"):
        node = link_node(link, model_name, "%s/%s" % (path_name, name_of(link, "link")), context)
        if node is not None:
            children.append(node)
    for nested in model.findall("model"):
        node = model_node(nested, path_name, context, depth + 1)
        if node is not None:
            children.append(node)
    for included in model.findall("include"):
        node = include_node(included, path_name, context, depth + 1)
        if node is not None:
            children.append(node)

    if not children:
        return None

    node = {
        "type": "assembly",
        "name": path_name,
        "model": model_name,
        "location": urdf_common.round_packed(
            urdf_common.to_packed(gazebo_common.parse_pose(model.find("pose"), context["warnings"])),
            context["precision"],
        ),
        "links": children,
    }
    if text_of(model, "static") is not None:
        node["static"] = text_of(model, "static").strip().lower() in ("1", "true")
    return node


def include_node(include, prefix, context, depth=0):
    """An ``<include>``, resolved to the model it names, or None.

    Best effort, and this is the half most likely to come up empty: an
    ``<include>`` names a model by URI, and outside a Gazebo installation there
    is no model database to resolve one against. What is resolvable -- a
    relative path, a ``file://``, a ``model://`` that lands in the configured
    model paths or beside the world file -- is read; anything else is counted
    and reported.
    """
    uri = text_of(include, "uri")
    path = gazebo_common.resolve_uri(uri, context["world_dir"], context["model_paths"])
    if path is not None and os.path.isdir(path):
        path = _model_file_in(path)
    if path is None or not os.path.isfile(path):
        context["warnings"].append("Cannot resolve the included model '%s'" % (uri or "<no uri>"))
        context["dropped"].add("include")
        return None

    try:
        included_root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as e:
        context["warnings"].append("Cannot read the included model '%s': %s" % (path, e))
        context["dropped"].add("include")
        return None

    if included_root.tag == "model":
        models = [included_root]
    else:
        # Top-level models, then anywhere as a fallback. Not './/model' outright:
        # that also matches the models nested *inside* a model, which
        # 'model_node()' reads itself, so counting those as extras would report
        # a file that is read in full as one that is not.
        models = included_root.findall("model") or included_root.findall(".//model")
    if not models:
        context["warnings"].append("The included file '%s' declares no model" % path)
        context["dropped"].add("include")
        return None
    if len(models) > 1:
        # An <include> places one model, so the rest of them go unplaced.
        context["warnings"].append(
            "The included file '%s' declares %d models; only the first, '%s', is placed"
            % (path, len(models), name_of(models[0], "model"))
        )
        context["dropped"].add("include", len(models) - 1)

    # The include's own name and pose win over the model's, which is what
    # SDFormat says an <include> does.
    outer_dir = context["world_dir"]
    context["world_dir"] = os.path.dirname(os.path.abspath(path))
    try:
        node = model_node(models[0], prefix, context, depth)
    finally:
        context["world_dir"] = outer_dir
    if node is None:
        return None

    name = text_of(include, "name")
    if name:
        node["model"] = name
    pose = include.find("pose")
    if pose is not None:
        node["location"] = urdf_common.round_packed(
            urdf_common.to_packed(gazebo_common.parse_pose(pose, context["warnings"])),
            context["precision"],
        )
    static = text_of(include, "static")
    if static is not None:
        node["static"] = static.strip().lower() in ("1", "true")
    return node


def _model_file_in(directory):
    """The SDF file of a model directory, read from its 'model.config' if there is one."""
    config = os.path.join(directory, "model.config")
    if os.path.isfile(config):
        try:
            root = ElementTree.parse(config).getroot()
        except ElementTree.ParseError:
            root = None
        if root is not None:
            for sdf in root.findall(".//sdf"):
                candidate = os.path.join(directory, (sdf.text or "").strip())
                if os.path.isfile(candidate):
                    return candidate
    for name in ("model.sdf", "model.world"):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def world_element(root, path):
    """The ``<world>`` this file describes, or a synthetic one around its models.

    A ``.world`` normally holds ``<sdf><world>``. A file that holds a bare
    ``<model>`` is read as a world of that one model, so that pointing a scene
    at a model file works rather than failing on a technicality.
    """
    if root.tag == "world":
        return root
    world = root.find("world")
    if world is not None:
        return world
    if root.tag == "model" or root.find("model") is not None:
        synthetic = ElementTree.Element("world")
        synthetic.set("name", os.path.splitext(os.path.basename(path))[0])
        for model in [root] if root.tag == "model" else root.findall("model"):
            synthetic.append(model)
        return synthetic
    raise ValueError("%s: no <world> and no <model> to read" % path)


def process(request):
    world_file = request["world_file"]
    if not os.path.isfile(world_file):
        raise FileNotFoundError(world_file)

    try:
        root = ElementTree.parse(world_file).getroot()
    except ElementTree.ParseError as e:
        raise ValueError("%s: %s" % (world_file, e)) from e

    world = world_element(root, world_file)

    ignore_collision = request.get("ignoreCollision")
    if ignore_collision is not True:
        ignore_collision = frozenset(ignore_collision or ())

    context = {
        # Where relative, 'file://' and 'model://' references are resolved
        # from. Not the parsed file's own directory: a world file is a Jinja2
        # template, and a rendered one sits in PartCAD's state directory while
        # the meshes and models it names sit beside the file the package
        # declared.
        "world_dir": request.get("base_dir") or os.path.dirname(os.path.abspath(world_file)),
        "model_paths": list(request.get("model_paths") or []),
        "output_folder": request["output_folder"],
        "precision": request.get("precision", 6),
        "ignore_collision": ignore_collision,
        "max_depth": request.get("max_depth", 16),
        "warnings": [],
        "dropped": Dropped(),
        "primitives": {},
        "written": set(),
        "unplaced": [],
        "seen": set(),
    }

    context["dropped"].add("light", len(world.findall("light")))
    context["dropped"].add("plugin", len(world.findall("plugin")))
    context["dropped"].add("actor", len(world.findall("actor")))
    context["dropped"].add("physics", len(world.findall("physics")))

    children = []
    for model in world.findall("model"):
        node = model_node(model, "", context)
        if node is not None:
            children.append(node)
    for included in world.findall("include"):
        node = include_node(included, "", context)
        if node is not None:
            children.append(node)

    if not children and not context["unplaced"]:
        raise ValueError("No geometry found in %s" % world_file)

    return {
        "root": {
            "type": "assembly",
            "name": name_of(world, os.path.splitext(os.path.basename(world_file))[0]),
            "location": urdf_common.to_packed(gazebo_common.IDENTITY),
            "links": children,
            "parts": context["unplaced"],
        },
        "world_name": name_of(world, os.path.splitext(os.path.basename(world_file))[0]),
        "warnings": context["warnings"],
        "dropped": context["dropped"].summary(),
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
