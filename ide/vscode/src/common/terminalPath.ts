//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The PartCAD command line tools on the PATH of the integrated terminal, so
// that `pc` works in a terminal the user opens in this window without them
// installing anything or editing a shell profile.
//
// This is the same thing `ide/standalone/bootstrap/extension.js` does
// for the PartCAD IDE, whose tools sit at a fixed place inside the application.
// Here the directory is whatever the extension resolved or provisioned, which
// is what the rest of this module is about.
//
// It also marks those terminals with `PARTCAD_MANAGED_BY`, which is how
// `pc upgrade` knows to refuse: a bundle the extension owns is replaced by
// updating the extension.
//

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

import { checkoutService, debugCheckout } from './debug';
import { traceInfo } from './log/logging';
import { resolveServicePath } from './provision';
import { getAddToolsToTerminalPathFromSetting } from './settings';

/** `pc` as the filesystem spells it. */
const CLI = process.platform === 'win32' ? 'pc.exe' : 'pc';

/**
 * Marks a terminal as one this extension seeded, for the tools it seeded it with.
 *
 * `pc upgrade` reads it and refuses: a bundle the extension downloaded is
 * replaced by updating the extension, and upgrading from inside it would install
 * a second copy the extension does not know about. Kept in step with
 * `MANAGED_BY_ENV` / `MANAGED_BY_EXTENSION` in
 * `partcad_client/selfupdate.py`, which is the only reader.
 */
const MANAGED_BY = 'PARTCAD_MANAGED_BY';
const MANAGED_BY_EXTENSION = 'vscode-extension';

/**
 * The directory currently prepended, so a refresh can tell when nothing moved.
 *
 * `null` until the first refresh, which is then never mistaken for "nothing
 * moved": a window that finds no tools has to say so, or a terminal without
 * `pc` leaves nothing in the log to explain it.
 */
let applied: string | undefined | null = null;

/**
 * The directory holding the tools, or undefined when nothing is installed yet.
 *
 * This is the directory the resolved `partcad-json-rpc` lives in: a standalone
 * bundle is laid out as `<install-dir>/<version>/{pc,partcad,partcad-json-rpc}`,
 * one directory holding all three, so the executable the extension already found
 * names it -- and putting it on PATH covers every entry point at once. Some of
 * `resolveServicePath`'s fallbacks (the `~/.local/bin` launcher `install.sh`
 * links, a plain PATH lookup, and a `pip install partcad` in the user's own
 * environment) resolve to a directory that is on PATH already; prepending it
 * again is deliberate and inert, and cheaper than reasoning about what a shell
 * will do with the PATH it has not been given yet.
 */
export function toolsDirectory(context: vscode.ExtensionContext, serverId: string): string | undefined {
    // The service `restartBackend` runs, looked up the same way: under the
    // debugger that is the checkout's own `.venv`, which `resolveServicePath`
    // knows nothing about -- so a debug window used to put nothing on the PATH
    // and its terminals had no `pc` at all.
    const checkout = debugCheckout(context);
    const execPath = (checkout && checkoutService(checkout)) || resolveServicePath(context, serverId);
    return execPath ? path.dirname(execPath) : undefined;
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
    // Applied twice: when the terminal's process is created, and again once
    // shell integration reports the shell is up. The second is the one that
    // counts. The first lands before the user's rc files run, and those
    // commonly prepend a directory of their own -- `conda init` activating
    // `base` is the usual one, and a base environment with an older PartCAD in
    // it then answers `pc` ahead of ours. The first stays for a shell without
    // integration (turned off, or one VS Code cannot inject into), where it is
    // all there is. The directory then appears on PATH twice, which is inert.
    collection.prepend('PATH', directory + path.delimiter, {
        applyAtProcessCreation: true,
        applyAtShellIntegration: true,
    });
    collection.replace(MANAGED_BY, MANAGED_BY_EXTENSION);
    traceInfo(`PartCAD: added ${directory} to the terminal PATH`);

    if (!fs.existsSync(path.join(directory, CLI))) {
        // Worth saying rather than hiding: the directory is the right one -- it
        // is where the resolved service lives -- but `pc` itself is not beside
        // it, so a terminal will not get the command. A standalone bundle always
        // carries all three, so this means a hand-set `partcad.servicePath`
        // pointing somewhere unusual.
        traceInfo(`PartCAD: note that ${directory} has no '${CLI}' in it`);
    }
}

/** The editor setting `applyAtShellIntegration` depends on. */
const SHELL_INTEGRATION_SECTION = 'terminal.integrated.shellIntegration';
const SHELL_INTEGRATION_SETTING = `${SHELL_INTEGRATION_SECTION}.enabled`;

export const SHELL_INTEGRATION_OFF_MESSAGE =
    'PartCAD commands (pc, partcad) may not work in this terminal: terminal shell integration is turned off, ' +
    'so a shell startup file (a `conda init`, for one) can put a different PartCAD ahead of this one on the PATH. ' +
    'Turn shell integration on, then open a new terminal.';
export const ENABLE_SHELL_INTEGRATION_ACTION = 'Enable Shell Integration';
const OPEN_SETTING_ACTION = 'Open Setting';

/** Whether the warning has been shown in this window. */
let warnedShellIntegrationOff = false;

/**
 * Whether a terminal the user just opened will get the tools only at process
 * creation, where its rc files can override them.
 *
 * Only for a terminal that runs a shell: the extension's own `PartCAD` output
 * view is a pseudoterminal, and so are other extensions' -- there is no shell
 * in them to read an rc file or to integrate with.
 */
export function needsShellIntegrationWarning(terminal: vscode.Terminal, serverId: string): boolean {
    if (warnedShellIntegrationOff || !applied) {
        return false;
    }
    if (!getAddToolsToTerminalPathFromSetting(serverId)) {
        return false;
    }
    if ('pty' in terminal.creationOptions) {
        return false;
    }
    return vscode.workspace.getConfiguration(SHELL_INTEGRATION_SECTION).get<boolean>('enabled') === false;
}

/**
 * Warn, once per window, when a terminal opens with shell integration off.
 *
 * `refreshToolsPath` re-applies the tools directory once shell integration
 * reports the shell is up; that second application is what puts it ahead of
 * whatever the user's rc files prepend. With the setting off it never happens,
 * and `pc` is whichever one the rc files put first -- which is the bug this
 * warns about rather than one the extension can fix on its own.
 */
export async function warnIfShellIntegrationOff(terminal: vscode.Terminal, serverId: string): Promise<void> {
    if (!needsShellIntegrationWarning(terminal, serverId)) {
        return;
    }
    warnedShellIntegrationOff = true;
    traceInfo(`PartCAD: ${SHELL_INTEGRATION_SETTING} is off; the tools may be shadowed on the terminal PATH`);

    const chosen = await vscode.window.showWarningMessage(
        SHELL_INTEGRATION_OFF_MESSAGE,
        ENABLE_SHELL_INTEGRATION_ACTION,
        OPEN_SETTING_ACTION,
    );
    if (chosen === ENABLE_SHELL_INTEGRATION_ACTION) {
        await vscode.workspace
            .getConfiguration(SHELL_INTEGRATION_SECTION)
            .update('enabled', true, vscode.ConfigurationTarget.Global);
    } else if (chosen === OPEN_SETTING_ACTION) {
        await vscode.commands.executeCommand('workbench.action.openSettings', SHELL_INTEGRATION_SETTING);
    }
}

/** Forget the applied directory. For tests, and for a clean deactivate. */
export function resetToolsPathForTesting(): void {
    applied = null;
    warnedShellIntegrationOff = false;
}
