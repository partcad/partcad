// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Code shared by the JavaScript wrapper scripts - the twin of
// 'wrappers/wrapper_common.py'.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { encodeShape, deserialize, serialize } from "./chili3d_envelope.mjs";

// The name/label the request carried, echoed onto the shape a response returns
// (the sandbox does not otherwise know a shape's PartCAD name).
let requestName = null;
let requestLabel = null;

/** Read the request the runtime wrote to stdin. */
export async function handleInput() {
    if (process.argv.length < 3) {
        process.stderr.write(`Usage: ${process.argv[1]} <path> [<cwd>]\n`);
        process.exit(1);
    }
    const scriptPath = path.normalize(process.argv[2]);
    const cwd = process.argv.length > 3 ? path.normalize(process.argv[3]) : null;

    const chunks = [];
    for await (const chunk of process.stdin) {
        chunks.push(chunk);
    }
    const request = deserialize(Buffer.concat(chunks).toString("utf8"));
    requestName = request?.name ?? null;
    requestLabel = request?.label ?? null;

    return { scriptPath, cwd, request };
}

/** Write the response as the last line of stdout. */
export function handleOutput(model) {
    process.stdout.write(serialize(model) + "\n");
}

/** Normalize an exception for the response envelope, as a plain message. */
export function exceptionToString(error) {
    if (error === null || error === undefined) {
        return null;
    }
    return error instanceof Error ? error.message : String(error);
}

/** Report an exception on stderr the way the Python wrappers do. */
export function handleException(error, scriptPath = null) {
    process.stderr.write("Error: [");
    process.stderr.write(String(exceptionToString(error)).trim());
    process.stderr.write("] on the line: [");

    // The first stack frame that names the script, so the message points at the
    // user's code rather than at this wrapper.
    const stack = error instanceof Error && error.stack ? error.stack.split("\n") : [];
    const frame = scriptPath === null ? undefined : stack.find((line) => line.includes(path.basename(scriptPath)));
    if (frame === undefined) {
        process.stderr.write(stack.length > 1 ? stack[1].trim() : "No traceback available");
    } else {
        process.stderr.write(frame.trim());
    }
    process.stderr.write("]\n");
}

function isTopoDS(value) {
    return (
        value !== null &&
        typeof value === "object" &&
        typeof value.shapeType === "function" &&
        typeof value.isNull === "function"
    );
}

/**
 * Reduce whatever a script handed back to a TopoDS_Shape, or null.
 *
 * Chili3D presents geometry at several levels and a script may reasonably
 * return any of them: the raw 'TopoDS_Shape' from the kernel, the 'ShapeResult'
 * its factory returns, the 'Result' the high-level API returns, the 'IShape'
 * inside that, or a document node wrapping one. A failed result throws, so the
 * script's own error message reaches the user instead of an empty part.
 */
export function toShape(value, depth = 0) {
    if (value === null || value === undefined || typeof value !== "object" || depth > 8) {
        return null;
    }
    if (isTopoDS(value)) {
        return value.isNull() ? null : value;
    }
    if ("isOk" in value) {
        if (!value.isOk) {
            throw new Error(String(value.error ?? "the operation failed"));
        }
        // 'ShapeResult' (the kernel) carries "shape"; 'Result' (the API) carries
        // "value". Both are unwrapped the same way.
        return toShape("shape" in value ? value.shape : value.value, depth + 1);
    }
    if ("shape" in value) {
        return toShape(value.shape, depth + 1);
    }
    return null;
}

/**
 * Compound a script's result shapes and collect its components.
 *
 * The twin of 'wrapper_common.combine()': the filtering happens here so the
 * PartCAD core never touches live geometry. 'kind' picks the rule:
 *   - "sketch": keep only the 1D/2D geometry (edges/wires/faces), descending
 *     into a compound that wraps such geometry rather than discarding it.
 *   - "part" (default): every shape is a component, and everything except bare
 *     edges/wires/faces goes into the compound.
 * Nested arrays are walked and preserved in the components tree.
 *
 * Returns '{compound, components}', both already encoded as envelopes, or
 * '{compound: null, components: []}' when the script produced no geometry.
 */
export function combine(values, kind = "part") {
    const wasm = globalThis.wasm;
    const enums = wasm.TopAbs_ShapeEnum;
    const COMPOUND = enums.TopAbs_COMPOUND.value;
    const lowerDimensional = new Set([enums.TopAbs_EDGE.value, enums.TopAbs_WIRE.value, enums.TopAbs_FACE.value]);

    const compounded = [];
    const components = [];

    const walk = (items, out) => {
        for (const item of items) {
            if (item === null || item === undefined || typeof item === "string") {
                continue;
            }
            if (Array.isArray(item)) {
                const child = [];
                walk(item, child);
                out.push(child);
                continue;
            }
            const shape = toShape(item);
            if (shape === null) {
                continue;
            }
            const shapeType = shape.shapeType().value;
            if (kind === "sketch") {
                if (shapeType === COMPOUND) {
                    walk(wasm.Shape.iterShape(shape), out);
                    continue;
                }
                if (lowerDimensional.has(shapeType)) {
                    out.push(shape);
                    compounded.push(shape);
                }
            } else {
                out.push(shape);
                if (!lowerDimensional.has(shapeType)) {
                    compounded.push(shape);
                }
            }
        }
    };

    walk(values, components);

    if (components.length === 0) {
        return { compound: null, components: [] };
    }

    const combined = wasm.ShapeFactory.combine(compounded);
    if (!combined.isOk) {
        throw new Error("Failed to combine the resulting shapes: " + combined.error);
    }

    const encode = (item) =>
        Array.isArray(item) ? item.map(encode) : encodeShape(item, requestName, requestLabel);

    return {
        compound: encodeShape(combined.shape, requestName, requestLabel),
        components: components.map(encode),
    };
}

// Matches the specifier of a static import/export or of an 'import()' whose
// argument is a literal. Only relative specifiers are of interest - see
// prepareScript().
const RELATIVE_SPECIFIER = /(\b(?:from|import)\s*\(?\s*)(['"])(\.\.?\/[^'"]*)\2/g;

/**
 * Turn a script into a module the sandbox can import, and return its path.
 *
 * Three things happen to the source:
 *
 *   - the 'patch' expressions from the part's configuration are applied, the
 *     same way the Python wrappers apply theirs;
 *   - relative specifiers are rewritten to absolute file URLs, because the
 *     module is about to be written somewhere other than next to the original,
 *     and a relative import has to keep meaning what it meant there;
 *   - nothing is done to bare specifiers, which is the point of writing the
 *     module into the sandbox: 'import "chili3d"' then resolves through the
 *     'node_modules' the sandbox links into that directory, exactly as it would
 *     for any other project.
 *
 * The module is written into the per-package sandbox directory under a name
 * derived from the original path, so two parts never collide and a re-render
 * overwrites its own file rather than accumulating.
 */
export function prepareScript(scriptPath, patch, directory) {
    let source = fs.readFileSync(scriptPath, "utf8");
    for (const [pattern, replacement] of Object.entries(patch ?? {})) {
        if (pattern === "\\Z") {
            // The end-of-input anchor PartCAD itself generates for "show" and
            // "showObject". JavaScript has no '\Z', and the '$' it does have
            // would match at every line end under the 'm' flag the other
            // patches need, so this one is appended rather than substituted.
            source += replacement;
            continue;
        }
        // 'm' to match the Python wrappers, whose patches are applied with
        // re.MULTILINE. The replacement is returned from a function so that a
        // '$' inside it stays a literal '$' rather than a group reference.
        source = source.replace(new RegExp(pattern, "gm"), () => replacement);
    }

    const scriptDir = path.dirname(path.resolve(scriptPath));
    source = source.replace(RELATIVE_SPECIFIER, (match, prefix, quote, specifier) => {
        const resolved = pathToFileURL(path.resolve(scriptDir, specifier)).href;
        return `${prefix}${quote}${resolved}${quote}`;
    });

    const digest = crypto.createHash("sha256").update(path.resolve(scriptPath)).digest("hex").slice(0, 16);
    const modulePath = path.join(directory, `.partcad.${digest}.mjs`);
    fs.writeFileSync(modulePath, source);
    return modulePath;
}
