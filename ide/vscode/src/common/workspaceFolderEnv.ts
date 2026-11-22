//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Which folder this window has open, told to `pc init`.
//
// `pc init` writes the agents' MCP configuration, the skills and the "Render"
// command into the folder an editor opens, because that is the only place an
// editor or agent reads them from -- and it has no way of its own to know which
// folder that is. The git repository's root is a guess, and wrong whenever the
// window opened a folder of repositories, or a folder inside one. The extension
// knows, so it says:
//
// * to the terminals of each workspace folder, as `PARTCAD_WORKSPACE_FOLDER`,
//   through a collection scoped to that folder. VS Code applies a scoped
//   collection to a terminal whose starting directory is in the folder (or,
//   when it has none, the last active folder), so in a multi-root workspace each
//   folder's terminals get their own. A terminal keeps the value wherever it
//   `cd`s to, which is why `pc init` uses it only for a package inside it
//   (`partcad.launch_config.choose_editor_folder`);
// * to the `pc init` that "Init package" runs (`initInvocation`): the folder the
//   new package is in. Creating a package is the client's work -- it writes
//   files on this machine, beside the package and into the folder this window
//   has open -- so it is `pc init`, run here like `pc lint --file`, and the
//   daemon is only asked to load what was created.
//
// Unlike the PATH in `terminalPath.ts` this does not depend on
// `partcad.addToolsToTerminalPath`: it states a fact about the window, and
// whichever `pc` a terminal runs -- the extension's, or one the user installed
// -- is told it.
//

import * as path from 'path';
import * as vscode from 'vscode';

/**
 * The variable. Kept in step with `WORKSPACE_FOLDER_ENV` in
 * `src/partcad_utils/agent_config.py`, which is what reads it.
 */
export const WORKSPACE_FOLDER_ENV = 'PARTCAD_WORKSPACE_FOLDER';

/** What a folder's terminals are told: its path on disk, or nothing for a folder that is not on disk. */
export function workspaceFolderValue(folder: { uri: { scheme: string; fsPath: string } }): string | undefined {
    return folder.uri.scheme === 'file' ? folder.uri.fsPath : undefined;
}

/**
 * Set the variable on the terminals of each folder in `added`, and take it off
 * those of each folder in `removed`.
 *
 * `getScoped` returns a collection of its own for each folder, which another
 * folder's does not touch. The window-wide collection's `clear()` would: with no
 * scope it empties every scope, which is why `refreshToolsPath` deletes the
 * variables it owns instead.
 */
export function advertiseWorkspaceFolders(
    collection: vscode.GlobalEnvironmentVariableCollection,
    added: readonly vscode.WorkspaceFolder[],
    removed: readonly vscode.WorkspaceFolder[] = [],
): void {
    for (const folder of removed) {
        collection.getScoped({ workspaceFolder: folder }).clear();
    }
    for (const folder of added) {
        const scoped = collection.getScoped({ workspaceFolder: folder });
        const value = workspaceFolderValue(folder);
        if (value === undefined) {
            scoped.delete(WORKSPACE_FOLDER_ENV);
            continue;
        }
        scoped.description = 'Tells `pc init` which folder this window has open';
        scoped.replace(WORKSPACE_FOLDER_ENV, value, { applyAtProcessCreation: true });
    }
}

/** Advertise every workspace folder now, and each one added or removed later. */
export function registerWorkspaceFolderVariable(context: vscode.ExtensionContext): void {
    const collection = context.environmentVariableCollection;
    advertiseWorkspaceFolders(collection, vscode.workspace.workspaceFolders ?? []);
    context.subscriptions.push(
        vscode.workspace.onDidChangeWorkspaceFolders((event) =>
            advertiseWorkspaceFolders(collection, event.added, event.removed),
        ),
    );
}

/** The workspace folder holding `fsPath`, as "Init package" tells `pc init`; undefined when none does. */
export function workspaceFolderOf(fsPath: string): string | undefined {
    if (!fsPath) {
        return undefined;
    }
    const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(fsPath));
    return folder ? workspaceFolderValue(folder) : undefined;
}

/** What "Init package" runs: `pc -p <directory> init`, with the folder the package is in. */
export interface InitInvocation {
    /** The directory the package is created in, and `pc init` is run in. */
    directory: string;
    /** The arguments after `pc --no-ansi`. */
    args: string[];
    /** What to add to the environment: `PARTCAD_WORKSPACE_FOLDER`, where the directory is in a workspace folder. */
    env: Record<string, string>;
}

/**
 * How to create a package at `packagePath` -- a directory, or the `partcad.yaml`
 * to create in one -- with `pc init`.
 *
 * `-p` names the directory rather than the file, because `pc` takes `-p` to be a
 * path that exists. `folderOf` is `workspaceFolderOf`, a parameter so that a
 * test need not have the folder open.
 */
export function initInvocation(
    packagePath: string,
    fallback: string,
    folderOf: (fsPath: string) => string | undefined = workspaceFolderOf,
): InitInvocation {
    const target = packagePath || fallback;
    const directory = /\.ya?ml$/i.test(target) ? path.dirname(target) : target;
    const folder = folderOf(directory);
    return {
        directory,
        args: ['-p', directory, 'init'],
        env: folder ? { [WORKSPACE_FOLDER_ENV]: folder } : {},
    };
}
