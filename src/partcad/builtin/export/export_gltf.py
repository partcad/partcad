#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in glTF exporter (see '//builtin/export' in partcad.yaml).

A part's CMF is written as glTF writes appearance: a material per primitive.
The faces of one CMF set (see 'cmf_export') are made one piece, and each piece
gets the material of its set - named after its colour, material and finish, its
display as 'baseColorFactor' (linear, as glTF's factors are; a display is sRGB),
its finish's roughness and metallic, and PartCAD's references under the
material's 'extras', where glTF keeps what an application says of its own
(docs/design/cmf.md, section 9). So a part of one colour is one mesh still, and a
part of two is a mesh per colour, as the IDE draws it (see 'wrapper_gltf._colored').

OCCT's writer makes a material of a colour and nothing else, and makes one
material of two sets drawn alike. So the writer is handed each set in a colour of
its own, made up to tell it apart ('_tag'), and each material that comes out is
replaced by the set's own afterwards ('_materials'). A shape that states no CMF
is written exactly as it was before.
"""

import json
import os
import sys

# Imported before build123d, which reaches OCP and VTK: see the note in
# ocp_serialize about VTK's bundled expat shadowing the standard library's.
sys.path.append(os.path.dirname(__file__))
import wrapper_common

import build123d as b3d

# What this implementation reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again. 2: a material per CMF set.
CACHE_VERSION = 2

# Declares no TESSELLATION (see 'wrapper_export.TESSELLATION_NAME'), though it
# meshes the way the STL and 3MF exporters do: build123d turns the shape to
# glTF's Y-up before meshing it, and a relative mesh of the turned shape is not
# the mesh of the shape as it lies, by a few triangles. So this file is written
# from a decoding of its own, and comes out as it does on its own.


def _tag(index):
    """The made-up colour set 'index' is handed to the writer in: its number, plus one, in 24 bits."""
    value = index + 1
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def _untag(factor):
    """The set a material the writer made of a '_tag' colour is of, or None.

    A build123d colour is sRGB, and the writer writes it as glTF's linear
    factor, so the factor is turned back into the bytes it was made of.
    """
    if not isinstance(factor, (list, tuple)) or len(factor) < 3:
        return None
    try:
        red, green, blue = (_byte_of_linear(float(channel)) for channel in factor[:3])
    except (TypeError, ValueError):
        return None
    return ((red << 16) | (green << 8) | blue) - 1


def _byte_of_linear(value) -> int:
    """A linear value from 0 to 1 as the sRGB byte it is (IEC 61966-2-1): the inverse of 'cmf_export.linear'."""
    value = max(0.0, min(1.0, value))
    encoded = value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return int(round(encoded * 255))


def _pieces(request, warnings):
    """'(compound, sets)': the shape as a child per piece of one set, and the sets in the order their tags count.

    None when nothing in the tree states CMF: the shape is then written whole,
    as it always was.
    """
    import cmf_export
    import ocp_serialize

    tree = request.get("shape_tree")
    if tree is None or not cmf_export.carries_cmf(tree):
        return None
    sets, keys, children = [], {}, []
    memo = {}
    # The pieces of each geometry, made once however often it is placed, so
    # that the writer still writes one mesh of a part placed a hundred times.
    made = {}
    for leaf in cmf_export.leaves(tree, warnings):
        payload = leaf.node[ocp_serialize.KEY_BREP]
        made_key = (
            payload if isinstance(payload, (str, bytes)) else bytes(payload),
            leaf.node.get(ocp_serialize.KEY_CHILD),
            leaf.color,
        )
        if made_key not in made:
            made[made_key] = [
                (cmf_set, ocp_serialize.compound_of([piece]))
                for cmf_set, piece in cmf_export.groups(leaf.definition, cmf_export.face_sets(leaf, memo))
            ]
        for cmf_set, piece in made[made_key]:
            child = b3d.Compound(leaf.placed(piece))
            if not cmf_export.is_plain(cmf_set):
                key = cmf_export.appearance_key(cmf_set)
                if key not in keys:
                    keys[key] = len(sets)
                    sets.append(cmf_set)
                red, green, blue = _tag(keys[key])
                child.color = b3d.Color(red / 255.0, green / 255.0, blue / 255.0, 1.0)
            children.append(child)
    if not sets:
        return None
    return b3d.Compound(children=children), sets


def material_of(cmf_set, written=None):
    """The glTF material a set is: what the writer wrote for it ('written'), with the set's own appearance."""
    import cmf_export

    material = dict(written or {})
    material["name"] = cmf_export.display_name(cmf_set)
    pbr = dict(material.get("pbrMetallicRoughness") or {})
    if cmf_set.rgba is not None:
        red, green, blue, alpha = cmf_set.rgba
        pbr["baseColorFactor"] = [round(cmf_export.linear(channel), 6) for channel in (red, green, blue)] + [
            round(float(alpha), 6)
        ]
        if alpha < 1:
            material["alphaMode"] = "BLEND"
        else:
            material.pop("alphaMode", None)
    else:
        pbr.pop("baseColorFactor", None)
    if cmf_set.roughness is not None:
        pbr["roughnessFactor"] = round(float(cmf_set.roughness), 6)
    if cmf_set.metallic is not None:
        pbr["metallicFactor"] = round(float(cmf_set.metallic), 6)
    material["pbrMetallicRoughness"] = pbr
    references = {key: getattr(cmf_set, key) for key in ("color", "material", "finish") if getattr(cmf_set, key)}
    if references:
        extras = dict(material.get("extras") or {})
        extras["partcad"] = references
        material["extras"] = extras
    return material


def _materials(meta, sets):
    """'meta' (a glTF's JSON) with each material the writer made of a set's tag replaced by the set's own."""
    materials = meta.get("materials") or []
    for index, material in enumerate(materials):
        found = _untag((material.get("pbrMetallicRoughness") or {}).get("baseColorFactor"))
        if found is not None and 0 <= found < len(sets):
            materials[index] = material_of(sets[found], material)
    return meta


def _rewrite(path, binary, sets):
    """Give the materials of the glTF at 'path' their sets' appearance, in place."""
    import wrapper_gltf

    if binary:
        with open(path, "rb") as f:
            meta, buffer = wrapper_gltf._read_glb(f.read())
        with open(path, "wb") as f:
            f.write(wrapper_gltf._write_glb(_materials(meta, sets), buffer))
        return
    with open(path, encoding="utf-8") as f:
        meta = json.load(f)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_materials(meta, sets), f, separators=(",", ":"))


def process(path, request):
    try:
        obj = request.get("wrapped")
        if obj is None:
            raise ValueError("No wrapped object provided for GLTF export")

        warnings = []
        pieces = _pieces(request, warnings)
        if pieces is None:
            # The caller sends raw OCCT geometry, so rebuild the build123d wrapper that
            # export_gltf() needs. 'cast' picks the matching type, which matters here
            # because an assembly arrives as a compound rather than a solid.
            #
            # Compound.cast, not Shape.cast: build123d 0.11 made Shape.cast abstract,
            # so it silently returns None and export_gltf then fails on None.location.
            # Compound.cast carries the full lookup table (vertex through compound)
            # that Shape.cast used to have, and is what build123d's own import_step
            # uses.
            obj, sets = b3d.Compound.cast(obj), None
        else:
            obj, sets = pieces

        tolerance = request.get("tolerance", 0.1)
        angular_tolerance = request.get("angularTolerance", 0.1)
        binary = request.get("binary", False)

        if not os.path.isabs(path):
            path = os.path.abspath(path)

        out_dir = os.path.dirname(path)
        os.makedirs(out_dir, exist_ok=True)

        b3d.export_gltf(
            obj,
            path,
            binary=binary,
            linear_deflection=tolerance,
            angular_deflection=angular_tolerance,
        )

        # Check if file is successfully created
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create GLTF file: {path}")
        if sets:
            _rewrite(path, binary, sets)

        # A '.gltf' that is not binary keeps its buffers in a file of their own,
        # beside it and named after it, which OpenCASCADE's writer puts there
        # and the '.gltf' names. It is part of the answer, so it is said to be.
        files = []
        buffers = os.path.splitext(path)[0] + ".bin"
        if not binary and os.path.isfile(buffers):
            files.append(os.path.basename(buffers))

        return {"success": True, "exception": None, "files": files, "warnings": warnings}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
