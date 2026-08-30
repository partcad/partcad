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
    ITEM_TYPE_NONE,
    ITEM_TYPE_ASSEMBLY,
    ITEM_TYPE_PACKAGE,
    ITEM_TYPE_SCENE,
    ITEM_TYPE_SKETCH,
    ITEM_TYPE_INTERFACE,
    ITEM_TYPE_PART,
    ITEM_TYPE_SOFTWARE,
    ITEM_TYPE_BROKEN,
} from './PartcadItem';

/** An object the package declares that PartCAD could not create, and why. */
type BrokenItem = { kind: string; name: string; reason: string };

type ItemMetadata = {
    name: string;
    dir: string | undefined;
    packages: PartConfig[];
    sketches: PartConfig[];
    interfaces: PartConfig[];
    parts: PartConfig[];
    assemblies: PartConfig[];
    // Optional: an older PartCAD service does not report any of these.
    scenes?: PartConfig[];
    software?: PartConfig[];
    broken?: BrokenItem[];
};

/** The ASSY files an .assy-typed object of one kind points at. */
function assyPaths(items: PartConfig[] | undefined): string[] {
    return (items ?? [])
        .filter((item) => item.type === 'assy' && item.item_path !== undefined)
        .map((item) => item.item_path as string);
}

export class PartcadExplorer implements vscode.TreeDataProvider<PartcadItem> {
    public static readonly viewType = 'partcadExplorer';

    packages: { [name: string]: ItemMetadata };
    root: string;

    constructor() {
        let wsUri = undefined;
        if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
            wsUri = vscode.workspace.workspaceFolders[0].uri;
        }

        this.root = '//';
        this.packages = {};

        vscode.commands.registerCommand('partcad.inspectSource', (item) => this.inspectSource(item));

        vscode.commands.registerCommand(`partcad.exportToSVG`, (item) => this.exportToSVG(item));
        vscode.commands.registerCommand(`partcad.exportToPNG`, (item) => this.exportToPNG(item));
        vscode.commands.registerCommand(`partcad.exportToJPEG`, (item) => this.exportToJPEG(item));
        vscode.commands.registerCommand(`partcad.exportToSTEP`, (item) => this.exportToSTEP(item));
        vscode.commands.registerCommand(`partcad.exportToSTL`, (item) => this.exportToSTL(item));
        vscode.commands.registerCommand(`partcad.exportTo3MF`, (item) => this.exportTo3MF(item));
        vscode.commands.registerCommand(`partcad.exportToThreeJS`, (item) => this.exportToThreeJS(item));
        vscode.commands.registerCommand(`partcad.exportToOBJ`, (item) => this.exportToOBJ(item));
        vscode.commands.registerCommand(`partcad.exportToIGES`, (item) => this.exportToIGES(item));
        vscode.commands.registerCommand(`partcad.exportToGLTF`, (item) => this.exportToGLTF(item));
        vscode.commands.registerCommand(`partcad.exportToWorld`, (item) => this.exportToWorld(item));

        // One command per application rather than one that asks which: a context
        // menu is where the user says what they want, and a picker on top of a
        // menu is the same question twice.
        vscode.commands.registerCommand(`partcad.openInFreeCAD`, (item) => this.openWith('freecad', item));

        vscode.commands.registerCommand(`partcad.test`, (item) => this.test(item));

        vscode.commands.registerCommand(`partcad.addPartItem`, (item) => this.addPart(item));
        vscode.commands.registerCommand(`partcad.addAssemblyItem`, (item) => this.addAssembly(item));
        vscode.commands.registerCommand(`partcad.addSceneItem`, (item) => this.addScene(item));
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

    public async addPart(item: PartcadItem) {
        let packageName = this.root;
        if (item.itemType === ITEM_TYPE_PACKAGE) {
            packageName = item.name;
        } else if (item.itemType !== ITEM_TYPE_NONE) {
            packageName = item.pkg;
        }

        await vscode.commands.executeCommand('partcad.packagePath', {
            packageName: packageName,
            callback: 'partcad.addPart2',
        });
    }

    public async addAssembly(item: PartcadItem) {
        let packageName = this.root;
        if (item.itemType === ITEM_TYPE_PACKAGE) {
            packageName = item.name;
        } else if (item.itemType !== ITEM_TYPE_NONE) {
            packageName = item.pkg;
        }

        await vscode.commands.executeCommand('partcad.packagePath', {
            packageName: packageName,
            callback: 'partcad.addAssembly2',
        });
    }

    public async addScene(item: PartcadItem) {
        let packageName = this.root;
        if (item.itemType === ITEM_TYPE_PACKAGE) {
            packageName = item.name;
        } else if (item.itemType !== ITEM_TYPE_NONE) {
            packageName = item.pkg;
        }

        await vscode.commands.executeCommand('partcad.packagePath', {
            packageName: packageName,
            callback: 'partcad.addScene2',
        });
    }

    /**
     * Open the file a part or an assembly is defined by in a third-party CAD
     * application ("Open in..." in the context menu).
     *
     * It is the item's own source file that is handed over, not a rendering of
     * it: rendering is the daemon's work, and this deliberately has none in it.
     * `pc open` runs on the machine the user is sitting at, finds a locally
     * installed application or (when the setting allows it) a container, and
     * says what to install when it can find neither -- which is why the failure
     * is shown as it comes back rather than summarised.
     */
    public async openWith(tool: string, item: PartcadItem) {
        // `config.item_path` rather than `itemPath`: the latter is set only for
        // the types this editor can edit (scripts), and a STEP or BREP part --
        // exactly what another CAD application is for -- is not one of them.
        const path = item?.config?.item_path ?? item?.itemPath;
        if (path === undefined) {
            await vscode.window.showWarningMessage(
                `'${item?.name}' has no file of its own to open in another application.`,
            );
            return;
        }
        try {
            // Under a progress notification because the first open of a
            // containerised application downloads its image, which takes
            // minutes and would otherwise look like nothing happening.
            await vscode.window.withProgress(
                { location: vscode.ProgressLocation.Notification, title: `${item.name}`, cancellable: false },
                async (progress) => {
                    progress.report({ message: 'Opening...' });
                    await vscode.commands.executeCommand('partcad.openExternal', { path: path, tool: tool });
                },
            );
        } catch (e) {
            const reason = e instanceof Error ? e.message : `${e}`;
            await vscode.window.showErrorMessage(`Could not open '${item.name}'`, { modal: false, detail: reason });
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

    clearItems() {
        let wsUri = undefined;
        if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
            wsUri = vscode.workspace.workspaceFolders[0].uri;
        }

        // Keep 'this.root' as is?
        this.packages = {};
        this.refresh();
    }

    setRoot(root: string) {
        this.root = root;
        this.refresh();
    }

    setItems(name: string, items: ItemMetadata) {
        this.packages[name] = items;
        this.refresh();
    }

    /**
     * Which ASSY files the loaded packages say are scenes, and which assemblies.
     *
     * What the ASSY linter needs in order to pick a schema: a file only a scene
     * points at is checked without `how`, and one an assembly points at is
     * checked in full (see `PartcadLint`). This is a plain read of the package
     * contents the tree already holds - the declaration itself, not a guess at
     * it - which is why the extension answers this rather than leaving the
     * client to work it out from the files on disk.
     *
     * Absent from both sets means "unknown", not "assembly": a package that has
     * not loaded reports nothing, and a scene inside it must not be reported as
     * a broken assembly in the meantime.
     */
    public assyFlavors(): { scenes: Set<string>; assemblies: Set<string> } {
        const scenes = new Set<string>();
        const assemblies = new Set<string>();
        for (const items of Object.values(this.packages)) {
            assyPaths(items.scenes).forEach((path) => scenes.add(path));
            assyPaths(items.assemblies).forEach((path) => assemblies.add(path));
        }
        return { scenes, assemblies };
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
            // The assembly types that *are* a file, so the tree can open one.
            if (assembly.type === 'assy' || assembly.type === 'urdf') {
                filepath = assembly.item_path;
            }
            elements.push(new PartcadItem(dir, assembly.name, items.name, assembly, filepath, ITEM_TYPE_ASSEMBLY));
        }

        const scenes = (items.scenes ?? []).slice().sort((i1, i2) => {
            if (i1.type === 'alias' && i2.type !== 'alias') {
                return 1;
            }
            if (i1.type !== 'alias' && i2.type === 'alias') {
                return -1;
            }
            return i1['name'].localeCompare(i2['name']);
        });
        for (const scene of scenes) {
            let filepath = undefined;
            // The scene types that *are* a file, so the tree can open one.
            if (scene.type === 'assy' || scene.type === 'world') {
                filepath = scene.item_path;
            }
            elements.push(new PartcadItem(dir, scene.name, items.name, scene, filepath, ITEM_TYPE_SCENE));
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
                part.type === 'chili3d' ||
                part.type === 'scad'
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

        // After the geometry, because software is what the product ships with
        // rather than what it is shaped like. No alias-last ordering as above:
        // software has no alias type to sort behind the rest.
        const software = (items.software ?? []).slice().sort((i1, i2) => i1['name'].localeCompare(i2['name']));
        for (const item of software) {
            // 'item_path' of a software object is the file itself - a firmware
            // image, a disk image, a binary - and not source anyone edits, so it
            // is not handed over as a file to open. The inspector shows it as
            // the path it is.
            elements.push(new PartcadItem(dir, item.name, items.name, item, undefined, ITEM_TYPE_SOFTWARE));
        }

        // Last, so they never push the working objects out of view, and sorted
        // so the listing is stable between refreshes.
        const broken = (items.broken ?? []).slice().sort((i1, i2) => i1.name.localeCompare(i2.name));
        for (const item of broken) {
            elements.push(
                new PartcadItem(
                    dir,
                    item.name,
                    items.name,
                    { name: item.name, type: item.kind, desc: item.reason },
                    undefined,
                    ITEM_TYPE_BROKEN,
                ),
            );
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

        if (!(this.root in this.packages)) {
            return Promise.resolve([]);
        }

        return Promise.resolve(this.expandItems(this.packages[this.root].dir, this.packages[this.root]));
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

    public async exportToJPEG(item: PartcadItem) {
        await this.doExportItem('jpeg', 'JPEG files', 'jpg', item);
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

    /** Write a scene out as a Gazebo world (SDFormat) plus its mesh files. */
    public async exportToWorld(item: PartcadItem) {
        await this.doExportItem('world', 'Gazebo world files', 'world', item);
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
                                } else if (itemType === ITEM_TYPE_SCENE) {
                                    return vscode.commands.executeCommand(
                                        'partcad.exportScene',
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
