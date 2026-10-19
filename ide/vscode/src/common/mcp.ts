//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The PartCAD MCP server, `pc mcp`, offered to the editor's own agent.
//
// VS Code runs MCP servers for its chat (and for any extension that asks), and
// an extension can contribute them: a provider lists server definitions, and
// the editor starts, trusts and stops them like the ones a user configured by
// hand. So an editor with this extension installed has PartCAD's server
// without anyone writing a `.vscode/mcp.json` -- and with the `pc` this
// extension resolved or downloaded, which a hand-written one cannot name.
//
// Nothing about the server is here. It is `pc mcp`, run beside the service
// this extension already found (`toolsDirectory`, the directory it puts on the
// terminal PATH), and everything it does is in `partcad_client.mcp_server`.
//

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

import { traceInfo } from './log/logging';
import { toolsDirectory } from './terminalPath';

/** The provider's id; `contributes.mcpServerDefinitionProviders` names the same one. */
export const MCP_PROVIDER_ID = 'partcad.mcpServers';

/** `pc` as the filesystem spells it. */
const CLI = process.platform === 'win32' ? 'pc.exe' : 'pc';

/** What one server definition says, before it becomes the editor's object. */
export interface McpServerCommand {
    label: string;
    command: string;
    args: string[];
    cwd: string;
}

/**
 * One server per workspace folder that is a PartCAD package: `pc -p <folder> mcp`.
 *
 * A pure function of what was resolved and what is open, so that a test can
 * ask what would be offered without an editor that has the MCP API. Per folder
 * rather than one for the window, because `pc mcp` serves one workspace and
 * confines an agent's files to it: a server for the first folder would answer
 * questions about the second with the first one's package. A folder that is not
 * a package gets none -- an agent offered a PartCAD server there has nothing to
 * use it on.
 */
export function mcpServerCommands(
    cli: string | undefined,
    folders: readonly { name: string; fsPath: string; isPackage: boolean }[],
): McpServerCommand[] {
    if (!cli) {
        return [];
    }
    const packages = folders.filter((folder) => folder.isPackage);
    return packages.map((folder) => ({
        label: packages.length > 1 ? `PartCAD (${folder.name})` : 'PartCAD',
        command: cli,
        args: ['-p', folder.fsPath, 'mcp'],
        cwd: folder.fsPath,
    }));
}

/** The `pc` beside the resolved service, or undefined when nothing is installed yet. */
function resolvedCli(context: vscode.ExtensionContext, serverId: string): string | undefined {
    const directory = toolsDirectory(context, serverId);
    const candidate = directory && path.join(directory, CLI);
    return candidate && fs.existsSync(candidate) ? candidate : undefined;
}

/**
 * Offer `pc mcp` to the editor; return what tells it the offer changed.
 *
 * Call the returned `refresh` whenever the `pc` it names can have moved -- the
 * same moments `refreshToolsPath` is called, for the same reason: `pc upgrade`
 * deletes the bundle a definition made yesterday points into.
 *
 * Called from `activateTrusted`, so nothing is offered in Restricted Mode,
 * where this extension starts nothing else either: the server runs the code a
 * package's parts are written in, and the editor would otherwise offer to start
 * it in a folder the user has not trusted.
 */
export function registerMcpServers(context: vscode.ExtensionContext, serverId: string): { refresh: () => void } {
    // Feature-detected as well as required by `engines`: a fork of VS Code
    // reports the version it was forked from, and an extension host that
    // reports 1.101 need not implement every API 1.101 has. Such an editor
    // must still get every other thing this extension does.
    if (typeof vscode.lm?.registerMcpServerDefinitionProvider !== 'function') {
        traceInfo('PartCAD: this editor has no MCP API; not offering the PartCAD MCP server');
        return { refresh: () => undefined };
    }

    const changed = new vscode.EventEmitter<void>();
    const refresh = () => changed.fire();
    const watcher = vscode.workspace.createFileSystemWatcher('**/partcad.yaml', false, true, false);

    context.subscriptions.push(
        changed,
        watcher,
        watcher.onDidCreate(refresh),
        watcher.onDidDelete(refresh),
        vscode.workspace.onDidChangeWorkspaceFolders(refresh),
        vscode.lm.registerMcpServerDefinitionProvider(MCP_PROVIDER_ID, {
            onDidChangeMcpServerDefinitions: changed.event,
            provideMcpServerDefinitions: () => {
                const folders = (vscode.workspace.workspaceFolders ?? []).map((folder) => ({
                    name: folder.name,
                    fsPath: folder.uri.fsPath,
                    isPackage: fs.existsSync(path.join(folder.uri.fsPath, 'partcad.yaml')),
                }));
                return mcpServerCommands(resolvedCli(context, serverId), folders).map((server) => {
                    const definition = new vscode.McpStdioServerDefinition(server.label, server.command, server.args);
                    definition.cwd = vscode.Uri.file(server.cwd);
                    return definition;
                });
            },
        }),
    );
    return { refresh };
}
