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
// this runs first whatever the import order elsewhere - which matters, because
// the crash it has to catch happens during another module's *import*. 'scene.ts'
// builds its 'THREE.WebGLRenderer' at module scope, and that constructor throws
// when the webview has no WebGL context to give it. Nothing is listening yet at
// that point: no 'message' handler is registered, no 'ready' is posted, and the
// panel keeps the "Nothing to display yet." its HTML starts with - which is also
// what it says before the user has asked for anything, so a viewer that crashed
// on the way up was indistinguishable from one that was merely idle.
//

import { FetchTabMessage } from './messages';

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

/** Report something that went wrong in here into the extension's log. */
export function reportError(message: string): void {
    vscode.postMessage({ type: 'error', message });
}

/** What the panel says instead of pretending it is merely idle. */
function report(what: string, detail: string): void {
    const overlay = document.getElementById('overlay');
    if (overlay !== null) {
        overlay.textContent = `${what}: ${detail}`;
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
        if (/webgl/i.test(message)) {
            return (
                `${message} The PartCAD Viewer needs WebGL and this window has none. ` +
                'Run "code --status": if it reports "webgl: disabled_off", there is no working GPU ' +
                'driver behind this window (common with the snap package, with an NVIDIA driver, ' +
                'or over a remote display). Restart VS Code with "--enable-unsafe-swiftshader" to ' +
                'render in software, and make it stick with "Preferences: Configure Runtime Arguments".'
            );
        }
        return message;
    }
    return String(error);
}

window.addEventListener('error', (event: ErrorEvent) => {
    report('The PartCAD Viewer failed to start', describe(event.error ?? event.message));
});

window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
    report('The PartCAD Viewer hit an error', describe(event.reason));
});
