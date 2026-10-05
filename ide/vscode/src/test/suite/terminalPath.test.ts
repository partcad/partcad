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

import {
    needsShellIntegrationWarning,
    refreshToolsPath,
    resetToolsPathForTesting,
    toolsDirectory,
    warnIfShellIntegrationOff,
} from '../../common/terminalPath';

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
    public readonly options: (vscode.EnvironmentVariableMutatorOptions | undefined)[] = [];
    public persistent = true;
    public description: string | vscode.MarkdownString | undefined;

    clear(): void {
        this.calls.push('clear');
    }
    prepend(variable: string, value: string, options?: vscode.EnvironmentVariableMutatorOptions): void {
        this.calls.push(`prepend ${variable}=${value}`);
        this.options.push(options);
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

    test("under the debugger the directory is the checkout's .venv, as for the service", async () => {
        // `restartBackend` runs `<checkout>/.venv/bin/partcad-json-rpc` when the
        // extension is debugged with Python attached. The PATH has to follow it:
        // looking the tools up the ordinary way found nothing in a dev container
        // and left the debug window's terminals without `pc`.
        const checkout = path.join(tmp, 'checkout');
        const venvBin = path.join(checkout, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin');
        fs.mkdirSync(venvBin, { recursive: true });
        fs.writeFileSync(path.join(venvBin, EXE), '');
        const context = {
            ...fakeContext(new RecordingCollection()),
            extensionMode: vscode.ExtensionMode.Development,
            extensionPath: path.join(checkout, 'ide', 'vscode'),
        } as unknown as vscode.ExtensionContext;
        await pointServicePathAt(undefined);

        const saved = process.env.PC_DEBUGPY;
        process.env.PC_DEBUGPY = 'localhost:5678';
        try {
            assert.strictEqual(toolsDirectory(context, 'partcad'), venvBin);
        } finally {
            if (saved === undefined) {
                delete process.env.PC_DEBUGPY;
            } else {
                process.env.PC_DEBUGPY = saved;
            }
        }
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

    test('the directory is put back after the shell has read its rc files', async () => {
        // Applied only at process creation, the prepend lands before `.zshrc`
        // runs, and `conda init` activating `base` there puts its own `bin`
        // -- with an older PartCAD's `pc` in it -- ahead of ours.
        const collection = new RecordingCollection();
        const dir = bundle(tmp, '0.8.0');
        await pointServicePathAt(path.join(dir, EXE));
        refreshToolsPath(fakeContext(collection), 'partcad');

        assert.deepStrictEqual(collection.options, [{ applyAtProcessCreation: true, applyAtShellIntegration: true }]);
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

    // ---- the warning when shell integration is off --------------------------

    /** A terminal as `onDidOpenTerminal` hands it over: a shell, or a pseudoterminal. */
    function terminal(options: vscode.TerminalOptions | vscode.ExtensionTerminalOptions = {}): vscode.Terminal {
        return { creationOptions: options } as unknown as vscode.Terminal;
    }

    async function setShellIntegration(enabled: boolean | undefined): Promise<void> {
        await vscode.workspace
            .getConfiguration('terminal.integrated.shellIntegration')
            .update('enabled', enabled, vscode.ConfigurationTarget.Global);
    }

    /** Put a bundle on the PATH, so there is something for an rc file to shadow. */
    async function applyBundle(): Promise<void> {
        const dir = bundle(tmp, '0.8.0');
        await pointServicePathAt(path.join(dir, EXE));
        refreshToolsPath(fakeContext(new RecordingCollection()), 'partcad');
    }

    test('a shell opened with shell integration off is warned about', async () => {
        await applyBundle();
        await setShellIntegration(false);
        try {
            assert.ok(needsShellIntegrationWarning(terminal(), 'partcad'));
        } finally {
            await setShellIntegration(undefined);
        }
    });

    test('no warning with shell integration on', async () => {
        await applyBundle();
        await setShellIntegration(true);
        try {
            assert.ok(!needsShellIntegrationWarning(terminal(), 'partcad'));
        } finally {
            await setShellIntegration(undefined);
        }
    });

    test('no warning for a pseudoterminal, which runs no shell', async () => {
        await applyBundle();
        await setShellIntegration(false);
        try {
            const pty = { onDidWrite: new vscode.EventEmitter<string>().event, open() {}, close() {} };
            assert.ok(!needsShellIntegrationWarning(terminal({ name: 'PartCAD', pty }), 'partcad'));
        } finally {
            await setShellIntegration(undefined);
        }
    });

    test('no warning when the extension put nothing on the PATH', async () => {
        await pointServicePathAt(undefined);
        await setShellIntegration(false);
        try {
            assert.ok(!needsShellIntegrationWarning(terminal(), 'partcad'));
        } finally {
            await setShellIntegration(undefined);
        }
    });

    test('the warning is shown once per window, not once per terminal', async () => {
        await applyBundle();
        await setShellIntegration(false);
        try {
            // Not awaited: the message stays up until someone answers it.
            void warnIfShellIntegrationOff(terminal(), 'partcad');
            assert.ok(!needsShellIntegrationWarning(terminal(), 'partcad'), 'already warned');
        } finally {
            await setShellIntegration(undefined);
        }
    });
});
