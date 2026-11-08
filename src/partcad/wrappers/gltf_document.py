#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A glTF 2.0 file read for what PartCAD makes of it: its meshes, where its nodes put them, and their materials.

Both readers of glTF read through this: the 'gltf' part type
('wrapper_import_gltf'), which makes one shape of everything the scene draws,
and the 'gltf' assembly type ('builtin/import/import_gltf.py'), which keeps the
node tree. It is plain Python and NumPy, with no CAD kernel in it, so that the
assembly reader - which only splits a file up - never loads one.

**What is read.** The default scene (or, in a file that names none, every node
that is no other node's child), node by node, each placed by its 'matrix' or its
'translation', 'rotation' and 'scale'; every primitive drawn as triangles
(lists, strips and fans), its vertex positions and its indices in any type the
specification allows; and the material each primitive names. What glTF does not
read as a solid shape - points and lines, the skin that would pose a mesh, morph
targets, animations - is counted ('Document.dropped') rather than passed over.

**Web assets.** glTF made for delivery over the web is usually made smaller by
one of four extensions, and each is read here, so that a file is read whatever
optimised it:

- 'KHR_mesh_quantization': positions stored as 8- or 16-bit integers, with the
  scale that undoes it on the node. Read like any other accessor.
- 'KHR_draco_mesh_compression': a primitive compressed by Google's Draco,
  decoded by DracoPy - Python bindings to Draco's own decoder - which the
  sandbox installs only for a file that needs it (see 'part_factory_gltf').
- 'EXT_meshopt_compression' and 'KHR_meshopt_compression': buffer views
  compressed by meshoptimizer's codecs, decoded by 'meshopt_decode'.
- 'EXT_mesh_gpu_instancing': a node drawn many times over, each copy placed by
  a row of its instance attributes.

A file that *requires* any other extension is refused, naming it, unless the
extension changes only how the file looks - its materials, textures, lights -
which a shape does not carry ('APPEARANCE'). That is what 'extensionsRequired'
asks of a reader, and what keeps a file that would be read wrong from being
read at all.

**Units.** glTF states metres, +Y up and +Z towards the viewer; PartCAD states
millimetres and +Z up. 'TO_PARTCAD' turns one into the other, and every caller
applies it: a part's shape is in PartCAD's terms, as every part's is.
"""

import base64
import json
import os
from collections import Counter
from urllib.parse import unquote, unquote_to_bytes

import numpy as np

# What this produces is what a 'gltf' part is made of: a change to what it reads
# is a change to 'wrapper_import_gltf''s CACHE_VERSION, which is the number the
# cache reads (see 'partcad.code_version').

GLB_MAGIC = b"glTF"
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942

DRACO = "KHR_draco_mesh_compression"
MESHOPT = ("EXT_meshopt_compression", "KHR_meshopt_compression")
QUANTIZATION = "KHR_mesh_quantization"
INSTANCING = "EXT_mesh_gpu_instancing"
VISIBILITY = "KHR_node_visibility"

# The extensions read here: a file may require them.
READ = frozenset({DRACO, QUANTIZATION, INSTANCING, VISIBILITY, *MESHOPT})

# Extensions that change how a file looks, or what it says about itself, and not
# the shape it is: a file that requires one is read without it, since a shape
# carries no texture, light or camera. 'KHR_materials_pbrSpecularGlossiness' is
# read for its colour (see 'Document.material'). Every 'KHR_materials_*' is one
# of these, including those Khronos ratifies after this list was written
# ('MATERIALS'): a material is how a surface is drawn.
MATERIALS = "KHR_materials_"
APPEARANCE = frozenset(
    {
        "KHR_materials_anisotropy",
        "KHR_materials_clearcoat",
        "KHR_materials_diffuse_transmission",
        "KHR_materials_dispersion",
        "KHR_materials_emissive_strength",
        "KHR_materials_ior",
        "KHR_materials_iridescence",
        "KHR_materials_pbrSpecularGlossiness",
        "KHR_materials_sheen",
        "KHR_materials_specular",
        "KHR_materials_transmission",
        "KHR_materials_unlit",
        "KHR_materials_variants",
        "KHR_materials_volume",
        "KHR_texture_basisu",
        "KHR_texture_transform",
        "EXT_texture_avif",
        "EXT_texture_webp",
        "KHR_lights_punctual",
        "EXT_lights_image_based",
        "KHR_xmp_json_ld",
        "KHR_animation_pointer",
    }
)

# glTF's metres, +Y up, to PartCAD's millimetres, +Z up: a quarter turn about X,
# which takes +Y to +Z and +Z to -Y, and a thousand millimetres to the metre.
AXES = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
MILLIMETRES_PER_UNIT = 1000.0
TO_PARTCAD = np.eye(4)
TO_PARTCAD[:3, :3] = AXES * MILLIMETRES_PER_UNIT

_COMPONENTS = {
    5120: np.dtype("i1"),
    5121: np.dtype("u1"),
    5122: np.dtype("<i2"),
    5123: np.dtype("<u2"),
    5125: np.dtype("<u4"),
    5126: np.dtype("<f4"),
}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}

# Primitive modes: what each one is.
_TRIANGLES, _STRIP, _FAN = 4, 5, 6
_MODE_NAMES = {0: "point primitives", 1: "line primitives", 2: "line primitives", 3: "line primitives"}

# What 'Document.dropped' counts that is read after a fashion rather than left
# out, and how to say so.
SKINNED = "skinned meshes"


class GltfError(ValueError):
    """What is wrong with a glTF file, in words that name it."""


class UnsupportedExtension(GltfError):
    """The file requires an extension PartCAD does not read."""


def is_glb(data: bytes) -> bool:
    """Whether 'data' is a binary glTF ('.glb'), whatever its file is called."""
    return data[: len(GLB_MAGIC)] == GLB_MAGIC


def split_glb(data: bytes):
    """'(document, binary chunk or None)' of a '.glb' (glTF 2.0, section 4.4)."""
    if len(data) < 20:
        raise GltfError("the file is too short to be a binary glTF")
    version = int.from_bytes(data[4:8], "little")
    if version != 2:
        raise GltfError("binary glTF version %d is not 2" % version)
    length = min(int.from_bytes(data[8:12], "little"), len(data))
    document, binary = None, None
    pos = 12
    while pos + 8 <= length:
        size = int.from_bytes(data[pos : pos + 4], "little")
        kind = int.from_bytes(data[pos + 4 : pos + 8], "little")
        chunk = data[pos + 8 : pos + 8 + size]
        if len(chunk) < size:
            raise GltfError("the binary glTF is cut short")
        if kind == _CHUNK_JSON and document is None:
            document = _json(chunk)
        elif kind == _CHUNK_BIN and binary is None:
            binary = chunk
        pos += 8 + size
    if document is None:
        raise GltfError("the binary glTF has no JSON chunk")
    return document, binary


def _json(data: bytes):
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise GltfError("the file is not glTF: %s" % e) from None
    if not isinstance(document, dict):
        raise GltfError("the file is not glTF: its JSON is not an object")
    return document


def write_glb(document: dict, binary: bytes) -> bytes:
    """A '.glb' of 'document' and its binary chunk, each padded to four bytes as section 4.4 says."""
    text = json.dumps(document, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    chunks = len(text).to_bytes(4, "little") + _CHUNK_JSON.to_bytes(4, "little") + text
    if binary:
        chunks += len(binary).to_bytes(4, "little") + _CHUNK_BIN.to_bytes(4, "little") + binary
    return GLB_MAGIC + (2).to_bytes(4, "little") + (12 + len(chunks)).to_bytes(4, "little") + chunks


class Primitive:
    """One primitive drawn as triangles: its vertices, its triangles (indices into them) and its material."""

    __slots__ = ("positions", "triangles", "material")

    def __init__(self, positions, triangles, material):
        self.positions = positions
        self.triangles = triangles
        self.material = material


class Material:
    """What a glTF material says that PartCAD keeps: its name, its look, and PartCAD's own references."""

    __slots__ = ("index", "name", "rgba", "metallic", "roughness", "extras")

    def __init__(self, index, name, rgba, metallic, roughness, extras):
        self.index = index
        self.name = name
        # Linear, as glTF's factors are, alpha last; None if it states no colour.
        self.rgba = rgba
        self.metallic = metallic
        self.roughness = roughness
        self.extras = extras


class Node:
    """A node of the scene: its own transform, its mesh, its children, and the copies instancing makes of it."""

    __slots__ = ("index", "name", "matrix", "mesh", "children", "instances")

    def __init__(self, index, name, matrix, mesh, children, instances):
        self.index = index
        self.name = name
        self.matrix = matrix
        self.mesh = mesh
        self.children = children
        # None, or a 4 x 4 matrix per copy, each placed by it under the node.
        self.instances = instances


class Document:
    """A glTF file: '.gltf' with the buffers it names beside it, or a '.glb'."""

    def __init__(self, path):
        self.path = os.fspath(path)
        self.directory = os.path.dirname(os.path.abspath(self.path))
        try:
            with open(self.path, "rb") as f:
                data = f.read()
        except OSError as e:
            raise GltfError("cannot read %s: %s" % (self.path, e.strerror or e)) from None
        if is_glb(data):
            self.json, self._binary = split_glb(data)
        else:
            self.json, self._binary = _json(data), None
        version = str((self.json.get("asset") or {}).get("version", ""))
        if not version.startswith("2."):
            raise GltfError("the file is glTF %s, and PartCAD reads glTF 2.0" % (version or "of no version"))
        required = _names(self.json.get("extensionsRequired"))
        missing = sorted(name for name in required - READ - APPEARANCE if not name.startswith(MATERIALS))
        if missing:
            raise UnsupportedExtension(
                "the file requires %s, which PartCAD does not read" % ", ".join("'%s'" % name for name in missing)
            )
        self.used = _names(self.json.get("extensionsUsed"))
        self.dropped = Counter()
        self._buffers = {}
        self._views = {}
        self._meshes = {}

    # -- Storage -----------------------------------------------------------

    def _item(self, section, index):
        items = self.json.get(section) or []
        if not isinstance(index, int) or not 0 <= index < len(items) or not isinstance(items[index], dict):
            raise GltfError("the file refers to %s %r, which it does not have" % (section, index))
        return items[index]

    def buffer(self, index) -> bytes:
        """The bytes of buffer 'index': the binary chunk, a 'data:' URI, or a file beside the '.gltf'."""
        if index in self._buffers:
            return self._buffers[index]
        item = self._item("buffers", index)
        uri = item.get("uri")
        if uri is None:
            if index != 0 or self._binary is None:
                raise GltfError(
                    "buffer %d holds no data: it is the stand-in a compression extension leaves for a reader that"
                    " does not decode it" % index
                )
            data = self._binary
        elif uri.startswith("data:"):
            header, _, payload = uri.partition(",")
            data = base64.b64decode(payload) if header.endswith(";base64") else unquote_to_bytes(payload)
        else:
            path = self._beside(unquote(uri))
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                raise GltfError("the buffer '%s' the file names is not there" % unquote(uri)) from None
        if len(data) < int(item.get("byteLength", 0)):
            raise GltfError("buffer %d is shorter than the file says" % index)
        self._buffers[index] = data
        return data

    def _beside(self, relative) -> str:
        """The path of a buffer the file names, which has to be at or below the file's own directory.

        A '.gltf' names its buffers relative to itself, and one fetched from a
        catalog could otherwise name any file this machine can read - an absolute
        path, '../../.ssh/id_rsa' - and have its bytes read as vertices into a
        shape that is then exported or shared. Symbolic links are followed before
        the check, so one cannot lead out either. This is what 'gltf_companions'
        already holds the files it hashes and copies to.
        """
        base = os.path.realpath(self.directory)
        path = os.path.realpath(os.path.join(base, relative))
        try:
            inside = not os.path.isabs(relative) and os.path.commonpath([base, path]) == base
        except ValueError:  # another drive, on Windows
            inside = False
        if not inside:
            raise GltfError("the buffer '%s' the file names is outside the directory the file is in" % relative)
        return path

    def view(self, index):
        """'(bytes, byte stride or None)' of buffer view 'index', decompressed when meshoptimizer compressed it."""
        if index in self._views:
            return self._views[index]
        view = self._item("bufferViews", index)
        extensions = view.get("extensions") or {}
        compressed = next((name for name in MESHOPT if isinstance(extensions.get(name), dict)), None)
        if compressed is not None:
            import meshopt_decode

            spec = extensions[compressed]
            source = self.buffer(spec.get("buffer"))
            start = int(spec.get("byteOffset", 0))
            try:
                data = meshopt_decode.decode(
                    source[start : start + int(spec["byteLength"])],
                    int(spec["count"]),
                    int(spec["byteStride"]),
                    spec.get("mode"),
                    spec.get("filter", "NONE"),
                    khr=compressed.startswith("KHR_"),
                )
            except (KeyError, TypeError) as e:
                raise GltfError("buffer view %d's %s says no %s" % (index, compressed, e)) from None
            except ValueError as e:
                raise GltfError("buffer view %d: %s" % (index, e)) from None
        else:
            source = self.buffer(view.get("buffer"))
            start = int(view.get("byteOffset", 0))
            data = source[start : start + int(view.get("byteLength", 0))]
            if len(data) < int(view.get("byteLength", 0)):
                raise GltfError("buffer view %d runs past the end of its buffer" % index)
        self._views[index] = (data, view.get("byteStride"))
        return self._views[index]

    def accessor(self, index) -> np.ndarray:
        """Accessor 'index' as a 'count' by width array; a normalized integer one as the floats it stands for."""
        accessor = self._item("accessors", index)
        dtype = _COMPONENTS.get(accessor.get("componentType"))
        width = _WIDTH.get(accessor.get("type"))
        if dtype is None or width is None:
            raise GltfError("accessor %d is of a type glTF does not have" % index)
        if accessor.get("type") in ("MAT2", "MAT3") and dtype.itemsize < 4:
            raise GltfError("accessor %d is a padded matrix, which PartCAD does not read" % index)
        count = int(accessor.get("count", 0))
        if "bufferView" in accessor:
            data, stride = self.view(accessor["bufferView"])
            offset = int(accessor.get("byteOffset", 0))
            element = dtype.itemsize * width
            stride = int(stride or element)
            if count and offset + stride * (count - 1) + element > len(data):
                raise GltfError("accessor %d runs past the end of its buffer view" % index)
            values = np.ndarray((count, width), dtype, data, offset, (stride, dtype.itemsize)).copy()
        else:
            values = np.zeros((count, width), dtype)
        sparse = accessor.get("sparse")
        if isinstance(sparse, dict) and int(sparse.get("count", 0)):
            values = values.copy()
            entries = int(sparse["count"])
            where = self._sparse_part(sparse.get("indices") or {}, entries, 1, None).reshape(-1)
            replaced = self._sparse_part(sparse.get("values") or {}, entries, width, dtype)
            if where.size and where.max() >= count:
                raise GltfError("accessor %d's sparse indices run past its end" % index)
            values[where.astype(np.int64)] = replaced
        if accessor.get("normalized") and dtype.kind in "iu":
            values = _normalized(values)
        return values

    def _sparse_part(self, part, count, width, dtype):
        dtype = dtype if dtype is not None else _COMPONENTS.get(part.get("componentType"))
        if dtype is None:
            raise GltfError("a sparse accessor has indices of a type glTF does not have")
        data, _stride = self.view(part.get("bufferView"))
        offset = int(part.get("byteOffset", 0))
        if offset + count * width * dtype.itemsize > len(data):
            raise GltfError("a sparse accessor runs past the end of its buffer view")
        return np.frombuffer(data, dtype, count * width, offset).reshape(count, width)

    # -- Meshes ------------------------------------------------------------

    def primitives(self, mesh_index):
        """The primitives of mesh 'mesh_index' drawn as triangles, each as a 'Primitive'."""
        if mesh_index in self._meshes:
            return self._meshes[mesh_index]
        mesh = self._item("meshes", mesh_index)
        found = []
        for primitive in mesh.get("primitives") or []:
            if not isinstance(primitive, dict):
                continue
            mode = primitive.get("mode", _TRIANGLES)
            if mode not in (_TRIANGLES, _STRIP, _FAN):
                self.dropped[_MODE_NAMES.get(mode, "primitives of an unknown mode")] += 1
                continue
            if primitive.get("targets"):
                self.dropped["morph targets"] += len(primitive["targets"])
            positions, indices = self._vertices(primitive)
            if positions is None:
                continue
            triangles = _triangles(indices, mode)
            if triangles.size and (triangles.max() >= len(positions) or triangles.min() < 0):
                raise GltfError("mesh %d has a triangle with a vertex it does not have" % mesh_index)
            material = primitive.get("material")
            found.append(Primitive(positions, triangles, material if isinstance(material, int) else None))
        self._meshes[mesh_index] = found
        return found

    def _vertices(self, primitive):
        """'(positions, indices)' of a primitive: as its accessors say, or as Draco decodes them."""
        attributes = primitive.get("attributes") or {}
        draco = (primitive.get("extensions") or {}).get(DRACO)
        if isinstance(draco, dict):
            fallback = "POSITION" in attributes and "bufferView" in self._item("accessors", attributes["POSITION"])
            decoded = self._draco(draco, fallback)
            if decoded is not None:
                return decoded
        if "POSITION" not in attributes:
            self.dropped["primitives with no positions"] += 1
            return None, None
        positions = self.accessor(attributes["POSITION"]).astype(np.float64)
        if positions.shape[1] != 3:
            raise GltfError("a primitive's positions are not 3D vectors")
        if "indices" in primitive:
            indices = self.accessor(primitive["indices"]).reshape(-1).astype(np.int64)
        else:
            indices = np.arange(len(positions), dtype=np.int64)
        return positions, indices

    def _draco(self, draco, fallback):
        """'(positions, indices)' Draco decodes a primitive to; None to read the uncompressed copy beside it."""
        try:
            import DracoPy
        except ImportError:
            if fallback:
                return None
            raise GltfError(
                "the file's meshes are compressed with Draco (%s), and DracoPy, which decodes them, is not installed"
                % DRACO
            ) from None
        data, _stride = self.view(draco.get("bufferView"))
        try:
            decoded = DracoPy.decode(bytes(data))
        except Exception as e:  # pylint: disable=broad-except
            raise GltfError("a Draco-compressed primitive does not decode: %s" % e) from None
        faces = getattr(decoded, "faces", None)
        if faces is None:
            # A point cloud, which is what Draco makes of a primitive of points.
            self.dropped["point primitives"] += 1
            return np.zeros((0, 3)), np.zeros(0, np.int64)
        positions = np.asarray(decoded.points, dtype=np.float64).reshape(-1, 3)
        return positions, np.asarray(faces, dtype=np.int64).reshape(-1)

    # -- Materials ---------------------------------------------------------

    def material(self, index):
        """Material 'index' as a 'Material', or None for a primitive that names none.

        What the material states and nothing else: its colour only where it
        states a factor (one drawn with a texture and no factor is the texture's,
        not white), its roughness and metallic only where it states them (glTF's
        defaults of 1 would make every material that says nothing a rough metal).
        """
        if index is None:
            return None
        item = self._item("materials", index)
        pbr = item.get("pbrMetallicRoughness")
        glossy = (item.get("extensions") or {}).get("KHR_materials_pbrSpecularGlossiness")
        rgba = metallic = roughness = None
        if isinstance(pbr, dict):
            rgba = pbr.get("baseColorFactor")
            metallic = _factor(pbr.get("metallicFactor"))
            roughness = _factor(pbr.get("roughnessFactor"))
        elif isinstance(glossy, dict):
            rgba = glossy.get("diffuseFactor")
            glossiness = _factor(glossy.get("glossinessFactor"))
            roughness = None if glossiness is None else 1.0 - glossiness
        rgba = _color(rgba)
        name = item.get("name") if isinstance(item.get("name"), str) and item.get("name").strip() else None
        extras = item.get("extras") if isinstance(item.get("extras"), dict) else {}
        return Material(index, name, rgba, metallic, roughness, extras)

    # -- The scene ---------------------------------------------------------

    def roots(self):
        """The nodes of the scene the file shows, each with its children: a list of 'Node'."""
        nodes = self.json.get("nodes") or []
        scenes = self.json.get("scenes") or []
        if scenes:
            chosen = self.json.get("scene", 0)
            scene = self._item("scenes", chosen if isinstance(chosen, int) else 0)
            indices = scene.get("nodes") or []
        else:
            children = {child for node in nodes if isinstance(node, dict) for child in node.get("children") or []}
            indices = [index for index in range(len(nodes)) if index not in children]
        if self.json.get("animations"):
            self.dropped["animations"] += len(self.json["animations"])
        return [node for node in (self._node(index, ()) for index in indices) if node is not None]

    def _node(self, index, path):
        if index in path:
            raise GltfError("node %d is its own ancestor" % index)
        item = self._item("nodes", index)
        visibility = (item.get("extensions") or {}).get(VISIBILITY)
        if isinstance(visibility, dict) and visibility.get("visible") is False:
            self.dropped["hidden nodes"] += 1
            return None
        if "skin" in item and isinstance(item.get("mesh"), int):
            self.dropped[SKINNED] += 1
        mesh = item.get("mesh") if isinstance(item.get("mesh"), int) else None
        instances = None
        instancing = (item.get("extensions") or {}).get(INSTANCING)
        if isinstance(instancing, dict) and mesh is not None:
            instances = self._instances(instancing.get("attributes") or {})
        children = [self._node(child, path + (index,)) for child in item.get("children") or []]
        name = item.get("name") if isinstance(item.get("name"), str) else None
        return Node(index, name, local_matrix(item), mesh, [c for c in children if c is not None], instances)

    def _instances(self, attributes):
        """A matrix per copy 'EXT_mesh_gpu_instancing' makes, from its translation, rotation and scale rows."""
        columns = {}
        for key, width in (("TRANSLATION", 3), ("ROTATION", 4), ("SCALE", 3)):
            if key in attributes:
                values = self.accessor(attributes[key]).astype(np.float64)
                if values.shape[1] != width:
                    raise GltfError("an instanced node's %s is not a %d-vector" % (key, width))
                columns[key] = values
        if not columns:
            return None
        count = min(len(values) for values in columns.values())
        matrices = []
        for row in range(count):
            matrices.append(
                trs_matrix(
                    columns["TRANSLATION"][row] if "TRANSLATION" in columns else (0, 0, 0),
                    columns["ROTATION"][row] if "ROTATION" in columns else (0, 0, 0, 1),
                    columns["SCALE"][row] if "SCALE" in columns else (1, 1, 1),
                )
            )
        return matrices

    def placed_meshes(self):
        """Every mesh the scene draws, as '(node, world matrix in glTF's units)', instanced copies one by one."""
        found = []

        def walk(node, parent):
            world = parent @ node.matrix
            if node.mesh is not None:
                for copy in node.instances if node.instances is not None else [np.eye(4)]:
                    found.append((node, world @ copy))
            for child in node.children:
                walk(child, world)

        for root in self.roots():
            walk(root, np.eye(4))
        return found


def _names(value) -> set:
    """The extension names a file lists: its strings, and nothing for a list that is not one."""
    return {name for name in value if isinstance(name, str)} if isinstance(value, list) else set()


def _factor(value):
    """A factor from 0 to 1 as the file states it, or None if it states none."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(max(float(value), 0.0), 1.0)


def _color(value):
    """'(red, green, blue, alpha)', linear from 0 to 1, of a stated colour factor; None if none is stated."""
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    channels = [_factor(channel) for channel in value[:4]]
    if any(channel is None for channel in channels):
        return None
    return tuple(channels) + (1.0,) * (4 - len(channels))


def _normalized(values: np.ndarray) -> np.ndarray:
    """A normalized integer accessor's values as the floats they stand for (glTF 2.0, section 3.11)."""
    info = np.iinfo(values.dtype)
    if info.min < 0:
        return np.maximum(values.astype(np.float64) / info.max, -1.0)
    return values.astype(np.float64) / info.max


def _triangles(indices: np.ndarray, mode: int) -> np.ndarray:
    """The triangles a list, a strip or a fan of 'indices' draws, as an 'n' by 3 array."""
    if mode == _TRIANGLES:
        usable = len(indices) - len(indices) % 3
        return indices[:usable].reshape(-1, 3)
    if len(indices) < 3:
        return np.zeros((0, 3), np.int64)
    steps = np.arange(len(indices) - 2)
    if mode == _STRIP:
        # Every other triangle of a strip is turned, so that they all face one way.
        odd = steps % 2
        return np.stack([indices[steps], indices[steps + 1 + odd], indices[steps + 2 - odd]], axis=1)
    return np.stack([indices[steps + 1], indices[steps + 2], np.full_like(steps, indices[0])], axis=1)


def trs_matrix(translation, rotation, scale) -> np.ndarray:
    """The 4 x 4 matrix of a translation, a unit quaternion '(x, y, z, w)' and a scale, applied scale first."""
    x, y, z, w = (float(value) for value in rotation)
    norm = np.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    rotate = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    matrix = np.eye(4)
    matrix[:3, :3] = rotate * np.asarray(scale, dtype=np.float64)
    matrix[:3, 3] = np.asarray(translation, dtype=np.float64)
    return matrix


def local_matrix(node: dict) -> np.ndarray:
    """A node's own transform: its 'matrix' (column by column), or its translation, rotation and scale."""
    if isinstance(node.get("matrix"), list) and len(node["matrix"]) == 16:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    return trs_matrix(
        node.get("translation") or (0.0, 0.0, 0.0),
        node.get("rotation") or (0.0, 0.0, 0.0, 1.0),
        node.get("scale") or (1.0, 1.0, 1.0),
    )


def decompose(matrix: np.ndarray):
    """'(rotation, translation, stretch)' of an affine 4 x 4 matrix, its linear part 'rotation @ stretch'.

    A location in PartCAD - and in OCCT - is a rotation and a translation, so a
    node's scale, its shear and its mirroring cannot be one: they are what
    'stretch' holds, symmetric, for the geometry to be made with, and the rest is
    where that geometry is put. The polar decomposition, from a singular value
    decomposition; a mirroring is left in 'stretch', so that 'rotation' is one.
    """
    linear = matrix[:3, :3]
    u, _sigma, vt = np.linalg.svd(linear)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] = -u[:, -1]
        rotation = u @ vt
    stretch = rotation.T @ linear
    return rotation, matrix[:3, 3].copy(), stretch


def axis_angle(rotation: np.ndarray):
    """'(axis, degrees)' of a rotation matrix: what a PartCAD location states."""
    trace = float(np.trace(rotation))
    # The quaternion, by whichever of its components is largest, for precision.
    if trace > 0:
        s = np.sqrt(trace + 1.0) * 2
        w = 0.25 * s
        x = (rotation[2, 1] - rotation[1, 2]) / s
        y = (rotation[0, 2] - rotation[2, 0]) / s
        z = (rotation[1, 0] - rotation[0, 1]) / s
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        s = np.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2
        w = (rotation[2, 1] - rotation[1, 2]) / s
        x = 0.25 * s
        y = (rotation[0, 1] + rotation[1, 0]) / s
        z = (rotation[0, 2] + rotation[2, 0]) / s
    elif rotation[1, 1] > rotation[2, 2]:
        s = np.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2
        w = (rotation[0, 2] - rotation[2, 0]) / s
        x = (rotation[0, 1] + rotation[1, 0]) / s
        y = 0.25 * s
        z = (rotation[1, 2] + rotation[2, 1]) / s
    else:
        s = np.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2
        w = (rotation[1, 0] - rotation[0, 1]) / s
        x = (rotation[0, 2] + rotation[2, 0]) / s
        y = (rotation[1, 2] + rotation[2, 1]) / s
        z = 0.25 * s
    if w < 0:
        w, x, y, z = -w, -x, -y, -z
    sine = np.sqrt(x * x + y * y + z * z)
    if sine < 1e-12:
        return (0.0, 0.0, 1.0), 0.0
    return (x / sine, y / sine, z / sine), float(np.degrees(2.0 * np.arctan2(sine, w)))


def warnings_of(dropped: Counter) -> list:
    """What a read left out, or read only after a fashion, as sentences for a log."""
    said = []
    left_out = ["%d %s" % (count, what) for what, count in sorted(dropped.items()) if count and what != SKINNED]
    if left_out:
        said.append("Not read, since a shape does not hold them: %s" % ", ".join(left_out))
    if dropped.get(SKINNED):
        said.append(
            "%d skinned mesh(es) read as bound, not as any pose a skeleton would put them in" % dropped[SKINNED]
        )
    return said
