#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'gltf' assembly type: a glTF scene as an assembly, a part per mesh, placed as its nodes place it.

A glTF file is a tree of nodes, each placed by its parent and each drawing a
mesh or not. Read as an assembly, the tree is the assembly's: a node with
children - or with copies of itself, under 'EXT_mesh_gpu_instancing' - is a
sub-assembly, a node that only draws a mesh is a part placed where the node puts
it, and a node that does neither is left out.

Each distinct mesh is written out as a '.glb' of its own, holding that mesh and
its materials and nothing else, and is read by the 'gltf' part type - so a part
of a glTF assembly is read exactly as a glTF part is, colours and all, and a
mesh the scene draws a hundred times is one file and one part placed a hundred
times. What a node does that a placement cannot - scale a mesh, stretch it,
mirror it - is made into that mesh's file instead, so a mesh scaled two ways is
two files.

The reading is 'gltf_document''s, the same as the part type's, so the
compression extensions of the web's glTF are read here too. Nothing here loads
a CAD kernel: the reader splits the file up and does arithmetic; the parts are
built afterwards, each in its own run.

The import contract is 'wrappers/wrapper_import.py''s: a file goes in, a tree of
placed parts comes out, each part naming the file it is read from. Placements
are where each part is in the assembly as a whole, and a sub-assembly is placed
nowhere of its own, as the STEP assembly type places them.
"""

import os
import re
import sys

# Siblings are imported by bare name, and the sandbox sets PYTHONSAFEPATH.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Raise with any change to what this produces (see 'partcad.code_version'),
# including to what 'gltf_document' reads.
CACHE_VERSION = 1

# How many digits a placement is rounded to: a nanometre at millimetre scale,
# which is finer than a float32 vertex of a glTF can tell apart.
PRECISION = 6

# What an object name may hold, less the '/' that separates the assembly's name
# from its parts' (see the 'parts' section of the package schema).
_NOT_IN_A_NAME = re.compile(r"[^A-Za-z0-9_.-]+")

# glTF's own accessor types: what a part's file is written with.
_FLOAT, _UNSIGNED_INT = 5126, 5125
_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963


def node_name(raw, fallback):
    """A name an object can have, out of what the file called it, or 'fallback' when it called it nothing."""
    name = _NOT_IN_A_NAME.sub("_", raw or "").strip("_.-")
    return name or fallback


def _unique(links):
    """'links' with every name told apart from its siblings', by a number after it."""
    seen = {}
    for link in links:
        if link["type"] != "assembly":
            continue  # a part's node is named after its file, and shares it
        name = link["name"]
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            link["name"] = "%s_%d" % (name, seen[name])
    return links


class PartFiles:
    """One '.glb' per mesh the scene draws, per way it is stretched: what each part of the assembly is read from."""

    def __init__(self, document, folder):
        self.document = document
        self.folder = folder
        self.files = {}
        self.used = set()

    def file_for(self, mesh_index, stretch):
        """The file mesh 'mesh_index' is written to, 'stretch' (in PartCAD's axes) made into it; None if it is empty."""
        import gltf_document
        import numpy as np

        key = (mesh_index, tuple(np.round(stretch, 9).reshape(-1)))
        if key in self.files:
            return self.files[key]
        primitives = [p for p in self.document.primitives(mesh_index) if len(p.triangles)]
        if not primitives:
            self.files[key] = None
            return None
        # The part type turns the file's axes into PartCAD's, so what the node
        # stretches is stated in the file's.
        in_file_axes = gltf_document.AXES.T @ stretch @ gltf_document.AXES
        mesh = self.document.json["meshes"][mesh_index]
        name = node_name(mesh.get("name") if isinstance(mesh.get("name"), str) else None, "mesh%d" % mesh_index)
        path = os.path.join(self.folder, name + ".glb")
        suffix = 1
        while path in self.used:
            suffix += 1
            path = os.path.join(self.folder, "%s_%d.glb" % (name, suffix))
        self.used.add(path)
        with open(path, "wb") as f:
            f.write(self._glb(primitives, in_file_axes))
        self.files[key] = path
        return path

    def _glb(self, primitives, transform):
        import gltf_document

        binary = bytearray()
        views, accessors, materials, written = [], [], [], {}

        def add(data, target, component, kind, bounds=None):
            offset = len(binary)
            binary.extend(data.tobytes())
            binary.extend(b"\0" * (-len(binary) % 4))
            views.append({"buffer": 0, "byteOffset": offset, "byteLength": data.nbytes, "target": target})
            accessor = {"bufferView": len(views) - 1, "componentType": component, "count": len(data), "type": kind}
            if bounds is not None:
                accessor["min"], accessor["max"] = bounds
            accessors.append(accessor)
            return len(accessors) - 1

        out = []
        for primitive in primitives:
            positions = (primitive.positions @ transform.T).astype("<f4")
            position = add(
                positions,
                _ARRAY_BUFFER,
                _FLOAT,
                "VEC3",
                (positions.min(axis=0).tolist(), positions.max(axis=0).tolist()),
            )
            indices = add(primitive.triangles.reshape(-1).astype("<u4"), _ELEMENT_ARRAY_BUFFER, _UNSIGNED_INT, "SCALAR")
            entry = {"attributes": {"POSITION": position}, "indices": indices}
            if primitive.material is not None:
                if primitive.material not in written:
                    written[primitive.material] = len(materials)
                    materials.append(self._material(primitive.material))
                entry["material"] = written[primitive.material]
            out.append(entry)

        document = {
            "asset": {"version": "2.0", "generator": "PartCAD"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": out}],
            "buffers": [{"byteLength": len(binary)}],
            "bufferViews": views,
            "accessors": accessors,
        }
        if materials:
            document["materials"] = materials
        return gltf_document.write_glb(document, bytes(binary))

    def _material(self, index):
        """What the part type reads of a material - its name, its factors, its extras - and none of its textures."""
        material = self.document.material(index)
        written = {}
        if material.name:
            written["name"] = material.name
        pbr = {}
        if material.rgba is not None:
            pbr["baseColorFactor"] = list(material.rgba)
        if material.metallic is not None:
            pbr["metallicFactor"] = material.metallic
        if material.roughness is not None:
            pbr["roughnessFactor"] = material.roughness
        if pbr:
            written["pbrMetallicRoughness"] = pbr
        if material.extras:
            written["extras"] = material.extras
        return written


def _location(rotation, translation):
    import gltf_document

    axis, angle = gltf_document.axis_angle(rotation)
    return [
        [round(float(value), PRECISION) for value in translation],
        [round(float(value), PRECISION) for value in axis],
        round(angle, PRECISION),
    ]


def process(_path, request):
    import gltf_document
    import numpy as np

    source = request["source_file"]
    model_name = node_name(os.path.splitext(os.path.basename(source))[0], "model")
    document = gltf_document.Document(source)
    os.makedirs(request["output_folder"], exist_ok=True)
    files = PartFiles(document, request["output_folder"])
    from_partcad = np.linalg.inv(gltf_document.TO_PARTCAD)

    def part(mesh_index, world):
        # Where the mesh is, in PartCAD's terms, and what the node does to it
        # that a placement cannot.
        rotation, translation, stretch = gltf_document.decompose(gltf_document.TO_PARTCAD @ world @ from_partcad)
        part_file = files.file_for(mesh_index, stretch)
        if part_file is None:
            return None
        return {
            "type": "part",
            # Named after the file, which a part is registered once per: two
            # placements of one mesh are one part.
            "name": os.path.splitext(os.path.basename(part_file))[0],
            "part_file": part_file,
            "part_type": "gltf",
            "location": _location(rotation, translation),
        }

    def walk(node, parent, fallback):
        world = parent @ node.matrix
        name = node_name(node.name, fallback)
        if node.mesh is not None and node.instances is None and not node.children:
            return part(node.mesh, world)
        links = []
        if node.mesh is not None:
            for copy in node.instances if node.instances is not None else [np.eye(4)]:
                link = part(node.mesh, world @ copy)
                if link is not None:
                    links.append(link)
        for index, child in enumerate(node.children, start=1):
            link = walk(child, world, "%s_%d" % (name, index))
            if link is not None:
                links.append(link)
        if not links:
            return None
        return {"type": "assembly", "name": name, "links": _unique(links)}

    roots = [walk(root, np.eye(4), "node%d" % root.index) for root in document.roots()]
    roots = [root for root in roots if root is not None]
    if not roots:
        raise RuntimeError("%s draws no triangles" % os.path.basename(source))
    if len(roots) == 1 and roots[0]["type"] == "assembly":
        tree = roots[0]
    else:
        tree = {"type": "assembly", "name": model_name, "links": _unique(roots)}
    return {
        "root": tree,
        "model_name": tree["name"],
        "warnings": gltf_document.warnings_of(document.dropped),
    }
