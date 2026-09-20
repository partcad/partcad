//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Reading the service's "not yet -- build these first".
//

import * as assert from 'assert';

import { identity, pendingSubassemblies, requestParams, RETRY_LATER } from '../../common/staging';

suite('What the service wants built first', () => {
    test('the entries it named', () => {
        const pending = pendingSubassemblies(RETRY_LATER, {
            subassemblies: [
                { package: '//sub', name: 'unit' },
                { package: '//sub', name: 'unit;gap=4.0' },
            ],
        });
        assert.deepStrictEqual(pending.map(identity), ['//sub:unit', '//sub:unit;gap=4.0']);
    });

    test('an ordinary error is not a request to build anything', () => {
        // Every other failure reaches the user as it always did; only this one
        // code is acted on.
        assert.deepStrictEqual(pendingSubassemblies(-32602, { subassemblies: [{ name: 'unit' }] }), []);
        assert.deepStrictEqual(pendingSubassemblies(undefined, undefined), []);
    });

    test('a malformed payload is nothing to act on', () => {
        // Which is what makes the error be reported: an empty list is what the
        // caller rethrows on.
        assert.deepStrictEqual(pendingSubassemblies(RETRY_LATER, {}), []);
        assert.deepStrictEqual(pendingSubassemblies(RETRY_LATER, { subassemblies: 'unit' }), []);
        assert.deepStrictEqual(pendingSubassemblies(RETRY_LATER, { subassemblies: [{ package: '//sub' }, 7] }), []);
    });

    test('a staging request keeps the result on the service', () => {
        assert.deepStrictEqual(requestParams({ package: '//sub', name: 'unit' }), {
            package: '//sub',
            name: 'unit',
            kind: 'assembly',
            cacheOnly: true,
        });
    });

    test('a scene is asked for as a scene', () => {
        // The same files and the same tree, but a package registers the two
        // apart: asked for as an assembly, it is simply not found.
        const pending = pendingSubassemblies(RETRY_LATER, {
            subassemblies: [{ package: '//sub', name: 'bench', kind: 'scene' }],
        });
        assert.strictEqual(requestParams(pending[0]).kind, 'scene');
        assert.strictEqual(identity(pending[0]), '//sub:bench (scene)');
    });

    test('a context travels with it when there is one', () => {
        // The extension has none of its own today; a request carrying one must
        // still stage into that context and not into the session default.
        assert.strictEqual(requestParams({ name: 'unit' }, 'ctx-7').context, 'ctx-7');
        assert.ok(!('context' in requestParams({ name: 'unit' })));
    });
});
