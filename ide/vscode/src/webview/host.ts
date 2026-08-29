//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The one handle on the extension host.
//
// 'acquireVsCodeApi()' may be called exactly once per webview - a second call
// throws - so it is called here, and everything that has something to say to the
// extension goes through this module rather than acquiring its own.
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
