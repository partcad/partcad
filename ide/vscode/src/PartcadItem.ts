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
                light: path.join(__filename, '..', '..', 'resources', 'light', 'file-submodule.svg'),
                dark: path.join(__filename, '..', '..', 'resources', 'dark', 'file-submodule.svg'),
            };
            this.contextValue = itemPath === undefined ? 'package' : 'packageWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectPackage',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else if (itemType === ITEM_TYPE_SKETCH) {
            this.iconPath = {
                light: path.join(__filename, '..', '..', 'resources', 'light', 'misc.svg'),
                dark: path.join(__filename, '..', '..', 'resources', 'dark', 'misc.svg'),
            };
            this.contextValue = itemPath === undefined ? 'sketch' : 'sketchWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectSketch',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else if (itemType === ITEM_TYPE_INTERFACE) {
            this.iconPath = {
                light: path.join(__filename, '..', '..', 'resources', 'light', 'interface.svg'),
                dark: path.join(__filename, '..', '..', 'resources', 'dark', 'interface.svg'),
            };
            this.contextValue = itemPath === undefined ? 'interface' : 'interfaceWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectInterface',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else if (itemType === ITEM_TYPE_SCENE) {
            this.iconPath = {
                light: path.join(__filename, '..', '..', 'resources', 'light', 'globe.svg'),
                dark: path.join(__filename, '..', '..', 'resources', 'dark', 'globe.svg'),
            };
            this.contextValue = itemPath === undefined ? 'scene' : 'sceneWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectScene',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        } else if (itemType === ITEM_TYPE_ASSEMBLY) {
            this.iconPath = {
                light: path.join(__filename, '..', '..', 'resources', 'light', 'extensions.svg'),
                dark: path.join(__filename, '..', '..', 'resources', 'dark', 'extensions.svg'),
            };
            this.contextValue = itemPath === undefined ? 'assembly' : 'assemblyWithCode';
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
                light: path.join(__filename, '..', '..', 'resources', 'light', 'file-binary.svg'),
                dark: path.join(__filename, '..', '..', 'resources', 'dark', 'file-binary.svg'),
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
                    light: path.join(__filename, '..', '..', 'resources', 'light', 'file-symlink-file.svg'),
                    dark: path.join(__filename, '..', '..', 'resources', 'dark', 'file-symlink-file.svg'),
                };
            } else {
                this.iconPath = new vscode.ThemeIcon('database');
            }
            this.contextValue = itemPath === undefined ? 'part' : 'partWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectPart',
                arguments: [{ name, pkg, config, itemPath }, {/*params*/}],
            };
        }
    }
}
