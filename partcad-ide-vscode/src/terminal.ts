//
// PartCAD, 2025
//
// Author: Roman Kuzmenko
// Created: 2025-04-04
//
// Licensed under Apache License, Version 2.0.
//

import * as vscode from 'vscode';
import * as path from 'path';

export function terminalInit(
    context: vscode.ExtensionContext,
    terminalEmitter: vscode.EventEmitter<string>,
): vscode.Terminal {
    const defaultLine = 'Keep an eye on this Terminal View to know what PartCAD is busy with...\r\n';
    const pty = {
        onDidWrite: terminalEmitter.event,
        open: () => terminalEmitter?.fire(defaultLine),
        close: () => {},
        handleInput: async (_char: string) => {},
    };

    let partcadTerminal: vscode.Terminal = vscode.window.createTerminal({
        name: 'PartCAD',
        location: vscode.TerminalLocation.Panel,
        isTransient: true,
        pty: pty,
        iconPath: vscode.Uri.joinPath(context.extensionUri, 'resources', 'logo.svg'),
    });
    partcadTerminal.show(true);

    return partcadTerminal;
}
