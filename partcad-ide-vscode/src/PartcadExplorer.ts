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
    packages: PartConfig[];
    sketches: PartConfig[];
    interfaces: PartConfig[];
    parts: PartConfig[];
    assemblies: PartConfig[];
};

export class PartcadExplorer implements vscode.TreeDataProvider<PartcadItem> {
    public static readonly viewType = 'partcadExplorer';

    packages: { [name: string]: ItemMetadata };
    // currentItemType: string;
    // currentItemName: string;
    // currentItemPackage: string;
    // currentItemParams: { [id: string]: string };

    constructor() {
        this.packages = {
            ['/']: {
                name: '/',
                packages: [],
                sketches: [],
                interfaces: [],
                parts: [],
                assemblies: [],
            },
        };

        // this.currentItemType = 'none';
        // this.currentItemName = 'this';
        // this.currentItemPackage = 'this';
        // this.currentItemParams = {};

        vscode.commands.registerCommand('partcad.inspectSource', (item) => this.inspectSource(item));
        vscode.commands.registerCommand('partcad.regeneratePart', (item) => this.regeneratePart(item));
        vscode.commands.registerCommand('partcad.changePart', (item) => this.changePart(item));
    }

    // public async inspectPart(item: PartcadItem) {
    //     this.currentItemType = ITEM_TYPE_PART;
    //     this.currentItemName = item.name;
    //     this.currentItemPackage = item.pkg;
    //     this.currentItemParams = item.params;
    //     await vscode.commands.executeCommand('setContext', 'partcad.itemSelected', true);
    //     await partcadInspector?.inspectPackage(pkg);
    //     await vscode.commands.executeCommand('partcad.getStats');
    // }

    public async inspectSource(item: PartcadItem) {
        if (item.itemPath !== undefined) {
            await vscode.commands.executeCommand(
                'vscode.openWith',
                vscode.Uri.file(item.itemPath),
                'default',
                vscode.ViewColumn.One,
            );
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
        this.packages = {
            ['/']: {
                name: '/',
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

    expandItems(items: ItemMetadata): PartcadItem[] {
        const elements: PartcadItem[] = [];

        items.packages = items.packages.sort((i1, i2) => {
            return i1['name'].localeCompare(i2['name']);
        });
        for (const pkg of items.packages) {
            elements.push(new PartcadItem(pkg.name, items.name, pkg, undefined, ITEM_TYPE_PACKAGE));
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
            elements.push(new PartcadItem(assembly.name, items.name, assembly, filepath, ITEM_TYPE_ASSEMBLY));
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
            elements.push(new PartcadItem(part.name, items.name, part, filepath, ITEM_TYPE_PART));
        }

        items.interfaces = items.interfaces.sort((i1, i2) => {
            return i1['name'].localeCompare(i2['name']);
        });
        for (const intf of items.interfaces) {
            elements.push(new PartcadItem(intf.name, items.name, intf, undefined, ITEM_TYPE_INTERFACE));
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
            elements.push(new PartcadItem(sketch.name, items.name, sketch, filepath, ITEM_TYPE_SKETCH));
        }

        return elements;
    }

    getChildren(element?: PartcadItem): Thenable<PartcadItem[]> {
        if (element) {
            if (element.name in this.packages) {
                return Promise.resolve(this.expandItems(this.packages[element.name]));
            } else {
                return this.getPackageContents(element.name);
            }
        }

        return Promise.resolve(this.expandItems(this.packages['/']));
    }

    private _onDidChangeTreeData: vscode.EventEmitter<PartcadItem | undefined | null> = new vscode.EventEmitter<
        PartcadItem | undefined | null
    >();
    readonly onDidChangeTreeData: vscode.Event<PartcadItem | undefined | null> = this._onDidChangeTreeData.event;

    refresh(): void {
        this._onDidChangeTreeData.fire(undefined);
    }

    public async exportItem(
        exportType: string,
        displayString: string,
        fileExt: string,
        itemType: string,
        itemPkg: string,
        itemName: string,
        params: Object,
    ) {
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

                    let filters: { [name: string]: string[] } = {};
                    filters[displayString] = [fileExt];
                    vscode.window
                        .showSaveDialog({
                            title: 'Select the filename for the new script',
                            filters: filters,
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
