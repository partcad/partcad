//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Cancelling the requests whose answers nobody is going to look at.
//

import * as assert from 'assert';
import * as vscode from 'vscode';

import { InFlight, isCancellation, REQUEST_CANCELLED, RequestCancelledError } from '../../common/cancellation';

suite('Which errors are a request having been cancelled', () => {
    test("the service's answer to a cancelled request", () => {
        // What vscode-jsonrpc rejects with: a ResponseError carrying the code.
        assert.strictEqual(isCancellation({ code: REQUEST_CANCELLED, message: 'Request cancelled' }), true);
        assert.strictEqual(REQUEST_CANCELLED, -32800);
    });

    test('a request given up on before it was sent', () => {
        assert.strictEqual(isCancellation(new RequestCancelledError()), true);
        assert.strictEqual(isCancellation(new vscode.CancellationError()), true);
    });

    test('a failure is not one', () => {
        assert.strictEqual(isCancellation(new Error('Assembly //:top is not found')), false);
        assert.strictEqual(isCancellation({ code: -32002 }), false);
        assert.strictEqual(isCancellation(undefined), false);
        assert.strictEqual(isCancellation('Request cancelled'), false);
    });
});

suite('The requests a view has in flight', () => {
    test('a newer request under the same key cancels the older one', () => {
        const inFlight = new InFlight();
        const older = inFlight.begin('bom');
        const other = inFlight.begin('requirements');
        const newer = inFlight.begin('bom');
        assert.strictEqual(older.token.isCancellationRequested, true);
        assert.strictEqual(other.token.isCancellationRequested, false);
        assert.strictEqual(newer.token.isCancellationRequested, false);
    });

    test('a request without a key is never replaced, only cancelled with everything', () => {
        // The runs of an analysis or a simulation: each answers a question of
        // its own.
        const inFlight = new InFlight();
        const first = inFlight.begin();
        const second = inFlight.begin();
        assert.strictEqual(first.token.isCancellationRequested, false);
        inFlight.cancelAll();
        assert.strictEqual(first.token.isCancellationRequested, true);
        assert.strictEqual(second.token.isCancellationRequested, true);
    });

    test('an answered request is forgotten, and its key is free', () => {
        const inFlight = new InFlight();
        const answered = inFlight.begin('bom');
        inFlight.end(answered);
        assert.strictEqual(inFlight.size, 0);
        const next = inFlight.begin('bom');
        inFlight.cancelAll();
        assert.strictEqual(next.token.isCancellationRequested, true);
        assert.strictEqual(answered.token.isCancellationRequested, false);
    });

    test('ending a request a newer one replaced leaves the newer one in place', () => {
        const inFlight = new InFlight();
        const older = inFlight.begin('2d');
        const newer = inFlight.begin('2d');
        inFlight.end(older);
        const newest = inFlight.begin('2d');
        assert.strictEqual(newer.token.isCancellationRequested, true);
        assert.strictEqual(newest.token.isCancellationRequested, false);
    });
});
