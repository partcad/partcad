/*
 * PartCAD, 2026
 *
 * Licensed under Apache License, Version 2.0.
 */

/**
 * The editor while an object is open in another application.
 *
 * `pc ide open` waits for the application to close, so that what was done in it
 * can be brought back into the package -- converted back into the object's own
 * format and written over its source. Until then the package is in two places at
 * once, and anything PartCAD did with it here (render it, rebuild it, edit its
 * source) would be done to the version that is about to be replaced. So the
 * editor says so as loudly as it can -- a banner taking the editor area -- and
 * every PartCAD command is disabled through the `partcad.editingExternally`
 * context key, which each command's `enablement` names.
 *
 * Stopping the wait is allowed and is not the same as closing the application:
 * `pc ide open` stops, the application stays open (it is in a session of its own),
 * and whatever is done in it from then on is not brought back. The banner says
 * that before anybody presses it.
 */

import * as vscode from 'vscode';

/** Set while an application opened by `pc ide open` is open; every PartCAD command is disabled while it is. */
export const EDITING_CONTEXT = 'partcad.editingExternally';

/** What `pc ide open --json` said about an open that worked. */
export interface OpenOutcome {
    detail: string;
    method: string;
    changed?: boolean;
    writtenBack?: string | null;
    edited?: string | null;
}

function escapeHtml(text: string): string {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/** The banner, as HTML. Pure, so that what it says can be tested without a window. */
export function bannerHtml(name: string, application: string, nonce: string, cspSource: string): string {
    const what = escapeHtml(name);
    const app = escapeHtml(application);
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Editing ${what} in ${app}</title>
<style>
  body { display: flex; align-items: center; justify-content: center; min-height: 90vh; margin: 0;
         color: var(--vscode-foreground); background: var(--vscode-editor-background);
         font-family: var(--vscode-font-family); }
  main { max-width: 42rem; padding: 2rem; text-align: center; }
  h1 { font-size: 2.4rem; font-weight: 600; margin: 0 0 1rem; }
  p { font-size: 1.15rem; line-height: 1.6; margin: 0 0 1rem; }
  .muted { color: var(--vscode-descriptionForeground); font-size: 0.95rem; }
  button { margin-top: 1.5rem; padding: 0.5rem 1.2rem; font-size: 0.95rem; cursor: pointer;
           color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground);
           border: none; border-radius: 2px; }
  button:hover { background: var(--vscode-button-secondaryHoverBackground); }
</style>
</head>
<body>
<main>
  <h1>Editing ${what} in ${app}</h1>
  <p>Make your changes in ${app}, save them, and close ${app} to come back here.</p>
  <p>PartCAD brings what you saved back into the package when ${app} closes. Until then its commands are paused, so
  that nothing is built from a version that is about to be replaced.</p>
  <p class="muted">Stopping the wait leaves ${app} open, and what you save there from then on is not brought back.</p>
  <button id="stop">Stop waiting</button>
</main>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  document.getElementById('stop').addEventListener('click', () => vscode.postMessage('stop'));
</script>
</body>
</html>`;
}

/** What to tell somebody when the application has closed. Pure, for the same reason as the banner. */
export function outcomeMessage(name: string, application: string, outcome: OpenOutcome): string {
    if (!outcome.changed) {
        return `${application} closed; '${name}' is unchanged.`;
    }
    if (outcome.writtenBack) {
        return `Saved your changes to '${name}' (${outcome.writtenBack}).`;
    }
    if (outcome.edited) {
        return (
            `Your changes to '${name}' are in ${outcome.edited}. Its source is not a file PartCAD can write ` +
            `back into, so it was left as it was.`
        );
    }
    return `${application} closed; '${name}' changed.`;
}

function nonce(): string {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let value = '';
    for (let i = 0; i < 32; i++) {
        value += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return value;
}

/**
 * Show the banner and pause PartCAD's commands until the returned disposable is disposed.
 *
 * `onStop` is called when somebody presses "Stop waiting" -- in the banner, or
 * Cancel on the progress notification beside it.
 */
export async function showEditingBanner(
    name: string,
    application: string,
    onStop: () => void,
): Promise<vscode.Disposable> {
    await vscode.commands.executeCommand('setContext', EDITING_CONTEXT, true);
    const panel = vscode.window.createWebviewPanel(
        'partcad.editingExternally',
        `Editing ${name} in ${application}`,
        { viewColumn: vscode.ViewColumn.Active, preserveFocus: false },
        { enableScripts: true, retainContextWhenHidden: true },
    );
    panel.webview.html = bannerHtml(name, application, nonce(), panel.webview.cspSource);
    const listener = panel.webview.onDidReceiveMessage((message) => {
        if (message === 'stop') {
            onStop();
        }
    });
    let disposed = false;
    return new vscode.Disposable(() => {
        if (disposed) {
            return;
        }
        disposed = true;
        listener.dispose();
        panel.dispose();
        void vscode.commands.executeCommand('setContext', EDITING_CONTEXT, false);
    });
}
