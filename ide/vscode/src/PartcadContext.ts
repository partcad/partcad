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
    // Two numbers per kind: how many objects the loaded packages declare, and
    // how many of those have been built. Both spellings of the first are
    // optional because they arrive from whichever PartCAD is serving: the
    // `<kind>Declared` keys are the ones that say what the number is, and the
    // bare `<kind>` keys are what a service published before them sends.
    sketchesDeclared?: number;
    sketches?: number;
    sketchesInstantiated: number;
    interfacesDeclared?: number;
    interfaces?: number;
    interfacesInstantiated: number;
    partsDeclared?: number;
    parts?: number;
    partsInstantiated: number;
    assembliesDeclared?: number;
    assemblies?: number;
    assembliesInstantiated: number;
    // Optional in both spellings: an older PartCAD service does not report
    // scenes at all.
    scenesDeclared?: number;
    scenes?: number;
    scenesInstantiated?: number;
};

/** The declared count of a kind, whichever of the two keys carried it. */
function declared(stats: Stats, kind: 'sketches' | 'interfaces' | 'parts' | 'assemblies' | 'scenes'): number {
    const asDeclared = stats[`${kind}Declared` as keyof Stats];
    if (typeof asDeclared === 'number') {
        return asDeclared;
    }
    const bare = stats[kind as keyof Stats];
    return typeof bare === 'number' ? bare : 0;
}

/**
 * What the version cell holds until PartCAD has reported one.
 *
 * Not a version, and therefore never a mismatch: the extension is compared
 * against what the service said, and before the first `info` it has said
 * nothing.
 */
const VERSION_UNKNOWN = 'Loading...';

let saved: {
    stats: Stats;
    version: string;
} = {
    stats: {
        path: 'Loading...',
        size: 0,
        packages: 0,
        packagesInstantiated: 0,
        sketchesDeclared: 0,
        sketchesInstantiated: 0,
        interfacesDeclared: 0,
        interfacesInstantiated: 0,
        partsDeclared: 0,
        partsInstantiated: 0,
        assembliesDeclared: 0,
        assembliesInstantiated: 0,
        scenesDeclared: 0,
        scenesInstantiated: 0,
    },
    version: VERSION_UNKNOWN,
};

/**
 * Whether the PartCAD the service reports is a different release from the one
 * this extension was published with.
 *
 * `dev-tools/bumpversion.toml` moves `ide/vscode/package.json` along with every
 * other version constant in the repository, so an extension and the PartCAD it
 * shipped beside state the same string. Anything else means the two come from
 * different releases -- and the JSON-RPC surface grows methods, so an older
 * PartCAD answering a newer extension fails in whatever way the method it does
 * not have happens to fail in. The context view is where that is visible before
 * it is confusing, hence the red.
 *
 * Two non-answers are deliberately not mismatches: the placeholder above, and
 * an extension version this build could not read at all -- neither is evidence
 * of disagreement, and colouring them red would cry wolf on every start.
 */
export function versionsDiffer(partcadVersion?: string, extensionVersion?: string): boolean {
    const reported = (partcadVersion ?? '').trim();
    const expected = (extensionVersion ?? '').trim();
    if (reported === '' || reported === VERSION_UNKNOWN || expected === '') {
        return false;
    }
    return reported !== expected;
}

export class PartcadContext implements vscode.WebviewViewProvider {
    public static readonly viewType = 'partcadContext';

    private _view?: vscode.WebviewView;

    constructor(
        private readonly _extensionUri: vscode.Uri,
        // The extension's own version, to compare what PartCAD reports against.
        private readonly _extensionVersion: string,
    ) {}

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

        // A PartCAD that is not this extension's release is called out rather
        // than merely stated: the number is in the view either way, and nobody
        // compares it against an extension version they would have to go and
        // look up. The title says what it is being compared against, because
        // "this is wrong" without "and here is what was expected" is not
        // actionable.
        const mismatch = versionsDiffer(saved.version, this._extensionVersion);
        const versionClass = mismatch ? 'version mismatch' : 'version';
        const versionTitle = mismatch
            ? ` title="PartCAD ${escapeHtml(saved.version)} does not match this extension` +
              ` (${escapeHtml(this._extensionVersion)}). Update PartCAD, or install the matching extension."`
            : '';

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
        <td id="version" class="${versionClass}"${versionTitle}>${escapeHtml(saved.version)}</td>
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
        <td id="num-sketches" class="num-sketches">${declared(saved.stats, 'sketches')}&nbsp;(${saved.stats.sketchesInstantiated})</td>
        </tr>
        <tr>
        <td>Interfaces:</td>
        <td id="num-interfaces" class="num-interfaces">${declared(saved.stats, 'interfaces')}&nbsp;(${saved.stats.interfacesInstantiated})</td>
        </tr>
        <tr>
        <td>Parts:</td>
        <td id="num-parts" class="num-parts">${declared(saved.stats, 'parts')}&nbsp;(${saved.stats.partsInstantiated})</td>
        </tr>
        <tr>
        <td>Assemblies:</td>
        <td id="num-assemblies" class="num-assemblies">${declared(saved.stats, 'assemblies')}&nbsp;(${saved.stats.assembliesInstantiated})</td>
        </tr>
        <tr>
        <td>Scenes:</td>
        <td id="num-scenes" class="num-scenes">${declared(saved.stats, 'scenes')}&nbsp;(${saved.stats.scenesInstantiated ?? 0})</td>
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

/**
 * Escape a value for HTML text or for a double-quoted attribute.
 *
 * The version arrives from the service rather than from this extension, and the
 * title attribute above puts it inside quotes, where an unescaped one would end
 * the attribute.
 */
function escapeHtml(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function getNonce() {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
