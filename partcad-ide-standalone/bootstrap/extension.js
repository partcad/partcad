//
// PartCAD, 2026
//
// Author: PartCAD (support@partcad.org)
//
// Licensed under Apache License, Version 2.0.
//
// What makes the PartCAD IDE a PartCAD IDE rather than a VSCodium with
// extensions in it. It ships only inside that IDE (see ../README.md); it is not
// published, and it does nothing in a plain VS Code, where `appRoot` has no
// PartCAD tools next to it and the user chose their own layout.
//

const fs = require('fs');
const path = require('path');
const vscode = require('vscode');

// The view container the PartCAD extension contributes to the activity bar. VS
// Code derives one command per contributed container, named after its id.
const WORKBENCH_COMMAND = 'workbench.view.extension.partcad-container';

const SERVICE_EXECUTABLE = process.platform === 'win32' ? 'partcad-json-rpc.exe' : 'partcad-json-rpc';

let output;

function log(message) {
    if (!output) {
        output = vscode.window.createOutputChannel('PartCAD IDE');
    }
    output.appendLine(message);
}

/**
 * The directory holding the PartCAD command line tools this IDE was built with,
 * or undefined when the IDE is running without them (a developer build, or this
 * extension installed into an editor of the user's own).
 *
 * `appRoot` is `<resources>/app`, and `build.sh` puts the tools in
 * `<resources>/partcad-cli` on every platform, so one path works for the Linux
 * and Windows layouts and for the macOS application bundle alike.
 */
function bundledToolsDirectory() {
    const directory = path.join(vscode.env.appRoot, '..', 'partcad-cli');
    try {
        return fs.statSync(path.join(directory, SERVICE_EXECUTABLE)).isFile() ? directory : undefined;
    } catch {
        return undefined;
    }
}

/**
 * Point the PartCAD extension at the bundled service, so that a user who has no
 * Python -- the reason this IDE exists -- is not asked to download one on first
 * use.
 *
 * Only when the setting is unset or points at something that is no longer
 * there: a path the user chose is theirs, and a path from an older install of
 * this IDE is stale after an upgrade or a move, which is why it is rewritten
 * rather than left alone.
 */
async function useBundledService(servicePath) {
    const configuration = vscode.workspace.getConfiguration('partcad');
    const configured = configuration.inspect('servicePath');
    const current = configured ? configured.globalValue : undefined;

    if (current === servicePath) {
        return;
    }
    if (current && fs.existsSync(current)) {
        log(`Keeping partcad.servicePath as configured: ${current}`);
        return;
    }

    await configuration.update('servicePath', servicePath, vscode.ConfigurationTarget.Global);
    log(`Set partcad.servicePath to the bundled service: ${servicePath}`);
}

async function showWorkbench() {
    const commands = await vscode.commands.getCommands(true);
    if (!commands.includes(WORKBENCH_COMMAND)) {
        // The PartCAD extension is disabled or was uninstalled. Opening the IDE
        // into an editor is the right outcome then, not an error dialog.
        log(`The PartCAD workbench is not available (${WORKBENCH_COMMAND} is not registered).`);
        return;
    }
    await vscode.commands.executeCommand(WORKBENCH_COMMAND);
}

async function activate(context) {
    const configuration = vscode.workspace.getConfiguration('partcadIde');

    if (configuration.get('useBundledTools', true)) {
        const tools = bundledToolsDirectory();
        if (tools) {
            // So that `pc` works in the IDE's terminal without the user
            // installing anything or editing their shell profile.
            context.environmentVariableCollection.description = 'Adds the bundled PartCAD tools to the PATH';
            context.environmentVariableCollection.prepend('PATH', tools + path.delimiter);
            try {
                await useBundledService(path.join(tools, SERVICE_EXECUTABLE));
            } catch (error) {
                log(`Could not configure the bundled PartCAD service: ${error}`);
            }
        } else {
            log('No bundled PartCAD tools next to this application; leaving the PartCAD settings alone.');
        }
    }

    if (configuration.get('openWorkbenchOnStartup', true)) {
        try {
            await showWorkbench();
        } catch (error) {
            log(`Could not open the PartCAD workbench: ${error}`);
        }
    }
}

function deactivate() {}

module.exports = { activate, deactivate };
