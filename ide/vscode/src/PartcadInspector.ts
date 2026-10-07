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

type ItemData = {
    pkg: string;
    name: string;
    itemPath: string | undefined;
    config?: { type?: string; parameters?: Record<string, Record<string, unknown>> };
};

/** What the Inspector last showed, kept here so that `pc ide state` can say so without the webview. */
interface Shown {
    kind: string;
    item: ItemData;
    params: Record<string, unknown>;
}

/** How long the Inspector's webview has to say what its fields hold. */
const STATE_REPLY_MS = 3000;

/** The kinds of item that can be inspected, and how each is shown. */
const KINDS = {
    sketch: { command: 'partcad.showSketch', progress: 'Inspecting the sketch...' },
    interface: { command: 'partcad.showInterface', progress: 'Inspecting the interface...' },
    part: { command: 'partcad.showPart', progress: 'Inspecting the part...' },
    assembly: { command: 'partcad.showAssembly', progress: 'Inspecting the assembly...' },
    scene: { command: 'partcad.showScene', progress: 'Inspecting the scene...' },
} as const;

type ItemKind = keyof typeof KINDS;

export class PartcadInspector implements vscode.WebviewViewProvider {
    public static readonly viewType = 'partcadInspector';

    private _view?: vscode.WebviewView;

    private _showResolve?: (value: any) => void;

    /**
     * Renders asked for and not yet reported done.
     *
     * '?/partcad/showPartDone' carries no inspection identifier, so a
     * completion cannot be matched to its request by name. It can be matched by
     * count: PartCAD reports one completion per render it was asked for, so
     * only once every earlier render has reported in is the completion this
     * inspection's own. Without the count, a render superseded by a faster
     * click resolves the newer inspection instead of its own.
     */
    private _pendingShows: number = 0;

    private shownPackage: string = '';
    private shownItem: string = '';
    private shown: Shown | undefined;
    private stateRequests = 0;
    private readonly stateReplies = new Map<number, (reply: InspectorReply) => void>();

    constructor(private readonly _extensionUri: vscode.Uri) {
        this.clear().then(() => {
            // Do nothing
        });
    }

    async clear() {
        this.shownPackage = '';
        this.shownItem = '';
        this.shown = undefined;
        await this._view?.webview.postMessage({ type: 'clear' });
    }

    /**
     * showDone is called when lsp_server tells the extension that the show command is complete
     */
    public showDone() {
        if (this._pendingShows > 0) {
            this._pendingShows -= 1;
        }
        if (this._pendingShows === 0 && this._showResolve) {
            const resolve = this._showResolve;
            this._showResolve = undefined;
            resolve(undefined);
        }
    }

    public async inspectPackage(pkg: ItemData) {
        this.shown = { kind: 'package', item: pkg, params: {} };
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

    public async inspectScene(scene: ItemData, params: Object) {
        await this.inspect('scene', scene, params);
    }

    /**
     * Show what a software object is, and render nothing.
     *
     * Software is a file the package ships - a firmware image, a disk image, a
     * binary - and not geometry, so there is nothing for the PartCAD Viewer to
     * draw and it is deliberately left alone: whatever shape it is showing stays
     * on screen. That is why this does not go through 'inspect()', which exists
     * to ask PartCAD for a render.
     */
    public async inspectSoftware(software: ItemData) {
        // Forgotten rather than remembered, because the details on screen are no
        // longer any item's: without this, inspecting the part that was shown
        // before this software object would find its own name still recorded and
        // skip re-posting, leaving the software details in view.
        this.shownPackage = '';
        this.shownItem = '';
        this.shown = { kind: 'software', item: software, params: {} };
        await this._view?.webview.postMessage({ type: 'software', obj: software, params: {} });
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
        this.shown = { kind, item, params: { ...(params as Record<string, unknown>) } };

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
                    // by this one rather than left to hang. Its render is still
                    // running, though, so it is still owed a completion, which
                    // '_pendingShows' keeps this one from taking for its own.
                    if (this._showResolve) {
                        this._showResolve(undefined);
                    }
                    this._showResolve = resolve;
                    this._pendingShows += 1;
                });

                progress.report({ message: progressMessage, increment: 20 });
                const rendered = (async () => {
                    try {
                        await vscode.commands.executeCommand(command, { pkg: packageName, name: itemName, params });
                    } catch (error) {
                        // A render that never started will never be reported
                        // done; drop its share of the count so it cannot leave
                        // a later inspection waiting forever.
                        this.showDone();
                        throw error;
                    }
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

        webviewView.webview.onDidReceiveMessage((message: { action: string; command: string; params: [] } & any) => {
            if (message.action === 'state') {
                this.stateReplies.get(message.token)?.(message as InspectorReply);
                return;
            }
            if (message.action === 'command') {
                vscode.commands.executeCommand(message.command, ...message.params);
            }
        });
    }

    /**
     * What the Inspector shows, for `pc ide state`.
     *
     * The object and the parameters it was last shown with are known here. What
     * the fields hold *now* is only in the webview -- somebody may have typed a
     * new value and not pressed Update -- so it is asked, and when it cannot
     * answer (collapsed, not yet opened) the state says the values it reports
     * are the applied ones.
     */
    public async state(): Promise<unknown> {
        if (this.shown === undefined) {
            return null;
        }
        const reply = await this.askWebview();
        return inspectorState(this.shown, reply);
    }

    private askWebview(): Promise<InspectorReply | undefined> {
        const view = this._view;
        if (view === undefined) {
            return Promise.resolve(undefined);
        }
        const token = ++this.stateRequests;
        return new Promise((resolve) => {
            const timer = setTimeout(() => finish(undefined), STATE_REPLY_MS);
            const finish = (reply: InspectorReply | undefined) => {
                clearTimeout(timer);
                this.stateReplies.delete(token);
                resolve(reply);
            };
            this.stateReplies.set(token, finish);
            view.webview.postMessage({ type: 'state', token }).then(
                (delivered) => {
                    if (!delivered) {
                        finish(undefined);
                    }
                },
                () => finish(undefined),
            );
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

/** What the Inspector's webview says about itself when asked. */
export interface InspectorReply {
    /** The rows of its table, label to the text in it. */
    properties?: Record<string, string>;
    /** Each parameter field, by parameter name, as it holds now. */
    values?: Record<string, string>;
}

/**
 * The Inspector's entry of the state. Pure, so that it is tested without a window.
 *
 * 'reply' is undefined when the webview did not answer; the values are then the
 * applied ones, and `live` says so.
 */
export function inspectorState(shown: Shown, reply: InspectorReply | undefined): Record<string, unknown> {
    const { kind, item, params } = shown;
    const isPackage = kind === 'package';
    const declared = item.config?.parameters ?? {};
    const parameters: Record<string, unknown> = {};
    for (const [name, spec] of Object.entries(declared)) {
        const value = reply?.values?.[name] ?? params[name] ?? spec.default ?? null;
        parameters[name] = { ...spec, value };
    }
    return {
        kind,
        path: isPackage ? item.name : `${item.pkg}:${item.name}`,
        package: isPackage ? item.name : item.pkg,
        name: item.name,
        type: item.config?.type ?? null,
        file: item.itemPath ?? null,
        properties: reply?.properties ?? null,
        parameters,
        applied: params,
        live: reply !== undefined,
    };
}
