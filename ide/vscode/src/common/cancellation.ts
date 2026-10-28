//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Cancelling a request whose answer nobody is going to look at.
//
// A selection that moves on makes the requests made for the last one stale: the
// Digital Thread drops their answers on arrival (see the tokens in
// `webview/viewer.ts`), and the Inspector stops waiting for the render it asked
// for. Until the daemon could be told, each of them still ran to the end, and
// every request behind it waited -- the daemon serves one at a time.
//
// So such a request is made with a cancellation token, and the token is
// cancelled the moment the request is superseded. `vscode-jsonrpc` then sends
// `$/cancelRequest`; the daemon answers a request that is still queued at once,
// with REQUEST_CANCELLED, and asks a running one to stop at its next safe point
// (`src/partcad_service_json_rpc/core/cancellation.py`). A daemon from before
// that ignores the notification and answers as it always did, which is exactly
// the old behaviour -- the answer is dropped here instead.
//

import * as vscode from 'vscode';

/** What a cancelled request is answered with: LSP's RequestCancelled. */
export const REQUEST_CANCELLED = -32800;

/** A request this side gave up on before it was sent, or between the steps of one. */
export class RequestCancelledError extends Error {
    readonly code = REQUEST_CANCELLED;

    constructor() {
        super('Request cancelled');
    }
}

/** Whether an error is a request having been cancelled, rather than one that failed. */
export function isCancellation(error: unknown): boolean {
    return (
        (typeof error === 'object' && error !== null && (error as { code?: unknown }).code === REQUEST_CANCELLED) ||
        error instanceof vscode.CancellationError
    );
}

/**
 * The requests one view has in flight, so that one it will drop is cancelled instead.
 *
 * A request may be made under a key: a newer request under the same key
 * supersedes it, and it is cancelled then. Every request is cancelled by
 * `cancelAll`, which is for the moment none of them is wanted any more.
 */
export class InFlight {
    private readonly sources = new Set<vscode.CancellationTokenSource>();
    private readonly byKey = new Map<string, vscode.CancellationTokenSource>();

    /** Start one; the request already in flight under `key`, if any, is cancelled. */
    begin(key?: string): vscode.CancellationTokenSource {
        const source = new vscode.CancellationTokenSource();
        if (key !== undefined) {
            this.byKey.get(key)?.cancel();
            this.byKey.set(key, source);
        }
        this.sources.add(source);
        return source;
    }

    /** It has been answered, one way or the other: forget it. */
    end(source: vscode.CancellationTokenSource): void {
        this.sources.delete(source);
        for (const [key, current] of this.byKey) {
            if (current === source) {
                this.byKey.delete(key);
            }
        }
        source.dispose();
    }

    /** Cancel everything in flight. */
    cancelAll(): void {
        for (const source of this.sources) {
            source.cancel();
        }
    }

    /** How many are in flight, for the tests. */
    get size(): number {
        return this.sources.size;
    }
}
