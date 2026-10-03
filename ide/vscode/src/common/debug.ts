//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Debugging PartCAD's Python from the repository's `Debug Extension and Python`
// launch configuration. It starts a debugpy listener and an Extension
// Development Host whose environment carries `PC_DEBUGPY`; every service this
// extension starts inherits that, and attaches to the listener as it starts
// (`partcad_service_json_rpc.debugger`).
//
// Two things stand in the way, and both are handled here, once, on the first
// connection this extension host makes:
//
// * Which service runs. Left to `resolveServicePath`, it is whatever a user's
//   window would run -- a downloaded bundle, more often than not -- and no
//   breakpoint in this checkout is ever hit. So while debugging, the checkout's
//   own `.venv` is preferred when it has one.
// * Which daemon answers. A daemon is warm and outlives whoever started it, so
//   the one a first connection reaches was usually started without the variable,
//   or by a previous debug session whose listener is gone. If it is this
//   checkout's and not attached, it is stopped, and connecting again starts one
//   that is. A daemon running anything else is left alone: replacing it would
//   start the same code again, no nearer to the debugger.
//
// Neither applies outside development mode or without `PC_DEBUGPY`, so an
// installed extension never takes either path.
//

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

/** The variable the launch configuration sets; the service reads the same one. */
export const DEBUGPY_ENV = 'PC_DEBUGPY';

/** The JSON-RPC method that says where a service runs from and whether it is attached. */
export const DEBUG_STATUS_METHOD = 'daemon.debug';

/** What `daemon.debug` answers. */
export type DebugStatus = { source?: string; pid?: number; debugger?: boolean };

/**
 * The checkout this extension is being debugged from, or undefined when it is
 * not being debugged with Python attached.
 *
 * The extension's own directory is `<checkout>/ide/vscode`.
 */
export function debugCheckout(context: vscode.ExtensionContext): string | undefined {
    if (context.extensionMode !== vscode.ExtensionMode.Development || !process.env[DEBUGPY_ENV]) {
        return undefined;
    }
    return path.resolve(context.extensionPath, '..', '..');
}

/** The checkout's own `partcad-json-rpc`, when its `.venv` has one. */
export function checkoutService(checkout: string): string | undefined {
    const candidate =
        process.platform === 'win32'
            ? path.join(checkout, '.venv', 'Scripts', 'partcad-json-rpc.exe')
            : path.join(checkout, '.venv', 'bin', 'partcad-json-rpc');
    return fs.existsSync(candidate) ? candidate : undefined;
}

function canonical(p: string): string {
    try {
        p = fs.realpathSync(p);
    } catch {
        p = path.resolve(p);
    }
    return process.platform === 'win32' ? p.toLowerCase() : p;
}

/**
 * Whether a daemon reporting `status` should be replaced by one attached to the
 * debugger: it runs this checkout's code and nothing is attached to it.
 *
 * Exported for the test suite.
 */
export function needsReplacing(status: DebugStatus | undefined, checkout: string): boolean {
    if (!status?.source || status.debugger === true) {
        return false;
    }
    return canonical(status.source) === canonical(path.join(checkout, 'src', 'partcad_service_json_rpc'));
}
