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

        if (itemType === ITEM_TYPE_PACKAGE) {
            this.iconPath = {
                light: path.join(__filename, '..', '..', 'resources', 'light', 'file-submodule.svg'),
                dark: path.join(__filename, '..', '..', 'resources', 'dark', 'file-submodule.svg'),
            };
            this.contextValue = itemPath === undefined ? 'package' : 'packageWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectPackage',
                arguments: [
                    { name, pkg, config, itemPath },
                    {
                        /*params*/
                    },
                ],
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
                arguments: [
                    { name, pkg, config, itemPath },
                    {
                        /*params*/
                    },
                ],
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
                arguments: [
                    { name, pkg, config, itemPath },
                    {
                        /*params*/
                    },
                ],
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
                arguments: [
                    { name, pkg, config, itemPath },
                    {
                        /*params*/
                    },
                ],
            };
        } else {
            if (config.type === 'alias') {
                this.iconPath = {
                    light: path.join(__filename, '..', '..', 'resources', 'light', 'file-symlink-file.svg'),
                    dark: path.join(__filename, '..', '..', 'resources', 'dark', 'file-symlink-file.svg'),
                };
            } else {
                this.iconPath = {
                    light: path.join(__filename, '..', '..', 'resources', 'light', 'file-binary.svg'),
                    dark: path.join(__filename, '..', '..', 'resources', 'dark', 'file-binary.svg'),
                };
            }
            this.contextValue = config.type.startsWith('ai-')
                ? 'partWithAI'
                : itemPath === undefined
                  ? 'part'
                  : 'partWithCode';
            this.command = {
                title: 'Inspect',
                command: 'partcad.inspectPart',
                arguments: [
                    { name, pkg, config, itemPath },
                    {
                        /*params*/
                    },
                ],
            };
        }
    }
}
