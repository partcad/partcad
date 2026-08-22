// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Loads Chili3D inside a bare Node.js process.
//
// Chili3D is built for the browser, so three things have to happen before its
// API can be touched here:
//
//   1. It has to be found. This file is part of the PartCAD installation, not
//      of the sandbox, so a bare 'import "chili3d"' would resolve against
//      PartCAD's own directory and find nothing. Everything is therefore
//      resolved explicitly, starting from the sandbox directory Node.js was
//      launched in (see runtime_javascript for that layout).
//   2. Its OCCT kernel has to be instantiated. The kernel is an Emscripten
//      module that fetches its '.wasm' over HTTP in a browser; in Node.js the
//      bytes are read from disk and handed to it instead, which its loader
//      supports through 'wasmBinary'.
//   3. Enough of a DOM has to exist for its bundle to import at all: evaluating
//      it defines custom elements, so a bare Node.js fails with "HTMLElement is
//      not defined" before any modeling code runs.

import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

// The globals Chili3D's bundle touches while it is being imported. Anything
// Node.js already provides is left alone - this shim exists for the import to
// succeed, and nothing on the modeling path uses it afterwards.
const DOM_GLOBALS = [
    "window",
    "document",
    "navigator",
    "location",
    "customElements",
    "HTMLElement",
    "HTMLCanvasElement",
    "HTMLDivElement",
    "HTMLInputElement",
    "Node",
    "Element",
    "DocumentFragment",
    "ShadowRoot",
    "CSSStyleSheet",
    "getComputedStyle",
    "requestAnimationFrame",
    "cancelAnimationFrame",
    "Event",
    "CustomEvent",
    "EventTarget",
    "MutationObserver",
    "ResizeObserver",
    "Image",
    "DOMParser",
    "XMLSerializer",
];

/**
 * The sandbox directory Node.js resolves dependencies from.
 *
 * Walks up from the working directory looking for a 'node_modules', which is
 * how Node.js itself resolves. The runtime launches the wrapper in the
 * per-package directory, whose 'node_modules' is a link to the environment's,
 * so the first hit is the right one.
 */
export function findSandboxRoot(start = process.cwd()) {
    let dir = path.resolve(start);
    for (;;) {
        if (fs.existsSync(path.join(dir, "node_modules"))) {
            return dir;
        }
        const parent = path.dirname(dir);
        if (parent === dir) {
            return null;
        }
        dir = parent;
    }
}

/**
 * The real directory of an installed npm package, or null if it is not there.
 *
 * The path is resolved through to its real location on purpose. The sandbox
 * reaches 'node_modules' through a link, and importing the same file by two
 * different paths would load two copies of the module - two Chili3D instances
 * whose classes are not each other's.
 */
export function findPackageDir(name, root = findSandboxRoot()) {
    if (root === null) {
        return null;
    }
    const candidate = path.join(root, "node_modules", ...name.split("/"));
    if (!fs.existsSync(candidate)) {
        return null;
    }
    return fs.realpathSync(candidate);
}

/** The entry point declared by an installed package's manifest. */
function packageEntry(packageDir) {
    const manifest = JSON.parse(fs.readFileSync(path.join(packageDir, "package.json"), "utf8"));
    const exported = manifest.exports;
    let relative = null;
    if (typeof exported === "string") {
        relative = exported;
    } else if (exported !== null && typeof exported === "object") {
        const root = exported["."] ?? exported;
        relative = typeof root === "string" ? root : (root?.import ?? root?.default ?? null);
        if (relative !== null && typeof relative === "object") {
            relative = relative.default ?? null;
        }
    }
    relative ??= manifest.module ?? manifest.main ?? "index.js";
    return path.join(packageDir, relative);
}

async function importPackage(name, root) {
    const packageDir = findPackageDir(name, root);
    if (packageDir === null) {
        throw new Error(
            `'${name}' is not installed in the PartCAD sandbox (looked under ${root ?? process.cwd()}). ` +
                "This usually means the sandbox failed to provision; run with --verbose to see the npm output.",
        );
    }
    return await import(pathToFileURL(packageEntry(packageDir)).href);
}

/** Install the DOM globals Chili3D's bundle needs in order to be imported. */
async function installDomShim(root) {
    if (typeof globalThis.HTMLElement !== "undefined") {
        return;
    }
    const { Window } = await importPackage("happy-dom", root);
    const window = new Window({ url: "http://localhost/" });
    for (const name of DOM_GLOBALS) {
        if (globalThis[name] === undefined && window[name] !== undefined) {
            globalThis[name] = window[name];
        }
    }
}

/**
 * Instantiate Chili3D's OCCT kernel and publish it as the 'wasm' global.
 *
 * The global is not a convenience: Chili3D's own API reads 'global.wasm' (its
 * 'initWasm()' is what normally sets it, by a route that only works in a
 * browser), so its high-level classes do not work until this is in place.
 */
/**
 * Where the kernel's Emscripten loader and its '.wasm' sit next to each other.
 *
 * The published package has carried them in more than one place across
 * releases - as the workspace package they are built in, and inside the browser
 * bundle's asset directories - and the version is the package's to choose, so
 * the known layouts are tried first and then a bounded scan covers the rest.
 */
function findKernelDir(chili3dDir) {
    const known = [
        path.join(chili3dDir, "packages", "chili-wasm", "lib"),
        path.join(chili3dDir, "dist", "wasm"),
        path.join(chili3dDir, "dist", "assets"),
    ];
    const holdsKernel = (dir) =>
        fs.existsSync(path.join(dir, "chili-wasm.js")) && fs.existsSync(path.join(dir, "chili-wasm.wasm"));

    for (const dir of known) {
        if (holdsKernel(dir)) {
            return dir;
        }
    }

    // Breadth-first and depth-capped: the package is large (the '.wasm' alone
    // is ~15MB) and this runs on every render, so it must not turn into a walk
    // of the whole tree.
    let frontier = [chili3dDir];
    for (let depth = 0; depth < 4 && frontier.length > 0; depth++) {
        const next = [];
        for (const dir of frontier) {
            let entries;
            try {
                entries = fs.readdirSync(dir, { withFileTypes: true });
            } catch {
                continue;
            }
            for (const entry of entries) {
                if (!entry.isDirectory() || entry.name === "node_modules") {
                    continue;
                }
                const child = path.join(dir, entry.name);
                if (holdsKernel(child)) {
                    return child;
                }
                next.push(child);
            }
        }
        frontier = next;
    }
    return null;
}

async function initKernel(chili3dDir) {
    const dir = findKernelDir(chili3dDir);
    if (dir === null) {
        const version = JSON.parse(fs.readFileSync(path.join(chili3dDir, "package.json"), "utf8")).version;
        throw new Error(
            `The Chili3D WebAssembly kernel is not part of the installed 'chili3d' (version ${version}, in ` +
                `${chili3dDir}). Not every release publishes it; pick one that does, with 'chili3dVersion' ` +
                "on the part or the package.",
        );
    }
    const factory = (await import(pathToFileURL(path.join(dir, "chili-wasm.js")).href)).default;
    return await factory({
        wasmBinary: fs.readFileSync(path.join(dir, "chili-wasm.wasm")),
        // Emscripten prints to stdout by default, and stdout is where the
        // response goes. Route both streams to stderr, which PartCAD shows as
        // a warning rather than trying to parse.
        print: (text) => process.stderr.write(text + "\n"),
        printErr: (text) => process.stderr.write(text + "\n"),
    });
}

/**
 * Load Chili3D and return what a script gets to work with.
 *
 * Returns '{wasm, chili3d, shapeFactory}': the raw kernel, the Chili3D module
 * namespace, and a ready-made high-level shape factory.
 */
export async function loadChili3d() {
    const root = findSandboxRoot();
    const chili3dDir = findPackageDir("chili3d", root);
    if (chili3dDir === null) {
        throw new Error(
            `'chili3d' is not installed in the PartCAD sandbox (looked under ${root ?? process.cwd()}). ` +
                "This usually means the sandbox failed to provision; run with --verbose to see the npm output.",
        );
    }

    // The kernel first: it has no DOM dependency, so a failure here is about
    // WebAssembly and is worth reporting without the shim in the picture.
    globalThis.wasm = await initKernel(chili3dDir);

    await installDomShim(root);
    const chili3d = await import(pathToFileURL(packageEntry(chili3dDir)).href);

    return {
        wasm: globalThis.wasm,
        chili3d,
        shapeFactory: new chili3d.ShapeFactory(),
    };
}
