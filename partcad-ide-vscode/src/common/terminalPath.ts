//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The PartCAD command line tools on the PATH of the integrated terminal, so
// that `pc` works in a terminal the user opens in this window without them
// installing anything or editing a shell profile.
//
// This is the same thing `partcad-ide-standalone/bootstrap/extension.js` does
// for the PartCAD IDE, whose tools sit at a fixed place inside the application.
// Here the directory is whatever the extension resolved or provisioned, which
// is what the rest of this module is about.
//

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

import { traceInfo } from './log/logging';
import { resolveServicePath } from './provision';
import { getAddToolsToTerminalPathFromSetting, getBackendFromSetting } from './settings';

/** `pc` as the filesystem spells it. */
const CLI = process.platform === 'win32' ? 'pc.exe' : 'pc';

/**
 * Where the Python backend's `pc` would be, as the language server reported it.
 *
 * The extension cannot work this out on its own: it is the scripts directory of
 * the interpreter the server is running on, under the scheme `pip install
 * --user` writes to, and only that interpreter can say what it is. Undefined
 * until `?/partcad/scriptsPath` arrives, which is after the server has finished
 * provisioning.
 */
let pythonScriptsDirectory: string | undefined;

/** The directory currently prepended, so a refresh can tell when nothing moved. */
let applied: string | undefined;

/**
 * The directory holding the tools, for the backend in use, or undefined.
 *
 * For the service backend this is the directory the resolved `partcad-json-rpc`
 * lives in: a standalone bundle is laid out as `<install-dir>/<version>/{pc,
 * partcad,partcad-json-rpc}`, one directory holding all three, so the executable
 * the extension already found names it. Some of `resolveServicePath`'s fallbacks
 * (the `~/.local/bin` launcher `install.sh` links, and a plain PATH lookup)
 * resolve to a directory that is on PATH already; prepending it again is
 * deliberate and inert, and cheaper than reasoning about what a shell will do
 * with the PATH it has not been given yet.
 */
export function toolsDirectory(context: vscode.ExtensionContext, serverId: string): string | undefined {
    if (getBackendFromSetting(serverId) === 'service') {
        const execPath = resolveServicePath(context, serverId);
        return execPath ? path.dirname(execPath) : undefined;
    }
    return pythonScriptsDirectory;
}

/**
 * Record the scripts directory the language server reported.
 *
 * Returns true when it changed, so the caller knows whether to refresh. The
 * server sends it once its environment is provisioned; before then the Python
 * backend contributes nothing to the PATH.
 */
export function setPythonScriptsDirectory(directory: string | undefined): boolean {
    const normalized = directory && directory.length > 0 ? directory : undefined;
    if (normalized === pythonScriptsDirectory) {
        return false;
    }
    pythonScriptsDirectory = normalized;
    return true;
}

/**
 * Put the tools directory for the current backend on the terminal PATH.
 *
 * Call it on activation and again whenever the directory can have moved -- `pc
 * upgrade` installs a bundle side by side under a directory named for the new
 * version and deletes the superseded one, so the path this prepended yesterday
 * can be gone today.
 *
 * Unconditional by design: it does not ask whether the workspace holds a PartCAD
 * package, and it does not look at what is on PATH already. An activated
 * extension means the user wants the tools, in every terminal of the window.
 * That also makes the collection global rather than `getScoped` per workspace
 * folder.
 */
export function refreshToolsPath(context: vscode.ExtensionContext, serverId: string): void {
    const collection = context.environmentVariableCollection;

    if (!getAddToolsToTerminalPathFromSetting(serverId)) {
        if (applied !== undefined) {
            traceInfo('PartCAD: partcad.addToolsToTerminalPath is off; removing the tools from the terminal PATH');
        }
        collection.clear();
        applied = undefined;
        return;
    }

    const directory = toolsDirectory(context, serverId);
    if (directory === applied) {
        return;
    }

    // Not persisted. The default is to restore the collection on the next
    // window before the extension has run, which would put yesterday's bundle
    // directory -- deleted by `pc upgrade`, which removes every superseded one
    // -- on the PATH of every terminal until activation got around to fixing
    // it. Re-applying on each activation costs nothing and cannot go stale.
    collection.persistent = false;

    // Replace rather than stack: `prepend` appends to what the collection
    // already holds, so refreshing after an upgrade would leave both the old
    // and the new directory on PATH, oldest first.
    collection.clear();
    applied = directory;

    if (!directory) {
        traceInfo('PartCAD: no command line tools resolved yet; leaving the terminal PATH alone');
        return;
    }

    collection.description = 'Adds the PartCAD command line tools (pc, partcad) to the PATH';
    collection.prepend('PATH', directory + path.delimiter);
    traceInfo(`PartCAD: added ${directory} to the terminal PATH`);

    if (!fs.existsSync(path.join(directory, CLI))) {
        // Worth saying rather than hiding: the directory is the right one --
        // it is where this backend's executables live -- but `pc` itself is not
        // in it, so a terminal will not get the command. For the service
        // backend that means a bundle built without the CLI; for the Python
        // backend, an environment provisioned without `partcad-cli`.
        traceInfo(`PartCAD: note that ${directory} has no '${CLI}' in it yet`);
    }
}

/** Forget the applied directory. For tests, and for a clean deactivate. */
export function resetToolsPathForTesting(): void {
    applied = undefined;
    pythonScriptsDirectory = undefined;
}
