//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The editor while an object is open in another application: what the banner
// says, what is said when the application closes, and that every PartCAD
// command is paused meanwhile.
//

import * as assert from 'assert';
import * as fs from 'fs';
import * as path from 'path';

import { EDITING_CONTEXT, bannerHtml, outcomeMessage } from '../../editingBanner';

suite('Editing an object in another application', () => {
    test('the banner names the object and the application, and how to come back', () => {
        const html = bannerHtml('bracket', 'FreeCAD', 'n0nce', 'vscode-resource:');
        assert.ok(html.includes('Editing bracket in FreeCAD'));
        assert.ok(html.includes('close FreeCAD'));
        assert.ok(html.includes('Stop waiting'));
        // And what stopping costs, before anybody presses it.
        assert.ok(html.includes('not brought back'));
    });

    test('the banner runs only its own script', () => {
        const html = bannerHtml('bracket', 'FreeCAD', 'n0nce', 'vscode-resource:');
        assert.ok(html.includes("script-src 'nonce-n0nce'"));
        assert.ok(html.includes('<script nonce="n0nce">'));
    });

    test('a name is text in the banner, not markup', () => {
        // Object names come from a package somebody else may have written.
        const html = bannerHtml('<img src=x onerror=alert(1)>', 'FreeCAD', 'n', 'c');
        assert.ok(!html.includes('<img src=x'));
        assert.ok(html.includes('&lt;img src=x'));
    });

    test('nothing changed is said as such', () => {
        assert.strictEqual(
            outcomeMessage('bracket', 'FreeCAD', { detail: '', method: 'native', changed: false }),
            "FreeCAD closed; 'bracket' is unchanged.",
        );
    });

    test('an edit written back says where it went', () => {
        const message = outcomeMessage('bracket', 'Blender', {
            detail: '',
            method: 'docker',
            changed: true,
            writtenBack: '/w/bracket.3mf',
        });
        assert.ok(message.startsWith("Saved your changes to 'bracket'"));
        assert.ok(message.includes('/w/bracket.3mf'));
    });

    test('an edit that could not be written back says where it is instead', () => {
        const message = outcomeMessage('bracket', 'FreeCAD', {
            detail: '',
            method: 'native',
            changed: true,
            writtenBack: null,
            edited: '/w/.partcad/open/bracket-1.step',
        });
        assert.ok(message.includes('/w/.partcad/open/bracket-1.step'));
        assert.ok(message.includes('left as it was'));
    });

    test('every PartCAD command is paused while an application is open', () => {
        // A command added later without this would run against a package that
        // is about to be replaced -- so it is checked for every one of them.
        const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', '..', 'package.json'), 'utf8'));
        const unguarded = (manifest.contributes.commands as { command: string; enablement?: string }[])
            .filter((command) => command.enablement !== `!${EDITING_CONTEXT}`)
            .map((command) => command.command);
        assert.deepStrictEqual(unguarded, []);
    });
});
