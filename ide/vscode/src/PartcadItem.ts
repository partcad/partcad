//
// PartCAD, 2024
//
// Author: Roman Kuzmenko
// Created: 2024-12-28
//
// Licensed under Apache License, Version 2.0.
//

import * as vscode from 'vscode';
import * as path from 'path';

/**
 * An object type without the package that declares it.
 *
 * A file format a plugin package implements is written as a full resource path
 * -- `sim-gazebo:world`, `sim-mujoco:mjcf` -- because that is what resolves it,
 * and the engine scene formats are all of them now: PartCAD itself ships no
 * simulator and no simulator's scene format. The tree only ever asks *which
 * format* a scene is, never whose, so it compares the part after the last ':'.
 */
export function bareType(objectType: string | undefined): string {
    return (objectType ?? '').split(':').pop() ?? '';
}

/**
 * The 2D drawing formats an object can be held in: AutoCAD's two.
 *
 * A sketch PartCAD reads from a DXF is one, and so is a part or an assembly
 * whose type a plugin package implements for either format -- 'cadcraft:dwg',
 * 'cadcraft:dxf' -- which is why the type is compared bare. These are the
 * objects CADCraft, a drafting application, has anything to open: a solid
 * PartCAD would have to draw first, and an edit to a drawing of it would have
 * nowhere to go back to.
 */
export const DRAWING_TYPES = ['dwg', 'dxf'];

export function isDrawing(objectType: string | undefined): boolean {
    return DRAWING_TYPES.includes(bareType(objectType).toLowerCase());
}

/**
 * The sketch types PartCAD reads from a file, inlined from
 * `partcad.shape.SKETCH_EXTENSION_MAPPING`: every one of them is a sketch PartCAD
 * can draw as a DXF, and so one an application that opens drawings can be
 * handed -- as it is when it already is a DXF, and converted when it is an SVG
 * or a CadQuery or build123d script (`pc ide open --kind sketch`).
 */
export const CONVERTIBLE_SKETCH_TYPES = ['svg', 'dxf', 'cadquery', 'build123d'];

export const ITEM_TYPE_NONE = 'none';
export const ITEM_TYPE_PACKAGE = 'package';
export const ITEM_TYPE_SKETCH = 'sketch';
export const ITEM_TYPE_INTERFACE = 'interface';
export const ITEM_TYPE_PART = 'part';
export const ITEM_TYPE_ASSEMBLY = 'assembly';
export const ITEM_TYPE_SOFTWARE = 'software';
/**
 * A placed arrangement of objects - a workcell, a table, a simulation world.
 *
 * Built out of the very same files an assembly is, and every operation that
 * works on an assembly works on one; what separates them is that a scene states
 * only where things are, never how they got there. See `partcad.scene`.
 */
export const ITEM_TYPE_SCENE = 'scene';
/**
 * An object the package declares but PartCAD could not create.
 *
 * Shown rather than omitted: a package that lists nothing looks exactly like an
 * empty one, so silently dropping these leaves the user with no way to tell that
 * something is wrong, let alone what.
 */
export const ITEM_TYPE_BROKEN = 'broken';

// eslint-disable-next-line @typescript-eslint/naming-convention
export type PartConfig = { name: string; desc?: string; type: string; item_path?: string };

function shortenName(name: string, parentName: string): string {
    if (name.startsWith(parentName)) {
        name = name.substring(parentName.length);
        while (name.startsWith('/')) {
            name = name.substring(1);
        }
    }
    return name;
}

export class PartcadItem extends vscode.TreeItem {
    params: { [id: string]: string };

    constructor(
        public readonly dir: string | undefined,
        public readonly name: string,
        public pkg: string,
        public config: PartConfig,
        public itemPath: string | undefined,
        public itemType: string,
    ) {
        super(
            itemType === ITEM_TYPE_PACKAGE ? shortenName(name, pkg) : name,
            itemType === ITEM_TYPE_PACKAGE
                ? vscode.TreeItemCollapsibleState.Collapsed
                : vscode.TreeItemCollapsibleState.None,
        );
        this.params = {};
        this.config = config;
        if (itemType === ITEM_TYPE_PACKAGE) {
            this.tooltip = name;
            if (config.desc !== undefined && config.desc !== 'undefined') {
                this.tooltip += `\n${config.desc}`;
            }
        } else if (config.desc !== undefined && config.desc !== 'undefined') {
            this.tooltip = `${config.desc}`;
        }
        // this.description = `${config.desc}`;

        if (itemType === ITEM_TYPE_BROKEN) {
            // Themed rather than one of the bundled SVGs, so it reads as an
            // error in both light and dark themes without a second asset.
            this.iconPath = new vscode.ThemeIcon('warning', new vscode.ThemeColor('problemsWarningIcon.foreground'));
            // The reason is put in 'description' as well as the tooltip: it
            // shows greyed out next to the name, which is what makes the problem
            // visible without hovering over every row.
            this.description = config.desc;
            this.tooltip = `${name}\n\n${config.desc ?? 'This object could not be loaded.'}`;
            this.contextValue = 'brokenItem';
            this.command = {
                title: 'Why can this not be loaded?',
                command: 'partcad.showBrokenItem',
                arguments: [{ name, pkg, reason: config.desc }],
            };
        } else if (itemType === ITEM_TYPE_PACKAGE) {
            this.iconPath = {
                light: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'light', 'file-submodule.svg')),
                dark: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'dark', 'file-submodule.svg')),
            };
            this.contextValue = itemPath === undefined ? 'package' : 'packageWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectPackage',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else if (itemType === ITEM_TYPE_SKETCH) {
            this.iconPath = {
                light: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'light', 'misc.svg')),
                dark: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'dark', 'misc.svg')),
            };
            // Every sketch PartCAD reads from a file can be opened in an
            // application that opens drawings ("Open in > CADCraft"): a DXF as it
            // is, an SVG or a script converted into one. A DXF gets a value of its
            // own, as a 'kicad' part does below, and so does a script, which this
            // tree does not open for editing (no `itemPath`) but which still has a
            // file to convert; a sketch with no file of its own -- 'basic', an
            // alias -- has nothing to open and stays 'sketch'.
            if (itemPath !== undefined) {
                this.contextValue = isDrawing(config.type) ? 'sketchDrawing' : 'sketchWithCode';
            } else if (config?.item_path && CONVERTIBLE_SKETCH_TYPES.includes(bareType(config.type))) {
                this.contextValue = 'sketchScript';
            } else {
                this.contextValue = 'sketch';
            }
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectSketch',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else if (itemType === ITEM_TYPE_INTERFACE) {
            this.iconPath = {
                light: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'light', 'interface.svg')),
                dark: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'dark', 'interface.svg')),
            };
            this.contextValue = itemPath === undefined ? 'interface' : 'interfaceWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectInterface',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else if (itemType === ITEM_TYPE_SCENE) {
            this.iconPath = {
                light: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'light', 'globe.svg')),
                dark: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'dark', 'globe.svg')),
            };
            // A scene held in a simulator's own format gets a context value of
            // its own: those are the scenes another application can open,
            // because a '.world' file *is* what Gazebo reads and an MJCF model
            // *is* what MuJoCo reads. An ASSY scene is PartCAD's own format and
            // is nothing but references to the parts of a package, so there is
            // nothing to hand over. Only once there is a file, though - the
            // value is what puts "Open in > ..." and "Open source" on the row,
            // and neither has anything to act on without one.
            //
            // Each takes only its own format. Nothing converts between them
            // here: an engine's scene format is implemented by that engine's
            // plugin package, and `pc ide open` is handed a file with no package
            // around it to reach either implementation through.
            //
            // The type is compared bare, because a scene declares one of these
            // as 'sim-gazebo:world' or 'sim-mujoco:mjcf' -- through the package
            // that implements it, which is the only spelling that resolves.
            this.contextValue =
                itemPath === undefined
                    ? 'scene'
                    : bareType(config.type) === 'world'
                      ? 'sceneWorld'
                      : bareType(config.type) === 'mjcf'
                        ? 'sceneMjcf'
                        : 'sceneWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectScene',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else if (itemType === ITEM_TYPE_ASSEMBLY) {
            this.iconPath = {
                light: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'light', 'extensions.svg')),
                dark: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'dark', 'extensions.svg')),
            };
            // An assembly read from a drawing (an 'import:' reader for DWG or DXF)
            // is one CADCraft can be pointed at, so it is told apart like a
            // drawing sketch above and a drawing part below.
            this.contextValue =
                itemPath !== undefined ? 'assemblyWithCode' : isDrawing(config.type) ? 'assemblyDrawing' : 'assembly';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectAssembly',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else if (itemType === ITEM_TYPE_SOFTWARE) {
            // The icon parts used before they moved to 'database': software is a
            // file the package ships rather than geometry, which is what this
            // icon said about a part and says about software just as well.
            this.iconPath = {
                light: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'light', 'file-binary.svg')),
                dark: vscode.Uri.file(path.join(__filename, '..', '..', 'resources', 'dark', 'file-binary.svg')),
            };
            // No 'WithCode' variant: a software object's file is a firmware or
            // disk image rather than source, so the explorer hands over no path
            // for it and there is nothing for the 'Edit' actions to open.
            this.contextValue = 'software';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectSoftware',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else {
            if (config.type === 'alias') {
                this.iconPath = {
                    light: vscode.Uri.file(
                        path.join(__filename, '..', '..', 'resources', 'light', 'file-symlink-file.svg'),
                    ),
                    dark: vscode.Uri.file(
                        path.join(__filename, '..', '..', 'resources', 'dark', 'file-symlink-file.svg'),
                    ),
                };
            } else {
                this.iconPath = new vscode.ThemeIcon('database');
            }
            // As with a world scene above: a 'kicad' part is the one kind of
            // part KiCad can be pointed at, because the board it is generated
            // from is a file beside it (see the 'kicad' entry of 'builtin/open/partcad.yaml' and
            // 'partcad_client.external'). 'itemPath' stays undefined for it -
            // what the tree would open is the STEP KiCad writes, not source.
            //
            // A part read from a drawing ('cadcraft:dwg') is told apart the same
            // way, for CADCraft: what it is handed is the DWG or the DXF itself.
            this.contextValue =
                config.type === 'kicad'
                    ? 'partKicad'
                    : isDrawing(config.type)
                      ? 'partDrawing'
                      : itemPath === undefined
                        ? 'part'
                        : 'partWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectPart',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        }
    }
}
