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

/**
 * How a line reaches the `PartCAD` terminal view.
 *
 * Everything the user sees in that view arrives over the backend's
 * `?/partcad/terminal` and `?/partcad/log` notifications, which means nothing
 * can be reported there when the backend is what failed -- and "no PartCAD
 * service available" is exactly that case. It went to the output channel, which
 * nobody has open.
 *
 * The writer itself stays in `extension.ts`, because reopening a closed terminal
 * and popping it to the front need the terminal, the extension context and two
 * settings. This is only the registration, so that a module with none of those
 * (`common/backend.ts`) can report to the user without importing `extension.ts`
 * and forming an import cycle.
 */
type TerminalWriter = (text: string) => void;

let writer: TerminalWriter | undefined;

/** Called once by `activate`, with the terminal in place. */
export function setTerminalWriter(fn: TerminalWriter | undefined): void {
    writer = fn;
}

/**
 * Write to the `PartCAD` terminal view. Lines must end in `\r\n`: this is a
 * pseudoterminal, and a bare `\n` moves down a row without returning to column
 * one, so the next line starts wherever the last one ended.
 *
 * A no-op before `activate` has created the terminal; the caller has nowhere to
 * put the text in that window, and the output channel still has it.
 */
export function writeTerminal(text: string): void {
    writer?.(text);
}

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
