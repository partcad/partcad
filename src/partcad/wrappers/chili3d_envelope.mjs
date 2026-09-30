// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The JavaScript end of the shape wire format, wire-compatible with
// 'wrappers/ocp_serialize.py' and 'shape_envelope.py'.
//
// A single shape is '{"name", "label", "brep"}', where "brep" is the base64 of
// the zstd-compressed bytes OCCT's BRepTools writer produces. An assembly is
// '{"name", "label", "assembly": [...]}'. Requests and responses are ordinary
// JSON objects carrying such objects under keys like "shape" or "components".
//
// Chili3D reaches the same writer through its WebAssembly build:
// 'Converter.convertToBrep' returns exactly what 'BRepTools.Write_s' writes, so
// the bytes the Python end reads back are the ones it would have produced
// itself.

import zlib from "node:zlib";

export const KEY_BREP = "brep";
export const KEY_ASSEMBLY = "assembly";
export const KEY_BYTES = "__bytes__";
export const KEY_LOCATION = "location";

// The zstd frame header. The Python end sniffs for it rather than being told
// which encoding a payload uses, so writing plain BREP where this Node.js has
// no zstd stays readable there. It cannot collide with a raw payload: BREP
// always begins with its own ASCII header ("CASCADE Topology" or
// "DBRep_DrawableShape").
const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

// 'node:zlib' grew the zstd helpers in Node.js 22.15. Detected rather than
// assumed, because a sandbox may be pinned to an older major line.
const zstdCompressSync = typeof zlib.zstdCompressSync === "function" ? zlib.zstdCompressSync : null;
const zstdDecompressSync = typeof zlib.zstdDecompressSync === "function" ? zlib.zstdDecompressSync : null;

let zstdWarned = false;

function compress(data) {
    if (zstdCompressSync === null) {
        if (!zstdWarned) {
            zstdWarned = true;
            process.stderr.write("chili3d_envelope: zstd is not available, leaving BREP payloads uncompressed\n");
        }
        return data;
    }
    return zstdCompressSync(data);
}

function decompress(data) {
    if (!data.subarray(0, ZSTD_MAGIC.length).equals(ZSTD_MAGIC)) {
        return data;
    }
    if (zstdDecompressSync === null) {
        throw new Error(
            "Received a zstd-compressed BREP payload, but this Node.js has no zstd in 'node:zlib'. " +
                "It arrived in Node.js 22.15.",
        );
    }
    return zstdDecompressSync(data);
}

/** Represent a single TopoDS_Shape as {"name", "label", "brep"}. */
export function encodeShape(shape, name = null, label = null) {
    const brep = globalThis.wasm.Converter.convertToBrep(shape);
    return {
        name,
        label,
        [KEY_BREP]: compress(Buffer.from(brep, "utf8")).toString("base64"),
    };
}

/** Turn a shape object back into a TopoDS_Shape. */
export function decodeShape(object) {
    if (!isShapeObject(object)) {
        throw new Error("Not a shape object: " + JSON.stringify(Object.keys(object ?? {})));
    }
    const brep = decompress(Buffer.from(object[KEY_BREP], "base64")).toString("utf8");
    return globalThis.wasm.Converter.convertFromBrep(brep);
}

export function isShapeObject(object) {
    return object !== null && typeof object === "object" && KEY_BREP in object;
}

export function isAssemblyObject(object) {
    return object !== null && typeof object === "object" && KEY_ASSEMBLY in object;
}

/**
 * Serialize a response into the single line that travels over the pipe.
 *
 * Plain JSON, not base64-wrapped JSON: the BREP payload inside is already
 * base64, so the JSON is single-line and transport-safe as it is.
 */
export function serialize(object) {
    return JSON.stringify(object);
}

/**
 * Deserialize a request produced by the Python end.
 *
 * The request is taken as the last non-empty line, mirroring what the Python
 * side does with a response, so that anything written ahead of it is ignored.
 */
export function deserialize(text) {
    const lines = String(text)
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0);
    if (lines.length === 0) {
        throw new Error("the request is empty");
    }
    return JSON.parse(lines[lines.length - 1]);
}
