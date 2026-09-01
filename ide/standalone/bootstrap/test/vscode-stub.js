//
// PartCAD, 2026
//
// Author: PartCAD (support@partcad.org)
//
// Licensed under Apache License, Version 2.0.
//
// As much of the `vscode` module as `../extension.js` touches, and the
// extension host state it is handed. Node resolves `require('vscode')` to
// nothing -- the real one is injected by the editor at run time -- so the tests
// beside this file intercept the load and hand back `makeVscode()`.
//

const Module = require('node:module');
const path = require('node:path');

// What the editor reports as registered by default: the commands the PartCAD
// extension contributes, because in this IDE it is always installed.
const REGISTERED_COMMANDS = ['workbench.view.extension.partcad-container', 'partcad.refresh'];

/** A `vscode` module, plus a record of everything the extension did to it. */
function makeVscode({ appRoot, workspaceFolders = [], commands = REGISTERED_COMMANDS } = {}) {
    const calls = [];
    const settings = new Map();

    const uri = (fsPath) => ({ scheme: 'file', fsPath, toString: () => `file://${fsPath}` });

    const api = {
        // What the extension did, in order, for a test to assert on.
        calls,
        settings,
        version: '1.82.0',

        env: {
            appRoot,
            openExternal: async (target) => calls.push(['openExternal', target.toString()]),
        },

        Uri: { file: uri, parse: (value) => ({ scheme: 'https', toString: () => value }) },

        ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
        ProgressLocation: { Notification: 15, Window: 10 },

        workspace: {
            // Undefined rather than empty when there is none: that is what the
            // editor hands an empty window, and what the extension tests for.
            workspaceFolders: workspaceFolders.length
                ? workspaceFolders.map((folder) => ({ uri: uri(folder) }))
                : undefined,
            workspaceFile: undefined,
            getConfiguration: (section) => ({
                get: (key, fallback) => (settings.has(`${section}.${key}`) ? settings.get(`${section}.${key}`) : fallback),
                inspect: (key) => ({ globalValue: settings.get(`${section}.${key}`) }),
                update: async (key, value) => settings.set(`${section}.${key}`, value),
            }),
            openTextDocument: async (fsPath) => {
                calls.push(['openTextDocument', fsPath]);
                return { fsPath };
            },
        },

        window: {
            createOutputChannel: () => ({ appendLine: (line) => calls.push(['log', line]) }),
            showErrorMessage: (message) => calls.push(['error', message]),
            // What the test said the user would press, or nothing.
            showInformationMessage: async (message, ...items) => {
                calls.push(['information', message, ...items]);
                return items.find((item) => item === api.window.pressed);
            },
            // The item a test wants chosen from the next quick pick.
            showQuickPick: async (items) => {
                calls.push(['quickPick', items.map((item) => item.label)]);
                return items.find((item) => item.label === api.window.picked);
            },
            picked: undefined,
            pressed: undefined,
            showTextDocument: (document) => calls.push(['showTextDocument', document.fsPath]),
            withProgress: (options, task) => task(),
        },

        commands: {
            registered: new Map(),
            getCommands: async () => commands,
            registerCommand: (command, handler) => {
                api.commands.registered.set(command, handler);
                return { dispose() {} };
            },
            executeCommand: async (command, ...args) => {
                calls.push(['command', command, ...args]);
            },
        },
    };

    return api;
}

/** The `ExtensionContext` the editor passes to `activate`. */
function makeContext(extensionPath) {
    const state = new Map();
    return {
        extensionPath,
        subscriptions: [],
        environmentVariableCollection: { prepend: () => {}, description: undefined },
        globalState: {
            get: (key) => state.get(key),
            update: async (key, value) => state.set(key, value),
            keys: () => [...state.keys()],
        },
    };
}

/**
 * Load `../extension.js` against `vscode`, freshly, so that the module state it
 * keeps (the output channel) does not leak from one test into the next.
 */
function loadExtension(vscode) {
    const load = Module._load;
    Module._load = function (request, ...rest) {
        return request === 'vscode' ? vscode : load.call(this, request, ...rest);
    };
    try {
        const entry = path.join(__dirname, '..', 'extension.js');
        delete require.cache[require.resolve(entry)];
        return require(entry);
    } finally {
        Module._load = load;
    }
}

module.exports = { makeVscode, makeContext, loadExtension };
