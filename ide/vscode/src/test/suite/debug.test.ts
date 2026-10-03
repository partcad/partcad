//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Whether a debug session replaces the daemon it first reaches.
//

import * as assert from 'assert';
import * as path from 'path';

import { needsReplacing } from '../../common/debug';

suite('Replacing a daemon for the debugger', () => {
    const checkout = path.resolve('/work/partcad');
    const source = path.join(checkout, 'src', 'partcad_service_json_rpc');

    test("this checkout's daemon, not attached, is replaced", () => {
        assert.strictEqual(needsReplacing({ source, pid: 1, debugger: false }, checkout), true);
    });

    test('an attached daemon is kept', () => {
        assert.strictEqual(needsReplacing({ source, pid: 1, debugger: true }, checkout), false);
    });

    test("another installation's daemon is left alone", () => {
        // Replacing it would start the same code again, no nearer to the debugger.
        const bundle = path.resolve('/home/me/.partcad/bundle/_internal/partcad_service_json_rpc');
        assert.strictEqual(needsReplacing({ source: bundle, pid: 1, debugger: false }, checkout), false);
    });

    test('a daemon that cannot say is left alone', () => {
        // A service older than `daemon.debug` answers "method not found".
        assert.strictEqual(needsReplacing(undefined, checkout), false);
        assert.strictEqual(needsReplacing({}, checkout), false);
    });
});
