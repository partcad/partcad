#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in MJCF (MuJoCo) exporter (see '//builtin/export' in partcad.yaml).

Writes a PartCAD scene -- or an assembly, or any other shape -- as an MJCF
``.xml`` model plus the mesh files it references. MJCF is what MuJoCo describes
a model in, and this is the format `pc sim` hands a scene over in: a simulation
plugin is given a file, and for the MuJoCo plugin that file is this one.

Like the URDF and world exporters beside it, this one is handed the assembly
*tree* itself rather than the geometry it decodes to -- which is what
``decode: false`` on this format's declaration asks for, see
wrapper_export.DECODE_KEY. Decoding would keep the tree's shape and nothing
else about it: every node's ``name`` and ``label`` is dropped and its placement
is baked into the geometry rather than staying readable as data, and the bodies,
their poses and their properties are built from all three.

The mapping is the reverse of the MJCF reader's (wrapper_import_mjcf):

  * the exported object is the ``<mujoco>`` model,
  * anything placed in it is a ``<body>``, nested exactly as the tree nests,
  * a node that is geometry contributes a ``<geom type="mesh">`` referencing a
    mesh written next to the model file.

Three things this exporter decides that the file does not say, because a static
arrangement does not say them and a *simulation* needs all three:

  * **What moves.** MuJoCo bodies are welded to the world unless they carry a
    joint, so ``static: true`` (the default, and what a scene means) writes no
    joints at all. ``static: false`` gives every movable unit a ``<freejoint>``,
    which is what makes a simulation of one worth running.
  * **What a movable unit is.** With ``flatten: true`` every node that holds
    geometry becomes a body of its own directly in the ``<worldbody>``, at the
    world pose the tree puts it at. Without it the bodies nest as the tree does
    -- and a nested body with no joint between it and its parent is one rigid
    body with it, which is right for a rigid product and wrong for a stack of
    blocks that is meant to be able to fall over.
  * **What it stands on.** ``ground_plane`` and ``light`` are not part of what
    the scene says; they are what makes the model usable, the same way the world
    exporter's ``sun`` and ``ground_plane`` are. The plane is a ``<geom>`` of
    the ``<worldbody>`` itself, so it is static whatever ``static`` says.

Two conventions are shared with the other two exporters and are what makes the
round trip close: meshes are written in millimetres -- the unit PartCAD uses
everywhere -- and referenced with ``scale="0.001 0.001 0.001"``, which is how
MJCF says "these coordinates are millimetres"; and geometry is written in its
own frame and placed by the element that holds it, so a shape that appears more
than once is written once and referenced by every geom that uses it.

Note that MuJoCo reads **binary** STL only, which is why ``ascii`` defaults to
false here and an ``ascii: true`` is reported rather than quietly written.
"""

import math
import os
import re
import sys
from xml.etree import ElementTree

# Pinned before anything that may pull OCP - see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import mujoco_common  # noqa: E402
import ocp_serialize  # noqa: E402
import urdf_common  # noqa: E402

# Metres per millimetre, for the mesh ``scale``: the meshes are written in
# millimetres and MJCF reads mesh coordinates as metres after scaling.
MESH_SCALE = 1.0 / urdf_common.MM_PER_M

# Density used when a part does not state a mass, in kg/m^3. Aluminium, the
# same default the URDF and world exporters use and for the same reason: a
# middle-of-the-road value for a machined part, whose provenance is obvious in
# the output rather than looking like a measurement.
DEFAULT_DENSITY = 2700.0

# MJCF names end up as XML attributes and are referenced by name from geoms and
# from the simulation's own output, so anything outside this set is replaced.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")

# PartCAD property -> the ``<geom>`` attribute that states it, and how to write
# it. MJCF states friction as one attribute holding three coefficients, so the
# sliding one -- which is what PartCAD's 'friction' is -- is filled in beside
# MuJoCo's own defaults for the other two.
GEOM_PHYSICS = {
    "friction": ("friction", lambda v: mujoco_common.format_numbers([float(v), 0.005, 0.0001], 6)),
    "restitution": ("solref", lambda v: _solref_for_restitution(float(v))),
}

# Every part property this exporter has an MJCF spelling for. A 'physics'
# property outside this set is one PartCAD supports and MJCF does not: it is
# reported through the response and logged at info level, which is the mirror
# image of the reader reporting what it cannot keep.
MJCF_STATED = frozenset(("mass", "centerOfMass", "inertiaOrientation", "inertia", "friction", "restitution"))


def _solref_for_restitution(restitution):
    """MuJoCo's ``solref`` for a coefficient of restitution, or None.

    MuJoCo states contact softness as a (time constant, damping ratio) pair
    rather than as a restitution, and a damping ratio below one is what makes a
    contact bounce. The mapping is not exact -- nothing in MuJoCo is a
    restitution -- so it is only written for a part that states one, and only
    as the damping ratio the value most nearly means.
    """
    restitution = max(0.0, min(1.0, restitution))
    if restitution <= 0.0:
        return None
    return mujoco_common.format_numbers([0.02, max(0.01, 1.0 - restitution)], 6)


def sanitize_name(name, fallback):
    """An MJCF-safe name derived from a PartCAD name.

    PartCAD names carry package paths and ':' separators ("//pub/examples:logo")
    and the '/' that groups a link's own shapes, none of which belong in a name
    that a geom, a sensor or a keyframe refers to.

    A parameterized object's name also carries its parameter values, after a
    ';'. Those are dropped rather than spelled out: `pc sim` runs a scene whose
    subject *is* a parameter, so keeping them would make the model's name a
    transcription of the whole declaration -- and a name is read, not parsed.
    Which instance it is is what the run is about and is reported beside the
    file, not smuggled into it.
    """
    name = str(name or "").partition(";")[0]
    name = _UNSAFE_NAME.sub("_", name).strip("_")
    return name or fallback


class NameAllocator:
    """Hands out unique names, since MJCF requires them within an element type.

    Unique across the whole document rather than per type: that satisfies the
    requirement everywhere at once, and it keeps the names readable in what a
    simulation reports, which is where they are read from.
    """

    def __init__(self):
        self.used = set()

    def take(self, name, fallback="body"):
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
    pose of the element above the geometry, not part of the geometry.
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


def mesh_asset(shape, node, body_name, state):
    """Write 'shape' out as a mesh (or reuse one) and return the asset's name.

    An identical shape used twice - a repeated fastener, a row of blocks -
    shares one mesh file and one ``<asset><mesh>``, the way a model written by
    hand would.
    """
    key = node.get(ocp_serialize.KEY_BREP)
    asset_name = state["meshes"].get(key)
    if asset_name is not None:
        return asset_name

    asset_name = state["mesh_names"].take(node.get("label") or body_name, "mesh")
    write_mesh(shape, os.path.join(state["mesh_dir"], "%s.stl" % asset_name), state["options"])
    mesh = ElementTree.SubElement(state["asset"], "mesh")
    mesh.set("name", asset_name)
    mesh.set("file", "%s/%s.stl" % (state["mesh_dir_name"], asset_name))
    mesh.set("scale", mujoco_common.format_numbers((MESH_SCALE,) * 3, 6))
    state["meshes"][key] = asset_name
    return asset_name


def shape_elements(node):
    """The (shape node, placement) pairs one body is built from, and its children.

    Usually a node is one shape and that is the whole of it. A sub-assembly
    whose children are named *under* it - "wrist" holding "wrist/1" and
    "wrist/2" - is one thing made of several shapes, and goes back out as one
    body with several ``<geom>`` elements rather than as a body per shape.

    The slash is the whole of the rule, and it is the only hierarchy PartCAD
    encodes in a name. It is the same rule the URDF and world exporters apply,
    and the same one all three readers write.
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


def carried_inertial(physics):
    """The ``<inertial>`` values a part states about itself, or None.

    Only what the part actually says. Nothing is computed here, unlike in the
    URDF and world exporters: MuJoCo computes a body's inertia from its geoms
    and their density perfectly well, and an inertia tensor computed here and
    rounded on the way out can fail MuJoCo's positive-definiteness check and
    take the whole model with it. So a part that states its mass gets its mass,
    and a part that does not gets the density instead (see 'emit_geom').
    """
    if "mass" not in physics:
        return None
    values = {"mass": float(physics["mass"])}
    if "centerOfMass" in physics:
        values["centerOfMass"] = [float(v) for v in physics["centerOfMass"]]
    if "inertiaOrientation" in physics:
        values["inertiaOrientation"] = [float(v) for v in physics["inertiaOrientation"]]
    inertia = physics.get("inertia")
    if isinstance(inertia, dict) and any(abs(float(inertia.get(key, 0.0))) > 0 for key in ("ixx", "iyy", "izz")):
        values["inertia"] = {key: float(inertia.get(key, 0.0)) for key in ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")}
    return values


def write_inertial(body, values):
    """Write one body's ``<inertial>`` from the values a part stated."""
    if values is None:
        return
    inertial = ElementTree.SubElement(body, "inertial")
    centre = values.get("centerOfMass") or (0.0, 0.0, 0.0)
    inertial.set("pos", mujoco_common.format_numbers([v / urdf_common.MM_PER_M for v in centre]))
    inertial.set("mass", mujoco_common.format_numbers([values["mass"]]))
    orientation = values.get("inertiaOrientation")
    if orientation:
        rotation = urdf_common.rpy_to_quat([math.radians(v) for v in orientation])
        inertial.set("quat", mujoco_common.format_numbers(rotation))
    inertia = values.get("inertia")
    if inertia:
        # MJCF orders 'fullinertia' as ixx iyy izz ixy ixz iyz.
        inertial.set(
            "fullinertia",
            mujoco_common.format_numbers(
                [inertia["ixx"], inertia["iyy"], inertia["izz"], inertia["ixy"], inertia["ixz"], inertia["iyz"]]
            ),
        )
    else:
        # MuJoCo needs one of the two, and a body that states a mass and no
        # tensor is a point mass as far as the file is concerned. A tiny
        # diagonal keeps it a body rather than making it singular.
        inertial.set("diaginertia", mujoco_common.format_numbers([1e-6, 1e-6, 1e-6]))


def emit_geom(body, shape_node, placement, asset_name, physics, state, index):
    """Add one ``<geom>`` to a body, with what its part says about itself."""
    geom = ElementTree.SubElement(body, "geom")
    geom.set("name", state["geom_names"].take("%s_geom_%d" % (body.get("name"), index), "geom"))
    geom.set("type", "mesh")
    geom.set("mesh", asset_name)
    if placement is not None:
        pose = urdf_common.from_packed(placement)
        if not urdf_common.is_identity(pose):
            geom.set("pos", mujoco_common.format_pos(pose))
            geom.set("quat", mujoco_common.format_quat(pose))

    properties = state["properties"].get(shape_node.get("name")) or {}
    rgba = mujoco_common.color_rgba(properties.get("color"))
    if rgba is not None:
        geom.set("rgba", rgba)

    if "mass" in physics:
        # Stated on the body's '<inertial>' rather than here: a body made of
        # several geoms would otherwise carry its whole mass once per geom.
        pass
    else:
        geom.set("density", mujoco_common.format_numbers([state["options"]["density"]], 6))

    for name, (attribute, render) in GEOM_PHYSICS.items():
        if name not in physics:
            continue
        value = render(physics[name])
        if value is not None:
            geom.set(attribute, value)
    return geom


def emit_body(parent, node, pose, elements, children_present, state):
    """Add one ``<body>``, with a geom per shape it holds. Returns the element."""
    body_name = state["body_names"].take(node.get("label") or node.get("name"), "body")
    body = ElementTree.SubElement(parent, "body")
    body.set("name", body_name)
    if not urdf_common.is_identity(pose):
        body.set("pos", mujoco_common.format_pos(pose))
        body.set("quat", mujoco_common.format_quat(pose))

    physics = (state["properties"].get(node.get("name")) or {}).get("physics") or {}
    inertial = carried_inertial(physics)
    if inertial is not None:
        write_inertial(body, inertial)

    if not state["options"]["static"] and parent.tag == "worldbody":
        # What makes a simulation of this model worth running: a body with no
        # joint is welded to the world and can neither fall nor be pushed.
        ElementTree.SubElement(body, "freejoint")

    written = 0
    for index, (shape_node, placement) in enumerate(elements):
        shape = node_geometry(shape_node)
        if shape is None:
            continue
        asset_name = mesh_asset(shape, shape_node, body_name, state)
        emit_geom(body, shape_node, placement, asset_name, physics, state, index)
        written += 1

    if not written and not children_present:
        # A frame with nothing in it and nothing under it. MuJoCo accepts an
        # empty body, but it is noise in the model and in what a simulation
        # reports, so it goes back out.
        parent.remove(body)
        state["body_names"].used.discard(body_name)
        return None

    state["unsupported"].update(set(physics) - MJCF_STATED)
    return body


def emit_nested(node, parent, pose, state):
    """Add 'node' and its subtree under 'parent', mirroring the tree's nesting."""
    elements, children = shape_elements(node)
    body = emit_body(parent, node, pose, elements, bool(children), state)
    if body is None:
        return
    for child in children:
        emit_nested(child, body, urdf_common.from_packed(child.get(ocp_serialize.KEY_LOCATION)), state)


def emit_flat(node, worldbody, pose, state):
    """Add every node that holds geometry as a body of the ``<worldbody>`` itself.

    Each one is placed at the world pose the tree puts it at, so the arrangement
    is unchanged -- what changes is that the bodies are now independent of each
    other, which is what lets them move independently. See the module docstring.
    """
    elements, children = shape_elements(node)
    if elements:
        emit_body(worldbody, node, pose, elements, False, state)
    for child in children:
        emit_flat(
            child,
            worldbody,
            urdf_common.compose(pose, urdf_common.from_packed(child.get(ocp_serialize.KEY_LOCATION))),
            state,
        )


def add_ground_plane(worldbody, state):
    """The floor the model stands on: a static plane, and MuJoCo's own default."""
    geom = ElementTree.SubElement(worldbody, "geom")
    geom.set("name", state["geom_names"].take("ground_plane", "ground_plane"))
    geom.set("type", "plane")
    geom.set("size", "0 0 0.05")
    geom.set("pos", "0 0 0")
    geom.set("rgba", "0.8 0.8 0.8 1")
    geom.set("condim", "3")


def add_light(worldbody):
    """The light a model needs to be looked at. It affects nothing physical."""
    light = ElementTree.SubElement(worldbody, "light")
    light.set("name", "sun")
    light.set("directional", "true")
    light.set("pos", "0 0 10")
    light.set("dir", "-0.5 0.1 -0.9")
    light.set("diffuse", "0.8 0.8 0.8")
    light.set("specular", "0.2 0.2 0.2")


def process(path, request):
    root = request["wrapped"]
    if not isinstance(root, dict) or not (
        ocp_serialize.is_shape_object(root) or ocp_serialize.is_assembly_object(root)
    ):
        raise ValueError("The MJCF exporter needs a shape or an assembly to export")

    model_dir = os.path.dirname(os.path.abspath(path)) or "."
    stem = os.path.splitext(os.path.basename(path))[0] or "model"
    model_name = sanitize_name(request.get("model_name") or root.get("label") or stem, stem)
    mesh_dir_name = request.get("mesh_dir") or "%s_meshes" % stem
    mesh_dir = os.path.join(model_dir, mesh_dir_name)
    os.makedirs(mesh_dir, exist_ok=True)

    warnings = []
    if request.get("ascii", False):
        warnings.append("MuJoCo reads binary STL only; 'ascii: true' produces meshes it will refuse to load")

    mujoco = ElementTree.Element("mujoco")
    mujoco.set("model", model_name)
    # Radians, so that what is written needs no <compiler> to be read back the
    # way it was meant -- MJCF's own default is degrees, and every angle here
    # is a quaternion anyway.
    compiler = ElementTree.SubElement(mujoco, "compiler")
    compiler.set("angle", "radian")
    option = ElementTree.SubElement(mujoco, "option")
    option.set("gravity", mujoco_common.format_numbers(request.get("gravity") or (0.0, 0.0, -9.81), 6))
    if request.get("timestep"):
        option.set("timestep", mujoco_common.format_numbers([request["timestep"]], 6))
    asset = ElementTree.SubElement(mujoco, "asset")
    worldbody = ElementTree.SubElement(mujoco, "worldbody")

    state = {
        "asset": asset,
        "body_names": NameAllocator(),
        "geom_names": NameAllocator(),
        "mesh_names": NameAllocator(),
        "meshes": {},
        "mesh_dir": mesh_dir,
        "mesh_dir_name": mesh_dir_name,
        # Shape full name -> the properties its part declares ('physics',
        # 'material', 'color'). A part that came from a URDF, a world or an
        # MJCF model states its mass and friction here, and they go back out
        # rather than being recomputed.
        "properties": request.get("properties") or {},
        "unsupported": set(),
        "options": {
            "tolerance": request.get("tolerance", 0.1),
            "angularTolerance": request.get("angularTolerance", 0.1),
            "ascii": request.get("ascii", False),
            "density": request.get("density") or DEFAULT_DENSITY,
            "static": request.get("static", True),
        },
        "warnings": warnings,
    }

    if request.get("light", True):
        add_light(worldbody)
    if request.get("ground_plane", True):
        add_ground_plane(worldbody, state)

    emit = emit_flat if request.get("flatten", False) else emit_nested
    root_pose = urdf_common.from_packed(root.get(ocp_serialize.KEY_LOCATION))
    if ocp_serialize.is_shape_object(root):
        emit(root, worldbody, root_pose, state)
    else:
        # The exported object *is* the model, so its children are its top-level
        # bodies, each carrying the exported object's own placement on top of
        # its own.
        for child in root.get(ocp_serialize.KEY_ASSEMBLY) or []:
            child_pose = urdf_common.compose(root_pose, urdf_common.from_packed(child.get(ocp_serialize.KEY_LOCATION)))
            emit(child, worldbody, child_pose, state)

    if not state["meshes"]:
        warnings.append("Nothing was exported: the object holds no geometry MJCF can reference")

    ElementTree.indent(mujoco, space="  ")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" ?>\n')
        f.write(ElementTree.tostring(mujoco, encoding="unicode"))
        f.write("\n")

    return {
        "success": True,
        "exception": None,
        "model_name": model_name,
        "mesh_dir": mesh_dir,
        "meshes": sorted("%s/%s.stl" % (mesh_dir_name, name) for name in set(state["meshes"].values())),
        "warnings": warnings,
        # Properties PartCAD holds and MJCF cannot state. Reported at info level
        # by the caller: nothing is wrong with the file, it just says less than
        # the package does.
        "unsupported": sorted(state["unsupported"]),
    }
