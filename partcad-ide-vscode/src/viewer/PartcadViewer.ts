//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//

import * as vscode from 'vscode';
import { traceError, traceVerbose } from '../common/log/logging';
import * as utils from '../utils';
import { MSG_CLEAR, MSG_SHOW, ViewerMessage, decodeGltf } from './protocol';

/** What the webview is handed: the glTF, decompressed, as base64. */
interface WebviewObject {
    name: string;
    label: string | null;
    gltf: string;
    size: number;
}

/**
 * The "PartCAD Viewer" editor tab.
 *
 * A webview panel rather than a view in the side bar: a 3D model wants the whole
 * editor area, and it has to survive being switched away from, which is what
 * 'retainContextWhenHidden' buys (reloading the webview would drop the model and
 * the camera the user set up).
 */
export class PartcadViewer implements vscode.Disposable {
    public static readonly viewType = 'partcadViewer';
    public static readonly title = 'PartCAD Viewer';

    private panel: vscode.WebviewPanel | undefined;
    private lastShow: ViewerMessage | undefined;

    constructor(private readonly extensionUri: vscode.Uri) {}

    /** Whether the viewer tab currently exists. */
    public get isOpen(): boolean {
        return this.panel !== undefined;
    }

    /** Open the viewer (or bring it forward) without changing what it displays. */
    public reveal(preserveFocus = true): void {
        if (this.panel !== undefined) {
            this.panel.reveal(undefined, preserveFocus);
            return;
        }
        this.create(vscode.ViewColumn.Beside, preserveFocus);
        if (this.lastShow !== undefined) {
            // Reopening after a close should not leave an empty canvas when we
            // still know what was in it.
            this.handle(this.lastShow);
        }
    }

    /** Adopt a panel VS Code restored from a previous session. */
    public restore(panel: vscode.WebviewPanel): void {
        this.panel?.dispose();
        this.attach(panel);
    }

    /** Route a protocol message from a connected PartCAD to the webview. */
    public handle(message: ViewerMessage): void {
        if (message.type === MSG_CLEAR) {
            this.lastShow = undefined;
            void this.panel?.webview.postMessage({ type: 'clear' });
            return;
        }
        if (message.type !== MSG_SHOW) {
            return;
        }

        let objects: WebviewObject[];
        try {
            objects = (message.objects ?? []).map((object, index) => {
                // Decompressed here, in the extension host, rather than in the
                // webview: Node has zlib built in, a webview would need either a
                // bundled inflater or DecompressionStream.
                const gltf = decodeGltf(object.gltf);
                return {
                    name: object.name ?? `object-${index}`,
                    label: object.label ?? null,
                    gltf: gltf.toString('base64'),
                    size: gltf.length,
                };
            });
        } catch (error: any) {
            traceError(`PartCAD Viewer: failed to decode the geometry: ${error.message}`);
            void vscode.window.showErrorMessage(`PartCAD Viewer: failed to decode the geometry: ${error.message}`);
            return;
        }

        this.lastShow = message;

        // Showing something is what opens the viewer: the user asked to inspect
        // an item, and an inspection with nowhere to draw is not useful.
        if (this.panel === undefined) {
            this.create(vscode.ViewColumn.Beside, true);
        }

        void this.panel?.webview.postMessage({
            type: 'show',
            name: message.name ?? null,
            kind: message.kind ?? null,
            keepCamera: message.keepCamera === true,
            objects,
            markers: message.markers ?? [],
        });
    }

    private create(column: vscode.ViewColumn, preserveFocus: boolean): void {
        const panel = vscode.window.createWebviewPanel(
            PartcadViewer.viewType,
            PartcadViewer.title,
            { viewColumn: column, preserveFocus },
            this.webviewOptions(),
        );
        this.attach(panel);
    }

    private attach(panel: vscode.WebviewPanel): void {
        panel.webview.options = this.webviewOptions();
        panel.iconPath = utils.joinPath(this.extensionUri, 'resources', 'logo.svg');
        panel.webview.html = this.html(panel.webview);
        panel.onDidDispose(() => {
            if (this.panel === panel) {
                this.panel = undefined;
            }
        });
        panel.webview.onDidReceiveMessage((message: { type: string; message?: string }) => {
            if (message.type === 'error') {
                traceError(`PartCAD Viewer: ${message.message}`);
            } else if (message.type === 'ready' && this.lastShow !== undefined) {
                // The webview finished booting after we had already been asked
                // to show something (a restored tab, or a show that raced the
                // panel's first paint).
                this.handle(this.lastShow);
            } else {
                traceVerbose(`PartCAD Viewer: ${message.type}`);
            }
        });
        this.panel = panel;
    }

    private webviewOptions(): vscode.WebviewPanelOptions & vscode.WebviewOptions {
        return {
            enableScripts: true,
            // Switching to another editor tab must not throw the model away.
            retainContextWhenHidden: true,
            localResourceRoots: [this.extensionUri],
        };
    }

    private html(webview: vscode.Webview): string {
        const scriptUri = webview.asWebviewUri(utils.joinPath(this.extensionUri, 'dist', 'viewer.js'));
        const styleUri = webview.asWebviewUri(utils.joinPath(this.extensionUri, 'resources', 'css', 'viewer.css'));
        const nonce = getNonce();

        // No 'connect-src': the geometry arrives over postMessage and is parsed
        // from memory, so the viewer never issues a network request. Nothing
        // here may be relaxed to load an asset from a CDN.
        return `<!DOCTYPE html>
			<html lang="en">
			<head>
				<meta charset="UTF-8">
				<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; img-src ${webview.cspSource} data: blob:; script-src 'nonce-${nonce}';">
				<meta name="viewport" content="width=device-width, initial-scale=1.0">
				<link href="${styleUri}" rel="stylesheet">
				<title>${PartcadViewer.title}</title>
			</head>
			<body>
				<div id="viewer" class="viewer">
					<div id="overlay" class="overlay">Nothing to display yet.</div>
					<div id="label" class="label"></div>
				</div>
				<script nonce="${nonce}" src="${scriptUri}"></script>
			</body>
			</html>`;
    }

    public dispose(): void {
        this.panel?.dispose();
        this.panel = undefined;
    }
}

function getNonce(): string {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
