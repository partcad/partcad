//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// `pc ide open <directory>`: open the folder, and show the PartCAD workbench in
// the window that opens it.
//
// An editor's command line can open a folder but cannot run a command in the
// window it opens, so the CLI leaves a request first and opens the folder after
// it (`partcad_client.ide`). One file per request:
//
//     ~/.partcad/ide/requests/<random>.json
//     {"folder": "/abs/path", "view": "workbench", "requested": <seconds since the epoch>}
//
// Read as the extension activates -- a folder opened in a new window -- and
// whenever the window gains focus, which is what opening a folder that already
// has a window does. A request is taken by the window whose workspace is that
// folder, and deleted; one nobody took is ignored once it is `REQUEST_TTL_S`
// old and deleted by whoever reads it next, so a folder opened when the
// extension was not installed does not jump to the workbench the next time it
// is opened by hand. The Python side writes the file under a temporary name and
// renames it into place, so a request is never read half-written.
//

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

import { partcadHome } from './common/garage';
import { traceError, traceVerbose } from './common/log/logging';

/** `REQUEST_TTL` in `partcad_client.ide`. */
export const REQUEST_TTL_S = 300;

/** The command VS Code derives from the view container `package.json` contributes. */
export const WORKBENCH_COMMAND = 'workbench.view.extension.partcad-container';

export interface WorkbenchRequest {
    folder: string;
    view: string;
    requested: number;
}

/** Where the requests are left: `~/.partcad/ide/requests`. */
export function requestsDirectory(home?: string): string {
    return path.join(partcadHome(home), 'ide', 'requests');
}

/** Whether two paths are one folder, as far as can be told without asking the disk too much. */
function sameFolder(left: string, right: string): boolean {
    const resolve = (value: string) => {
        let resolved = path.resolve(value);
        try {
            resolved = fs.realpathSync.native(resolved);
        } catch {
            // Gone, or never there: compared as written.
        }
        return process.platform === 'win32' || process.platform === 'darwin' ? resolved.toLowerCase() : resolved;
    };
    return resolve(left) === resolve(right);
}

/**
 * Take the requests addressed to one of `folders`, deleting them and every
 * expired request on the way, and say whether there was one.
 */
export function takeRequests(folders: string[], options: { home?: string; now?: number } = {}): boolean {
    const directory = requestsDirectory(options.home);
    const now = options.now ?? Date.now() / 1000;
    let entries: string[];
    try {
        entries = fs.readdirSync(directory);
    } catch {
        return false;
    }
    let taken = false;
    for (const entry of entries) {
        if (!entry.endsWith('.json') || entry.startsWith('.')) {
            continue;
        }
        const file = path.join(directory, entry);
        let request: Partial<WorkbenchRequest> | undefined;
        try {
            request = JSON.parse(fs.readFileSync(file, 'utf8')) as Partial<WorkbenchRequest>;
        } catch {
            request = undefined;
        }
        const expired =
            request === undefined ||
            typeof request.requested !== 'number' ||
            now - request.requested > REQUEST_TTL_S ||
            typeof request.folder !== 'string';
        const mine = !expired && folders.some((folder) => sameFolder(folder, request!.folder as string));
        if (expired || mine) {
            try {
                fs.unlinkSync(file);
            } catch {
                // Another window took it first; that window shows the workbench.
                continue;
            }
        }
        if (mine && request?.view === 'workbench') {
            taken = true;
        }
    }
    return taken;
}

/** Show the PartCAD workbench whenever a request for one of this window's folders turns up. */
export function registerWorkbenchRequests(context: vscode.ExtensionContext): void {
    const check = () => {
        const folders = (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath);
        if (folders.length === 0) {
            return;
        }
        let taken = false;
        try {
            taken = takeRequests(folders);
        } catch (error: unknown) {
            traceError(`PartCAD: could not read the workbench requests: ${error}`);
            return;
        }
        if (taken) {
            traceVerbose('PartCAD: showing the workbench, as `pc ide open` asked');
            void vscode.commands.executeCommand(WORKBENCH_COMMAND);
        }
    };
    context.subscriptions.push(
        vscode.window.onDidChangeWindowState((state) => {
            if (state.focused) {
                check();
            }
        }),
        vscode.workspace.onDidChangeWorkspaceFolders(() => check()),
    );
    check();
}
