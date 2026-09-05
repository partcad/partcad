#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Sandbox entry point for reading an MJCF (MuJoCo) file as a PartCAD object.

An MJCF file describes a model MuJoCo can simulate: a ``<worldbody>`` holding
bodies, each body holding geoms and further bodies. A PartCAD assembly -- and a
PartCAD scene, which is the same tree read with a different intent -- is a tree
of placed shapes, which is that same arrangement minus the simulation. So the
two meet at the model's initial state: every body is placed where its ``pos``
and orientation put it inside the body that holds it, every geom where its own
put it inside its body, and the result is the tree an ASSY file produces.
Everything downstream (rendering, export, bill of materials, inspection,
caching) therefore treats an MJCF object and an ASSY one identically.

What comes back is plain data: nodes naming the file each shape is read from,
and the placements between them. The only geometry generated here is the
primitives -- a ``box``, a ``cylinder``, a ``sphere`` -- which have no file of
their own and are written out as STEP (see 'primitive_shapes'). A mesh is
referenced where it lies and read by the part factory for its format.

**This is a best-effort reader**, exactly as the URDF and SDFormat readers are.
MJCF describes a running simulation and PartCAD describes where things are, so
what a static arrangement cannot hold -- joints, actuators, tendons, sensors,
lights, cameras, contact and equality constraints, keyframes -- is counted and
reported rather than passed over in silence. See docs/source/simulation.rst.
"""

import math
import os
import sys
import xml.etree.ElementTree as ElementTree

# Pinned before anything that may pull OCP - see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import mujoco_common  # noqa: E402
import primitive_shapes  # noqa: E402
import urdf_common  # noqa: E402
import wrapper_common  # noqa: E402

# What an MJCF model may carry that a PartCAD tree has nowhere to put. Counted
# and reported; see 'DROPPED_LABELS' in assembly_factory_mjcf.py for the wording.
DROPPABLE = (
    "friction",
    "joint",
    "actuator",
    "tendon",
    "equality",
    "contact",
    "sensor",
    "light",
    "camera",
    "site",
    "keyframe",
    "plugin",
    "geometry",
    "include",
)

# Where a mesh asset's own ``<mesh>`` scale and the geom that uses it meet: the
# geom names the asset, the asset names the file.
MESH_ASSET_KEYS = ("name", "file", "scale")


class Dropped(dict):
    """Counters for the model content that does not survive as a static tree."""

    def __init__(self):
        super().__init__({key: 0 for key in DROPPABLE})

    def add(self, key, count=1):
        self[key] = self.get(key, 0) + count

    def summary(self):
        return {key: value for key, value in self.items() if value}


def name_of(element, fallback):
    return (element.get("name") or "").strip() or fallback


def load(path, seen=None):
    """Parse an MJCF file, splicing in whatever its ``<include>`` elements name.

    MuJoCo resolves an ``<include>`` before the model is compiled, and a file
    that includes another is meaningless without it, so the same happens here
    rather than counting the include as dropped content. A cycle -- or a file
    that cannot be read -- stops at the element rather than at the model.
    """
    seen = set() if seen is None else seen
    real = os.path.realpath(path)
    root = ElementTree.parse(path).getroot()
    if real in seen:
        return root, ["Refusing to include '%s' a second time" % path]
    seen.add(real)

    warnings = []
    directory = os.path.dirname(os.path.abspath(path))
    for parent in [root] + list(root.iter()):
        for include in list(parent.findall("include")):
            index = list(parent).index(include)
            parent.remove(include)
            named = (include.get("file") or "").strip()
            candidate = named if os.path.isabs(named) else os.path.join(directory, named)
            if not named or not os.path.isfile(candidate):
                warnings.append("Cannot resolve the included file '%s'" % (named or "<no file>"))
                continue
            try:
                included, nested_warnings = load(candidate, seen)
            except ElementTree.ParseError as e:
                warnings.append("Cannot read the included file '%s': %s" % (candidate, e))
                continue
            warnings.extend(nested_warnings)
            for offset, child in enumerate(list(included)):
                parent.insert(index + offset, child)
    return root, warnings


def mesh_assets(root, context):
    """The ``<asset><mesh>`` elements of a model, by name.

    Every mesh a geom can name, resolved to a file on disk once rather than
    once per geom that uses it. A mesh whose file cannot be found is left out
    and reported when a geom asks for it, so a model with an unused broken
    asset still reads.
    """
    assets = {}
    for asset in root.findall("asset"):
        for mesh in asset.findall("mesh"):
            name = mesh.get("name") or os.path.splitext(os.path.basename(mesh.get("file") or ""))[0]
            if not name:
                continue
            assets[name] = {
                "file": mesh.get("file"),
                "path": mujoco_common.resolve_mesh_path(mesh.get("file"), context["compiler"]),
                "scale": mesh.get("scale"),
            }
    return assets


def geom_physics(attributes, context):
    """What a ``<geom>`` says about its contact, as named PartCAD properties.

    MJCF states friction as three coefficients in one attribute -- sliding,
    torsional and rolling. PartCAD has a property for the first and none for the
    other two, so the first is kept under the name every format states it under
    ('friction' here, ``mu`` in SDFormat, ``mu1`` in URDF) and the other two are
    counted and reported rather than invented properties for.
    """
    values = mujoco_common.numbers(attributes.get("friction"), context["warnings"], "friction")
    if not values:
        return {}
    if len(values) > 1 and any(abs(value) > 0 for value in values[1:]):
        context["dropped"].add("friction")
    return {"friction": values[0]}


def geom_node(attributes, name, context, body_name):
    """The part node for one ``<geom>``, or None when there is no shape in it.

    A mesh is referenced where it lies: the part reads the file the asset
    named, and the geom's own placement becomes the part's location rather than
    a transform applied to a copy of the geometry.
    """
    element = ElementTree.Element("geom", {k: v for k, v in attributes.items() if isinstance(v, str)})
    pose = mujoco_common.parse_pose(element, context["compiler"], context["warnings"])
    kind = (attributes.get("type") or ("mesh" if attributes.get("mesh") else "sphere")).strip()

    node = {
        "type": "part",
        "name": name,
        "body": body_name,
        "link": body_name,
        "scale": 1.0,
    }
    color = mujoco_common.color_hex(attributes.get("rgba"))
    if color:
        node["color"] = color
    physics = geom_physics(attributes, context)
    if physics:
        node["physics"] = physics

    if kind == "mesh":
        asset_name = (attributes.get("mesh") or "").strip()
        asset = context["assets"].get(asset_name)
        if asset is None or not asset.get("path"):
            context["warnings"].append(
                "The geom '%s' names the mesh asset '%s', which has no file PartCAD can find" % (name, asset_name)
            )
            context["dropped"].add("geometry")
            return None
        path = asset["path"]
        extension = os.path.splitext(path)[1].lower()
        part_type = mujoco_common.MESH_PART_TYPES.get(extension)
        if part_type is None:
            context["warnings"].append(
                "'%s' uses the mesh format '%s', which PartCAD cannot read; skipping it" % (name, extension or "<none>")
            )
            context["dropped"].add("geometry")
            return None
        node["part_file"] = os.path.abspath(path)
        node["part_type"] = part_type
        node["scale"] = mujoco_common.mesh_scale_factor(asset.get("scale"), context["warnings"])
        node["location"] = _packed(pose, context)
        return node

    size = mujoco_common.numbers(attributes.get("size"), context["warnings"], "size")
    fromto = mujoco_common.numbers(attributes.get("fromto"), context["warnings"], "fromto")
    mm = mujoco_common.MM_PER_M

    if kind == "box":
        if len(size) != 3:
            context["warnings"].append("A box geom needs three half-sizes, found %d; skipping '%s'" % (len(size), name))
            context["dropped"].add("geometry")
            return None
        # MJCF states half-extents where PartCAD's primitive takes the full ones.
        node["part_file"] = primitive_shapes.write_primitive_step("box", [2.0 * v * mm for v in size], name, context)
        node["part_type"] = "step"
        node["location"] = _packed(pose, context)
        return node

    if kind == "sphere":
        if not size:
            context["warnings"].append("A sphere geom needs a radius; skipping '%s'" % name)
            context["dropped"].add("geometry")
            return None
        node["part_file"] = primitive_shapes.write_primitive_step("sphere", (size[0] * mm,), name, context)
        node["part_type"] = "step"
        node["location"] = _packed(pose, context)
        return node

    if kind == "cylinder":
        if len(fromto) == 6:
            pose, length = _fromto_pose(fromto, context)
            if pose is None:
                context["dropped"].add("geometry")
                return None
        elif len(size) >= 2:
            # MJCF states the half-length, PartCAD's primitive the whole one.
            length = 2.0 * size[1] * mm
        else:
            context["warnings"].append("A cylinder geom needs a radius and a half-length; skipping '%s'" % name)
            context["dropped"].add("geometry")
            return None
        if not size:
            context["warnings"].append("A cylinder geom needs a radius; skipping '%s'" % name)
            context["dropped"].add("geometry")
            return None
        node["part_file"] = primitive_shapes.write_primitive_step("cylinder", (size[0] * mm, length), name, context)
        node["part_type"] = "step"
        node["location"] = _packed(pose, context)
        return node

    if kind in mujoco_common.UNBUILDABLE_GEOMETRY:
        context["warnings"].append(
            "'%s' is a %s geom, which a PartCAD tree has no shape for; skipping it" % (name, kind)
        )
        context["dropped"].add("geometry")
        return None

    context["warnings"].append("'%s' has no geometry PartCAD can read (type '%s'); skipping it" % (name, kind))
    context["dropped"].add("geometry")
    return None


def _fromto_pose(fromto, context):
    """The pose and length of a geom stated as the segment between two points."""
    mm = mujoco_common.MM_PER_M
    start = [v * mm for v in fromto[:3]]
    end = [v * mm for v in fromto[3:6]]
    direction = [end[index] - start[index] for index in range(3)]
    length = math.sqrt(sum(v * v for v in direction))
    if length < 1e-9:
        context["warnings"].append("A 'fromto' states a zero-length segment; skipping the geom")
        return None, 0.0
    centre = tuple((start[index] + end[index]) / 2.0 for index in range(3))
    element = ElementTree.Element("geom", {"zaxis": " ".join(repr(v) for v in direction)})
    rotation = mujoco_common.parse_orientation(element, context["compiler"], context["warnings"])
    return (rotation, centre), length


def _packed(pose, context):
    return urdf_common.round_packed(urdf_common.to_packed(pose), context["precision"])


def body_physics(body, context):
    """What a body says about its own mass and inertia, as PartCAD properties.

    Only ``<inertial>`` is read. Everything else a body carries is about how
    the simulation runs rather than about the thing itself, and PartCAD states
    what a shape *is*.
    """
    inertial = body.find("inertial")
    if inertial is None:
        return {}

    physics = {}
    mass = inertial.get("mass")
    if mass is not None:
        values = mujoco_common.numbers(mass, context["warnings"], "mass")
        if values:
            physics["mass"] = values[0]  # kg, as MJCF states it

    position = mujoco_common.numbers(inertial.get("pos"), context["warnings"], "pos")
    if len(position) == 3 and any(abs(v) > urdf_common.EPSILON for v in position):
        physics["centerOfMass"] = [round(v * mujoco_common.MM_PER_M, 9) for v in position]

    rotation = mujoco_common.parse_orientation(inertial, context["compiler"], context["warnings"])
    rpy = urdf_common.quat_to_rpy(rotation)
    if any(abs(v) > urdf_common.EPSILON for v in rpy):
        physics["inertiaOrientation"] = [round(math.degrees(v), 9) for v in rpy]

    diagonal = mujoco_common.numbers(inertial.get("diaginertia"), context["warnings"], "diaginertia")
    full = mujoco_common.numbers(inertial.get("fullinertia"), context["warnings"], "fullinertia")
    if len(full) == 6:
        # MJCF orders 'fullinertia' as ixx iyy izz ixy ixz iyz.
        ixx, iyy, izz, ixy, ixz, iyz = full
        physics["inertia"] = {"ixx": ixx, "iyy": iyy, "izz": izz, "ixy": ixy, "ixz": ixz, "iyz": iyz}
    elif len(diagonal) == 3:
        physics["inertia"] = {
            "ixx": diagonal[0],
            "iyy": diagonal[1],
            "izz": diagonal[2],
            "ixy": 0.0,
            "ixz": 0.0,
            "iyz": 0.0,
        }
    return physics


def body_node(body, prefix, context, childclass=None, depth=0):
    """One ``<body>`` as a node of the tree, or None when it holds no geometry.

    A body is a container: its geoms and the bodies nested in it are placed
    inside it and it is placed inside whatever holds it. That is exactly a
    PartCAD sub-assembly, so MJCF's nesting and PartCAD's agree and nothing has
    to be flattened. A body whose only content is a single geom *is* that geom,
    named after the body, which is the same rule the other two readers apply.
    """
    if depth > context["max_depth"]:
        context["warnings"].append("Refusing to descend past %d nested bodies" % context["max_depth"])
        return None

    body_name = name_of(body, "body")
    path_name = "%s/%s" % (prefix, body_name) if prefix else body_name
    if path_name in context["seen"]:
        # MJCF requires names to be unique, but an unnamed body has no name to
        # be unique, and this reader gives every one of them the same fallback.
        suffix = 1
        while "%s_%d" % (path_name, suffix) in context["seen"]:
            suffix += 1
        path_name = "%s_%d" % (path_name, suffix)
    context["seen"].add(path_name)

    for kind in ("joint", "freejoint", "site", "camera", "light", "plugin"):
        context["dropped"].add("joint" if kind == "freejoint" else kind, len(body.findall(kind)))

    childclass = body.get("childclass") or childclass
    physics = body_physics(body, context)
    pose = mujoco_common.parse_pose(body, context["compiler"], context["warnings"])

    geoms = body.findall("geom")
    nodes = []
    for index, geom in enumerate(geoms):
        attributes = mujoco_common.geom_attributes(geom, context["classes"], childclass)
        name = path_name if len(geoms) == 1 else "%s/%s" % (path_name, name_of(geom, str(index + 1)))
        node = geom_node(attributes, name, context, body_name)
        if node is not None:
            if physics:
                # Merged rather than assigned: what the body says about its mass
                # and what the geom says about its contact are different facts
                # about the same shape, and the geom has already stated its own.
                node["physics"] = dict(node.get("physics") or {}, **physics)
            nodes.append(node)

    children = []
    for nested in body.findall("body"):
        node = body_node(nested, path_name, context, childclass, depth + 1)
        if node is not None:
            children.append(node)

    if not nodes and not children:
        return None

    if len(nodes) == 1 and not children:
        node = nodes[0]
        node["location"] = urdf_common.round_packed(
            urdf_common.to_packed(urdf_common.compose(pose, urdf_common.from_packed(node["location"]))),
            context["precision"],
        )
        return node

    group = {
        "type": "assembly",
        "name": path_name,
        "body": body_name,
        "link": body_name,
        "location": _packed(pose, context),
        "links": nodes + children,
    }
    if physics:
        group["physics"] = physics
    return group


def process(request):
    model_file = request["mjcf_file"]
    if not os.path.isfile(model_file):
        raise FileNotFoundError(model_file)

    try:
        root, warnings = load(model_file)
    except ElementTree.ParseError as e:
        raise ValueError("%s: %s" % (model_file, e)) from e

    if root.tag != "mujoco":
        raise ValueError("%s: the root element is <%s>, not <mujoco>" % (model_file, root.tag))

    # Where relative mesh paths are resolved from. Not the rendered file's own
    # directory: a template is rendered into PartCAD's state directory, and the
    # assets it names sit beside the file the package declared.
    base_dir = request.get("base_dir") or os.path.dirname(os.path.abspath(model_file))

    compiler = mujoco_common.Compiler(model_dir=base_dir)
    for element in root.findall("compiler"):
        compiler.update(element)

    context = {
        "compiler": compiler,
        "base_dir": base_dir,
        "output_folder": request["output_folder"],
        "precision": request.get("precision", 6),
        "max_depth": request.get("max_depth", 16),
        "warnings": list(warnings),
        "dropped": Dropped(),
        "classes": mujoco_common.collect_defaults(root),
        "primitives": {},
        "written": set(),
        "unplaced": [],
        "seen": set(),
    }
    context["assets"] = mesh_assets(root, context)

    for section, key in (
        ("actuator", "actuator"),
        ("tendon", "tendon"),
        ("equality", "equality"),
        ("contact", "contact"),
        ("sensor", "sensor"),
        ("keyframe", "keyframe"),
        ("extension", "plugin"),
    ):
        for element in root.findall(section):
            context["dropped"].add(key, max(1, len(list(element))))

    model_name = (root.get("model") or "").strip() or os.path.splitext(os.path.basename(model_file))[0]

    children = []
    for worldbody in root.findall("worldbody"):
        for kind in ("light", "camera", "site"):
            context["dropped"].add(kind, len(worldbody.findall(kind)))
        # A geom directly in the worldbody is the world's own shape - a floor,
        # a wall - and is placed exactly like a body with one geom.
        for index, geom in enumerate(worldbody.findall("geom")):
            attributes = mujoco_common.geom_attributes(geom, context["classes"], None)
            name = name_of(geom, "world/%d" % (index + 1))
            context["seen"].add(name)
            node = geom_node(attributes, name, context, "world")
            if node is not None:
                children.append(node)
        for body in worldbody.findall("body"):
            node = body_node(body, "", context)
            if node is not None:
                children.append(node)

    if not children and not context["unplaced"]:
        raise ValueError("No geometry found in %s" % model_file)

    return {
        "root": {
            "type": "assembly",
            "name": model_name,
            "location": urdf_common.to_packed(mujoco_common.IDENTITY),
            "links": children,
            "parts": context["unplaced"],
        },
        "model_name": model_name,
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
