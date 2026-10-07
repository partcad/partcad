//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Restricted Mode: the extension stays in the activity bar, starts nothing, and
// starts everything once the folder is trusted.
//
// The runner opens its workspace trusted, so the untrusted path is driven here
// through `activateWhenTrusted`'s `isTrusted` argument, with command ids of its
// own -- the real `partcad.*` ones are registered by the activated extension,
// and registering a command twice throws.
//

import * as assert from 'assert';
import * as vscode from 'vscode';

import {
    activateWhenTrusted,
    contributedCommands,
    contributedTerminalProfiles,
    MANAGE_TRUST_COMMAND,
    registerUntrustedCommands,
    UNTRUSTED_MESSAGE,
    untrustedTerminalProfile,
} from '../../common/trust';

const EXTENSION_ID = 'partcad.partcad-official';

function manifest(): any {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `${EXTENSION_ID} is not installed`);
    return extension.packageJSON;
}

function fakeContext(commands: string[]): vscode.ExtensionContext {
    return {
        subscriptions: [] as vscode.Disposable[],
        extension: { packageJSON: { contributes: { commands: commands.map((command) => ({ command })) } } },
    } as unknown as vscode.ExtensionContext;
}

function disposeAll(context: vscode.ExtensionContext): void {
    for (const disposable of context.subscriptions) {
        disposable.dispose();
    }
}

suite('Workspace trust', () => {
    test('the extension is not removed from an untrusted window', () => {
        // `false` is what made the editor drop the activity bar icon, the
        // Explorer and the settings from the PartCAD IDE's first window.
        assert.strictEqual(manifest().capabilities.untrustedWorkspaces.supported, 'limited');
    });

    test('an untrusted Explorer offers the way to trust the folder, and nothing else', () => {
        const welcomes = manifest().contributes.viewsWelcome.filter(
            (welcome: any) => welcome.view === 'partcadExplorer',
        );
        const untrusted = welcomes.filter((welcome: any) => welcome.when === '!isWorkspaceTrusted');
        assert.strictEqual(untrusted.length, 1);
        assert.ok(untrusted[0].contents.includes(`command:${MANAGE_TRUST_COMMAND}`));

        // Every other message either needs trust or needs a context key that
        // only the trusted activation sets; the one that needs neither is the
        // "being initialized" message, which would sit beside the trust
        // message for as long as the folder stays untrusted.
        for (const welcome of welcomes) {
            if (welcome === untrusted[0]) {
                continue;
            }
            assert.ok(
                welcome.when.includes('isWorkspaceTrusted') || /(^|&& )partcad\.[a-zA-Z]+( |$)/.test(welcome.when),
                `shown in an untrusted window beside the trust message: ${welcome.when}`,
            );
        }
    });

    test('the webview panes wait for trust, since nothing would ever fill them', () => {
        const views = manifest().contributes.views['partcad-container'];
        for (const view of views.filter((view: any) => view.type === 'webview')) {
            assert.strictEqual(view.when, 'isWorkspaceTrusted', view.id);
        }
    });

    test('every contributed command is found', () => {
        const commands = contributedCommands(manifest());
        assert.ok(commands.includes('partcad.restart'));
        assert.ok(commands.includes('partcad.addPart'));
        assert.deepStrictEqual(contributedCommands({}), []);
    });

    test('every contributed terminal profile is found', () => {
        assert.deepStrictEqual(contributedTerminalProfiles(manifest()), ['partcad.terminal']);
        assert.deepStrictEqual(contributedTerminalProfiles({}), []);
    });

    test('the "+" menu entry in an untrusted window opens a view that explains itself', () => {
        let explained = 0;
        const provider = untrustedTerminalProfile(async () => {
            explained += 1;
        });
        const profile = provider.provideTerminalProfile(
            new vscode.CancellationTokenSource().token,
        ) as vscode.TerminalProfile;
        const pty = (profile.options as vscode.ExtensionTerminalOptions).pty;
        let written = '';
        pty.onDidWrite((text) => (written += text));
        pty.open(undefined);
        assert.strictEqual(written, `${UNTRUSTED_MESSAGE}\r\n`);
        assert.strictEqual(explained, 1);
        pty.close();
    });

    test('a command run in an untrusted window explains itself', async () => {
        let explained = 0;
        const standIns = registerUntrustedCommands(['partcadTest.trust.explains'], async () => {
            explained += 1;
        });
        try {
            await vscode.commands.executeCommand('partcadTest.trust.explains');
            assert.strictEqual(explained, 1);
        } finally {
            standIns.dispose();
        }
        const registered = await vscode.commands.getCommands(true);
        assert.ok(!registered.includes('partcadTest.trust.explains'), 'the stand-ins go when disposed');
    });

    test('a trusted folder activates at once', async () => {
        let activations = 0;
        const context = fakeContext(['partcadTest.trust.trusted']);
        let asked = 0;
        await activateWhenTrusted(context, async () => void (activations += 1), {
            isTrusted: true,
            explain: async () => void (asked += 1),
        });
        try {
            assert.strictEqual(activations, 1);
            assert.strictEqual(asked, 0);
            const registered = await vscode.commands.getCommands(true);
            assert.ok(!registered.includes('partcadTest.trust.trusted'), 'no stand-ins in a trusted folder');
        } finally {
            disposeAll(context);
        }
    });

    test('an untrusted folder starts nothing, asks, and stands in for the commands', async () => {
        let activations = 0;
        let asked = 0;
        const context = fakeContext(['partcadTest.trust.untrusted']);
        await activateWhenTrusted(context, async () => void (activations += 1), {
            isTrusted: false,
            explain: async () => void (asked += 1),
        });
        try {
            assert.strictEqual(activations, 0);
            assert.strictEqual(asked, 1, 'the user is asked once, on activation');
            const registered = await vscode.commands.getCommands(true);
            assert.ok(registered.includes('partcadTest.trust.untrusted'));
        } finally {
            disposeAll(context);
        }
    });

    test('granting trust starts PartCAD and takes the stand-ins away', async () => {
        const granted = new vscode.EventEmitter<void>();
        let activations = 0;
        const context = fakeContext(['partcadTest.trust.granted']);
        await activateWhenTrusted(context, async () => void (activations += 1), {
            isTrusted: false,
            onDidGrantTrust: granted.event,
            explain: async () => undefined,
        });
        try {
            assert.strictEqual(activations, 0);
            await fireAndSettle(granted);
            assert.strictEqual(activations, 1);
            const registered = await vscode.commands.getCommands(true);
            // Before the real activation registers the same ids, or it throws.
            assert.ok(!registered.includes('partcadTest.trust.granted'), 'the stand-ins are gone');
        } finally {
            disposeAll(context);
            granted.dispose();
        }
    });

    test('a start that fails after trust was granted is reported, not dropped', async () => {
        const granted = new vscode.EventEmitter<void>();
        const failures: unknown[] = [];
        const context = fakeContext(['partcadTest.trust.fails']);
        await activateWhenTrusted(
            context,
            async () => {
                throw new Error('no service');
            },
            {
                isTrusted: false,
                onDidGrantTrust: granted.event,
                explain: async () => undefined,
                onFailure: async (error) => void failures.push(error),
            },
        );
        try {
            await fireAndSettle(granted);
            assert.strictEqual(failures.length, 1);
            assert.match(String(failures[0]), /no service/);
        } finally {
            disposeAll(context);
            granted.dispose();
        }
    });
});

/** Fire `emitter`, and let its asynchronous listeners run to completion. */
async function fireAndSettle(emitter: vscode.EventEmitter<void>): Promise<void> {
    emitter.fire();
    await new Promise((resolve) => setTimeout(resolve, 0));
}
