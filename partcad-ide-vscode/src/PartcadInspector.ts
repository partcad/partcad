//
// PartCAD, 2024
//
// Author: Roman Kuzmenko
// Created: 2024-12-28
//
// Licensed under Apache License, Version 2.0.
//

import * as vscode from 'vscode';
import * as utils from './utils';

type ItemData = { pkg: string; name: string; itemPath: string | undefined };

/** The kinds of item that can be inspected, and how each is shown. */
const KINDS = {
    sketch: { command: 'partcad.showSketch', progress: 'Inspecting the sketch...' },
    interface: { command: 'partcad.showInterface', progress: 'Inspecting the interface...' },
    part: { command: 'partcad.showPart', progress: 'Inspecting the part...' },
    assembly: { command: 'partcad.showAssembly', progress: 'Inspecting the assembly...' },
} as const;

type ItemKind = keyof typeof KINDS;

export class PartcadInspector implements vscode.WebviewViewProvider {
    public static readonly viewType = 'partcadInspector';

    private _view?: vscode.WebviewView;

    private _showResolve?: (value: any) => void;

    private shownPackage: string = '';
    private shownItem: string = '';

    constructor(private readonly _extensionUri: vscode.Uri) {
        this.clear().then(() => {
            // Do nothing
        });
    }

    async clear() {
        this.shownPackage = '';
        this.shownItem = '';
        await this._view?.webview.postMessage({ type: 'clear' });
    }

    /**
     * showDone is called when lsp_server tells the extension that the show command is complete
     */
    public showDone() {
        if (this._showResolve) {
            this._showResolve(undefined);
        }
    }

    public async inspectPackage(pkg: ItemData) {
        await this._view?.webview.postMessage({ type: 'package', obj: pkg, params: {} });
    }

    public async inspectSketch(sketch: ItemData, params: Object) {
        await this.inspect('sketch', sketch, params);
    }

    public async inspectInterface(intf: ItemData, params: Object) {
        await this.inspect('interface', intf, params);
    }

    public async inspectPart(part: ItemData, params: Object) {
        await this.inspect('part', part, params);
    }

    public async inspectAssembly(assembly: ItemData, params: Object) {
        await this.inspect('assembly', assembly, params);
    }

    /**
     * Render an item and show it in the PartCAD Viewer.
     *
     * PartCAD renders the item in its own process and pushes the result to the
     * viewer over the PartCAD IDE socket; the viewer tab opens itself when that
     * arrives. So there is nothing to launch and nothing to wait for here beyond
     * the render itself - which is what the '?/partcad/showPartDone'
     * notification, and so 'showDone()', resolves.
     */
    private async inspect(kind: ItemKind, item: ItemData, params: Object) {
        const { command, progress: progressMessage } = KINDS[kind];
        const itemName = item['name'];
        const packageName = item['pkg'];
        const itemPath = item['itemPath'];

        if (this.shownPackage !== packageName || this.shownItem !== itemName) {
            await this._view?.webview.postMessage({ type: kind, obj: item, params });
        }
        this.shownPackage = packageName;
        this.shownItem = itemName;

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: `${itemName}`,
                cancellable: false,
            },
            async (progress, _token) => {
                // Assigned before the render is asked for, because the
                // '?/partcad/showPartDone' that resolves it can arrive as soon as
                // the command below returns.
                const done = new Promise((resolve) => {
                    // A previous inspection that is still pending is superseded
                    // by this one rather than left to hang.
                    if (this._showResolve) {
                        this._showResolve(undefined);
                    }
                    this._showResolve = resolve;
                });

                progress.report({ message: progressMessage, increment: 20 });
                const rendered = (async () => {
                    await vscode.commands.executeCommand(command, { pkg: packageName, name: itemName, params });
                    // Wait for an outside call of this._showResolve()
                    await done;
                })();

                // An item defined in the root package has a file of its own; open
                // it beside the viewer so the user sees the source they are
                // inspecting. Not for items pulled in from a dependency, whose
                // files are not the user's to edit. Started after the render is
                // already under way so it costs no latency - the render is the
                // slow half, and nothing about it depends on the editor.
                if (itemPath !== undefined && packageName === '//') {
                    await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(itemPath), 'default', {
                        viewColumn: vscode.ViewColumn.One,
                        preview: true,
                    });
                }

                await rendered;
            },
        );
    }

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ) {
        this._view = webviewView;

        webviewView.webview.options = {
            // Allow scripts in the webview
            enableScripts: true,

            localResourceRoots: [this._extensionUri],
        };

        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

        webviewView.webview.onDidReceiveMessage((message: { action: string; command: string; params: [] }) => {
            if (message.action === 'command') {
                vscode.commands.executeCommand(message.command, ...message.params);
            }
        });
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        // Get the local path to main script run in the webview, then convert it to a uri we can use in the webview.
        const scriptUri = webview.asWebviewUri(utils.joinPath(this._extensionUri, 'resources', 'js', 'inspector.js'));

        // Do the same for the stylesheet.
        const styleMainUri = webview.asWebviewUri(utils.joinPath(this._extensionUri, 'resources', 'css', 'main.css'));
        const styleVscodeUri = webview.asWebviewUri(
            utils.joinPath(this._extensionUri, 'resources', 'css', 'vscode.css'),
        );

        // Use a nonce to only allow a specific script to be run.
        const nonce = getNonce();

        vscode.commands.executeCommand('partcad.getStats').then(undefined, (err) => {
            console.error(err);
        });

        return `<!DOCTYPE html>
			<html lang="en">
			<head>
				<meta charset="UTF-8">

				<!--
					Use a content security policy to only allow loading styles from our extension directory,
					and only allow scripts that have a specific nonce.
					(See the 'webview-sample' extension sample for img-src content security policy examples)
				-->
				<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">

				<meta name="viewport" content="width=device-width, initial-scale=1.0">

				<link href="${styleMainUri}" rel="stylesheet">
				<link href="${styleVscodeUri}" rel="stylesheet">

				<title>PartCAD Inspector</title>
			</head>
			<body>
				<div id="contents" class="contents">
				</div>

				<!--<button class="show-button">Explode</button>-->

				<script nonce="${nonce}" src="${scriptUri}"></script>
			</body>
			</html>`;
    }
}

function getNonce() {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
