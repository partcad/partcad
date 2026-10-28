#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What is actually inside the glTF PartCAD produces for an object.

Asks a shape for its glTF representation and prints the primitives of every node
of the tree: how many meshes, what mode each primitive is drawn in, how many
vertices. A node that draws nothing shows as such, which is the difference between
"nothing was sent" and "something was sent and cannot be seen".

Not a test and not part of the build: an eyeball on the geometry.

    poetry run python dev-tools/inspect_gltf.py examples //produce_sketch_basic:circle_01
"""

import argparse
import asyncio
import json
import struct
import sys

import partcad as pc
import partcad_ide_client
from partcad import shape_envelope

# glTF primitive modes, by the number the file states them as.
MODES = {0: "POINTS", 1: "LINES", 2: "LINE_LOOP", 3: "LINE_STRIP", 4: "TRIANGLES", 5: "TRIANGLE_STRIP"}


def glb_json(payload) -> dict:
    """The JSON chunk of a binary glTF payload, in either of its spellings (see 'decode_gltf')."""
    glb = partcad_ide_client.decode_gltf(payload)
    _magic, _version, length = struct.unpack("<4sII", glb[:12])
    offset = 12
    while offset < length:
        chunk_length, chunk_type = struct.unpack("<I4s", glb[offset : offset + 8])
        body = glb[offset + 8 : offset + 8 + chunk_length]
        if chunk_type.strip() == b"JSON":
            return json.loads(body)
        offset += 8 + chunk_length + (-chunk_length % 4)
    raise ValueError("no JSON chunk in the glTF")


def describe(payload: str) -> str:
    """One line about what a glTF payload can draw."""
    document = glb_json(payload)
    accessors = document.get("accessors") or []
    drawn = []
    for mesh in document.get("meshes") or []:
        for primitive in mesh.get("primitives") or []:
            mode = primitive.get("mode", 4)
            position = (primitive.get("attributes") or {}).get("POSITION")
            count = accessors[position].get("count") if position is not None else None
            drawn.append("%s x%s" % (MODES.get(mode, mode), count))
    materials = len(document.get("materials") or [])
    if not drawn:
        return "nothing to draw (%d mesh(es), %d material(s))" % (len(document.get("meshes") or []), materials)
    return "%s, %d material(s)" % ("; ".join(drawn), materials)


def walk(node, depth=0, table=None):
    # A node names its geometry in the root's table, or - hand-made - carries it.
    if table is None:
        table = node.get(shape_envelope.KEY_GEOMETRY) or {}

    def geometry(of):
        return of.get(shape_envelope.KEY_GLTF) or table.get(of.get(shape_envelope.KEY_GLTF_REF))

    label = node.get("label") or node.get("name") or "?"
    payload = geometry(node)
    print("%s%s: %s" % ("  " * depth, label, describe(payload) if payload else "no geometry"))
    for port in node.get(shape_envelope.KEY_PORTS) or []:
        print("%s  port %s: sketch=%s" % ("  " * depth, port.get("name"), port.get("sketch")))
    for reference, sketch in (node.get(shape_envelope.KEY_SKETCHES) or {}).items():
        drawn = geometry(sketch)
        print("%s  sketch %s: %s" % ("  " * depth, reference, describe(drawn) if drawn else "no geometry"))
    for child in node.get(shape_envelope.KEY_ASSEMBLY) or []:
        walk(child, depth + 1, table)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="the package root to initialize, e.g. 'examples'")
    parser.add_argument("objects", nargs="+", help="'<kind>:<name>', kind one of part/sketch/assembly/interface")
    args = parser.parse_args()

    ctx = pc.init(args.package)
    for spec in args.objects:
        kind, _, name = spec.partition(":")
        getter = {
            "part": ctx.get_part,
            "sketch": ctx.get_sketch,
            "assembly": ctx._get_assembly,
            "interface": ctx.get_interface,
        }[kind]
        obj = getter(name)
        if obj is None:
            print("%s: not found" % spec)
            continue
        print("=== %s" % spec)
        try:
            tree = asyncio.run(obj.get_representation(ctx, shape_envelope.FORM_GLTF))
        except Exception as e:
            print("  failed: %s" % e)
            continue
        if tree is None:
            print("  nothing")
            continue
        walk(tree)
    return 0


if __name__ == "__main__":
    sys.exit(main())
