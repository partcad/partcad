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
 * The tabs the panel offers, and the daemon operation behind each.
 *
 * The 3D view is not here: its contents arrive over the viewer protocol from
 * whichever 'partcad' asked for the shape to be shown, and are already in the
 * webview by the time a tab is looked at. Everything else is a question about
 * '<package>:<name>' that only this side can put to the daemon, so the renderer
 * asks and this answers -- see 'fetchTab'.
 */
const TAB_COMMANDS: Record<string, string> = {
    bom: 'partcad.bom',
    instructions: 'partcad.assemblyGuide',
    // What the object's CAM plugin draws of the instructions it writes, already
    // converted to glTF by PartCAD. Producing it means running the plugin in a
    // sandbox, which is why the tab is filled in on demand like every other one
    // rather than pushed with the geometry.
    cam: 'partcad.camVisual',
    supply: 'partcad.supplyQuote',
};

/**
 * The "PartCAD Viewer" editor tab.
 *
 * A webview panel rather than a view in the side bar: a 3D model wants the whole
 * editor area, and it has to survive being switched away from, which is what
 * 'retainContextWhenHidden' buys (reloading the webview would drop the model,
 * the camera the user set up, and every tab already fetched).
 */
export class PartcadViewer implements vscode.Disposable {
    public static readonly viewType = 'partcadViewer';
    public static readonly title = 'PartCAD Viewer';

    private panel: vscode.WebviewPanel | undefined;
    private lastShow: ViewerMessage | undefined;

    /**
     * Which object is on screen, counted the way the renderer counts it.
     *
     * The renderer bumps its own generation on every 'show' and every 'clear',
     * and drops anything that arrives for an older one, so a late answer about a
     * tab has to carry the same number to be believed. The two stay in step
     * because this is bumped for exactly the same two messages.
     */
    private generation = 0;

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
            // The renderer counts a 'clear' as a change of object like any
            // other, so this has to count it too or the two drift apart and
            // every later answer this side mints a token for is dropped.
            this.generation += 1;
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
            // What the panel's other tabs are about. A 'partcad' that does not
            // send it (an older one, or a shape belonging to no package) leaves
            // the renderer showing the 3D view alone.
            package: message.package ?? null,
            keepCamera: message.keepCamera === true,
            objects,
            markers: message.markers ?? [],
        });

        // Whether this object has a CAM view is a question for the daemon, and
        // the geometry must not wait on the answer - so it is asked afterwards
        // and the tab appears when it arrives. Only for a part: an assembly is
        // put together out of parts that each have their own instructions.
        this.generation += 1;
        if (message.package && message.name && (message.kind ?? 'part') === 'part') {
            void this.offerCamTab(message.package, message.name, this.generation);
        }
    }

    /**
     * Add the CAM tab, if this object turns out to have one.
     *
     * 'cam.info' reads configuration and builds nothing, so this costs a round
     * trip and no work. An object whose package declares no 'cam:' file type -
     * which is most of them - gets no tab and no message about not having one.
     */
    private async offerCamTab(pkg: string, name: string, token: number): Promise<void> {
        let visual: string | null = null;
        try {
            if ((await vscode.commands.getCommands(true)).includes('partcad.camInfo')) {
                const info = (await vscode.commands.executeCommand('partcad.camInfo', { pkg, name })) as
                    { visual?: string | null } | undefined;
                visual = info?.visual ?? null;
            }
        } catch (error: any) {
            // Not worth telling the user about: the tab is an extra, and the
            // object is on screen either way.
            traceVerbose(`PartCAD Viewer: no CAM view for ${pkg}:${name}: ${error?.message ?? error}`);
        }
        if (token !== this.generation) {
            // Something else is on screen by now.
            return;
        }
        void this.panel?.webview.postMessage({ type: 'tabs', token, cam: visual });
    }

    /**
     * Fill one of the panel's tabs in, on the renderer's request.
     *
     * 'token' is the renderer's generation of the object the request was made
     * for; it comes back untouched so that an answer arriving after the user
     * moved on can be dropped there rather than painted over what is now on
     * screen. A refusal is an answer too: asking for the instructions of an
     * assembly that has no assembly steps is told why, and the reader sees that
     * instead of an empty tab.
     */
    private async fetchTab(tab: string, token: number): Promise<void> {
        const post = (payload: { data?: unknown; error?: string }) =>
            void this.panel?.webview.postMessage({ type: 'tabData', tab, token, ...payload });

        const command = TAB_COMMANDS[tab];
        if (command === undefined) {
            post({ error: `There is nothing to fill the '${tab}' tab with.` });
            return;
        }
        const target = this.lastShow;
        if (!target?.package || !target.name) {
            post({ error: 'PartCAD did not say which package this object belongs to.' });
            return;
        }

        try {
            // The commands are registered by the backend, so an absent one means
            // no PartCAD is connected -- which is worth saying plainly rather
            // than reporting as a missing command.
            if (!(await vscode.commands.getCommands(true)).includes(command)) {
                throw new Error('PartCAD is not connected. Use "Restart PartCAD" to reconnect.');
            }
            post({ data: await vscode.commands.executeCommand(command, { pkg: target.package, name: target.name }) });
        } catch (error: any) {
            traceError(`PartCAD Viewer: failed to fetch the '${tab}' tab: ${error?.message ?? error}`);
            post({ error: `${error?.message ?? error}` });
        }
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
        panel.webview.onDidReceiveMessage(
            (message: { type: string; message?: string; tab?: string; token?: number }) => {
                if (message.type === 'error') {
                    traceError(`PartCAD Viewer: ${message.message}`);
                } else if (message.type === 'fetchTab') {
                    void this.fetchTab(message.tab ?? '', message.token ?? 0);
                } else if (message.type === 'ready' && this.lastShow !== undefined) {
                    // The webview finished booting after we had already been asked
                    // to show something (a restored tab, or a show that raced the
                    // panel's first paint).
                    this.handle(this.lastShow);
                } else {
                    traceVerbose(`PartCAD Viewer: ${message.type}`);
                }
            },
        );
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
				<div class="panel">
					<div id="tabs" class="tabs" hidden></div>
					<div class="panes">
						<div id="pane-3d" class="pane pane-3d">
							<div id="viewer" class="viewer">
								<div id="overlay" class="overlay">Nothing to display yet.</div>
								<div id="label" class="label"></div>
							</div>
						</div>
						<div id="pane-bom" class="pane" hidden></div>
						<div id="pane-instructions" class="pane" hidden></div>
						<div id="pane-cam" class="pane" hidden></div>
						<div id="pane-supply" class="pane" hidden></div>
					</div>
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
