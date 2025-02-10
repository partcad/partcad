//
// PartCAD, 2024
//
// Author: Roman Kuzmenko
// Created: 2024-12-28
//
// Licensed under Apache License, Version 2.0.
//

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as utils from './utils';

type Stats = {
    path: string;
    size: number;
    packages: number;
    packagesInstantiated: number;
    sketches: number;
    sketchesInstantiated: number;
    interfaces: number;
    interfacesInstantiated: number;
    parts: number;
    partsInstantiated: number;
    assemblies: number;
    assembliesInstantiated: number;
};

let saved: {
    stats: Stats;
    version: string;
} = {
    stats: {
        path: 'Loading...',
        size: 0,
        packages: 0,
        packagesInstantiated: 0,
        sketches: 0,
        sketchesInstantiated: 0,
        interfaces: 0,
        interfacesInstantiated: 0,
        parts: 0,
        partsInstantiated: 0,
        assemblies: 0,
        assembliesInstantiated: 0,
    },
    version: 'Loading...',
};

export class PartcadContext implements vscode.WebviewViewProvider {
    public static readonly viewType = 'partcadContext';

    private _view?: vscode.WebviewView;

    constructor(private readonly _extensionUri: vscode.Uri) {}

    public async setStats(stats: Stats, version: string) {
        console.log('setStats');
        saved.stats = stats;
        saved.version = version;
        if (this._view) {
            this._view.webview.html = this._getHtmlForWebview(this._view.webview);
        }
        // await this._view?.webview.postMessage({ type: 'stats', stats: stats, version: version });
    }

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ) {
        console.log('resolveWebviewView');
        this._view = webviewView;

        webviewView.webview.options = {
            // Allow scripts in the webview
            enableScripts: true,

            localResourceRoots: [this._extensionUri],
        };

        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        console.log('getHtmlForWebview');
        // Get the local path to main script run in the webview, then convert it to a uri we can use in the webview.
        const scriptUri = webview.asWebviewUri(utils.joinPath(this._extensionUri, 'resources', 'js', 'context.js'));

        // Do the same for the stylesheet.
        const styleMainUri = webview.asWebviewUri(utils.joinPath(this._extensionUri, 'resources', 'css', 'main.css'));
        const styleVscodeUri = webview.asWebviewUri(
            utils.joinPath(this._extensionUri, 'resources', 'css', 'vscode.css'),
        );

        // Use a nonce to only allow a specific script to be run.
        const nonce = getNonce();

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

				<title>PartCAD Context</title>
			</head>
			<body>
        <table>
        <tr>
        <td>PartCAD:</td>
        <td id="version" class="version">${saved.version}</td>
        </tr>
        <tr>
        <td>Package:</td>
        <td id="path" class="path">${saved.stats.path}</td>
        </tr>
        <tr>
        <td colspan=2>&nbsp;</td>
        </tr>
        <tr>
        <td>Packages:</td>
        <td id="num-packages" class="num-packages">${saved.stats.packages}&nbsp;(${saved.stats.packagesInstantiated})</td>
        </tr>
        <tr>
        <td>Sketches:</td>
        <td id="num-sketches" class="num-sketches">${saved.stats.sketches}&nbsp;(${saved.stats.sketchesInstantiated})</td>
        </tr>
        <tr>
        <td>Interfaces:</td>
        <td id="num-interfaces" class="num-interfaces">${saved.stats.interfaces}&nbsp;(${saved.stats.interfacesInstantiated})</td>
        </tr>
        <tr>
        <td>Parts:</td>
        <td id="num-parts" class="num-parts">${saved.stats.parts}&nbsp;(${saved.stats.partsInstantiated})</td>
        </tr>
        <tr>
        <td>Assemblies:</td>
        <td id="num-assemblies" class="num-assemblies">${saved.stats.assemblies}&nbsp;(${saved.stats.assembliesInstantiated})</td>
        </tr>
        <tr>
        <td>Memory:</td>
        <td id="num-memory" class="num-memory">${saved.stats.size}</td>
        </tr>
        </table>

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
