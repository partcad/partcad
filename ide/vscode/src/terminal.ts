//
// PartCAD, 2025
//
// Author: Roman Kuzmenko
// Created: 2025-04-04
//
// Licensed under Apache License, Version 2.0.
//

import * as vscode from 'vscode';

import { traceError } from './common/log/logging';

/**
 * How a line reaches the `PartCAD` terminal view.
 *
 * Everything the user sees in that view arrives over the backend's
 * `?/partcad/terminal` and `?/partcad/log` notifications, which means nothing
 * can be reported there when the backend is what failed -- and "no PartCAD
 * service available" is exactly that case. It went to the output channel, which
 * nobody has open.
 *
 * The views themselves are `PartcadTerminals`, which `extension.ts` creates
 * because it owns the extension context and the settings. This is only the
 * registration, so that a module with none of those (`common/backend.ts`) can
 * report to the user without importing `extension.ts` and forming an import
 * cycle.
 */
type TerminalWriter = (text: string, alert?: string) => void;

let writer: TerminalWriter | undefined;

/** Called once by `activate`, with the views in place. */
export function setTerminalWriter(fn: TerminalWriter | undefined): void {
    writer = fn;
}

/**
 * Write to the `PartCAD` terminal view. Lines must end in `\r\n`: this is a
 * pseudoterminal, and a bare `\n` moves down a row without returning to column
 * one, so the next line starts wherever the last one ended.
 *
 * `alert` is for what the extension says about itself when it leaves the window
 * without a working PartCAD -- no service, a service that would not start, one
 * that kept dying. That opens a view even if the user closed every one, since
 * nothing else on screen would say why PartCAD stopped, and when no view was
 * open it is said in an error popup as well.
 *
 * A no-op before `activate` has registered the writer; the caller has nowhere
 * to put the text in that window, and the output channel still has it.
 */
export function writeTerminal(text: string, alert?: string): void {
    writer?.(text, alert);
}

/** The `PartCAD` entry in the terminal panel's "+" menu (`contributes.terminal.profiles`). */
export const TERMINAL_PROFILE_ID = 'partcad.terminal';

/**
 * The name of the shell opened to the left of the `PartCAD` view, and how that
 * shell is found again after a reload, when VS Code restores it on its own.
 */
export const SHELL_NAME = 'Shell';

const VIEW_NAME = 'PartCAD';

const GREETING = 'Keep an eye on this Terminal View to know what PartCAD is busy with...\r\n';

/**
 * Written at the top of that shell when it is created (`TerminalOptions.message`
 * -- straight into the view, not to the shell, so the shell never sees it).
 */
export const SHELL_BANNER =
    [
        '',
        '   +--------+',
        '  /        /|',
        ' +--------+ |    \x1b[1mStart your favorite coding agent here,\x1b[0m',
        ' |        | +    \x1b[1mside by side with the PartCAD terminal!\x1b[0m',
        ' |        |/',
        ' +--------+',
        '',
    ].join('\r\n') + '\r\n';

/** How long after creating a shell one restored by VS Code may still turn up and replace it. */
const REVIVE_WINDOW_MS = 5000;
const REVIVE_POLL_MS = 250;

/** Roughly what a terminal's default 1000 lines of scrollback hold, coloured. */
const REPLAY_LIMIT = 256 * 1024;

/** One line of the progress footer being erased (`clear_footer` in `partcad_utils.logging_ansi_terminal`). */
const ERASE_LINE = '\x1b[1A\x1b[2K';
/** What the footer is drawn after: autowrap off, so that a narrow view cuts its lines short. */
const NO_WRAP = '\x1b[?7l';

interface Chunk {
    /** The erase run it starts with: the footer the chunk before it drew. */
    erase: string;
    rest: string;
    /** Nothing but a redrawn footer, which is what the renderer sends twice a second while a process runs. */
    footerOnly: boolean;
}

/**
 * What has been written to the `PartCAD` views, for a view that opens later.
 *
 * A view opened on demand, or reopened after the user closed it, would
 * otherwise start empty -- and VS Code drops whatever a pseudoterminal sends
 * before its `open()` has been called, so even a view opened by the extension
 * would miss what arrived while it was starting.
 *
 * It is kept in the chunks it arrived in, because the renderer writes one chunk
 * per log event: [erase the footer it drew last][the log lines][the footer
 * again]. That makes two things exact:
 *
 * - **Trimming.** The oldest chunks are dropped whole, and the first one kept is
 *   replayed without its erase run -- which would remove lines of a footer the
 *   new view never drew, eating into the history above it.
 * - **Merging footer redraws.** A footer-only chunk erases exactly the footer
 *   drawn by the chunk before it, so two of them in a row are the first one's
 *   erase run followed by the second one's footer. Without that a long build
 *   would push the history out of the buffer with its own progress ticks.
 */
export class ReplayBuffer {
    private readonly chunks: Chunk[] = [];
    private size = 0;

    constructor(private readonly limit = REPLAY_LIMIT) {}

    append(text: string): void {
        let at = 0;
        while (text.startsWith(ERASE_LINE, at)) {
            at += ERASE_LINE.length;
        }
        const chunk = { erase: text.slice(0, at), rest: text.slice(at), footerOnly: text.startsWith(NO_WRAP, at) };
        const last = this.chunks[this.chunks.length - 1];
        if (chunk.footerOnly && last?.footerOnly) {
            this.size += chunk.rest.length - last.rest.length;
            last.rest = chunk.rest;
        } else {
            this.chunks.push(chunk);
            this.size += text.length;
        }
        while (this.size > this.limit && this.chunks.length > 1) {
            const dropped = this.chunks.shift()!;
            this.size -= dropped.erase.length + dropped.rest.length;
        }
    }

    /** Everything kept, as a view that has drawn nothing yet has to be given it. */
    text(): string {
        return this.chunks.map((chunk, i) => (i === 0 ? '' : chunk.erase) + chunk.rest).join('');
    }
}

/** One `PartCAD` view: a pseudoterminal of its own, since `open()` writes into the view it opens. */
class View {
    private readonly emitter = new vscode.EventEmitter<string>();
    readonly pty: vscode.Pseudoterminal;
    /** Opened by VS Code. Until then anything sent to it is dropped, and the replay covers it. */
    opened = false;
    closed = false;
    /** Known when the extension created it; looked up by `pty` for one the "+" menu created. */
    terminal: vscode.Terminal | undefined;

    constructor(
        onOpen: (view: View) => void,
        onClose: (view: View) => void,
        /** The shell it was split off, if it was. */
        readonly parent?: vscode.Terminal,
    ) {
        this.pty = {
            onDidWrite: this.emitter.event,
            open: () => {
                this.opened = true;
                onOpen(this);
            },
            close: () => onClose(this),
            handleInput: async (_char: string) => {},
        };
    }

    write(text: string): void {
        if (this.opened && !this.closed) {
            this.emitter.fire(text);
        }
    }

    close(): void {
        if (!this.closed) {
            this.closed = true;
            this.emitter.dispose();
        }
    }

    belongsTo(terminal: vscode.Terminal): boolean {
        return (
            terminal === this.terminal || (terminal.creationOptions as vscode.ExtensionTerminalOptions).pty === this.pty
        );
    }
}

function isAlive(terminal: vscode.Terminal): boolean {
    return vscode.window.terminals.includes(terminal) && terminal.exitStatus === undefined;
}

export interface PartcadTerminalsOptions {
    /** Whether new output reopens a view the user closed: `partcad.reopenTerminal`. */
    reopen: () => boolean;
    /** Whether new output brings the view to the front: `partcad.popupTerminal`. */
    popup: () => boolean;
    iconPath?: vscode.Uri;
    /** Said, with its two buttons, when an alert finds no view open. */
    showError?: (message: string, ...actions: string[]) => Thenable<string | undefined>;
    /**
     * The rest are for the tests, which run beside the activated extension's own
     * views and must neither find its shell nor be mistaken for it.
     */
    shellName?: string;
    viewName?: string;
    reviveWindowMs?: number;
}

const RESTART_ACTION = 'Restart PartCAD';
const SHOW_ACTION = 'Show Terminal';

/**
 * The `PartCAD` terminal views, and the shell beside them.
 *
 * - **Created when there is something to show.** The first output in a window
 *   opens a view, split to the right of a shell -- an existing one by
 *   `SHELL_NAME`, or a new one running the user's default profile, with
 *   `SHELL_BANNER` at the top.
 * - **Closing one keeps it closed.** Further output goes to the replay buffer
 *   only, unless `partcad.reopenTerminal` is set or it is an alert (see
 *   `writeTerminal`). "PartCAD: Show Terminal" and the "+" menu open one again,
 *   with the history in it.
 * - **Any number of views**, every one written to. The renderer that draws the
 *   output is one per connection on the daemon's side; here it is only bytes,
 *   sent to each.
 * - **The shell is the user's.** It is never disposed with the views and VS Code
 *   restores it on a reload, which a pseudoterminal never is (`isTransient` or
 *   not: the editor forces it for extension terminals). So after a reload the
 *   view is re-created beside the restored shell -- unless that shell turned up
 *   only after the view needed one and a new shell was made. A restored shell
 *   seen within `REVIVE_WINDOW_MS` of that replaces the new one and its view,
 *   and a new view beside it gets everything from the replay.
 */
export class PartcadTerminals implements vscode.Disposable, vscode.TerminalProfileProvider {
    private readonly views = new Set<View>();
    private readonly replay = new ReplayBuffer();
    private readonly subscriptions: vscode.Disposable[] = [];
    private readonly shellName: string;
    private readonly viewName: string;
    private readonly reviveWindowMs: number;
    private readonly showError: (message: string, ...actions: string[]) => Thenable<string | undefined>;
    private shell: vscode.Terminal | undefined;
    /** Whether a view has been opened in this window, by the extension or by the user. */
    private everOpened = false;
    private reviveWatch: ReturnType<typeof setInterval> | undefined;

    constructor(private readonly options: PartcadTerminalsOptions) {
        this.shellName = options.shellName ?? SHELL_NAME;
        this.viewName = options.viewName ?? VIEW_NAME;
        this.reviveWindowMs = options.reviveWindowMs ?? REVIVE_WINDOW_MS;
        this.showError =
            options.showError ?? ((message, ...actions) => vscode.window.showErrorMessage(message, ...actions));
        // `close()` is how a view learns it is gone, but VS Code calls it only
        // for a view that had started; this catches one closed before that.
        this.subscriptions.push(
            vscode.window.onDidCloseTerminal((terminal) => {
                for (const view of this.views) {
                    if (view.belongsTo(terminal)) {
                        this.forget(view);
                    }
                }
                if (terminal === this.shell) {
                    this.shell = undefined;
                }
            }),
        );
    }

    write(text: string, alert?: string): void {
        this.replay.append(text);
        const live = this.newestView();
        if (live) {
            for (const view of this.views) {
                view.write(text);
            }
            if (alert !== undefined || this.options.popup()) {
                this.terminalOf(live)?.show(true);
            }
            return;
        }
        // Nothing to write to: there has not been a view yet, or the user closed
        // every one. A new view replays the buffer, `text` included.
        if (alert !== undefined || !this.everOpened || this.options.reopen()) {
            this.ensureView();
        }
        if (alert !== undefined) {
            this.alert(alert);
        }
    }

    /** "PartCAD: Show Terminal". */
    show(): void {
        const view = this.ensureView();
        this.terminalOf(view)?.show(false);
    }

    /** The "+" menu's `PartCAD` entry: always a new view, which is what that menu does. */
    provideTerminalProfile(): vscode.TerminalProfile {
        this.everOpened = true;
        const view = this.addView();
        return new vscode.TerminalProfile({ name: this.viewName, pty: view.pty, iconPath: this.options.iconPath });
    }

    dispose(): void {
        this.stopWatching();
        for (const view of [...this.views]) {
            this.terminalOf(view)?.dispose();
            this.forget(view);
        }
        for (const subscription of this.subscriptions) {
            subscription.dispose();
        }
    }

    private ensureView(): View {
        const live = this.newestView();
        if (live) {
            return live;
        }
        this.everOpened = true;
        let shell = this.findShell();
        if (!shell) {
            shell = vscode.window.createTerminal({
                name: this.shellName,
                location: vscode.TerminalLocation.Panel,
                message: SHELL_BANNER,
            });
            this.shell = shell;
            this.watchForRestoredShell(shell);
        }
        return this.openBeside(shell);
    }

    /** A new view, split to the right of `shell`. */
    private openBeside(shell: vscode.Terminal): View {
        const view = this.addView(shell);
        view.terminal = vscode.window.createTerminal({
            name: this.viewName,
            location: { parentTerminal: shell },
            pty: view.pty,
            iconPath: this.options.iconPath,
        });
        // The pane that the keyboard goes to when the panel is focused; the view
        // beside it takes no input.
        shell.show(true);
        return view;
    }

    private addView(parent?: vscode.Terminal): View {
        const view = new View(
            (opened) => opened.write(GREETING + this.replay.text()),
            (closed) => this.forget(closed),
            parent,
        );
        this.views.add(view);
        return view;
    }

    private forget(view: View): void {
        view.close();
        this.views.delete(view);
    }

    private newestView(): View | undefined {
        let newest: View | undefined;
        for (const view of this.views) {
            newest = view;
        }
        return newest;
    }

    private terminalOf(view: View): vscode.Terminal | undefined {
        view.terminal ??= vscode.window.terminals.find((terminal) => view.belongsTo(terminal));
        return view.terminal;
    }

    /**
     * By either of its names. `name` is the tab's title, and a shell's tab shows
     * its process's own title (`pwsh`, `bash`) until the process is ready: only
     * then does VS Code apply a name an extension gave it, or give a restored
     * terminal its old one back. `creationOptions.name` is what an extension
     * asked for and never changes, but a restored terminal may not have one.
     */
    private isShell(terminal: vscode.Terminal): boolean {
        const options = terminal.creationOptions as vscode.TerminalOptions;
        return (
            (terminal.name === this.shellName || options.name === this.shellName) &&
            !('pty' in options) &&
            terminal.exitStatus === undefined
        );
    }

    private findShell(): vscode.Terminal | undefined {
        if (this.shell && isAlive(this.shell)) {
            return this.shell;
        }
        this.shell = vscode.window.terminals.find((terminal) => this.isShell(terminal));
        return this.shell;
    }

    /**
     * Polled, not an event: a restored terminal is announced before its name is
     * (see `isShell`), and nothing tells an extension when the name arrives.
     */
    private watchForRestoredShell(ours: vscode.Terminal): void {
        this.stopWatching();
        const until = Date.now() + this.reviveWindowMs;
        this.reviveWatch = setInterval(() => {
            const restored = vscode.window.terminals.find((terminal) => terminal !== ours && this.isShell(terminal));
            if (restored) {
                this.stopWatching();
                this.replaceShell(ours, restored);
            } else if (Date.now() >= until || !isAlive(ours)) {
                this.stopWatching();
            }
        }, REVIVE_POLL_MS);
    }

    private stopWatching(): void {
        if (this.reviveWatch !== undefined) {
            clearInterval(this.reviveWatch);
            this.reviveWatch = undefined;
        }
    }

    private replaceShell(ours: vscode.Terminal, restored: vscode.Terminal): void {
        if (ours.state.isInteractedWith) {
            // Typed into already: closing it would take that away. Two shells, then.
            return;
        }
        const beside = [...this.views].filter((view) => view.parent === ours);
        this.shell = restored;
        for (const view of beside) {
            this.terminalOf(view)?.dispose();
            this.forget(view);
        }
        ours.dispose();
        // Not `ensureView()`, which would settle for a view from the "+" menu
        // if one is open -- and that one was never beside a shell.
        if (beside.length > 0) {
            this.openBeside(restored);
        }
    }

    private alert(message: string): void {
        this.showError(message, RESTART_ACTION, SHOW_ACTION).then(
            async (chosen) => {
                if (chosen === RESTART_ACTION) {
                    await vscode.commands.executeCommand('partcad.restart');
                } else if (chosen === SHOW_ACTION) {
                    this.show();
                }
            },
            (e) => traceError(`PartCAD: could not show "${message}": ${e}`),
        );
    }
}
