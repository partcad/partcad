//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The folder each terminal's window has open, as `pc init` is told it: one value
// per workspace folder, in a collection scoped to that folder, and taken away
// with the folder.
//

import * as assert from 'assert';
import * as path from 'path';
import * as vscode from 'vscode';

import {
    advertiseWorkspaceFolders,
    WORKSPACE_FOLDER_ENV,
    workspaceFolderOf,
    workspaceFolderValue,
} from '../../common/workspaceFolderEnv';

/** What one folder's scoped collection was told, in order. */
class ScopedCollection {
    public readonly calls: string[] = [];
    public readonly options: (vscode.EnvironmentVariableMutatorOptions | undefined)[] = [];
    public description: string | vscode.MarkdownString | undefined;

    replace(variable: string, value: string, options?: vscode.EnvironmentVariableMutatorOptions): void {
        this.calls.push(`replace ${variable}=${value}`);
        this.options.push(options);
    }
    delete(variable: string): void {
        this.calls.push(`delete ${variable}`);
    }
    clear(): void {
        this.calls.push('clear');
    }
}

/** A global collection whose `getScoped` hands out one `ScopedCollection` per folder, by name. */
class ScopingCollection {
    public readonly scopes = new Map<string, ScopedCollection>();
    public readonly globalCalls: string[] = [];

    getScoped(scope: vscode.EnvironmentVariableScope): ScopedCollection {
        const name = scope.workspaceFolder?.name ?? '<global>';
        if (!this.scopes.has(name)) {
            this.scopes.set(name, new ScopedCollection());
        }
        return this.scopes.get(name)!;
    }
    replace(variable: string, value: string): void {
        this.globalCalls.push(`replace ${variable}=${value}`);
    }
}

function folder(name: string, uri: vscode.Uri, index = 0): vscode.WorkspaceFolder {
    return { name, uri, index };
}

function advertise(
    collection: ScopingCollection,
    added: vscode.WorkspaceFolder[],
    removed: vscode.WorkspaceFolder[] = [],
) {
    advertiseWorkspaceFolders(collection as unknown as vscode.GlobalEnvironmentVariableCollection, added, removed);
}

suite('Workspace folder for pc init', () => {
    const robot = folder('robot', vscode.Uri.file(path.resolve('/work/robot')));
    const jigs = folder('jigs', vscode.Uri.file(path.resolve('/work/jigs')), 1);

    test('the variable is the one PartCAD reads', () => {
        // `partcad_utils.agent_config.WORKSPACE_FOLDER_ENV`; there is nothing to
        // import across the two languages, so the name is stated in both.
        assert.strictEqual(WORKSPACE_FOLDER_ENV, 'PARTCAD_WORKSPACE_FOLDER');
    });

    test('each folder of a multi-root workspace tells its own terminals its own path', () => {
        const collection = new ScopingCollection();

        advertise(collection, [robot, jigs]);

        assert.deepStrictEqual(collection.scopes.get('robot')!.calls, [
            `replace PARTCAD_WORKSPACE_FOLDER=${robot.uri.fsPath}`,
        ]);
        assert.deepStrictEqual(collection.scopes.get('jigs')!.calls, [
            `replace PARTCAD_WORKSPACE_FOLDER=${jigs.uri.fsPath}`,
        ]);
        // Never the window-wide collection: one value there would be wrong for
        // every folder but one.
        assert.deepStrictEqual(collection.globalCalls, []);
        assert.strictEqual(collection.scopes.get('robot')!.options[0]?.applyAtProcessCreation, true);
    });

    test('a folder taken out of the workspace takes its value with it', () => {
        const collection = new ScopingCollection();
        advertise(collection, [robot, jigs]);

        advertise(collection, [], [jigs]);

        assert.deepStrictEqual(collection.scopes.get('jigs')!.calls.slice(-1), ['clear']);
        assert.strictEqual(collection.scopes.get('robot')!.calls.length, 1);
    });

    test('a folder that is not on disk is told nothing', () => {
        const collection = new ScopingCollection();
        const virtual = folder('remote', vscode.Uri.parse('vscode-vfs://github/partcad/partcad'));

        advertise(collection, [virtual]);

        assert.strictEqual(workspaceFolderValue(virtual), undefined);
        assert.deepStrictEqual(collection.scopes.get('remote')!.calls, ['delete PARTCAD_WORKSPACE_FOLDER']);
    });

    test('the daemon is told the folder a new package is in, and nothing for one outside every folder', () => {
        const open = vscode.workspace.workspaceFolders?.[0];
        assert.ok(open, 'the tests run with a workspace open');

        assert.strictEqual(workspaceFolderOf(path.join(open.uri.fsPath, 'packages', 'robot')), open.uri.fsPath);
        assert.strictEqual(workspaceFolderOf(path.resolve('/nowhere/near/it')), undefined);
        assert.strictEqual(workspaceFolderOf(''), undefined);
    });
});
