//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The `PartCAD` terminal views: what the replay buffer keeps, when a view is
// opened and reopened, and the shell to the left of it.
//
// The activated extension has views and a shell of its own in this window, so
// every test here names its shell and its views differently and looks only for
// those -- by `creationOptions.name`, not `name`: a shell's `name` is its
// process's title until the process is ready, which on a Windows runner is long
// enough for a lookup by `name` to miss it.
//

import * as assert from 'assert';
import * as vscode from 'vscode';

import { PartcadTerminals, PartcadTerminalsOptions, ReplayBuffer, SHELL_BANNER } from '../../terminal';

const ERASE = '\x1b[1A\x1b[2K';
const NO_WRAP = '\x1b[?7l';
const WRAP = '\x1b[?7h';

/** A one-line progress footer as the renderer draws it, after erasing `erase` lines of the last one. */
function footer(text: string, erase = 0): string {
    return ERASE.repeat(erase) + NO_WRAP + text + '\r\n' + WRAP;
}

suite('PartCAD terminal: replay buffer', () => {
    test('keeps what was written, in order', () => {
        const replay = new ReplayBuffer();
        replay.append('one\r\n');
        replay.append('two\r\n');
        assert.strictEqual(replay.text(), 'one\r\ntwo\r\n');
    });

    test('a footer redrawn twice in a row is kept once, after the erase run before the first', () => {
        const replay = new ReplayBuffer();
        replay.append('line\r\n' + footer('build; 0s'));
        replay.append(footer('build; 1s', 1));
        replay.append(footer('build; 2s', 1));
        assert.strictEqual(replay.text(), 'line\r\n' + footer('build; 0s') + footer('build; 2s', 1));
    });

    test('a log line between two redraws is not merged away', () => {
        const replay = new ReplayBuffer();
        const chunks = [footer('build; 0s'), ERASE + 'INFO: done\r\n' + footer('build; 1s'), footer('build; 2s', 1)];
        for (const chunk of chunks) {
            replay.append(chunk);
        }
        assert.strictEqual(replay.text(), chunks.join(''));
    });

    test('the oldest chunks go first, and the first one kept erases nothing', () => {
        const replay = new ReplayBuffer(20);
        replay.append('0123456789\r\n');
        replay.append(ERASE + 'abcdefgh\r\n');
        // The erase run removed a footer the dropped chunk drew; a new view
        // never drew it, and erasing would eat into what is above.
        assert.strictEqual(replay.text(), 'abcdefgh\r\n');
    });

    test('a chunk bigger than the limit is still kept', () => {
        const replay = new ReplayBuffer(4);
        replay.append('0123456789\r\n');
        assert.strictEqual(replay.text(), '0123456789\r\n');
    });
});

suite('PartCAD terminal: the shell banner', () => {
    test('says what the shell is for, and fits half a terminal', () => {
        const plain = SHELL_BANNER.replace(/\x1b\[[0-9;]*m/g, '');
        assert.ok(plain.includes('Start your favorite coding agent here,'));
        assert.ok(plain.includes('side by side with the PartCAD terminal!'));
        for (const line of plain.split('\r\n')) {
            assert.ok(line.length <= 60, `too wide for a split panel: ${line}`);
            assert.ok(!line.includes('\n'), 'a pseudoterminal-style \\r\\n, not a bare \\n');
        }
    });
});

/** Every terminal in the window, for a failure message: CI has nothing else to show. */
function describeTerminals(): string {
    return vscode.window.terminals
        .map((t) => {
            const options = t.creationOptions as vscode.TerminalOptions;
            const exit = t.exitStatus ? ` exited ${t.exitStatus.code}` : '';
            return `"${t.name}" (asked for "${options.name}"${'pty' in options ? ', pty' : ''}${exit})`;
        })
        .join(', ');
}

/** Until `condition` holds, or fail after `ms`. */
async function waitFor(condition: () => boolean, what: string, ms = 15000): Promise<void> {
    const until = Date.now() + ms;
    while (!condition()) {
        if (Date.now() > until) {
            assert.fail(`timed out waiting for ${what}; terminals: ${describeTerminals()}`);
        }
        await new Promise((resolve) => setTimeout(resolve, 50));
    }
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function isPty(terminal: vscode.Terminal): boolean {
    return 'pty' in terminal.creationOptions;
}

function isAlive(terminal: vscode.Terminal): boolean {
    return vscode.window.terminals.includes(terminal) && terminal.exitStatus === undefined;
}

/**
 * What a view has been sent, read off its pseudoterminal: there is no API for
 * a terminal's screen. Listening starts before VS Code opens the view, since
 * it opens on a round trip to the workbench.
 */
class Output {
    text = '';
    constructor(terminal: vscode.Terminal) {
        (terminal.creationOptions as vscode.ExtensionTerminalOptions).pty.onDidWrite((data) => (this.text += data));
    }
}

suite('PartCAD terminal: views', () => {
    let count = 0;
    let shellName = '';
    let viewName = '';
    let terminals: PartcadTerminals | undefined;

    function make(options: Partial<PartcadTerminalsOptions> = {}): PartcadTerminals {
        terminals = new PartcadTerminals({
            reopen: () => false,
            popup: () => false,
            shellName,
            viewName,
            ...options,
        });
        return terminals;
    }

    const named = (t: vscode.Terminal, name: string) => (t.creationOptions as vscode.TerminalOptions).name === name;
    const shells = () => vscode.window.terminals.filter((t) => named(t, shellName) && !isPty(t));
    const views = () => vscode.window.terminals.filter((t) => named(t, viewName) && isPty(t));

    setup(() => {
        count += 1;
        shellName = `PartCAD test shell ${count}`;
        viewName = `PartCAD test view ${count}`;
    });

    teardown(async () => {
        terminals?.dispose();
        terminals = undefined;
        for (const terminal of [...shells(), ...views()]) {
            terminal.dispose();
        }
        await waitFor(() => shells().length === 0 && views().length === 0, 'the terminals to close');
    });

    test('nothing opens before there is output, and the first output opens a view beside a shell', async () => {
        const partcad = make();
        await sleep(300);
        assert.strictEqual(shells().length + views().length, 0, 'nothing to show yet');

        partcad.write('INFO: hello\r\n');
        assert.strictEqual(shells().length, 1);
        assert.strictEqual(views().length, 1);
        assert.strictEqual((shells()[0].creationOptions as vscode.TerminalOptions).message, SHELL_BANNER);
        const output = new Output(views()[0]);
        await waitFor(() => output.text.includes('INFO: hello'), 'the first output, replayed on open');

        partcad.write('INFO: again\r\n');
        await waitFor(() => output.text.includes('INFO: again'), 'output written to the open view');
    });

    test('output reaches every open view', async () => {
        const partcad = make();
        partcad.write('INFO: first\r\n');
        const first = new Output(views()[0]);

        // The terminal panel's "+" menu, as the editor runs it.
        const profile = partcad.provideTerminalProfile();
        const second = vscode.window.createTerminal(profile.options as vscode.ExtensionTerminalOptions);
        const secondOutput = new Output(second);
        await waitFor(() => secondOutput.text.includes('INFO: first'), 'the history, in a view opened later');
        assert.strictEqual(shells().length, 1, `the "+" menu opens a view, not another shell: ${describeTerminals()}`);

        partcad.write('INFO: second\r\n');
        await waitFor(
            () => first.text.includes('INFO: second') && secondOutput.text.includes('INFO: second'),
            'the same output in both views',
        );
    });

    test('a closed view stays closed, and opens again with what it missed', async () => {
        const partcad = make();
        partcad.write('INFO: one\r\n');
        const first = views()[0];
        const firstOutput = new Output(first);
        await waitFor(() => firstOutput.text.includes('INFO: one'), 'the view to open');

        first.dispose();
        await waitFor(() => views().length === 0, 'the view to close');
        partcad.write('INFO: two\r\n');
        await sleep(500);
        assert.strictEqual(views().length, 0, 'output does not reopen it');

        partcad.show();
        assert.strictEqual(views().length, 1);
        const output = new Output(views()[0]);
        await waitFor(
            () => output.text.includes('INFO: one') && output.text.includes('INFO: two'),
            'everything, in the view opened on demand',
        );
        assert.strictEqual(shells().length, 1, 'beside the shell that is still there');
    });

    test('with partcad.reopenTerminal, output reopens a closed view', async () => {
        const partcad = make({ reopen: () => true });
        partcad.write('INFO: one\r\n');
        const first = views()[0];
        first.dispose();
        await waitFor(() => views().length === 0, 'the view to close');

        partcad.write('INFO: two\r\n');
        assert.strictEqual(views().length, 1);
    });

    test('an alert reopens a closed view, and says so in a popup only when none was open', async () => {
        const popups: string[] = [];
        const partcad = make({
            showError: async (message: string) => {
                popups.push(message);
                return undefined;
            },
        });
        partcad.write('INFO: one\r\n');
        partcad.write('ERROR: one\r\n', 'with a view open');
        assert.deepStrictEqual(popups, [], 'no popup while a view is open');

        views()[0].dispose();
        await waitFor(() => views().length === 0, 'the view to close');
        partcad.write('ERROR: no service\r\n', 'No PartCAD service');
        assert.strictEqual(views().length, 1, 'reopened, whatever partcad.reopenTerminal says');
        assert.deepStrictEqual(popups, ['No PartCAD service']);
        const output = new Output(views()[0]);
        await waitFor(() => output.text.includes('ERROR: no service'), 'the alert in the view');
    });

    test('a shell of that name already open is the one the view goes beside', async () => {
        const existing = vscode.window.createTerminal({ name: shellName });
        await waitFor(() => isAlive(existing), 'the shell to open');

        make().write('INFO: hello\r\n');
        assert.deepStrictEqual(shells(), [existing], 'no second shell');
        assert.strictEqual(views().length, 1);
    });

    test('a shell restored soon after one was made replaces it, and the view moves beside it', async () => {
        const partcad = make();
        partcad.write('INFO: before the shell came back\r\n');
        const [made] = shells();
        const [first] = views();

        // What VS Code does after a reload, late: a shell of the same name.
        const restored = vscode.window.createTerminal({ name: shellName });
        await waitFor(() => !isAlive(made) && !vscode.window.terminals.includes(first), 'the new pair to close');
        await waitFor(() => views().length === 1, 'a view beside the restored shell');
        assert.deepStrictEqual(shells(), [restored]);
        const output = new Output(views()[0]);
        await waitFor(() => output.text.includes('INFO: before the shell came back'), 'the history, replayed');
    });

    test('a view from the "+" menu does not stand in for the one beside a restored shell', async () => {
        const partcad = make();
        partcad.write('INFO: hello\r\n');
        const [made] = shells();
        const [first] = views();
        const plus = vscode.window.createTerminal(
            partcad.provideTerminalProfile().options as vscode.ExtensionTerminalOptions,
        );

        vscode.window.createTerminal({ name: shellName });
        await waitFor(() => !isAlive(made) && !vscode.window.terminals.includes(first), 'the new pair to close');
        await waitFor(() => views().length === 2, 'a view beside the restored shell, besides the "+" one');
        assert.ok(views().includes(plus), 'the "+" view is left alone');
    });

    test('a shell restored after the window is left beside the one that was made', async () => {
        make({ reviveWindowMs: 200 }).write('INFO: hello\r\n');
        const [made] = shells();
        await sleep(600);

        vscode.window.createTerminal({ name: shellName });
        await sleep(600);
        assert.ok(isAlive(made), 'the shell that was made stays');
        assert.strictEqual(views().length, 1, 'and so does its view');
    });
});
