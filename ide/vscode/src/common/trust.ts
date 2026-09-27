//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the extension does in a folder the user has not trusted yet (the
// editor's Restricted Mode): nothing, visibly, and it asks.
//
// A PartCAD package is code -- loading one runs the scripts its parts are
// written in and fetches the packages it imports -- so nothing here starts a
// service, opens a terminal or touches the PATH until the folder is trusted.
// What it does not do is disappear. It used to declare untrusted workspaces
// unsupported, and the editor then removes everything the extension
// contributes: the activity bar icon, the Explorer, the settings -- and a user
// who dismissed the editor's trust dialog had no PartCAD and nothing saying why.
//
// This is for a regular VS Code. The PartCAD IDE starts with workspace trust
// turned off (ide/standalone/build.sh), so there every folder is trusted and
// none of this runs.
//

import * as vscode from 'vscode';

/** The editor's own command: the Workspace Trust editor, with its "Trust" button. */
export const MANAGE_TRUST_COMMAND = 'workbench.trust.manage';

export const UNTRUSTED_MESSAGE =
    'PartCAD is turned off in this folder until you trust it: opening a package runs the code its parts are written in.';

const MANAGE_TRUST_ACTION = 'Manage Workspace Trust';

/** The command ids a manifest contributes. */
export function contributedCommands(packageJSON: any): string[] {
    const commands = packageJSON?.contributes?.commands;
    return Array.isArray(commands) ? commands.map((command: { command: string }) => command.command) : [];
}

/** Say why PartCAD is not doing anything, and offer the way out. */
export async function explainUntrusted(): Promise<void> {
    const chosen = await vscode.window.showWarningMessage(UNTRUSTED_MESSAGE, MANAGE_TRUST_ACTION);
    if (chosen === MANAGE_TRUST_ACTION) {
        await vscode.commands.executeCommand(MANAGE_TRUST_COMMAND);
    }
}

/**
 * Register a stand-in for each of `commands` that explains why it cannot run.
 *
 * The editor lists a contributed command in the palette and in the view menus
 * whether or not the extension registered it, and running one that is not
 * registered is a "command 'partcad.addPart' not found" error -- which is true,
 * and says nothing a user can act on. The returned disposable removes them all,
 * which has to happen before the real commands are registered under the same
 * ids.
 */
export function registerUntrustedCommands(
    commands: string[],
    explain: () => Promise<void> = explainUntrusted,
): vscode.Disposable {
    const registered = commands.map((command) => vscode.commands.registerCommand(command, () => explain()));
    return vscode.Disposable.from(...registered);
}

/**
 * Run `activateTrusted` now if the folder is trusted, and otherwise ask for
 * trust and run it once it is granted.
 *
 * The question is not awaited: it is answered whenever the user gets to it,
 * and activation has to return before then.
 *
 * Trust is only ever *granted* within a window's lifetime: taking it away
 * reloads the window, so there is no event to undo what `activateTrusted` did.
 */
export async function activateWhenTrusted(
    context: vscode.ExtensionContext,
    activateTrusted: (context: vscode.ExtensionContext) => Promise<void>,
    isTrusted: boolean = vscode.workspace.isTrusted,
    explain: () => Promise<void> = explainUntrusted,
): Promise<void> {
    if (isTrusted) {
        await activateTrusted(context);
        return;
    }

    const standIns = registerUntrustedCommands(contributedCommands(context.extension?.packageJSON), explain);
    context.subscriptions.push(standIns);
    context.subscriptions.push(
        vscode.workspace.onDidGrantWorkspaceTrust(async () => {
            standIns.dispose();
            await activateTrusted(context);
        }),
    );
    explain().catch(() => undefined);
}
