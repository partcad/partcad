// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// This script is executed within the JavaScript sandbox environment (the
// Node.js runtime) to invoke Chili3D scripts - the twin of
// 'wrapper_cadquery.py' and 'wrapper_build123d.py'.
//
// A '.chili' file is an ES module that builds geometry with Chili3D and hands
// it back, either by calling the 'show()' the wrapper provides or by exporting
// it. What it gets to work with, as globals:
//
//   chili3d       the Chili3D module namespace (ShapeFactory, Plane, XYZ, ...)
//   shapeFactory  a ready-made 'new chili3d.ShapeFactory()'
//   wasm          the OCCT WebAssembly kernel, for what the API does not cover
//   show(...)     collect a shape (or an array of them) as the part's result
//   show_object   an alias, so a script reads like its CadQuery counterpart
//   parameters    the part's build parameters, also injected as globals
//
// The module is written into the sandbox before it is imported (see
// prepareScript), so a script is free to 'import "chili3d"' by name instead.

import path from "node:path";
import { pathToFileURL } from "node:url";

import { loadChili3d } from "./chili3d_kernel.mjs";
import { combine, handleException, handleInput, handleOutput, prepareScript } from "./chili3d_common.mjs";

// Identifiers a script can define its result under when it does not call
// show(), in the order they are looked at.
const RESULT_EXPORTS = ["default", "shape", "result", "part"];

async function process_(scriptPath, cwd, request, sandboxDir) {
    const shown = [];
    // 'show([a, b])' means the same as 'show(a, b)': one array argument is the
    // list of shapes, not a group holding one. Deeper nesting is preserved, so
    // a script that does want a group can still express one.
    const show = (...values) => {
        for (const value of values) {
            if (Array.isArray(value)) {
                shown.push(...value);
            } else {
                shown.push(value);
            }
        }
        return values.length === 1 ? values[0] : values;
    };

    const { chili3d, shapeFactory, wasm } = await loadChili3d();

    globalThis.chili3d = chili3d;
    globalThis.shapeFactory = shapeFactory;
    globalThis.wasm = wasm;
    globalThis.show = show;
    globalThis.show_object = show;
    globalThis.showObject = show;

    // Build parameters are reachable both as a bag and by name, the way the
    // CadQuery and build123d scripts see theirs.
    const parameters = request.build_parameters ?? {};
    globalThis.parameters = parameters;
    for (const [name, value] of Object.entries(parameters)) {
        globalThis[name] = value;
    }

    const modulePath = prepareScript(scriptPath, request.patch, sandboxDir);

    // Only now: the script is meant to see its own package as the working
    // directory, the way 'wrapper_common.handle_input()' arranges for the
    // Python ones. Resolution is unaffected - it follows the module's location,
    // which is inside the sandbox.
    if (cwd !== null) {
        process.chdir(cwd);
    }

    const module = await import(pathToFileURL(modulePath).href);

    if (shown.length === 0) {
        for (const name of RESULT_EXPORTS) {
            if (module[name] !== undefined) {
                show(module[name]);
                break;
            }
        }
    }

    const { compound, components } = combine(shown, request.kind ?? "part");
    if (compound === null) {
        throw new Error(
            "the script produced no shape: call show(...) with the result, or export it as 'default'",
        );
    }

    return {
        success: true,
        exception: null,
        shape: compound,
        components,
    };
}

const { scriptPath, cwd, request } = await handleInput();
// Captured before the script moves us: this is the sandbox directory the
// runtime launched Node.js in, and where the prepared module has to land for
// its bare imports to resolve.
const sandboxDir = path.resolve(process.cwd());

let model;
try {
    model = await process_(scriptPath, cwd, request, sandboxDir);
} catch (error) {
    handleException(error, scriptPath);
    model = {
        success: false,
        exception: error instanceof Error ? error.message : String(error),
        shape: null,
        components: [],
    };
}

handleOutput(model);
