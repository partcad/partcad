//
// PartCAD, 2024
//
// Author: Roman Kuzmenko
// Created: 2024-12-28
//
// Licensed under Apache License, Version 2.0.
//

import * as vscode from 'vscode';
import {
    PartcadItem,
    PartConfig,
    ITEM_TYPE_ASSEMBLY,
    ITEM_TYPE_PACKAGE,
    ITEM_TYPE_SKETCH,
    ITEM_TYPE_INTERFACE,
    ITEM_TYPE_PART,
} from './PartcadItem';

type ItemMetadata = {
    name: string;
    dir: string | undefined;
    packages: PartConfig[];
    sketches: PartConfig[];
    interfaces: PartConfig[];
    parts: PartConfig[];
    assemblies: PartConfig[];
};

export class PartcadExplorer implements vscode.TreeDataProvider<PartcadItem> {
    public static readonly viewType = 'partcadExplorer';

    packages: { [name: string]: ItemMetadata };

    constructor() {
        let wsUri = undefined;
        if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
            wsUri = vscode.workspace.workspaceFolders[0].uri;
        }
        this.packages = {
            ['//']: {
                name: '//',
                dir: wsUri?.fsPath,
                packages: [],
                sketches: [],
                interfaces: [],
                parts: [],
                assemblies: [],
            },
        };

        vscode.commands.registerCommand('partcad.inspectSource', (item) => this.inspectSource(item));
        vscode.commands.registerCommand('partcad.regeneratePart', (item) => this.regeneratePart(item));
        vscode.commands.registerCommand('partcad.changePart', (item) => this.changePart(item));

        vscode.commands.registerCommand(`partcad.exportToSVG`, (item) => this.exportToSVG(item));
        vscode.commands.registerCommand(`partcad.exportToPNG`, (item) => this.exportToPNG(item));
        vscode.commands.registerCommand(`partcad.exportToSTEP`, (item) => this.exportToSTEP(item));
        vscode.commands.registerCommand(`partcad.exportToSTL`, (item) => this.exportToSTL(item));
        vscode.commands.registerCommand(`partcad.exportTo3MF`, (item) => this.exportTo3MF(item));
        vscode.commands.registerCommand(`partcad.exportToThreeJS`, (item) => this.exportToThreeJS(item));
        vscode.commands.registerCommand(`partcad.exportToOBJ`, (item) => this.exportToOBJ(item));
        vscode.commands.registerCommand(`partcad.exportToIGES`, (item) => this.exportToIGES(item));
        vscode.commands.registerCommand(`partcad.exportToGLTF`, (item) => this.exportToGLTF(item));

        vscode.commands.registerCommand(`partcad.test`, (item) => this.test(item));
    }

    public async test(item: PartcadItem) {
        if (item.itemType === ITEM_TYPE_PACKAGE) {
            await vscode.commands.executeCommand('partcad.testReal', {
                packageName: item.name,
                objectName: '',
            });
        } else {
            await vscode.commands.executeCommand('partcad.testReal', {
                packageName: item.pkg,
                objectName: item.name,
            });
        }
    }

    public async inspectSource(item: PartcadItem) {
        if (item.itemPath !== undefined) {
            await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(item.itemPath), 'default', {
                viewColumn: vscode.ViewColumn.One,
                preview: true,
            });
            await vscode.commands.executeCommand('partcad.inspectFile', item.itemPath);
        }
    }

    public async regeneratePart(item: PartcadItem) {
        await vscode.commands.executeCommand('partcad.regeneratePartCb', { pkg: item.pkg, name: item.name });
    }

    public async changePart(item: PartcadItem) {
        await vscode.commands.executeCommand('partcad.changePartCb', { pkg: item.pkg, name: item.name });
    }

    clearItems() {
        let wsUri = undefined;
        if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
            wsUri = vscode.workspace.workspaceFolders[0].uri;
        }

        this.packages = {
            ['//']: {
                name: '//',
                dir: wsUri?.fsPath,
                packages: [],
                sketches: [],
                interfaces: [],
                parts: [],
                assemblies: [],
            },
        };
        this.refresh();
    }

    setItems(name: string, items: ItemMetadata) {
        this.packages[name] = items;
        this.refresh();
    }

    getTreeItem(element: PartcadItem): vscode.TreeItem {
        return element;
    }

    async getPackageContents(name: string): Promise<PartcadItem[]> {
        const elements: PartcadItem[] = [];

        await vscode.commands.executeCommand('partcad.loadPackageContents', name);

        return elements;
    }

    expandItems(dir: string | undefined, items: ItemMetadata): PartcadItem[] {
        const elements: PartcadItem[] = [];

        items.packages = items.packages.sort((i1, i2) => {
            return i1['name'].localeCompare(i2['name']);
        });
        for (const pkg of items.packages) {
            let filepath = undefined;
            if (pkg.item_path !== undefined) {
                filepath = pkg.item_path;
            }
            elements.push(new PartcadItem(dir, pkg.name, items.name, pkg, filepath, ITEM_TYPE_PACKAGE));
        }

        items.assemblies = items.assemblies.sort((i1, i2) => {
            if (i1.type === 'alias' && i2.type !== 'alias') {
                return 1;
            }
            if (i1.type !== 'alias' && i2.type === 'alias') {
                return -1;
            }
            return i1['name'].localeCompare(i2['name']);
        });
        for (const assembly of items.assemblies) {
            let filepath = undefined;
            if (assembly.type === 'assy') {
                filepath = assembly.item_path;
            }
            elements.push(new PartcadItem(dir, assembly.name, items.name, assembly, filepath, ITEM_TYPE_ASSEMBLY));
        }

        items.parts = items.parts.sort((i1, i2) => {
            if (i1.type === 'alias' && i2.type !== 'alias') {
                return 1;
            }
            if (i1.type !== 'alias' && i2.type === 'alias') {
                return -1;
            }
            return i1['name'].localeCompare(i2['name']);
        });
        for (const part of items.parts) {
            let filepath = undefined;
            if (
                part.type === 'cadquery' ||
                part.type === 'build123d' ||
                part.type === 'scad' ||
                part.type.startsWith('ai-')
            ) {
                filepath = part.item_path;
            }
            elements.push(new PartcadItem(dir, part.name, items.name, part, filepath, ITEM_TYPE_PART));
        }

        items.interfaces = items.interfaces.sort((i1, i2) => {
            return i1['name'].localeCompare(i2['name']);
        });
        for (const intf of items.interfaces) {
            elements.push(new PartcadItem(dir, intf.name, items.name, intf, undefined, ITEM_TYPE_INTERFACE));
        }

        items.sketches = items.sketches.sort((i1, i2) => {
            if (i1.type === 'alias' && i2.type !== 'alias') {
                return 1;
            }
            if (i1.type !== 'alias' && i2.type === 'alias') {
                return -1;
            }
            return i1['name'].localeCompare(i2['name']);
        });
        for (const sketch of items.sketches) {
            let filepath = undefined;
            if (sketch.type === 'dxf' || sketch.type === 'svg') {
                filepath = sketch.item_path;
            }
            elements.push(new PartcadItem(dir, sketch.name, items.name, sketch, filepath, ITEM_TYPE_SKETCH));
        }

        return elements;
    }

    getChildren(element?: PartcadItem): Thenable<PartcadItem[]> {
        if (element) {
            if (element.name in this.packages) {
                return Promise.resolve(this.expandItems(element.dir, this.packages[element.name]));
            } else {
                return this.getPackageContents(element.name);
            }
        }

        return Promise.resolve(this.expandItems(this.packages['//'].dir, this.packages['//']));
    }

    private _onDidChangeTreeData: vscode.EventEmitter<PartcadItem | undefined | null> = new vscode.EventEmitter<
        PartcadItem | undefined | null
    >();
    readonly onDidChangeTreeData: vscode.Event<PartcadItem | undefined | null> = this._onDidChangeTreeData.event;

    refresh(): void {
        this._onDidChangeTreeData.fire(undefined);
    }

    public async exportToSVG(item: PartcadItem) {
        await this.doExportItem('svg', 'SVG files', 'svg', item);
        await vscode.commands.executeCommand('partcad.getStats');
    }

    public async exportToPNG(item: PartcadItem) {
        await this.doExportItem('png', 'PNG files', 'png', item);
        await vscode.commands.executeCommand('partcad.getStats');
    }

    public async exportToSTEP(item: PartcadItem) {
        await this.doExportItem('step', 'STEP files', 'step', item);
        await vscode.commands.executeCommand('partcad.getStats');
    }

    public async exportToSTL(item: PartcadItem) {
        await this.doExportItem('stl', 'STL files', 'stl', item);
        await vscode.commands.executeCommand('partcad.getStats');
    }

    public async exportTo3MF(item: PartcadItem) {
        await this.doExportItem('3mf', '3MF files', '3mf', item);
        await vscode.commands.executeCommand('partcad.getStats');
    }

    public async exportToThreeJS(item: PartcadItem) {
        await this.doExportItem('threejs', 'ThreeJS files', 'json', item);
        await vscode.commands.executeCommand('partcad.getStats');
    }

    public async exportToOBJ(item: PartcadItem) {
        await this.doExportItem('obj', 'OBJ files', 'obj', item);
        await vscode.commands.executeCommand('partcad.getStats');
    }

    public async exportToIGES(item: PartcadItem) {
        await this.doExportItem('iges', 'IGES files', 'iges', item);
        await vscode.commands.executeCommand('partcad.getStats');
    }

    public async exportToGLTF(item: PartcadItem) {
        await this.doExportItem('gltf', 'glTF files', 'json', item);
        await vscode.commands.executeCommand('partcad.getStats');
    }

    public async doExportItem(exportType: string, displayString: string, fileExt: string, item: PartcadItem) {
        const itemType = item.itemType;
        const itemPkg = item.pkg;
        const itemName = item.name;
        const params = item.params;

        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: `${itemName}`,
                cancellable: false,
            },
            (progress, _token) => {
                progress.report({ message: 'Exporting...', increment: 10 });

                const process = new Promise((resolve, reject) => {
                    if (this._exportResolve) {
                        this._exportResolve(undefined);
                    }
                    this._exportResolve = resolve;

                    // TODO(clairbee): use the package path, instead of the workspace root

                    let uri = undefined;
                    if (item.dir) {
                        uri = vscode.Uri.file(item.dir);
                    }

                    let filters: { [name: string]: string[] } = {};
                    filters[displayString] = [fileExt];
                    vscode.window
                        .showSaveDialog({
                            title: 'Select the output filename',
                            filters: filters,
                            defaultUri: uri,
                        })
                        .then(
                            (uri: vscode.Uri | undefined) => {
                                if (!uri) {
                                    // Do NOT wait for an outside call of this._showResolve()
                                    reject();

                                    return new Promise((_resolve, reject) => {
                                        reject();
                                    });
                                }

                                const path = uri.fsPath;
                                if (itemType === ITEM_TYPE_PART) {
                                    return vscode.commands.executeCommand(
                                        'partcad.exportPart',
                                        exportType,
                                        path,
                                        itemPkg,
                                        itemName,
                                        params,
                                    );
                                } else if (itemType === ITEM_TYPE_ASSEMBLY) {
                                    return vscode.commands.executeCommand(
                                        'partcad.exportAssembly',
                                        exportType,
                                        path,
                                        itemPkg,
                                        itemName,
                                        params,
                                    );
                                } else {
                                    // Do NOT wait for an outside call of this._showResolve()
                                    reject();

                                    return new Promise((_resolve, reject) => {
                                        reject();
                                    });
                                }
                            },
                            () => {},
                        )
                        .then(
                            () => {
                                // Wait for an outside call of this._showResolve()
                            },
                            () => {
                                reject();
                            },
                        );
                });

                return process;
            },
        );
    }

    private _exportResolve?: (value: any) => void;

    /**
     * exportDone is called when lsp_server tells the extension that the show command is complete
     */
    public exportDone() {
        if (this._exportResolve) {
            this._exportResolve(undefined);
        }
    }
}
