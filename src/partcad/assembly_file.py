#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether a file holds an assembly rather than a part, by what the file itself says.

``pc import part`` imports one shape. A file that holds an assembly is refused
there unless ``--compound`` asks for that assembly as one part - its compound
(see 'partcad.assembly_compound') - because reading an assembly as a part
silently throws away what it is made of: its items, their names and where each
is placed. ``pc import assembly`` is what keeps all of that.

What counts as an assembly is what the formats ``pc import assembly`` reads say
about themselves:

  * **URDF** - always: a robot, its links and the joints between them.
  * **STEP** - a product structure that places more than one component (more
    than one ``NEXT_ASSEMBLY_USAGE_OCCURRENCE``). One product placing one
    component is a part that sits somewhere - which is how PartCAD writes a
    part placed away from the origin - and several solids with no product
    structure are one multi-body part, as a CAD tool writes one.
  * **glTF** - a scene that places more than one mesh: a node that draws one,
    counted once per GPU instance of it. That is what the 'gltf' assembly type
    makes a part of each (see 'builtin/import/import_gltf.py').

Anything else is a part, and so is a file that cannot be read here: the part
type's own reader is what says what is wrong with it.

Read without a CAD kernel, and without reading more of the file than it takes
to find a second component.
"""

import gzip
import json
import struct
import typing
from pathlib import Path

# The part types that are only ever an assembly: no part type reads them, so
# they are imported as a part only as their compound.
ASSEMBLY_ONLY_TYPES = ("urdf",)


class AssemblyNotPart(ValueError):
    """A file that holds an assembly, asked to be imported as a part without '--compound'.

    A usage error rather than a failure: nothing was imported, and the message
    says which of the two ways to import it to use.
    """


# The STEP entity that places one product in another.
_STEP_COMPONENT = b"NEXT_ASSEMBLY_USAGE_OCCURRENCE"
_CHUNK = 1 << 20
_GLB_MAGIC = b"glTF"
_GLB_JSON = 0x4E4F534A


def _step_components(path: Path, enough: int) -> int:
    """How many components the STEP file at 'path' places, counted up to 'enough'."""
    with open(path, "rb") as raw:
        gzipped = raw.read(2) == b"\x1f\x8b"
    opener = gzip.open if gzipped else open
    found = 0
    tail = b""
    with opener(path, "rb") as f:
        while found < enough:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            text = tail + chunk
            found += text.count(_STEP_COMPONENT)
            # What could be the start of a keyword split between two chunks,
            # and cannot be one already counted.
            tail = text[-(len(_STEP_COMPONENT) - 1) :]
    return found


def _gltf_document(path: Path) -> typing.Optional[dict]:
    """The JSON of a '.gltf', or of the first chunk of a '.glb'; None if it is neither."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] == _GLB_MAGIC:
            chunk = f.read(8)
            if len(chunk) < 8:
                return None
            length, kind = struct.unpack("<II", chunk)
            if kind != _GLB_JSON:
                return None
            return json.loads(f.read(length).decode("utf-8"))
        return json.loads((head + f.read()).decode("utf-8"))


def _gltf_meshes(path: Path, enough: int) -> int:
    """How many meshes the default scene of the glTF file at 'path' places, counted up to 'enough'."""
    document = _gltf_document(path)
    if not isinstance(document, dict):
        return 0
    nodes = document.get("nodes") or []
    accessors = document.get("accessors") or []
    scenes = document.get("scenes") or []
    scene = document.get("scene", 0)
    if isinstance(scene, int) and 0 <= scene < len(scenes):
        roots = scenes[scene].get("nodes") or []
    else:
        # No scene: every node no other node holds is a root.
        held = {child for node in nodes for child in (node.get("children") or [])}
        roots = [index for index in range(len(nodes)) if index not in held]

    def copies(node) -> int:
        instancing = (node.get("extensions") or {}).get("EXT_mesh_gpu_instancing") or {}
        for accessor in (instancing.get("attributes") or {}).values():
            if isinstance(accessor, int) and 0 <= accessor < len(accessors):
                return int(accessors[accessor].get("count") or 0)
        return 1

    found = 0
    seen = set()
    pending = list(roots)
    while pending and found < enough:
        index = pending.pop()
        if not isinstance(index, int) or not 0 <= index < len(nodes) or index in seen:
            continue
        seen.add(index)
        node = nodes[index]
        if node.get("mesh") is not None:
            found += copies(node)
        pending.extend(node.get("children") or [])
    return found


def assembly_in(path, file_type: str) -> typing.Optional[str]:
    """What makes the file at 'path', read as 'file_type', an assembly - in words - or None for a part."""
    file_type = (file_type or "").lower()
    path = Path(path)
    if file_type in ASSEMBLY_ONLY_TYPES:
        return "a %s describes an assembly" % file_type.upper()
    try:
        if file_type == "step":
            if _step_components(path, 2) >= 2:
                return "its product structure places several components"
        elif file_type == "gltf":
            if _gltf_meshes(path, 2) >= 2:
                return "its scene places several meshes"
    except Exception:  # pylint: disable=broad-except
        # Whatever this cannot make sense of - a file it cannot read, a glTF
        # whose structure is not the one the format names, a gzip stream cut
        # short - is read by the part type's own reader, which says what is
        # wrong with it in the format's own terms. This only asks a question.
        return None
    return None
