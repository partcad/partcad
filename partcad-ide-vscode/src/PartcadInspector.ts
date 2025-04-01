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
        const sketchName = sketch['name'];
        const packageName = sketch['pkg'];
        const itemPath = sketch['itemPath'];

        if (this.shownPackage !== packageName || this.shownItem !== sketchName) {
            await this._view?.webview.postMessage({ type: 'sketch', obj: sketch, params });
        }
        this.shownPackage = packageName;
        this.shownItem = sketchName;

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: `${sketchName}`,
                cancellable: false,
            },
            (progress, _token) => {
                progress.report({ message: 'Contacting OCP CAD Viewer...', increment: 10 });

                const process = new Promise((resolve, reject) => {
                    if (this._showResolve) {
                        this._showResolve(undefined);
                    }
                    this._showResolve = resolve;

                    // Find existing viewer;
                    let found = false;
                    const tabs: vscode.Tab[] = vscode.window.tabGroups.all.map((tg) => tg.tabs).flat();
                    for (var tab of tabs) {
                        if (tab.label === 'OCP CAD Viewer') {
                            found = true;
                            break;
                        }
                    }

                    if (!found) {
                        vscode.commands
                            .executeCommand('ocpCadViewer.ocpCadViewer')
                            .then(
                                () => {
                                    return new Promise((f) => setTimeout(f, 1700));
                                },
                                () => {
                                    reject();
                                },
                            )
                            .then(
                                () => {
                                    progress.report({ message: 'Inspecting the sketch...', increment: 20 });
                                    return vscode.commands.executeCommand('partcad.showSketch', {
                                        pkg: packageName,
                                        name: sketchName,
                                    });
                                },
                                () => {
                                    reject();
                                },
                            )
                            .then(
                                () => {
                                    // Wait for an outside call of this._showResolve()
                                },
                                () => {
                                    reject();
                                },
                            );
                    } else {
                        progress.report({ message: 'Inspecting the sketch...', increment: 20 });
                        vscode.commands
                            .executeCommand('partcad.showSketch', { pkg: packageName, name: sketchName, params })
                            .then(
                                () => {
                                    // Wait for an outside call of this._showResolve()
                                },
                                () => {
                                    reject();
                                },
                            );
                    }
                });

                if (itemPath !== undefined && packageName === '/') {
                    return new Promise((resolve, reject) => {
                        return vscode.commands
                            .executeCommand('vscode.openWith', vscode.Uri.file(itemPath), 'default', {
                                viewColumn: vscode.ViewColumn.One,
                                preview: true,
                            })
                            .then(() => {
                                return new Promise((f) => setTimeout(f, 1700)).then(
                                    () => {
                                        return process
                                            .then(() => {
                                                resolve(undefined);
                                            })
                                            .catch(() => {
                                                reject();
                                            });
                                    },
                                    () => {
                                        reject();
                                    },
                                );
                            });
                    });
                }

                return process;
            },
        );
    }

    public async inspectInterface(intf: ItemData, params: Object) {
        const intfName = intf['name'];
        const packageName = intf['pkg'];
        const itemPath = intf['itemPath'];

        if (this.shownPackage !== packageName || this.shownItem !== intfName) {
            await this._view?.webview.postMessage({ type: 'interface', obj: intf, params });
        }
        this.shownPackage = packageName;
        this.shownItem = intfName;

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: `${intfName}`,
                cancellable: false,
            },
            (progress, _token) => {
                progress.report({ message: 'Contacting OCP CAD Viewer...', increment: 10 });

                const process = new Promise((resolve, reject) => {
                    if (this._showResolve) {
                        this._showResolve(undefined);
                    }
                    this._showResolve = resolve;

                    // Find existing viewer;
                    let found = false;
                    const tabs: vscode.Tab[] = vscode.window.tabGroups.all.map((tg) => tg.tabs).flat();
                    for (var tab of tabs) {
                        if (tab.label === 'OCP CAD Viewer') {
                            found = true;
                            break;
                        }
                    }

                    if (!found) {
                        vscode.commands
                            .executeCommand('ocpCadViewer.ocpCadViewer')
                            .then(
                                () => {
                                    return new Promise((f) => setTimeout(f, 1700));
                                },
                                () => {
                                    reject();
                                },
                            )
                            .then(
                                () => {
                                    progress.report({ message: 'Inspecting the interface...', increment: 20 });
                                    return vscode.commands.executeCommand('partcad.showInterface', {
                                        pkg: packageName,
                                        name: intfName,
                                    });
                                },
                                () => {
                                    reject();
                                },
                            )
                            .then(
                                () => {
                                    // Wait for an outside call of this._showResolve()
                                },
                                () => {
                                    reject();
                                },
                            );
                    } else {
                        progress.report({ message: 'Inspecting the interface...', increment: 20 });
                        vscode.commands
                            .executeCommand('partcad.showInterface', { pkg: packageName, name: intfName, params })
                            .then(
                                () => {
                                    // Wait for an outside call of this._showResolve()
                                },
                                () => {
                                    reject();
                                },
                            );
                    }
                });

                if (itemPath !== undefined && packageName === '/') {
                    return new Promise((resolve, reject) => {
                        return vscode.commands
                            .executeCommand('vscode.openWith', vscode.Uri.file(itemPath), 'default', {
                                viewColumn: vscode.ViewColumn.One,
                                preview: true,
                            })
                            .then(() => {
                                return new Promise((f) => setTimeout(f, 1700)).then(
                                    () => {
                                        return process
                                            .then(() => {
                                                resolve(undefined);
                                            })
                                            .catch(() => {
                                                reject();
                                            });
                                    },
                                    () => {
                                        reject();
                                    },
                                );
                            });
                    });
                }

                return process;
            },
        );
    }

    public async inspectPart(part: ItemData, params: Object) {
        const partName = part['name'];
        const packageName = part['pkg'];
        const itemPath = part['itemPath'];

        if (this.shownPackage !== packageName || this.shownItem !== partName) {
            await this._view?.webview.postMessage({ type: 'part', obj: part, params });
        }
        this.shownPackage = packageName;
        this.shownItem = partName;

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: `${partName}`,
                cancellable: false,
            },
            (progress, _token) => {
                progress.report({ message: 'Contacting OCP CAD Viewer...', increment: 10 });

                const process = new Promise((resolve, reject) => {
                    if (this._showResolve) {
                        this._showResolve(undefined);
                    }
                    this._showResolve = resolve;

                    // Find existing viewer;
                    let found = false;
                    const tabs: vscode.Tab[] = vscode.window.tabGroups.all.map((tg) => tg.tabs).flat();
                    for (var tab of tabs) {
                        if (tab.label === 'OCP CAD Viewer') {
                            found = true;
                            break;
                        }
                    }

                    if (!found) {
                        vscode.commands
                            .executeCommand('ocpCadViewer.ocpCadViewer')
                            .then(
                                () => {
                                    return new Promise((f) => setTimeout(f, 1700));
                                },
                                () => {
                                    reject();
                                },
                            )
                            .then(
                                () => {
                                    progress.report({ message: 'Inspecting the part...', increment: 20 });
                                    return vscode.commands.executeCommand('partcad.showPart', {
                                        pkg: packageName,
                                        name: partName,
                                    });
                                },
                                () => {
                                    reject();
                                },
                            )
                            .then(
                                () => {
                                    // Wait for an outside call of this._showResolve()
                                },
                                () => {
                                    reject();
                                },
                            );
                    } else {
                        progress.report({ message: 'Inspecting the part...', increment: 20 });
                        vscode.commands
                            .executeCommand('partcad.showPart', { pkg: packageName, name: partName, params })
                            .then(
                                () => {
                                    // Wait for an outside call of this._showResolve()
                                },
                                () => {
                                    reject();
                                },
                            );
                    }
                });

                if (itemPath !== undefined && packageName === '/') {
                    return new Promise((resolve, reject) => {
                        return vscode.commands
                            .executeCommand('vscode.openWith', vscode.Uri.file(itemPath), 'default', {
                                viewColumn: vscode.ViewColumn.One,
                                preview: true,
                            })
                            .then(() => {
                                return new Promise((f) => setTimeout(f, 1700)).then(
                                    () => {
                                        return process
                                            .then(() => {
                                                resolve(undefined);
                                            })
                                            .catch(() => {
                                                reject();
                                            });
                                    },
                                    () => {
                                        reject();
                                    },
                                );
                            });
                    });
                }

                return process;
            },
        );
    }

    public async inspectAssembly(assembly: ItemData, params: Object) {
        const assemblyName = assembly['name'];
        const packageName = assembly['pkg'];
        const itemPath = assembly['itemPath'];

        if (this.shownPackage !== packageName || this.shownItem !== assemblyName) {
            await this._view?.webview.postMessage({ type: 'assembly', obj: assembly, params });
        }
        this.shownPackage = packageName;
        this.shownItem = assemblyName;

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: `${assemblyName}`,
                cancellable: false,
            },
            (progress, _token) => {
                progress.report({ message: 'Contacting OCP CAD Viewer...', increment: 10 });

                const process = new Promise((resolve, reject) => {
                    if (this._showResolve) {
                        this._showResolve(undefined);
                    }
                    this._showResolve = resolve;

                    // Find existing viewer;
                    let found = false;
                    const tabs: vscode.Tab[] = vscode.window.tabGroups.all.map((tg) => tg.tabs).flat();
                    for (var tab of tabs) {
                        if (tab.label === 'OCP CAD Viewer') {
                            found = true;
                            break;
                        }
                    }

                    if (!found) {
                        vscode.commands
                            .executeCommand('ocpCadViewer.ocpCadViewer')
                            .then(
                                () => {
                                    return new Promise((f) => setTimeout(f, 700));
                                },
                                () => {
                                    reject();
                                },
                            )
                            .then(
                                () => {
                                    progress.report({ message: 'Inspecting the assembly...', increment: 20 });
                                    return vscode.commands.executeCommand('partcad.showAssembly', {
                                        pkg: packageName,
                                        name: assemblyName,
                                    });
                                },
                                () => {
                                    reject();
                                },
                            )
                            .then(
                                () => {
                                    // Wait for an outside call of this._showResolve()
                                },
                                () => {
                                    reject();
                                },
                            );
                    } else {
                        progress.report({ message: 'Inspecting the assembly...', increment: 20 });
                        vscode.commands
                            .executeCommand('partcad.showAssembly', { pkg: packageName, name: assemblyName, params })
                            .then(
                                () => {
                                    // Wait for an outside call of this._showResolve()
                                },
                                () => {
                                    reject();
                                },
                            );
                    }
                });

                if (itemPath !== undefined && packageName === '/') {
                    return new Promise((resolve, reject) => {
                        return vscode.commands
                            .executeCommand('vscode.openWith', vscode.Uri.file(itemPath), 'default', {
                                viewColumn: vscode.ViewColumn.One,
                                preview: true,
                            })
                            .then(() => {
                                return new Promise((f) => setTimeout(f, 700)).then(
                                    () => {
                                        return process
                                            .then(() => {
                                                resolve(undefined);
                                            })
                                            .catch(() => {
                                                reject();
                                            });
                                    },
                                    () => {
                                        reject();
                                    },
                                );
                            });
                    });
                }

                return process;
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
