//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What `partcad.develIndex` tells the service, set and unset.
//

import * as assert from 'assert';
import * as vscode from 'vscode';

import { develIndexFor, getDevelIndexFromSetting } from '../../common/settings';

suite('Which branch of the public index the service reads', () => {
    test('a setting decides, whatever runs from sources', () => {
        for (const fromSources of [true, false]) {
            assert.strictEqual(develIndexFor(true, fromSources), true);
            assert.strictEqual(develIndexFor(false, fromSources), false);
        }
    });

    test('unset, an extension running from its sources reads devel', () => {
        assert.strictEqual(develIndexFor(undefined, true), true);
    });

    test('unset, an installed extension leaves it to PartCAD', () => {
        // Nothing is passed, so PartCAD's own default applies: on where it runs
        // from its sources, off for a wheel or a bundle.
        assert.strictEqual(develIndexFor(undefined, false), undefined);
    });

    test("a value in the user's settings is one a settings file set", async () => {
        const config = () => vscode.workspace.getConfiguration('partcad');
        const target = vscode.ConfigurationTarget.Global;
        assert.strictEqual(getDevelIndexFromSetting('partcad', false), undefined, 'nothing sets it to begin with');
        try {
            // Set to what package.json declares as its default: still said, so
            // still passed on, rather than read as unset.
            await config().update('develIndex', false, target);
            assert.strictEqual(getDevelIndexFromSetting('partcad', true), false);
            await config().update('develIndex', true, target);
            assert.strictEqual(getDevelIndexFromSetting('partcad', false), true);
        } finally {
            await config().update('develIndex', undefined, target);
        }
        assert.strictEqual(getDevelIndexFromSetting('partcad', true), true);
    });
});
