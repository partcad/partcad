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
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');
const vscode = require('vscode');

// The view container the PartCAD extension contributes to the activity bar. VS
// Code derives one command per contributed container, named after its id.
const WORKBENCH_COMMAND = 'workbench.view.extension.partcad-container';

const SERVICE_EXECUTABLE = process.platform === 'win32' ? 'partcad-json-rpc.exe' : 'partcad-json-rpc';
const CLI_EXECUTABLE = process.platform === 'win32' ? 'pc.exe' : 'pc';

// The welcome window: the walkthrough this extension contributes (see
// `package.json`), addressed the way the editor addresses one --
// `<publisher>.<name>#<walkthrough id>`.
const WALKTHROUGH = 'PartCAD.partcad-ide-bootstrap#partcadStart';

// The package the IDE creates for someone who has just installed it, and the
// workspace it opens the first time it starts.
//
// It goes under `~/.partcad`, not under the IDE's own `~/.partcad-ide`, because
// it is a package like any other: `pc` in a terminal and a second editor on the
// same machine see the one the IDE made, and uninstalling the IDE does not take
// the user's first design with it.
const STARTER_PACKAGE_PATH = ['.partcad', 'projects', 'start'];
const PACKAGE_CONFIGURATION = 'partcad.yaml';
const STARTER_DESCRIPTION = 'A PartCAD package to start from';

// Whether the first start has happened, and whether the welcome window is still
// owed to the user. Both are in `globalState`, which is per installation of the
// IDE rather than per workspace -- and which survives the window reopening on
// the starter package, the reason the second one exists at all.
const STARTER_DONE_KEY = 'partcadIde.starterPackage.done';
const WELCOME_PENDING_KEY = 'partcadIde.welcome.pending';

// `pc init` writes a template to disk: no network, no CAD kernel, no sandbox.
// It is slow anyway the first time, because it runs out of a PyInstaller bundle
// that unpacks itself before `main` -- on the cold filesystem of a machine that
// has just installed the IDE, which is precisely when this runs, that has taken
// tens of seconds.
const INIT_TIMEOUT_MS = 5 * 60 * 1000;

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

/** The PartCAD walkthrough, in the editor area, as the welcome window. */
async function showWelcome() {
    try {
        await vscode.commands.executeCommand('workbench.action.openWalkthrough', WALKTHROUGH, false);
    } catch (error) {
        // A welcome window that will not open is not a reason to stop: the IDE
        // behind it works.
        log(`Could not open the PartCAD welcome window: ${error}`);
    }
}

function starterPackageDirectory() {
    return path.join(os.homedir(), ...STARTER_PACKAGE_PATH);
}

/**
 * `pc init` in `directory`.
 *
 * The path it writes to is its working directory rather than an argument: `pc`
 * takes a package path globally (`-p`), but `init` creates `partcad.yaml`
 * beside wherever it was run. `--no-ansi` because nobody is watching this
 * terminal -- it turns the progress bars into plain text on stderr, which is
 * what the output channel below is for.
 */
function runInit(cli, directory) {
    return new Promise((resolve) => {
        execFile(
            cli,
            ['--no-ansi', 'init', '--desc', STARTER_DESCRIPTION],
            { cwd: directory, timeout: INIT_TIMEOUT_MS, windowsHide: true },
            (error, stdout, stderr) => {
                for (const stream of [stdout, stderr]) {
                    const text = (stream || '').trim();
                    if (text) {
                        log(text);
                    }
                }
                if (error) {
                    log(`Running '${cli} init' failed: ${error}`);
                }
                resolve();
            },
        );
    });
}

/**
 * The starter package, created if it is not there yet.
 *
 * Returns its directory when there is a package in it to open, and undefined
 * when there is not: an IDE built without the command line tools has no `pc` to
 * run, and a `pc init` that failed leaves nothing worth opening. Neither is an
 * error dialog -- the IDE still works, and the welcome window says how to make
 * a package by hand.
 */
async function createStarterPackage(tools) {
    const directory = starterPackageDirectory();
    const configuration = path.join(directory, PACKAGE_CONFIGURATION);

    if (fs.existsSync(configuration)) {
        return directory;
    }
    if (!tools) {
        log('No bundled PartCAD tools next to this application; not creating a starter package.');
        return undefined;
    }

    log(`Creating a PartCAD package in ${directory}`);
    await fs.promises.mkdir(directory, { recursive: true });
    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Window, title: 'Creating your first PartCAD package...' },
        () => runInit(path.join(tools, CLI_EXECUTABLE), directory),
    );

    // `pc init` reports a refusal -- a configuration file that is already there,
    // a directory it cannot write -- by logging it and exiting 0, so the file is
    // what says whether this worked.
    if (!fs.existsSync(configuration)) {
        log(`No ${PACKAGE_CONFIGURATION} in ${directory} after 'pc init'; leaving the workspace empty.`);
        // Nothing was created, so nothing is left behind: an empty directory in
        // the user's home is worse than none, because the next attempt cannot
        // tell it from a package that was emptied on purpose.
        await fs.promises.rmdir(directory).catch(() => {});
        return undefined;
    }
    return directory;
}

function isOpenWorkspace(directory) {
    const folders = vscode.workspace.workspaceFolders || [];
    return folders.some((folder) => path.resolve(folder.uri.fsPath) === path.resolve(directory));
}

/**
 * Open the starter package as the workspace, and arrange for the welcome window
 * to appear once it has.
 *
 * `vscode.openFolder` reopens the workbench on the new folder, and an editor
 * opened before it goes with the window it was opened in -- so the welcome
 * window is left as a note in `globalState` for the activation that follows,
 * rather than opened here.
 */
async function openStarterWorkspace(context, directory) {
    await context.globalState.update(WELCOME_PENDING_KEY, true);
    try {
        await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(directory), {
            forceNewWindow: false,
        });
    } catch (error) {
        await context.globalState.update(WELCOME_PENDING_KEY, false);
        throw error;
    }
}

/**
 * What the IDE does the first time it is started after being installed: make a
 * package for the user and open it, so that the PartCAD Explorer has something
 * in it and the welcome window has something to point at.
 *
 * It happens here rather than in the installers because there are three of them
 * -- `install.sh`, the Windows setup program, and a .dmg the user drags to
 * Applications, which is no installer at all -- and because the editor is what
 * has to open the folder in any case.
 */
async function setUpStarterPackage(context, tools) {
    if (context.globalState.get(STARTER_DONE_KEY)) {
        return;
    }

    if ((vscode.workspace.workspaceFolders || []).length > 0 || vscode.workspace.workspaceFile) {
        // Started on a folder of the user's own -- "Open with PartCAD IDE" on a
        // directory, or a window restored from a previous session. There is
        // nothing to set up, and recording it keeps the IDE from taking over
        // some later empty window instead.
        await context.globalState.update(STARTER_DONE_KEY, true);
        return;
    }

    const directory = await createStarterPackage(tools);
    await context.globalState.update(STARTER_DONE_KEY, true);

    if (!directory) {
        await showWelcome();
        return;
    }
    await openStarterWorkspace(context, directory);
}

/**
 * "PartCAD IDE: Open the starter package", and the button the welcome window's
 * first step carries. Creates the package if it is not there -- the first start
 * can have run without the command line tools, or before the user had a home
 * directory to write to.
 */
async function openStarterPackage() {
    const directory = await createStarterPackage(bundledToolsDirectory());
    if (!directory) {
        vscode.window.showErrorMessage(
            `PartCAD could not create a package in ${starterPackageDirectory()}. ` +
                'The "PartCAD IDE" output channel has the details.',
        );
        return;
    }
    if (isOpenWorkspace(directory)) {
        // It is already the workspace: opening the folder again would reload
        // the window for nothing, so show the package configuration instead.
        const document = await vscode.workspace.openTextDocument(path.join(directory, PACKAGE_CONFIGURATION));
        await vscode.window.showTextDocument(document);
        return;
    }
    await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(directory), { forceNewWindow: false });
}

async function activate(context) {
    const configuration = vscode.workspace.getConfiguration('partcadIde');

    context.subscriptions.push(vscode.commands.registerCommand('partcadIde.openStarterPackage', openStarterPackage));
    context.subscriptions.push(vscode.commands.registerCommand('partcadIde.showWelcome', showWelcome));

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

    // The other half of the first start, running in the window that
    // `vscode.openFolder` reopened. Cleared first: a welcome window that fails
    // to open is not owed forever.
    if (context.globalState.get(WELCOME_PENDING_KEY)) {
        await context.globalState.update(WELCOME_PENDING_KEY, false);
        await showWelcome();
    }

    if (configuration.get('createStarterPackage', true)) {
        try {
            await setUpStarterPackage(context, bundledToolsDirectory());
        } catch (error) {
            log(`Could not set up the starter package: ${error}`);
        }
    }
}

function deactivate() {}

module.exports = { activate, deactivate };
