//
// PartCAD, 2024
//
// Author: Roman Kuzmenko
// Created: 2024-12-28
//
// Licensed under Apache License, Version 2.0.
//

import * as vscode from 'vscode';
import { PartcadBackend, restartBackend } from './common/backend';
import { registerLogger, traceError, traceLog, traceVerbose } from './common/log/logging';
import {
    checkIfConfigurationChanged,
    getInstallOnOpenFromSetting,
    getPackagePathFromSetting,
    getReopenTerminalFromSetting,
    getPopupTerminalFromSetting,
} from './common/settings';
import { updateServiceBundle } from './common/provision';
import { refreshToolsPath } from './common/terminalPath';
import { loadServerDefaults } from './common/setup';
import { getLSClientTraceLevel } from './common/utilities';
import { createOutputChannel, isVirtualWorkspace, onDidChangeConfiguration, registerCommand } from './common/vscodeapi';

import { PartcadExplorer } from './PartcadExplorer';
import { PartcadInspector } from './PartcadInspector';
import { PartcadContext } from './PartcadContext';
import { PartcadLint } from './PartcadLint';
import { PartcadViewer } from './viewer/PartcadViewer';
import { PartcadViewerServer } from './viewer/PartcadViewerServer';
import * as PartcadItem from './PartcadItem';
import { examples } from './examples';
import { setTerminalWriter, terminalInit } from './terminal';
import * as utils from './utils';

let lsClient: PartcadBackend | undefined;
let partcadExplorer: PartcadExplorer | undefined;
let partcadExplorerView: vscode.TreeView<PartcadItem.PartcadItem | void>;
let partcadContext: PartcadContext | undefined;
let partcadInspector: PartcadInspector | undefined;
let partcadLint: PartcadLint | undefined;
let partcadViewer: PartcadViewer | undefined;
let partcadViewerServer: PartcadViewerServer | undefined;
let partcadTerminal: vscode.Terminal | undefined;
let terminalEmitter: vscode.EventEmitter<string> | undefined;

let lastConfigPath: string | undefined = undefined;
let lastRoot: string | undefined = undefined;
let currentItemType: string = PartcadItem.ITEM_TYPE_NONE;
let currentItemName: string = '//';
let currentItemPackage: string = '//';
let currentItemParams: { [id: string]: string } = {};
let itemToSelectOnRestart: string | undefined = undefined;

// Which packages this workspace has already had installed, keyed by the config
// file the install ran against, so that opening the same directory again is not
// another download. Stored in the workspace state: "a new workspace directory"
// has to survive a window reload, and a workspace whose `partcad.packagePath`
// now points somewhere else is a package that has not been installed yet.
const INSTALLED_PACKAGES_KEY = 'partcad.installedPackages';

/**
 * Download the package's dependencies the first time this workspace is opened.
 *
 * The PartCAD counterpart of `npm install`: it fetches every imported package
 * and prepares every sketch, part and assembly, so the first build is not also
 * the first download. It runs against the package `partcad.packagePath` points
 * at, because that is the one the service just loaded.
 */
async function installPackageOnOpen(
    context: vscode.ExtensionContext,
    serverId: string,
    configPath: string,
): Promise<void> {
    // The setting is resource-scoped, so a multi-root workspace can set it per
    // package: read it against the package this call is about.
    if (getInstallOnOpenFromSetting(serverId, vscode.Uri.file(configPath)) !== 'true') {
        return;
    }
    const installed = context.workspaceState.get<string[]>(INSTALLED_PACKAGES_KEY, []);
    if (installed.includes(configPath)) {
        return;
    }
    // Only a completed install counts: an interrupted one has to run again the
    // next time this workspace is opened.
    await vscode.commands.executeCommand('partcad.installPackage');
    await context.workspaceState.update(INSTALLED_PACKAGES_KEY, [...installed, configPath]);
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
    await vscode.commands.executeCommand('setContext', 'partcad.activated', false);
    await vscode.commands.executeCommand('setContext', 'partcad.failed', false);
    // Not yet known to be missing: `restartBackend` decides, and until it has,
    // the Explorer should say the extension is starting rather than that there
    // is nothing to start.
    await vscode.commands.executeCommand('setContext', 'partcad.serviceMissing', false);

    // This is required to get server name and module. This should be
    // the first thing that we do in this extension.
    const serverInfo = loadServerDefaults();
    const serverName = serverInfo.name;
    const serverId = serverInfo.module;

    /**
     * Put text in the `PartCAD` terminal view, reopening it if the user closed
     * it and raising it if they asked for that.
     *
     * Registered with `setTerminalWriter` below, so that code with no access to
     * the terminal -- `restartBackend`, which reports a backend that never
     * started -- can reach it too.
     */
    const showInTerminal = (text: string) => {
        if (!terminalEmitter) {
            // A precaution: the emitter exists from activation onwards.
            return;
        }
        if (
            getReopenTerminalFromSetting(serverId) === 'true' &&
            partcadTerminal !== undefined &&
            !vscode.window.terminals.includes(partcadTerminal)
        ) {
            // Reopen the terminal window if it was closed
            // TODO(clairbee): is this the right way to dispose?
            partcadTerminal.dispose();
            partcadTerminal = terminalInit(context, terminalEmitter);
        }
        if (getPopupTerminalFromSetting(serverId) === 'true' && partcadTerminal !== undefined) {
            // Show the terminal if it was hidden
            partcadTerminal.show(true);
        }
        terminalEmitter.fire(text);
    };

    // Setup logging
    const outputChannel = createOutputChannel(serverName);
    context.subscriptions.push(outputChannel, registerLogger(outputChannel));

    const changeLogLevel = async (c: vscode.LogLevel, g: vscode.LogLevel) => {
        const level = getLSClientTraceLevel(c, g);
        await lsClient?.setTrace(level);
    };

    context.subscriptions.push(
        outputChannel.onDidChangeLogLevel(async (e) => {
            await changeLogLevel(e, vscode.env.logLevel);
        }),
        vscode.env.onDidChangeLogLevel(async (e) => {
            await changeLogLevel(outputChannel.logLevel, e);
        }),
    );

    // The command line tools on the PATH of this window's terminals. Done here,
    // before any backend has started: for the service backend the directory is
    // whatever is already installed, and a user who opened a terminal first
    // should not have to wait for a language server to get `pc`.
    refreshToolsPath(context, serverId);

    // Log Server information
    traceLog(`Name: ${serverInfo.name}`);
    traceLog(`Module: ${serverInfo.module}`);
    traceVerbose(`Full Server Info: ${JSON.stringify(serverInfo)}`);

    // ASSY files and `partcad.yaml` are checked through the backend; the checker
    // is created here so the documents already open when the window came up get
    // checked as soon as the backend registers `partcad.lintFile`. The Explorer
    // is handed over as a getter rather than a value: it does not exist yet, and
    // what the checker wants from it - which ASSY files the packages declare as
    // scenes - only arrives once a package has loaded.
    partcadLint = new PartcadLint(() => partcadExplorer);
    context.subscriptions.push(partcadLint);

    const handleRestartServer = async (
        serverId: string,
        serverName: string,
        outputChannel: vscode.LogOutputChannel,
    ) => {
        lsClient = await restartBackend(serverId, serverName, outputChannel, context, lsClient).then(
            undefined,
            (err) => {
                console.log('handleRestartServer: ');
                console.log(err);
                return undefined;
            },
        );
        if (lsClient !== undefined) {
            await vscode.commands.executeCommand('setContext', 'partcad.activated', false);
            await vscode.commands.executeCommand('setContext', 'partcad.installed', false);
            await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', false);
            await vscode.commands.executeCommand('setContext', 'partcad.itemsReceived', false);
            await vscode.commands.executeCommand('setContext', 'partcad.failed', false);
            await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
            await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', true);

            partcadLint?.refresh();

            context.subscriptions.push(
                lsClient.onNotification('?/partcad/installed', async () => {
                    await vscode.commands.executeCommand('setContext', 'partcad.installed', true);
                    await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', false);
                    await vscode.commands.executeCommand('partcad.activate');
                    await vscode.commands.executeCommand('setContext', 'partcad.needsUpdate', false);
                    // The Python backend cannot check anything until PartCAD is
                    // installed into the interpreter; now it can.
                    partcadLint?.refresh();
                }),
                lsClient.onNotification('?/partcad/installFailed', async () => {
                    await vscode.commands.executeCommand('setContext', 'partcad.installed', false);
                    await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', false);
                    await vscode.commands.executeCommand('partcad.activate');
                }),
                lsClient.onNotification('?/partcad/loaded', async () => {
                    await vscode.commands.executeCommand('setContext', 'partcad.installed', true);
                    await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', true);
                    await vscode.commands.executeCommand('setContext', 'partcad.packageContentsBeingLoaded', true);
                    await vscode.commands.executeCommand('setContext', 'partcad.loaded', true);

                    const packagePath = getPackagePathFromSetting(serverId);
                    if (
                        packagePath &&
                        vscode.workspace.workspaceFolders &&
                        vscode.workspace.workspaceFolders.length === 1
                    ) {
                        const path = utils.joinPath(vscode.workspace.workspaceFolders[0].uri, packagePath).fsPath;
                        await vscode.commands.executeCommand('partcad.loadPackage', path);
                    } else {
                        await vscode.commands.executeCommand('partcad.loadPackage');
                    }
                }),
                lsClient.onNotification('?/partcad/packageLoaded', async ({ configPath, root }) => {
                    lastConfigPath = configPath;
                    lastRoot = root;

                    await vscode.commands.executeCommand('setContext', 'partcad.activated', true);
                    await vscode.commands.executeCommand('setContext', 'partcad.installed', true);
                    await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', true);
                    await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', false);
                    await vscode.commands.executeCommand('partcad.getStats');

                    if (itemToSelectOnRestart !== undefined) {
                        await vscode.commands.executeCommand('partcad.inspectFile', itemToSelectOnRestart);
                    } else if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                        const uri = vscode.Uri.file(configPath);

                        try {
                            // Check if the file exists (trigger an exception otherwise).
                            vscode.workspace.fs.stat(uri);

                            // // See if the package file is already opened
                            // let packageIsOpened = false;
                            // for (var fileName in vscode.workspace.textDocuments.map((doc) => doc.fileName)) {
                            //     if (fileName.endsWith('partcad.yaml')) {
                            //         packageIsOpened = true;
                            //     }
                            // }

                            // if (!packageIsOpened) {
                            if (vscode.workspace.textDocuments.length === 0) {
                                await vscode.commands.executeCommand(
                                    'vscode.openWith',
                                    uri,
                                    'default',
                                    vscode.ViewColumn.One,
                                );
                            }
                        } catch (_error) {
                            // The package file doesn't exist.
                            // Do not do anything.
                            // Expect the user to follow instructions in the Explorer view.
                        }
                    }

                    partcadExplorer?.setRoot(root);

                    await installPackageOnOpen(context, serverId, configPath);
                }),
                lsClient.onNotification('?/partcad/activateFailed', async () => {
                    await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
                    await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', false);
                    await vscode.commands.executeCommand('setContext', 'partcad.packageContentsBeingLoaded', false);
                    await vscode.commands.executeCommand('setContext', 'partcad.failed', true);
                }),
                lsClient.onNotification('?/partcad/packageLoadFailed', async () => {
                    await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
                    await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', false);
                    await vscode.commands.executeCommand('setContext', 'partcad.packageContentsBeingLoaded', false);
                    // vscode.commands.executeCommand('partcad.getStats');
                }),
                lsClient.onNotification('?/partcad/needsUpdate', async () => {
                    await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
                    await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', false);
                    await vscode.commands.executeCommand('setContext', 'partcad.packageContentsBeingLoaded', false);
                    await vscode.commands.executeCommand('setContext', 'partcad.needsUpdate', true);
                }),
                lsClient.onNotification('?/partcad/items', async (items) => {
                    partcadExplorer?.setItems(items.name, items);
                    // The package now says which of its ASSY files are scenes,
                    // which is what decides the schema each is checked against.
                    // Anything checked before this arrived was checked without
                    // that (see 'PartcadLint.flavorOf').
                    partcadLint?.refresh();
                    if (
                        items.packages.length === 0 &&
                        items.sketches.length === 0 &&
                        items.interfaces.length === 0 &&
                        items.parts.length === 0 &&
                        items.assemblies.length === 0 &&
                        // Scenes and software count too, and are optional
                        // because an older PartCAD reports neither: a package of
                        // nothing but software has something to show.
                        (items.scenes ?? []).length === 0 &&
                        (items.software ?? []).length === 0 &&
                        // Objects that failed to load count as items too: a
                        // package of nothing but broken ones has something to
                        // show, and hiding the tree behind the "no items"
                        // placeholder is what leaves the user with no way to
                        // find out what went wrong.
                        (items.broken ?? []).length === 0
                    ) {
                        await vscode.commands.executeCommand('setContext', 'partcad.itemsReceived', false);
                    } else {
                        await vscode.commands.executeCommand('setContext', 'partcad.itemsReceived', true);
                    }
                    await vscode.commands.executeCommand('setContext', 'partcad.packageContentsBeingLoaded', false);
                    await vscode.commands.executeCommand('partcad.getStats');

                    // // If package is reloaded and the treeview has memorized the previous selection,
                    // // then redraw the currently selected item
                    // if (partcadExplorerView?.selection.length === 1) {
                    //     let selected = partcadExplorerView.selection[0];
                    //     if (selected.itemType === PartcadItem.ITEM_TYPE_PART) {
                    //         await partcadInspector?.inspectPart(selected, {});
                    //     } else if (selected.itemType === PartcadItem.ITEM_TYPE_ASSEMBLY) {
                    //         await partcadInspector?.inspectAssembly(selected, {});
                    //     }
                    // }
                }),
                lsClient.onNotification('?/partcad/showPartDone', async () => {
                    await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
                    partcadInspector?.showDone();
                }),
                lsClient.onNotification('?/partcad/exportPartDone', async () => {
                    await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
                    partcadExplorer?.exportDone();
                }),
                lsClient.onNotification('?/partcad/doRestart', async () => {
                    await vscode.commands.executeCommand('partcad.restart');
                }),
                lsClient.onNotification('?/partcad/stats', async ({ stats, version }) => {
                    await partcadContext?.setStats(stats, version);
                }),
                // In the terminal as well as in a popup. A popup is dismissed --
                // or never noticed, with `partcad.showNotifications` turned down
                // -- and then the only account of why something failed is gone.
                // The failure this mattered for is activation: the Explorer can
                // only say that starting PartCAD did not finish, and the reason
                // it did not arrives here.
                //
                // Except when the service is drawing the display: these are
                // logged on its side too, so echoing them here would print each
                // one twice -- and an unrendered line inserted between the
                // renderer's writes desynchronises the footer, which erases the
                // lines it last drew by moving the cursor back over them.
                lsClient.onNotification('?/partcad/error', async (message) => {
                    if (!lsClient?.rendersLogs) {
                        showInTerminal(`ERROR: ${message}\r\n`);
                    }
                    await vscode.window.showErrorMessage(message);
                }),
                lsClient.onNotification('?/partcad/warn', async (message) => {
                    if (!lsClient?.rendersLogs) {
                        showInTerminal(`WARNING: ${message}\r\n`);
                    }
                    await vscode.window.showWarningMessage(message);
                }),
                lsClient.onNotification('?/partcad/info', async (message) => {
                    await vscode.window.showInformationMessage(message);
                }),
                // What the service drew: colours, level prefixes and the
                // multi-line progress footer, rendered by the same code the CLI
                // uses (see `requestRenderedLogs`). Written into the pty
                // verbatim -- it is terminal control bytes, not text to format.
                //
                // `Buffer`, not `atob`: `atob` yields one character per byte, so
                // any non-ASCII in a log line (a path, a description) would come
                // out as mojibake. The extension host is Node; this is exact.
                lsClient.onNotification('?/partcad/terminal', async (message) => {
                    // The renderer ends its lines with a bare "\n", which is
                    // right for the CLI: a real terminal has ONLCR on and turns
                    // it into a carriage return plus a line feed. A
                    // pseudoterminal does not, so without this every line starts
                    // where the last one ended and the display walks off to the
                    // right. Translating here rather than in the renderer keeps
                    // this a property of the destination, which is what it is.
                    const drawn = Buffer.from(message.line, 'base64').toString('utf8');
                    showInTerminal(drawn.replace(/\r?\n/g, '\r\n'));
                }),
                // The JSON-RPC service/daemon backend forwards structured log
                // events (plain records and process/action markers) instead of
                // pre-rendered ANSI. Render the log records as level-prefixed
                // lines in the same terminal; the process/action markers only
                // drive the CLI's ANSI progress footer, and the meaningful lines
                // (including "DONE: ...") already arrive as 'log' records.
                // The fallback, for a service too old to answer `log.mode`: it
                // forwards structured records and the extension prints them
                // plainly, without colour and without the progress footer. A
                // service that renders for us sends `?/partcad/terminal`
                // instead and never sends these, so this and the handler above
                // do not both run.
                lsClient.onNotification('?/partcad/log', async (event: any) => {
                    if (!event || event.kind !== 'log') {
                        return;
                    }

                    const level = event.levelname || 'INFO';
                    showInTerminal(`${level}: ${event.message ?? ''}\r\n`);
                }),
                lsClient.onNotification(`?/partcad/execute`, async ({ command, args }) => {
                    await vscode.commands.executeCommand(command, ...args);
                }),
            );
            await vscode.commands.executeCommand('partcad.activate');
            await vscode.commands.executeCommand('setContext', 'partcad.activated', true);
        } else {
            // No backend this time round. Nothing used to reset this, so a window
            // that had been connected and then lost its service stayed
            // "activated" -- and the Explorer showed the welcome view for a
            // running PartCAD next to the one for a missing one.
            await vscode.commands.executeCommand('setContext', 'partcad.activated', false);
        }
    };

    const runServer = async () => {
        if (vscode.workspace.workspaceFolders === undefined || vscode.workspace.workspaceFolders.length === 0) {
            traceError('No workspace folders found');
            await vscode.commands.executeCommand('setContext', 'partcad.failed', true);
            await vscode.commands.executeCommand('setContext', 'partcad.workspaceIsGood', false);
            return;
        }
        await vscode.commands.executeCommand('setContext', 'partcad.workspaceIsGood', true);

        // The service is a standalone executable; there is no interpreter to
        // resolve and no Python extension to ask, so nothing between here and
        // starting it. `partcad.pythonIsGood` went with the welcome view that
        // was its only reader.
        await handleRestartServer(serverId, serverName, outputChannel);
    };

    context.subscriptions.push(
        onDidChangeConfiguration(async (e: vscode.ConfigurationChangeEvent) => {
            // Cheap and idempotent, so it is not worth working out which of the
            // settings that decide the directory was the one that changed.
            refreshToolsPath(context, serverId);
            if (checkIfConfigurationChanged(e, serverId)) {
                await runServer();
            }
        }),
        registerCommand(`partcad.restart`, async () => {
            await vscode.commands.executeCommand('setContext', 'partcad.activated', false);
            await vscode.commands.executeCommand('setContext', 'partcad.installed', false);
            await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', false);
            await vscode.commands.executeCommand('setContext', 'partcad.itemsReceived', false);
            await vscode.commands.executeCommand('setContext', 'partcad.failed', false);
            await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
            await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', true);
            await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', false);
            currentItemType = PartcadItem.ITEM_TYPE_NONE;
            currentItemName = '//';
            currentItemPackage = '//';
            currentItemParams = {};

            partcadExplorer?.clearItems();
            await partcadInspector?.clear();

            // Terminate the shared daemon so its warm context is torn down,
            // then start a fresh daemon, reconnect, and reactivate.
            await lsClient?.stopDaemon?.();
            await handleRestartServer(serverId, serverName, outputChannel);
        }),
        registerCommand(`partcad.update`, async () => {
            await vscode.commands.executeCommand('setContext', 'partcad.activated', false);
            await vscode.commands.executeCommand('setContext', 'partcad.installed', false);
            await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', true);
            await vscode.commands.executeCommand('setContext', 'partcad.itemsReceived', false);
            await vscode.commands.executeCommand('setContext', 'partcad.failed', false);
            await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
            await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', true);
            await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', false);
            currentItemType = PartcadItem.ITEM_TYPE_NONE;
            currentItemName = '//';
            currentItemPackage = '//';
            currentItemParams = {};

            partcadExplorer?.clearItems();
            await partcadInspector?.clear();

            // The bundle upgrades itself by running its own `pc upgrade`, so
            // the extension and the CLI upgrade by the same code. That takes the
            // local daemons down with it, so reconnect afterwards -- to the new
            // executable, which is at a new path once the upgrade installed one.
            try {
                // `pc upgrade` stops every local daemon itself; this covers the
                // fallback download path, which does not, and this connection
                // has to go either way.
                await lsClient?.stopDaemon?.();
                // And the service process itself, before anything replaces the
                // files it is running from. `stopDaemon` stops the *shared*
                // daemon; the stdio channel owns a private process instead, and
                // nothing stopped that until the reconnect at the end of this
                // command -- long after the bundle it runs from had been
                // deleted and replaced. On Windows that deletion simply fails
                // (a directory with a running executable in it cannot be
                // removed), so every update left another ~180MB behind.
                const running = lsClient;
                lsClient = undefined;
                await running?.stop();
                const result = await updateServiceBundle(context, serverId, outputChannel);
                // `pc upgrade` installs beside the running bundle and deletes
                // every superseded one, so the directory this put on the PATH
                // may no longer exist.
                refreshToolsPath(context, serverId);
                if (!result.execPath) {
                    await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', false);
                    return;
                }
            } catch (e: any) {
                traceError(`PartCAD update failed: ${e?.stack ?? e}`);
                vscode.window.showErrorMessage(`Failed to update PartCAD: ${e?.message ?? e}`);
            }
            await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', false);
            await handleRestartServer(serverId, serverName, outputChannel);
        }),
        registerCommand(`partcad.installPackage`, async () => {
            await vscode.commands.executeCommand('setContext', 'partcad.packageContentsBeingLoaded', true);
            try {
                await vscode.commands.executeCommand('partcad.installPackageReal');
            } finally {
                // Installing loads packages that were not there before, so the
                // tree the Explorer is showing is now out of date.
                await vscode.commands.executeCommand('partcad.loadPackageContents');
            }
        }),
        registerCommand(`partcad.promptInitPackage`, async () => {
            if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length === 1) {
                const path = utils.joinPath(vscode.workspace.workspaceFolders[0].uri, 'partcad.yaml').fsPath;
                await vscode.commands.executeCommand('setContext', 'partcad.itemsReceived', false);
                await vscode.commands.executeCommand('setContext', 'partcad.failed', false);
                await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
                await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', false);
                await vscode.commands.executeCommand('partcad.initPackage', path);
            } else {
                await vscode.window.showErrorMessage('Failed to locate the default package configuration file.');
            }
        }),
        registerCommand(`partcad.promptInitPackageCustom`, async () => {
            const uri = await vscode.window.showOpenDialog({
                title: 'Select the folder or new package configuration file',
                canSelectFiles: true,
                canSelectMany: false,
                canSelectFolders: true,
                // eslint-disable-next-line @typescript-eslint/naming-convention
                filters: { 'PartCAD package configuration files': ['yaml'] },
            });
            if (uri && uri.length === 1) {
                await vscode.commands.executeCommand('setContext', 'partcad.itemsReceived', false);
                await vscode.commands.executeCommand('setContext', 'partcad.failed', false);
                await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
                await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', false);

                await vscode.commands.executeCommand('partcad.initPackage', uri[0].fsPath);
            }
        }),
        registerCommand(`partcad.promptLoadPackage`, async () => {
            const uri = await vscode.window.showOpenDialog({
                title: 'Select the folder or the package configuration file',
                canSelectFiles: true,
                canSelectMany: false,
                canSelectFolders: true,
                // eslint-disable-next-line @typescript-eslint/naming-convention
                filters: { 'PartCAD package configuration files': ['yaml'] },
            });
            if (uri && uri.length === 1) {
                await vscode.commands.executeCommand('setContext', 'partcad.itemsReceived', false);
                await vscode.commands.executeCommand('setContext', 'partcad.failed', false);
                await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
                await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', true);
                await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', false);

                partcadExplorer?.clearItems();
                await partcadInspector?.clear();

                await vscode.commands.executeCommand('partcad.loadPackage', uri[0].fsPath);
            }
        }),
        // TODO(clairbee): move package specific handlers of the commands to PartCADExplorer
        registerCommand(`partcad.importSketch`, async () => {
            await vscode.window.showWarningMessage(
                'Import functionality is not yet implemented in VSCode UI. Please, edit `partcad.yaml` manually.',
            );
        }),
        registerCommand(`partcad.importPart`, async () => {
            await vscode.window.showWarningMessage(
                'Import functionality is not yet implemented in VSCode UI. Please, use command line.',
            );
        }),
        registerCommand(`partcad.importAssembly`, async () => {
            await vscode.window.showWarningMessage(
                'Import functionality is not yet implemented in VSCode UI. Please, use command line.',
            );
        }),
        registerCommand(`partcad.importScene`, async () => {
            await vscode.window.showWarningMessage(
                'Import functionality is not yet implemented in VSCode UI. Please, use command line.',
            );
        }),
        registerCommand(`partcad.addInterface`, async () => {
            await vscode.window.showWarningMessage(
                'Adding interface is not yet implemented in VSCode UI. Please, edit `partcad.yaml` manually.',
            );
        }),
        registerCommand(`partcad.addSketch`, async () => {
            await vscode.window.showWarningMessage(
                'Adding sketch is not yet implemented in VSCode UI. Please, edit `partcad.yaml` manually.',
            );
        }),
        registerCommand(`partcad.addPart`, async () => {
            await vscode.commands.executeCommand('partcad.packagePath', {
                packageName: partcadExplorer?.root ?? '//',
                callback: 'partcad.addPart2',
            });
        }),
        registerCommand(`partcad.addPart2`, async ({ packageName, packagePath, isAbsolute }) => {
            let startUri = undefined;
            if (isAbsolute) {
                startUri = vscode.Uri.file(packagePath);
            } else {
                let wsUri = undefined;
                if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                    wsUri = vscode.workspace.workspaceFolders[0].uri;
                }
                if (!wsUri) {
                    await vscode.window.showWarningMessage('Failed to determine the workspace path');
                    return;
                }
                startUri = vscode.Uri.joinPath(wsUri, packagePath);
            }

            const partTypeTypes: { [partType: string]: string } = {
                // eslint-disable-next-line @typescript-eslint/naming-convention
                STEP: 'step',
                // eslint-disable-next-line @typescript-eslint/naming-convention
                STL: 'stl',
                // eslint-disable-next-line @typescript-eslint/naming-convention
                '3MF': '3mf',
                // eslint-disable-next-line @typescript-eslint/naming-convention
                OpenSCAD: 'scad',
                // eslint-disable-next-line @typescript-eslint/naming-convention
                CadQuery: 'cadquery',
                build123d: 'build123d',
                // eslint-disable-next-line @typescript-eslint/naming-convention
                Chili3D: 'chili3d',
            };
            const partType = await vscode.window.showQuickPick(
                ['STEP', 'STL', '3MF', 'OpenSCAD', 'CadQuery', 'build123d', 'Chili3D'],
                {
                    canPickMany: false,
                    title: 'What type of part would you like to create?',
                },
            );
            if (!partType) {
                await vscode.window.showWarningMessage('Part type was not selected');
                return;
            }
            let hasTemplates = false;
            let filters: { [name: string]: string[] } = {};
            if (partType === 'STEP') {
                filters[`${partType}`] = ['step'];
            } else if (partType === 'STL') {
                filters[`${partType}`] = ['stl'];
            } else if (partType === '3MF') {
                filters[`${partType}`] = ['3mf'];
            } else if (partType === 'OpenSCAD') {
                filters[`${partType}`] = ['scad'];
                hasTemplates = true;
            } else if (partType === 'Chili3D') {
                filters[`${partType}`] = ['chili'];
                hasTemplates = true;
            } else {
                filters[`${partType}`] = ['py'];
                hasTemplates = true;
            }

            let uri = undefined;
            if (hasTemplates) {
                uri = await vscode.window.showSaveDialog({
                    title: `Select or create a ${partType} file`,
                    filters: filters,
                    defaultUri: startUri,
                });
            } else {
                const uris = await vscode.window.showOpenDialog({
                    title: `Select a ${partType} file`,
                    filters: filters,
                    canSelectMany: false,
                    canSelectFolders: false,
                    canSelectFiles: true,
                    defaultUri: startUri,
                });
                if (uris?.length) {
                    uri = uris[0];
                }
            }
            if (!uri) {
                await vscode.window.showWarningMessage('File was not selected');
                return;
            }

            try {
                await vscode.workspace.fs.stat(uri);
            } catch {
                if (hasTemplates) {
                    const exampleChosen = await vscode.window.showQuickPick(Object.keys(examples[partType]), {
                        canPickMany: false,
                        title: 'Select the template',
                    });
                    let exampleText = '';
                    if (exampleChosen) {
                        exampleText = examples[partType][exampleChosen];
                    }
                    var exampleContents = new TextEncoder().encode(exampleText);

                    const wsedit = new vscode.WorkspaceEdit();
                    wsedit.createFile(uri, { ignoreIfExists: false, contents: exampleContents });
                    await vscode.workspace.applyEdit(wsedit);
                }
            }

            await vscode.commands.executeCommand('partcad.addPartReal', {
                kind: partTypeTypes[partType],
                path: uri.fsPath,
                packageName: packageName,
            });
            itemToSelectOnRestart = uri.fsPath;

            await vscode.commands.executeCommand('vscode.open', uri);
            await vscode.commands.executeCommand('partcad.restart');
        }),
        registerCommand(`partcad.addAssembly`, async () => {
            await vscode.commands.executeCommand('partcad.packagePath', {
                packageName: partcadExplorer?.root ?? '//',
                callback: 'partcad.addAssembly2',
            });
        }),
        registerCommand(`partcad.addAssembly2`, async ({ packageName, packagePath, isAbsolute }) => {
            let startUri = undefined;
            if (isAbsolute) {
                startUri = vscode.Uri.file(packagePath);
            } else {
                let wsUri = undefined;
                if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                    wsUri = vscode.workspace.workspaceFolders[0].uri;
                }
                if (!wsUri) {
                    await vscode.window.showWarningMessage('Failed to determine the package path');
                    return;
                }
                startUri = vscode.Uri.joinPath(wsUri, packagePath);
            }

            const assyName = await vscode.window.showInputBox({
                title: 'Enter the name of new assembly',
                prompt: 'Enter the name of new assembly',
                placeHolder: 'Assembly',
                ignoreFocusOut: true,
                password: false,
            });
            if (!assyName) {
                await vscode.window.showWarningMessage('No assembly name provided.');
                return;
            }

            const uri = vscode.Uri.joinPath(startUri, assyName + '.assy');
            const wsedit = new vscode.WorkspaceEdit();
            wsedit.createFile(uri, {
                ignoreIfExists: false,
                contents: new TextEncoder()
                    .encode(`# Each assembly file starts with a list of links (thank ROS and URDF for the terminology).
links:

# There are one or more links in each list.
# Each link is either a reference to an existing part or assembly,
# or a sub-assembly defined in place.
# In this example, we have two references to existing parts.

- part: //pub/electromechanics/towerpro:servo/mg90s
# 'name is used to make references to this part within this assembly file.
name: motor

- part: //pub/electromechanics/towerpro:servo/shoulder-unidir
name: shoulder
connect:
  # Most of the time, PartCAD is not able to automatically detect how to connect parts.
  # In such cases the user has to provide just enough hints for PartCAD to figure it out.

  # 'withInstance' references to the instance of the local interface
  # (assuming the type of local interface is deteremined automatically).
  withInstance: inner
  # 'name' references to another part to connect to.
  name: motor
  # 'to' is the name of the remote port to connect to.
  to: "/pub/std/metric/m:m2.5-threaded-hole-4"
`),
            });

            await vscode.workspace.applyEdit(wsedit);

            await vscode.commands.executeCommand('partcad.addAssemblyReal', {
                kind: 'assy',
                path: uri.fsPath,
                packageName: packageName,
            });
            itemToSelectOnRestart = uri.fsPath;

            await vscode.commands.executeCommand('vscode.open', uri);
            await vscode.commands.executeCommand('partcad.restart');
        }),
        registerCommand(`partcad.addScene`, async () => {
            await vscode.commands.executeCommand('partcad.packagePath', {
                packageName: partcadExplorer?.root ?? '//',
                callback: 'partcad.addScene2',
            });
        }),
        registerCommand(`partcad.addScene2`, async ({ packageName, packagePath, isAbsolute }) => {
            let startUri = undefined;
            if (isAbsolute) {
                startUri = vscode.Uri.file(packagePath);
            } else {
                let wsUri = undefined;
                if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                    wsUri = vscode.workspace.workspaceFolders[0].uri;
                }
                if (!wsUri) {
                    await vscode.window.showWarningMessage('Failed to determine the package path');
                    return;
                }
                startUri = vscode.Uri.joinPath(wsUri, packagePath);
            }

            const sceneName = await vscode.window.showInputBox({
                title: 'Enter the name of new scene',
                prompt: 'Enter the name of new scene',
                placeHolder: 'Scene',
                ignoreFocusOut: true,
                password: false,
            });
            if (!sceneName) {
                await vscode.window.showWarningMessage('No scene name provided.');
                return;
            }

            const uri = vscode.Uri.joinPath(startUri, sceneName + '.assy');
            const wsedit = new vscode.WorkspaceEdit();
            wsedit.createFile(uri, {
                ignoreIfExists: false,
                contents: new TextEncoder()
                    .encode(`# A scene states where things are. It is an Assembly YAML file like any other,
# read as a scene rather than as an assembly: the 'connect*' sections are all
# available, but 'how' is not - nothing here was assembled, so there is nothing
# to say about the assembling.
links:

# There are one or more links in each list.
# Each link is either a reference to an existing part or assembly,
# or a group defined in place.

- part: //pub/electromechanics/towerpro:servo/mg90s
# 'name' is used to make references to this object within this file.
name: motor
location: [[0, 0, 0], [0, 0, 1], 0]

- assembly: //pub/robotics/multimodal/openvmp/robots/don1:robot
name: robot
location: [[100, 0, 0], [0, 0, 1], 0]
`),
            });

            await vscode.workspace.applyEdit(wsedit);

            await vscode.commands.executeCommand('partcad.addSceneReal', {
                kind: 'assy',
                path: uri.fsPath,
                packageName: packageName,
            });
            itemToSelectOnRestart = uri.fsPath;

            await vscode.commands.executeCommand('vscode.open', uri);
            await vscode.commands.executeCommand('partcad.restart');
        }),
        registerCommand(`partcad.inspectPackage`, async (pkg) => {
            currentItemType = PartcadItem.ITEM_TYPE_PACKAGE;
            currentItemName = pkg.pkg;
            currentItemPackage = pkg.pkg;
            currentItemParams = {};
            // TODO(clairbee): add this when packages are viewable
            // itemToSelectOnRestart = pkg.itemPath;

            await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
            await partcadInspector?.inspectPackage(pkg);
            await vscode.commands.executeCommand('partcad.getStats');
        }),
        registerCommand(`partcad.inspectSketch`, async (sketch, params, doNotMemorize) => {
            if (!doNotMemorize) {
                currentItemType = PartcadItem.ITEM_TYPE_SKETCH;
                currentItemName = sketch.name;
                currentItemPackage = sketch.pkg;
                currentItemParams = params;
                itemToSelectOnRestart = sketch.itemPath;
            }
            await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
            await partcadInspector?.inspectSketch(sketch, params);
            await vscode.commands.executeCommand('partcad.getStats');
        }),
        registerCommand(`partcad.inspectInterface`, async (intf, params, doNotMemorize) => {
            if (!doNotMemorize) {
                currentItemType = PartcadItem.ITEM_TYPE_INTERFACE;
                currentItemName = intf.name;
                currentItemPackage = intf.pkg;
                currentItemParams = params;
                itemToSelectOnRestart = intf.itemPath;
            }
            await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
            await partcadInspector?.inspectInterface(intf, params);
            await vscode.commands.executeCommand('partcad.getStats');
        }),
        registerCommand(`partcad.inspectPart`, async (part, params, doNotMemorize) => {
            if (!doNotMemorize) {
                currentItemType = PartcadItem.ITEM_TYPE_PART;
                currentItemName = part.name;
                currentItemPackage = part.pkg;
                currentItemParams = params;
                itemToSelectOnRestart = part.itemPath;
            }
            await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
            await partcadInspector?.inspectPart(part, params);
            await vscode.commands.executeCommand('partcad.getStats');
        }),
        registerCommand(`partcad.inspectAssembly`, async (assy, params, doNotMemorize) => {
            if (!doNotMemorize) {
                currentItemType = PartcadItem.ITEM_TYPE_ASSEMBLY;
                currentItemName = assy.name;
                currentItemPackage = assy.pkg;
                currentItemParams = params;
                itemToSelectOnRestart = assy.itemPath;
            }
            await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
            await partcadInspector?.inspectAssembly(assy, params);
            await vscode.commands.executeCommand('partcad.getStats');
        }),
        registerCommand(`partcad.inspectScene`, async (scene, params, doNotMemorize) => {
            if (!doNotMemorize) {
                currentItemType = PartcadItem.ITEM_TYPE_SCENE;
                currentItemName = scene.name;
                currentItemPackage = scene.pkg;
                currentItemParams = params;
                itemToSelectOnRestart = scene.itemPath;
            }
            await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
            await partcadInspector?.inspectScene(scene, params);
            await vscode.commands.executeCommand('partcad.getStats');
        }),
        registerCommand(`partcad.inspectSoftware`, async (software) => {
            currentItemType = PartcadItem.ITEM_TYPE_SOFTWARE;
            currentItemName = software.name;
            currentItemPackage = software.pkg;
            currentItemParams = {};
            // No 'itemToSelectOnRestart': software has no source file of its own
            // to reopen, and its own file is a binary rather than something to
            // put back in an editor.

            await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
            await partcadInspector?.inspectSoftware(software);
            await vscode.commands.executeCommand('partcad.getStats');
        }),
        registerCommand(`partcad.inspectFileRoot`, async () => {
            if (lastConfigPath !== undefined) {
                await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(lastConfigPath), 'default', {
                    viewColumn: vscode.ViewColumn.One,
                    preview: true,
                });
            }
        }),
        registerCommand(`partcad.startInstall`, async () => {
            // The "not installed" and "needs to be updated" buttons in the
            // Explorer view. Installing what is missing and updating what is out
            // of date is one request as far as the user is concerned, so both
            // buttons end up in the same updater the toolbar's "Update PartCAD"
            // uses -- reached by the route each backend needs.
            await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', true);
            await vscode.commands.executeCommand('partcad.update');
        }),
        registerCommand(`partcad.support`, async () => {
            vscode.env.openExternal(vscode.Uri.parse('https://calendly.com/partcad-support/30min'));
        }),
        registerCommand(`partcad.viewer`, async () => {
            partcadViewer?.reveal(false);
        }),
        registerCommand(`partcad.showBrokenItem`, async ({ name, pkg, reason }) => {
            // Clicking a broken item explains it rather than doing nothing.
            // There is deliberately no attempt to inspect it: PartCAD could not
            // create the object, so there is nothing to render.
            await vscode.window
                .showWarningMessage(
                    `'${pkg}:${name}' could not be loaded.`,
                    { modal: false, detail: reason },
                    'Copy details',
                )
                .then(async (choice) => {
                    if (choice === 'Copy details') {
                        await vscode.env.clipboard.writeText(`${pkg}:${name}\n${reason ?? ''}`);
                    }
                });
        }),
    );

    /* Instantiate the viewer and start listening for PartCAD processes.
     *
     * Started here, during activation, rather than lazily when something is
     * first shown: a 'partcad' running outside the IDE - in a terminal, in a
     * notebook - connects on its own schedule, and there would be nothing for it
     * to connect to.
     */
    partcadViewer = new PartcadViewer(context.extensionUri);
    partcadViewerServer = new PartcadViewerServer();
    context.subscriptions.push(
        partcadViewer,
        partcadViewerServer,
        partcadViewerServer.onMessage((message) => partcadViewer?.handle(message)),
        vscode.window.registerWebviewPanelSerializer(PartcadViewer.viewType, {
            async deserializeWebviewPanel(panel: vscode.WebviewPanel) {
                // VS Code restores the tab after a window reload; adopt it so the
                // next show lands in it instead of opening a second one.
                partcadViewer?.restore(panel);
            },
        }),
    );
    await partcadViewerServer.start();

    /* Instantiate the context viewer */
    partcadContext = new PartcadContext(context.extensionUri);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(PartcadContext.viewType, partcadContext, {
            // webviewOptions: { retainContextWhenHidden: true },
        }),
    );

    /* Instantiate the package explorer */
    partcadExplorer = new PartcadExplorer();
    // context.subscriptions.push(vscode.window.registerTreeDataProvider(PartcadExplorer.viewType, partcadExplorer));
    partcadExplorerView = vscode.window.createTreeView('partcadExplorer', {
        treeDataProvider: partcadExplorer,
    });
    context.subscriptions.push(partcadExplorerView);

    /* Instantiate the inspector */
    partcadInspector = new PartcadInspector(context.extensionUri);
    context.subscriptions.push(vscode.window.registerWebviewViewProvider(PartcadInspector.viewType, partcadInspector));

    vscode.languages.registerImplementationProvider('scad', {
        provideImplementation(
            _document: vscode.TextDocument,
            _position: vscode.Position,
            _token: vscode.CancellationToken,
        ) {
            let openscadExtension = vscode.extensions.getExtension('antyos.openscad');
            if (openscadExtension === undefined) {
                vscode.window.showInformationMessage('OpenSCAD extension is not installed', 'Install').then((value) => {
                    if (value === 'Install') {
                        vscode.commands.executeCommand('workbench.extensions.installExtension', 'antyos.openscad');
                    }
                });
            }
            return undefined;
        },
    });

    /* Instantiate code completion */
    let completionPython = vscode.languages.registerCompletionItemProvider('python', {
        provideCompletionItems(
            document: vscode.TextDocument,
            _position: vscode.Position,
            _token: vscode.CancellationToken,
            _context: vscode.CompletionContext,
        ) {
            const items = [];

            let text = 'pc.get_';
            if (currentItemType === PartcadItem.ITEM_TYPE_SKETCH) {
                text += 'sketch';
            } else if (currentItemType === PartcadItem.ITEM_TYPE_INTERFACE) {
                return [];
            } else if (currentItemType === PartcadItem.ITEM_TYPE_PART) {
                text += 'part';
            } else if (currentItemType === PartcadItem.ITEM_TYPE_ASSEMBLY) {
                text += 'assembly';
            } else if (currentItemType === PartcadItem.ITEM_TYPE_SCENE) {
                text += 'scene';
            } else {
                return [];
            }

            const body = document.getText();

            let isCadquery = false;
            let isBuild123d = false;
            if (body.indexOf('import cadquery') !== -1) {
                text += '_cadquery';
                isCadquery = true;
            } else if (body.indexOf('import build123d') !== -1) {
                text += '_build123d';
                isBuild123d = true;
            }

            text += '("' + currentItemName + '"';
            text += ', "' + currentItemPackage + '"';
            const keys = Object.keys(currentItemParams);
            if (keys.length > 0) {
                text += ',  {\n';
                for (let param in keys) {
                    text += '  "' + keys[param] + '": "' + currentItemParams[keys[param]] + '",\n';
                }
                text += '}\n';
            }
            text += ')';

            if (isCadquery) {
                const item = new vscode.CompletionItem(
                    'pc.get(current item as CadQuery)',
                    vscode.CompletionItemKind.Snippet,
                );
                item.insertText = text;
                item.sortText = '               ';
                items.push(item);
            }

            if (isBuild123d) {
                const item = new vscode.CompletionItem(
                    'pc.get(current item as build123d)',
                    vscode.CompletionItemKind.Snippet,
                );
                item.insertText = text;
                items.push(item);
            }
            return items;
        },
    });
    context.subscriptions.push(completionPython);

    let completionYaml = vscode.languages.registerCompletionItemProvider('yaml', {
        provideCompletionItems(
            _document: vscode.TextDocument,
            _position: vscode.Position,
            _token: vscode.CancellationToken,
            _context: vscode.CompletionContext,
        ) {
            const items = [];

            let text = '';
            if (currentItemType === PartcadItem.ITEM_TYPE_PART) {
                text += 'part: ' + currentItemName + '\n';
            } else if (currentItemType === PartcadItem.ITEM_TYPE_ASSEMBLY) {
                text += 'assembly: ' + currentItemName + '\n';
            } else {
                return [];
            }

            text += '  package: ' + currentItemPackage + '\n';
            text += '  name: ' + currentItemName + '\n';
            text += '  location: [[0, 0, 0], [0, 0, 1], 0]' + '\n';
            const keys = Object.keys(currentItemParams);
            if (keys.length > 0) {
                text += '  params:\n';
                for (let param in keys) {
                    text += '    ' + keys[param] + ': ' + currentItemParams[keys[param]] + '\n';
                }
            }

            const item = new vscode.CompletionItem(
                'partcad: <current PartCAD item>',
                vscode.CompletionItemKind.Snippet,
            );
            item.insertText = text;
            item.sortText = '_________________';
            items.push(item);

            return items;
        },
    });
    context.subscriptions.push(completionYaml);

    terminalEmitter = new vscode.EventEmitter<string>();
    partcadTerminal = terminalInit(context, terminalEmitter);
    context.subscriptions.push(partcadTerminal);
    // Before `runServer()` below, so that a backend which fails to start has
    // somewhere to say so.
    setTerminalWriter(showInTerminal);
    context.subscriptions.push({ dispose: () => setTerminalWriter(undefined) });

    setImmediate(async () => {
        await runServer();
    });
}

export async function deactivate(): Promise<void> {
    try {
        if (!lsClient) {
            return;
        }

        await vscode.commands.executeCommand('setContext', 'partcad.activated', false);

        const clientToStop = lsClient;
        lsClient = undefined;

        await clientToStop.stop();
    } catch (error: any) {
        vscode.window.showErrorMessage(`Failed to deactivate extension: ${error}`);
        // vscode.window.showErrorMessage(`Failed to deactivate extension: ${error.message}`);
        throw error;
    }
}
