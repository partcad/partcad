//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// When the context view calls out the PartCAD version it is showing.
//

import * as assert from 'assert';

import { versionsDiffer } from '../../PartcadContext';

suite('The PartCAD version in the context view', () => {
    test('the release the extension shipped with is not called out', () => {
        assert.strictEqual(versionsDiffer('0.8.94', '0.8.94'), false);
    });

    test('any other release is', () => {
        // Either direction: an installation left behind by an older release,
        // and an extension the marketplace has not updated yet.
        assert.strictEqual(versionsDiffer('0.8.93', '0.8.94'), true);
        assert.strictEqual(versionsDiffer('0.8.95', '0.8.94'), true);
    });

    test('the placeholder shown before PartCAD answers is not a mismatch', () => {
        // The view is drawn once before the first `info` arrives, and a cell
        // reading "Loading..." in red is a false alarm on every start.
        assert.strictEqual(versionsDiffer('Loading...', '0.8.94'), false);
        assert.strictEqual(versionsDiffer('', '0.8.94'), false);
        assert.strictEqual(versionsDiffer(undefined, '0.8.94'), false);
    });

    test('an unknown extension version compares against nothing', () => {
        assert.strictEqual(versionsDiffer('0.8.94', ''), false);
        assert.strictEqual(versionsDiffer('0.8.94', undefined), false);
    });

    test('surrounding whitespace is not a difference', () => {
        assert.strictEqual(versionsDiffer(' 0.8.94\n', '0.8.94'), false);
    });
});
