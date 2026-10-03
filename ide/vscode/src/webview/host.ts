//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The one handle on the extension host, and the window-level error trap.
//
// 'acquireVsCodeApi()' may be called exactly once per webview - a second call
// throws - so it is called here, and everything that has something to say to the
// extension goes through this module rather than acquiring its own.
//
// The trap lives here for one reason: every other module in the webview imports
// this one, and a module's dependencies are evaluated before its own body. So
// this runs first whatever the import order elsewhere, and catches whatever
// nothing else did.
//
// The crash it was written for no longer reaches it. 'scene.ts' builds its
// 'THREE.WebGLRenderer' at module scope, and that constructor throws when the
// webview has no WebGL context to give it. Imported like any other module, that
// took the whole panel down with it - no 'message' handler, no tabs, nothing -
// for the want of one of its tabs. 'viewer.ts' now loads it on its own and hands
// the failure to 'reportFailure', which says it where the 3D view would have
// been, and every other tab goes on working.
//

import { FetchFormatsMessage, FetchTabMessage, TabId } from './messages';

declare function acquireVsCodeApi(): { postMessage(message: unknown): void };

const vscode = acquireVsCodeApi();

/** Tell the host this renderer has finished booting and can be shown into. */
export function ready(): void {
    vscode.postMessage({ type: 'ready' });
}

/** Ask the host to fill a tab in; it answers with a 'tabData' message. */
export function fetchTab(message: FetchTabMessage): void {
    vscode.postMessage(message);
}

/** Ask the host which file types a package renders to; it answers with 'formats'. */
export function fetchFormats(message: FetchFormatsMessage): void {
    vscode.postMessage(message);
}

/** Ask the host to save what a render tab is showing, wherever the user says. */
export function saveRendered(tab: TabId): void {
    vscode.postMessage({ type: 'save', tab });
}

/** Say that something failed, over the 3D view and into the extension's log. */
export function reportFailure(what: string, error: unknown): void {
    report(what, describe(error));
}

/** Report something that went wrong in here into the extension's log. */
export function reportError(message: string): void {
    vscode.postMessage({ type: 'error', message });
}

/** What the panel says instead of pretending it is merely idle. */
function report(what: string, detail: string): void {
    const overlay = document.getElementById('overlay');
    if (overlay !== null) {
        overlay.textContent = `${what}: ${detail}`;
        // Selectable, unlike the loading readout it replaces, which lets the
        // pointer through to the canvas: this is a message somebody has to act
        // on or quote, and it used to be one they could only retype.
        overlay.classList.add('failure');
        overlay.style.display = '';
    }
    // And into the extension's log, where a bug report can quote it.
    reportError(`${what}: ${detail}`);
}

function describe(error: unknown): string {
    if (error instanceof Error) {
        const message = error.message || String(error);
        // three.js says "Error creating WebGL context." and little else, and the
        // step from there to a fix is not one a user would guess. What is
        // actually going on is almost always that the window has no working GL
        // at all: "code --status" reports "webgl: disabled_off" and the GPU
        // process log ends in "Exiting GPU process due to errors during
        // initialization". Recent Chromium will not fall back to software WebGL
        // unless asked, which is the switch below -- and that is the whole fix,
        // since a part viewer does not need a GPU to be usable.
        //
        // Where the switch goes is the part that is easy to get wrong, and this
        // message used to get it wrong. It is a Chromium switch, read once when
        // the VS Code process starts, so it has to be on the command line that
        // starts that process: a new window -- an Extension Development Host
        // included -- is opened by the process already running and cannot take
        // it, and "Preferences: Configure Runtime Arguments" (argv.json) passes
        // on only a short allow-list of switches that this one is not on.
        if (/webgl/i.test(message)) {
            return noWebGL(message);
        }
        return message;
    }
    return String(error);
}

type Platform = 'windows' | 'mac' | 'linux';

/** The machine this panel is drawn on, which is where VS Code has to be restarted. */
function platform(): Platform {
    // The webview runs in the editor's own window, so this is the user's machine
    // even when the workspace is in a container or over SSH.
    const agent = navigator.userAgent;
    if (/Windows/i.test(agent)) {
        return 'windows';
    }
    return /Macintosh|Mac OS X/i.test(agent) ? 'mac' : 'linux';
}

/** The switch that makes Chromium draw WebGL in software (see `noWebGL`). */
const SOFTWARE_GL = '--enable-unsafe-swiftshader';

/**
 * Linux: rewrite VS Code's menu entry into the user's own applications folder,
 * with the switch added after the `code` executable on every `Exec=` line.
 *
 * A copy under `~/.local/share/applications` with the same file name takes
 * precedence over the system's, which is what makes the ordinary icon -- the
 * menu, the dock, a pinned favourite -- start VS Code this way, and deleting it
 * undoes everything. Both the `.deb`/`.rpm` entry and the snap's are covered.
 * The match is on "/code" followed by a space or the end of the line, which
 * skips the snap's `BAMF_DESKTOP_FILE_HINT=.../code_code.desktop`. One line,
 * so that copying it cannot leave half of it behind.
 */
const LINUX_ICON_COMMAND = String.raw`for f in /usr/share/applications/code.desktop /var/lib/snapd/desktop/applications/code_code.desktop; do [ -f "$f" ] && mkdir -p ~/.local/share/applications && sed '/^Exec=/ s#\(/code\)\( \|$\)#\1 ${SOFTWARE_GL}\2#' "$f" > ~/.local/share/applications/"$(basename "$f")" && echo "Done: the VS Code icon now starts it this way."; done`;

/**
 * What to say when there is no WebGL: steps a user can follow, on their system.
 *
 * Written for someone who has never heard of WebGL, a GPU driver or a
 * command-line switch, and should not have to: what is wrong, how to fix it
 * once from a terminal, and how to make the icon they normally click do the
 * same. Why the fix is a restart with a switch, and not a setting, is in the
 * comment in `describe`. The overlay keeps the line breaks and indents
 * ('.overlay.failure' in 'viewer.css'), and three.js's own words go last, for
 * whoever is asked to help.
 */
function noWebGL(message: string): string {
    const os = platform();
    const terminal = { windows: 'Command Prompt', mac: 'the Terminal app', linux: 'a terminal' }[os];
    const lines = [
        "this window can't show 3D models.",
        '',
        'VS Code could not use your graphics card. This is common on Linux, in virtual machines ' +
            'and over remote desktop. VS Code can draw the models without the graphics card instead.',
        '',
        'To do it now:',
        '1. Close every VS Code window.',
        `2. Open ${terminal} and run:`,
        `       code ${SOFTWARE_GL}`,
    ];
    if (os === 'mac') {
        lines.push(
            '   If the terminal says "command not found", open VS Code first, run "Shell Command: ' +
                "Install 'code' command in PATH\" from its Command Palette, and start again at step 1.",
        );
    }
    lines.push('3. Open the part again.');
    lines.push('', 'To make the VS Code icon do this every time:');
    if (os === 'windows') {
        lines.push(
            '1. Find the VS Code icon you usually click. For the Start menu, right-click Visual Studio Code ' +
                'there and choose "Open file location" (under "More" on Windows 11). For the taskbar, ' +
                'right-click the icon and then right-click "Visual Studio Code" in the menu that opens.',
            '2. Right-click that icon and choose Properties.',
            `3. In the Target box, go to the very end, after the closing quote mark, and type a space and ${SOFTWARE_GL}`,
            '4. Click OK. Do the same for any other VS Code icon you use.',
        );
    } else if (os === 'mac') {
        lines.push(
            '1. Open the Automator app, choose New Document, then Application.',
            '2. Find "Run Shell Script" in the list on the left, drag it to the right, and replace its text with:',
            `       open -a "Visual Studio Code" --args ${SOFTWARE_GL}`,
            '3. Save it in Applications as "VS Code for 3D", and drag it to the Dock.',
            '4. Start VS Code from that icon instead of the usual one.',
        );
    } else {
        lines.push(
            '1. Copy this line, paste it into a terminal and press Enter. You only need to do this once:',
            `       ${LINUX_ICON_COMMAND}`,
            '2. Close every VS Code window, and start it again from its icon.',
            `To undo it, delete the file it made in ~/.local/share/applications.`,
        );
    }
    lines.push('', 'The PartCAD IDE does all of this for you.', '', `(Details: ${message})`);
    return lines.join('\n');
}

window.addEventListener('error', (event: ErrorEvent) => {
    report('The PartCAD Viewer failed to start', describe(event.error ?? event.message));
});

window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    report('The PartCAD Viewer hit an error', describe(event.reason));
});
