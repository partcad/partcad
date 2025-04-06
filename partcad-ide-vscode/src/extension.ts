//
// PartCAD, 2024
//
// Author: Roman Kuzmenko
// Created: 2024-12-28
//
// Licensed under Apache License, Version 2.0.
//

import * as vscode from 'vscode';
import { LanguageClient } from 'vscode-languageclient/node';
import { registerLogger, traceError, traceLog, traceVerbose } from './common/log/logging';
import {
    checkVersion,
    getInterpreterDetails,
    initializePython,
    onDidChangePythonInterpreter,
    resolveInterpreter,
} from './common/python';
import { restartServer } from './common/server';
import {
    checkIfConfigurationChanged,
    getInterpreterFromSetting,
    getPackagePathFromSetting,
    getReopenTerminalFromSetting,
    getPopupTerminalFromSetting,
} from './common/settings';
import { loadServerDefaults } from './common/setup';
import { getLSClientTraceLevel } from './common/utilities';
import { createOutputChannel, isVirtualWorkspace, onDidChangeConfiguration, registerCommand } from './common/vscodeapi';

import { PartcadExplorer } from './PartcadExplorer';
import { PartcadInspector } from './PartcadInspector';
import { PartcadContext } from './PartcadContext';
import * as PartcadItem from './PartcadItem';
import { examples } from './examples';
import { terminalInit } from './terminal';
import * as utils from './utils';

let lsClient: LanguageClient | undefined;
let partcadExplorer: PartcadExplorer | undefined;
let partcadExplorerView: vscode.TreeView<PartcadItem.PartcadItem | void>;
let partcadContext: PartcadContext | undefined;
let partcadInspector: PartcadInspector | undefined;
let partcadTerminal: vscode.Terminal | undefined;
let terminalEmitter: vscode.EventEmitter<string> | undefined;

let currentItemType: string = PartcadItem.ITEM_TYPE_NONE;
let currentItemName: string = '//';
let currentItemPackage: string = '//';
let currentItemParams: { [id: string]: string } = {};
let itemToSelectOnRestart: string | undefined = undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
    await vscode.commands.executeCommand('setContext', 'partcad.activated', false);
    await vscode.commands.executeCommand('setContext', 'partcad.failed', false);

    // This is required to get server name and module. This should be
    // the first thing that we do in this extension.
    const serverInfo = loadServerDefaults();
    const serverName = serverInfo.name;
    const serverId = serverInfo.module;

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

    // Log Server information
    traceLog(`Name: ${serverInfo.name}`);
    traceLog(`Module: ${serverInfo.module}`);
    traceVerbose(`Full Server Info: ${JSON.stringify(serverInfo)}`);

    const handleRestartServer = async (
        serverId: string,
        serverName: string,
        outputChannel: vscode.LogOutputChannel,
    ) => {
        lsClient = await restartServer(serverId, serverName, outputChannel, lsClient).then(undefined, (err) => {
            console.log('handleRestartServer: ');
            console.log(err);
            return undefined;
        });
        if (lsClient !== undefined) {
            await vscode.commands.executeCommand('setContext', 'partcad.activated', false);
            await vscode.commands.executeCommand('setContext', 'partcad.installed', false);
            await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', false);
            await vscode.commands.executeCommand('setContext', 'partcad.itemsReceived', false);
            await vscode.commands.executeCommand('setContext', 'partcad.failed', false);
            await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
            await vscode.commands.executeCommand('setContext', 'partcad.beingLoaded', true);

            context.subscriptions.push(
                lsClient.onNotification('?/partcad/installed', async () => {
                    await vscode.commands.executeCommand('setContext', 'partcad.installed', true);
                    await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', false);
                    await vscode.commands.executeCommand('partcad.activate');
                    await vscode.commands.executeCommand('setContext', 'partcad.needsUpdate', false);
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
                lsClient.onNotification('?/partcad/packageLoaded', async (configPath) => {
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
                    if (
                        items.packages.length === 0 &&
                        items.sketches.length === 0 &&
                        items.interfaces.length === 0 &&
                        items.parts.length === 0 &&
                        items.assemblies.length === 0
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
                lsClient.onNotification('?/partcad/error', async (message) => {
                    await vscode.window.showErrorMessage(message);
                }),
                lsClient.onNotification('?/partcad/warn', async (message) => {
                    await vscode.window.showWarningMessage(message);
                }),
                lsClient.onNotification('?/partcad/info', async (message) => {
                    await vscode.window.showInformationMessage(message);
                }),
                lsClient.onNotification('?/partcad/terminal', async (message) => {
                    if (!terminalEmitter) {
                        // This is a precaution, the emitter should always exist
                        return;
                    }

                    if (
                        getReopenTerminalFromSetting(serverId) === 'true' &&
                        partcadTerminal !== undefined &&
                        !vscode.window.terminals.includes(partcadTerminal)
                    ) {
                        // Reopen the terminal window if it waas closed
                        // TODO(clairbee): is this the right way to dispose?
                        partcadTerminal.dispose();
                        partcadTerminal = terminalInit(terminalEmitter);
                    }
                    if (getPopupTerminalFromSetting(serverId) === 'true' && partcadTerminal !== undefined) {
                        // Show the terminal if it was hidden
                        partcadTerminal.show(true);
                    }

                    terminalEmitter.fire(atob(message.line));
                }),
                lsClient.onNotification(`?/partcad/execute`, async ({ command, args }) => {
                    await vscode.commands.executeCommand(command, ...args);
                }),
            );
            await vscode.commands.executeCommand('partcad.activate');
            await vscode.commands.executeCommand('setContext', 'partcad.activated', true);
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

        const interpreter = getInterpreterFromSetting(serverId);
        if (interpreter && interpreter.length > 0) {
            if (checkVersion(await resolveInterpreter(interpreter))) {
                traceVerbose(`Using interpreter from ${serverInfo.module}.interpreter: ${interpreter.join(' ')}`);
                await vscode.commands.executeCommand('setContext', 'partcad.pythonIsGood', true);
                await handleRestartServer(serverId, serverName, outputChannel);
            } else {
                await vscode.commands.executeCommand('setContext', 'partcad.failed', true);
                await vscode.commands.executeCommand('setContext', 'partcad.pythonIsGood', false);
            }
            return;
        }

        const interpreterDetails = await getInterpreterDetails();
        if (interpreterDetails.path) {
            traceVerbose(`Using interpreter from Python extension: ${interpreterDetails.path.join(' ')}`);
            await vscode.commands.executeCommand('setContext', 'partcad.pythonIsGood', true);
            await handleRestartServer(serverId, serverName, outputChannel);
            return;
        }

        traceError(
            'Python interpreter missing:\r\n' +
                '[Option 1] Select python interpreter using the ms-python.python.\r\n' +
                `[Option 2] Set an interpreter using "${serverId}.interpreter" setting.\r\n` +
                'Please use Python 3.8 or greater.',
        );
        await vscode.commands.executeCommand('setContext', 'partcad.failed', true);
        await vscode.commands.executeCommand('setContext', 'partcad.pythonIsGood', false);
    };

    context.subscriptions.push(
        onDidChangePythonInterpreter(async () => {
            await runServer();
        }),
        onDidChangeConfiguration(async (e: vscode.ConfigurationChangeEvent) => {
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

            // reload the context
            await vscode.commands.executeCommand('partcad.activate');
        }),
        registerCommand(`partcad.update`, async () => {
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

            // reload the context
            await vscode.commands.executeCommand('partcad.reinstall');
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
                await vscode.commands.executeCommand('setContext', 'partcad.packageLoaded', false);
                await vscode.commands.executeCommand('setContext', 'partcad.failed', false);
                await vscode.commands.executeCommand('partcad.loadPackage', uri[0].fsPath);
            }
        }),
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
        registerCommand(`partcad.genPart`, async () => {
            let packageName = '//';
            if (currentItemType === PartcadItem.ITEM_TYPE_PACKAGE) {
                packageName = currentItemName;
            } else if (currentItemType !== PartcadItem.ITEM_TYPE_NONE) {
                packageName = currentItemPackage;
            }

            await vscode.commands.executeCommand('partcad.packagePath', {
                packageName: packageName,
                callback: 'partcad.genPart2',
            });
        }),
        registerCommand(`partcad.genPart2`, async () => {
            const partTypeTypes: { [partType: string]: string } = {
                // eslint-disable-next-line @typescript-eslint/naming-convention
                OpenSCAD: 'ai-openscad',
                // eslint-disable-next-line @typescript-eslint/naming-convention
                CadQuery: 'ai-cadquery',
            };
            const partType = await vscode.window.showQuickPick(['OpenSCAD', 'CadQuery' /*, 'build123d'*/], {
                canPickMany: false,
                title: 'Select the type of part you want to generate',
            });
            if (!partType) {
                await vscode.window.showWarningMessage('Part type was not selected');
                return;
            }
            let filters: { [name: string]: string[] } = {};
            if (partType === 'OpenSCAD') {
                filters[`${partType}`] = ['scad'];
            } else {
                filters[`${partType}`] = ['py'];
            }

            const uri = await vscode.window.showSaveDialog({
                title: `Select the ${partType} file to be generated`,
                filters: filters,
            });
            if (!uri) {
                await vscode.window.showWarningMessage('File was not selected');
                return;
            }

            const provider = await vscode.window.showQuickPick(['google', 'openai', 'ollama'], {
                canPickMany: false,
                title: 'Select the model',
            });
            if (!provider) {
                await vscode.window.showWarningMessage('Provider was not selected');
                return;
            }

            const prompt = await vscode.window.showInputBox({
                title: 'Enter the prompt',
                prompt: 'Concisely describe the part, guiding the model through the process of creating it',
                placeHolder: 'A cube with a hole in the middle',
                ignoreFocusOut: true,
                password: false,
            });
            if (!prompt) {
                await vscode.window.showWarningMessage('Prompt was not provided');
                return;
            }

            // Create an empty file
            const wsedit = new vscode.WorkspaceEdit();
            wsedit.createFile(uri, { ignoreIfExists: true });
            await vscode.workspace.applyEdit(wsedit);

            var packageName = '//';
            if (currentItemType === PartcadItem.ITEM_TYPE_PACKAGE) {
                packageName = currentItemPackage + '/' + currentItemName;
            } else if (currentItemType !== PartcadItem.ITEM_TYPE_NONE) {
                packageName = currentItemPackage;
            }

            await vscode.commands.executeCommand('partcad.addPartReal', {
                kind: partTypeTypes[partType],
                path: uri.fsPath,
                config: { provider: provider, desc: prompt },
                packageName: packageName,
            });
            itemToSelectOnRestart = uri.fsPath;
            await vscode.commands.executeCommand('partcad.restart');
        }),
        registerCommand(`partcad.addPart`, async () => {
            let packageName = '//';
            if (currentItemType === PartcadItem.ITEM_TYPE_PACKAGE) {
                packageName = currentItemName;
            } else if (currentItemType !== PartcadItem.ITEM_TYPE_NONE) {
                packageName = currentItemPackage;
            }

            await vscode.commands.executeCommand('partcad.packagePath', {
                packageName: packageName,
                callback: 'partcad.addPart2',
            });
        }),
        registerCommand(`partcad.addPart2`, async ({ packageName, packagePath, isAbsolute }) => {
            vscode.window.showInformationMessage(`Adding a part to '{packageName}' at '{packagePath}'`);

            let startUri = undefined;
            if (isAbsolute) {
                startUri = vscode.Uri.parse(packagePath);
            } else {
                let wsUri = undefined;
                if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                    wsUri = vscode.workspace.workspaceFolders[0].uri;
                }
                if (!wsUri) {
                    await vscode.window.showWarningMessage('Failed to deteremine the workspace path');
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
            };
            const partType = await vscode.window.showQuickPick(
                ['STEP', 'STL', '3MF', 'OpenSCAD', 'CadQuery', 'build123d'],
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
            let packageName = '//';
            if (currentItemType === PartcadItem.ITEM_TYPE_PACKAGE) {
                packageName = currentItemName;
            } else if (currentItemType !== PartcadItem.ITEM_TYPE_NONE) {
                packageName = currentItemPackage;
            }

            await vscode.commands.executeCommand('partcad.packagePath', {
                packageName: packageName,
                callback: 'partcad.addAssembly2',
            });
        }),
        registerCommand(`partcad.addAssembly2`, async ({ packageName, packagePath, isAbsolute }) => {
            let startUri = undefined;
            if (isAbsolute) {
                startUri = vscode.Uri.parse(packagePath);
            } else {
                let wsUri = undefined;
                if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                    wsUri = vscode.workspace.workspaceFolders[0].uri;
                }
                if (!wsUri) {
                    await vscode.window.showWarningMessage('Failed to deteremine the package path');
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
        registerCommand(`partcad.inspectPackage`, async (pkg) => {
            currentItemType = PartcadItem.ITEM_TYPE_PACKAGE;
            currentItemName = pkg.pkg;
            currentItemPackage = pkg.pkg;
            currentItemParams = {};
            // TODO(claibee): add this when packages are viewable
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
        registerCommand(`partcad.inspectFileRoot`, async () => {
            await vscode.commands.executeCommand('partcad.inspectFile', '');
        }),
        registerCommand(`partcad.startInstall`, async () => {
            await vscode.commands.executeCommand('setContext', 'partcad.beingInstalled', true);
            await vscode.commands.executeCommand('partcad.install');
        }),
        registerCommand(`partcad.support`, async () => {
            vscode.env.openExternal(vscode.Uri.parse('https://calendly.com/partcad-support/30min'));
        }),
    );

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
            if (currentItemPackage !== '//') {
                text += ', "' + currentItemPackage + '"';
            }
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
    partcadTerminal = terminalInit(terminalEmitter);
    context.subscriptions.push(partcadTerminal);

    setImmediate(async () => {
        const interpreter = getInterpreterFromSetting(serverId);
        if (interpreter === undefined || interpreter.length === 0) {
            traceLog(`Python extension loading`);
            await initializePython(context.subscriptions);
            traceLog(`Python extension loaded`);
        } else {
            await runServer();
        }
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
