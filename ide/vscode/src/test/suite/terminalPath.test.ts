//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The tools directory that goes on the terminal PATH: which directory is
// chosen, and what the collection is left holding after the events that can
// move it -- a first install, and an upgrade.
//

import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

import { refreshToolsPath, resetToolsPathForTesting, toolsDirectory } from '../../common/terminalPath';

const EXE = process.platform === 'win32' ? 'partcad-json-rpc.exe' : 'partcad-json-rpc';
const CLI = process.platform === 'win32' ? 'pc.exe' : 'pc';

/**
 * The calls `refreshToolsPath` makes, in order.
 *
 * Order is the point of two of the tests below: `prepend` appends to what the
 * collection already holds, so a refresh that forgets to clear leaves both the
 * old and the new directory on PATH.
 */
class RecordingCollection {
    public readonly calls: string[] = [];
    public persistent = true;
    public description: string | vscode.MarkdownString | undefined;

    clear(): void {
        this.calls.push('clear');
    }
    prepend(variable: string, value: string): void {
        this.calls.push(`prepend ${variable}=${value}`);
    }
    /** The rest of the interface, unused here but required by the type. */
    replace(): void {}
    append(): void {}
    get(): undefined {
        return undefined;
    }
    forEach(): void {}
    delete(): void {}
    getScoped(): any {
        return this;
    }
    [Symbol.iterator](): any {
        return [][Symbol.iterator]();
    }
}

/** An ExtensionContext with only what `refreshToolsPath` reaches for. */
function fakeContext(collection: RecordingCollection): vscode.ExtensionContext {
    return {
        environmentVariableCollection: collection,
        globalStorageUri: vscode.Uri.file(path.join(os.tmpdir(), 'partcad-test-storage')),
    } as unknown as vscode.ExtensionContext;
}

/** A directory laid out the way a standalone bundle is. */
function bundle(root: string, version: string): string {
    const dir = path.join(root, version);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, EXE), '');
    fs.writeFileSync(path.join(dir, CLI), '');
    return dir;
}

async function pointServicePathAt(exe: string | undefined): Promise<void> {
    await vscode.workspace
        .getConfiguration('partcad')
        .update('servicePath', exe ?? '', vscode.ConfigurationTarget.Global);
}

suite('Terminal PATH', () => {
    let tmp: string;

    setup(() => {
        resetToolsPathForTesting();
        tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-terminal-path-'));
    });

    teardown(async () => {
        resetToolsPathForTesting();
        await pointServicePathAt(undefined);
        fs.rmSync(tmp, { recursive: true, force: true });
    });

    // ---- which directory ---------------------------------------------------

    test('the directory is the one the resolved executable lives in', async () => {
        // One directory holds `pc`, `partcad` and `partcad-json-rpc` together,
        // which is why putting it on PATH covers all three entry points at once.
        const dir = bundle(tmp, '0.8.0');
        await pointServicePathAt(path.join(dir, EXE));

        assert.strictEqual(toolsDirectory(fakeContext(new RecordingCollection()), 'partcad'), dir);
        assert.ok(fs.existsSync(path.join(dir, CLI)), 'the same directory holds `pc`');
    });

    // ---- what the collection is left holding -------------------------------

    test('a first install puts the directory on PATH without a reload', async () => {
        // Activation runs before anything is installed and finds nothing; the
        // download that follows is what creates the directory. Missing that
        // second refresh is what left a terminal without `pc` until the next
        // window -- the bug this covers.
        const collection = new RecordingCollection();
        const context = fakeContext(collection);

        await pointServicePathAt(undefined);
        refreshToolsPath(context, 'partcad');
        assert.ok(
            !collection.calls.some((c) => c.startsWith('prepend')),
            'nothing is installed yet, so nothing goes on the PATH',
        );

        const dir = bundle(tmp, '0.8.0');
        await pointServicePathAt(path.join(dir, EXE));
        refreshToolsPath(context, 'partcad');

        assert.deepStrictEqual(
            collection.calls.filter((c) => c.startsWith('prepend')),
            [`prepend PATH=${dir}${path.delimiter}`],
        );
        assert.strictEqual(collection.persistent, false, 'a deleted bundle directory must not survive a reload');
    });

    test('an upgrade replaces the directory rather than stacking a second one', async () => {
        // `pc upgrade` installs beside the running bundle and deletes every
        // superseded one, so the directory moves. `prepend` appends to what the
        // collection holds, so a refresh that forgets to clear would leave the
        // deleted directory on PATH ahead of the new one.
        const collection = new RecordingCollection();
        const context = fakeContext(collection);

        const oldDir = bundle(tmp, '0.8.0');
        await pointServicePathAt(path.join(oldDir, EXE));
        refreshToolsPath(context, 'partcad');

        const newDir = bundle(tmp, '0.9.0');
        await pointServicePathAt(path.join(newDir, EXE));
        refreshToolsPath(context, 'partcad');

        assert.deepStrictEqual(
            collection.calls.filter((c) => c.startsWith('prepend')),
            [`prepend PATH=${oldDir}${path.delimiter}`, `prepend PATH=${newDir}${path.delimiter}`],
        );
        // Every prepend is preceded by a clear, so only the last one is live.
        const firstPrepend = collection.calls.findIndex((c) => c.startsWith('prepend'));
        const lastClear = collection.calls.lastIndexOf('clear');
        const lastPrepend = collection.calls.length - 1;
        assert.ok(firstPrepend > 0 && collection.calls[firstPrepend - 1] === 'clear');
        assert.strictEqual(lastClear, lastPrepend - 1, 'the final prepend follows a clear');
    });

    test('refreshing with an unchanged directory does not touch the collection', async () => {
        const dir = bundle(tmp, '0.8.0');
        await pointServicePathAt(path.join(dir, EXE));

        const collection = new RecordingCollection();
        const context = fakeContext(collection);
        refreshToolsPath(context, 'partcad');
        const after = collection.calls.length;

        refreshToolsPath(context, 'partcad');
        assert.strictEqual(collection.calls.length, after, 'a no-op refresh is a no-op');
    });
});
