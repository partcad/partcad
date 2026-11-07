#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment to read a glTF
# file -- '.gltf' with its buffers beside it, or a single '.glb' -- as a part.
#
# 'gltf_document' reads the file: every mesh the scene draws, where its nodes
# put it, and its materials, including what the web's compression extensions
# (Draco, meshoptimizer, quantization, GPU instancing) store. Each mesh is then
# made into bodies by 'mesh_brep' -- a solid per closed piece, a shell per open
# one -- in PartCAD's millimetres and Z-up, and the part is all of them. A mesh a
# file draws many times is built once and placed many times.
#
# Each face is in the colour of its triangle's material, stated in the part's
# CMF section in glTF's own terms (convention 'gltf': the material's name, its
# display, its roughness and metallic), or in PartCAD's own where PartCAD wrote
# the file (the references 'export_gltf' keeps in the material's 'extras').

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

import numpy as np

sys.path.append(os.path.dirname(__file__))
import cmf_capture
import gltf_document
import mesh_brep
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again -- and with any change to what 'gltf_document',
# 'meshopt_decode' or 'mesh_brep' read or build, whose output this is. 2: read
# by PartCAD's own reader rather than OCCT's, a body per piece, and the
# materials' colours.
CACHE_VERSION = 2

CONVENTION = "gltf"

# The references PartCAD's own glTF export keeps in a material's 'extras' (see
# 'builtin/export/export_gltf.py').
_EXTRAS_KEY = "partcad"


def srgb(channel: float) -> int:
    """A linear glTF factor, 0 to 1, as the sRGB byte a display is stated in (IEC 61966-2-1)."""
    channel = min(max(float(channel), 0.0), 1.0)
    value = channel * 12.92 if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
    return int(round(value * 255))


def cmf_set_of(material):
    """What a glTF material states, as a CMF set in the terms it was stated in; None if it states nothing."""
    import cmf_section

    if material is None:
        return None
    rgba = None
    if material.rgba is not None:
        rgba = tuple(srgb(channel) for channel in material.rgba[:3]) + (round(float(material.rgba[3]), 6),)
    references = material.extras.get(_EXTRAS_KEY)
    if isinstance(references, dict):
        said = {key: references.get(key) for key in ("color", "material", "finish")}
        said = {key: value for key, value in said.items() if isinstance(value, str) and value}
        if said:
            return cmf_section.CmfSet(
                **said,
                rgba=rgba,
                roughness=material.roughness,
                metallic=material.metallic,
                origin=cmf_capture.PARTCAD,
            )
    # What glTF calls an appearance is its material, by name; one with no name
    # is the colour it draws, as a 3MF's is, and one with neither says nothing.
    designation = material.name or ("#%02X%02X%02X" % rgba[:3] if rgba is not None else None)
    if designation is None:
        return None
    return cmf_section.CmfSet(
        color=designation,
        rgba=rgba,
        roughness=material.roughness,
        metallic=material.metallic,
        # The part's 'cmfConvention', if it names one, is applied by the core.
        origin="raw:" + CONVENTION,
    )


def _merged(document, mesh_index, stretch):
    """'(points, triangles, material of each triangle)' of a mesh, every primitive in one, made with 'stretch'."""
    points, triangles, materials = [], [], []
    offset = 0
    for primitive in document.primitives(mesh_index):
        points.append(primitive.positions @ stretch.T)
        triangles.append(primitive.triangles + offset)
        materials.append(np.full(len(primitive.triangles), -1 if primitive.material is None else primitive.material))
        offset += len(primitive.positions)
    if not points:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
    return np.vstack(points), np.vstack(triangles), np.concatenate(materials)


def _location(rotation, translation):
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    trsf = gp_Trsf()
    trsf.SetValues(
        *(float(rotation[0, column]) for column in range(3)),
        float(translation[0]),
        *(float(rotation[1, column]) for column in range(3)),
        float(translation[1]),
        *(float(rotation[2, column]) for column in range(3)),
        float(translation[2]),
    )
    return TopLoc_Location(trsf)


def read(path):
    """'(shape, CMF section, warnings)' of the glTF file at 'path'.

    A mesh is split into pieces ('mesh_brep.split'), and a piece that closes on
    its own is a body, built once however many times the scene draws it. The
    pieces that do not are put together, every copy where the scene puts it,
    and split again: a body a file draws as several meshes - a mesh per colour,
    as PartCAD's own export and OCCT's writer draw one - is one body again,
    while two closed bodies that touch stay two.
    """
    import cmf_section
    import ocp_serialize
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    document = gltf_document.Document(path)
    built = {}
    shapes = []
    # Every body that becomes part of the shape, with its faces' materials.
    colored = []
    loose_points, loose_triangles, loose_materials = [], [], []
    loose_count = 0
    dropped_triangles = 0
    for node, world in document.placed_meshes():
        rotation, translation, stretch = gltf_document.decompose(gltf_document.TO_PARTCAD @ world)
        # A mesh drawn twice alike is built once: what the node stretches it by
        # is part of what it is, where the node puts it is not.
        key = (node.mesh, tuple(np.round(stretch, 9).reshape(-1)))
        if key not in built:
            points, triangles, materials = _merged(document, node.mesh, stretch)
            welded, pieces, dropped = mesh_brep.split(points, triangles)
            dropped_triangles += dropped
            closed = []
            loose = []
            for piece in pieces:
                if piece.closed:
                    body = mesh_brep.build(welded, piece)
                    closed.append(body)
                    colored.append((body, materials[body.triangles]))
                else:
                    used, local = np.unique(piece.oriented, return_inverse=True)
                    loose.append((welded[used], local.reshape(-1, 3), materials[piece.triangles]))
            built[key] = (closed, loose)
        closed, loose = built[key]
        if closed:
            location = _location(rotation, translation)
            shapes.extend(body.shape.Moved(location) for body in closed)
        for points, triangles, materials in loose:
            loose_points.append(points @ rotation.T + translation)
            loose_triangles.append(triangles + loose_count)
            loose_materials.append(materials)
            loose_count += len(points)

    open_pieces = 0
    if loose_points:
        materials = np.concatenate(loose_materials)
        bodies, dropped = mesh_brep.bodies(np.vstack(loose_points), np.vstack(loose_triangles))
        dropped_triangles += dropped
        for body in bodies:
            shapes.append(body.shape)
            colored.append((body, materials[body.triangles]))
            open_pieces += not body.closed

    if not shapes:
        raise RuntimeError("The glTF file draws no triangles")
    if len(shapes) == 1:
        shape = shapes[0]
    else:
        shape = ocp_serialize.compound_of(shapes)

    # Each body's faces in the colours of their triangles' materials, said of
    # the body as it was built: 'section_for' finds it wherever it was placed.
    # A CMF material is a solid's, not a face's, so what the faces' sets say of
    # one is said of the solid they bound, when they agree on it.
    cmf_capture.reset()
    sets = {}
    builder = BRep_Builder()
    for body, of_faces in colored:
        present = []
        for material_index in np.unique(of_faces).tolist():
            if material_index < 0:
                continue
            if material_index not in sets:
                sets[material_index] = cmf_set_of(document.material(material_index))
            if sets[material_index] is not None:
                present.append(material_index)
        if len(present) == 1 and np.all(of_faces == present[0]):
            cmf_capture._note(body.shape, sets[present[0]], 0)
            continue
        solid_materials = {sets[material_index].material for material_index in present}
        agreed = solid_materials.pop() if len(solid_materials) == 1 else None
        if present and set(np.unique(of_faces).tolist()) <= set(present):
            # Every face is in a set: the commonest is the body's, as a part
            # PartCAD made states it, and the other faces say their own.
            counts = {material_index: int(np.sum(of_faces == material_index)) for material_index in present}
            commonest = max(present, key=lambda material_index: (counts[material_index], -material_index))
            said = sets[commonest]
            cmf_capture._note(body.shape, said if agreed is not None else said.without(("material",)), 0)
            others = [material_index for material_index in present if material_index != commonest]
        else:
            # Some faces are in no set, and must not take on the body's.
            others = present
            if agreed is not None:
                material = cmf_section.CmfSet(material=agreed, origin=sets[present[0]].origin)
                cmf_capture._note(body.shape, material, 0)
        for material_index in others:
            faces = TopoDS_Compound()
            builder.MakeCompound(faces)
            for face_index in np.nonzero(of_faces == material_index)[0]:
                builder.Add(faces, body.faces[face_index])
            cmf_capture._note(faces, sets[material_index].without(("material",)), 0)
    section = cmf_capture.section_for(shape)

    warnings = gltf_document.warnings_of(document.dropped)
    if dropped_triangles:
        warnings.append(
            "%d triangle(s) bound nothing - corners at one place or on one line - and are left out" % dropped_triangles
        )
    if open_pieces:
        warnings.append(
            "%d piece(s) of the mesh are open - an edge with no triangle on its other side - and are read as"
            " surfaces, not solids" % open_pieces
        )
    return shape, section, warnings


def process(path, request):
    try:
        try:
            shape, section, warnings = read(path)
        except gltf_document.GltfError as e:
            raise RuntimeError("Failed to read the glTF file: %s" % e) from None
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e), "shape": None}

    return {
        "success": True,
        "exception": None,
        # Validated and moved here, while it is live (see wrapper_common.finished).
        "shape": wrapper_common.finished(shape, cmf=section),
        "warnings": warnings,
    }


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    result = process(path, request)
    wrapper_common.handle_output(result)
