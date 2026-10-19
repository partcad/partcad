//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The MCP servers this extension offers the editor: which ones, and what each
// one runs.
//

import * as assert from 'assert';
import * as vscode from 'vscode';

import { MCP_PROVIDER_ID, mcpServerCommands } from '../../common/mcp';

const EXTENSION_ID = 'partcad.partcad-official';

const PC = process.platform === 'win32' ? 'C:\\PartCAD\\0.8.220\\pc.exe' : '/opt/partcad/0.8.220/pc';

suite('MCP servers', () => {
    test('the provider is contributed under the id it registers', () => {
        // A provider registered under an id the manifest does not contribute is
        // refused by the editor, with nothing else in the extension noticing.
        const extension = vscode.extensions.getExtension(EXTENSION_ID);
        assert.ok(extension, `${EXTENSION_ID} is not installed`);
        const providers = extension.packageJSON.contributes.mcpServerDefinitionProviders;
        assert.deepStrictEqual(
            providers.map((provider: { id: string }) => provider.id),
            [MCP_PROVIDER_ID],
        );
    });

    test('a package folder gets `pc -p <folder> mcp`, started in that folder', () => {
        const folder = { name: 'widget', fsPath: '/work/widget', isPackage: true };
        assert.deepStrictEqual(mcpServerCommands(PC, [folder]), [
            { label: 'PartCAD', command: PC, args: ['-p', '/work/widget', 'mcp'], cwd: '/work/widget' },
        ]);
    });

    test('a folder that is not a package gets none', () => {
        assert.deepStrictEqual(mcpServerCommands(PC, [{ name: 'notes', fsPath: '/work/notes', isPackage: false }]), []);
    });

    test('nothing is offered before PartCAD is installed', () => {
        assert.deepStrictEqual(mcpServerCommands(undefined, [{ name: 'w', fsPath: '/work/w', isPackage: true }]), []);
    });

    test('several packages get one server each, told apart by their folder', () => {
        const servers = mcpServerCommands(PC, [
            { name: 'robot', fsPath: '/work/robot', isPackage: true },
            { name: 'docs', fsPath: '/work/docs', isPackage: false },
            { name: 'gripper', fsPath: '/work/gripper', isPackage: true },
        ]);
        assert.deepStrictEqual(
            servers.map((server) => [server.label, server.args[1]]),
            [
                ['PartCAD (robot)', '/work/robot'],
                ['PartCAD (gripper)', '/work/gripper'],
            ],
        );
    });
});
