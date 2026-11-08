//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A package's colours, materials and finishes in the PartCAD Explorer.
//
// They are listed beside the objects, after them - they are what the objects
// are made in - each kind in the order CMF names them, and each opened in the
// Digital Thread by one command and from one context menu entry, whichever kind
// it is (see docs/design/cmf.md, section 9).
//

import * as assert from 'assert';
import * as fs from 'fs';
import * as path from 'path';

import { PartcadExplorer } from '../../PartcadExplorer';
import { ITEM_TYPE_COLOR, ITEM_TYPE_FINISH, ITEM_TYPE_MATERIAL, PartConfig, PartcadItem } from '../../PartcadItem';

const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', '..', 'package.json'), 'utf8'));

/** The rows a package's contents expand into, without an explorer: listing them registers no command. */
function rows(items: Record<string, unknown>): PartcadItem[] {
    const contents = {
        name: '//',
        dir: undefined,
        packages: [],
        sketches: [],
        interfaces: [],
        parts: [],
        assemblies: [],
    };
    const expand = PartcadExplorer.prototype.expandItems as (dir: string | undefined, items: unknown) => PartcadItem[];
    return expand.call({}, undefined, { ...contents, ...items });
}

suite('Colours, materials and finishes in the explorer', () => {
    test('they are listed after the objects, colour, material, finish, and before what could not be loaded', () => {
        const part: PartConfig = { name: 'housing', type: 'step' };
        const listed = rows({
            parts: [part],
            software: [{ name: 'firmware', type: 'raw' }],
            finishes: [{ name: 'satin', type: 'finish' }],
            materials: [{ name: 'abs', type: 'material' }],
            colors: [
                { name: 'stone', type: 'alias', desc: 'alias of //vendor:Medium Stone Grey' },
                { name: 'red', type: 'color', display: '#C91A09', manufacturable: true },
                { name: 'preview', type: 'color', display: '#00FF00', manufacturable: false },
            ],
            broken: [{ kind: 'part', name: 'gone', reason: 'no such type' }],
        });

        assert.deepStrictEqual(
            listed.map((item) => [item.itemType, item.name]),
            [
                ['part', 'housing'],
                ['software', 'firmware'],
                // By name, an alias after what is declared outright, as for every kind.
                [ITEM_TYPE_COLOR, 'preview'],
                [ITEM_TYPE_COLOR, 'red'],
                [ITEM_TYPE_COLOR, 'stone'],
                [ITEM_TYPE_MATERIAL, 'abs'],
                [ITEM_TYPE_FINISH, 'satin'],
                ['broken', 'gone'],
            ],
        );
    });

    test('a row says what it is drawn in and that it is only a picture, and opens in the Digital Thread', () => {
        const [preview, red] = rows({
            colors: [
                { name: 'preview', type: 'color', display: '#00FF00', manufacturable: false },
                { name: 'red', type: 'color', display: '#C91A09', manufacturable: true },
            ],
        });

        assert.strictEqual(preview.description, '#00FF00 · display only');
        assert.strictEqual(red.description, '#C91A09');
        for (const item of [preview, red]) {
            assert.strictEqual(item.contextValue, 'cmf');
            assert.strictEqual(item.command?.command, 'partcad.inspectCmf');
            assert.deepStrictEqual(
                (item.command?.arguments?.[0] as { kind: string; pkg: string }).kind,
                ITEM_TYPE_COLOR,
            );
        }
    });

    test('an older PartCAD that lists none lists nothing in their place', () => {
        assert.deepStrictEqual(rows({}), []);
    });

    test('one command, on the context menu of all three kinds', () => {
        const commands: { command: string }[] = manifest.contributes.commands;
        assert.ok(commands.some((entry) => entry.command === 'partcad.inspectCmf'));
        const entry = (manifest.contributes.menus['view/item/context'] as { command?: string; when?: string }[]).find(
            (menu) => menu.command === 'partcad.inspectCmf',
        );
        assert.match(entry?.when ?? '', /viewItem == cmf/);
    });
});
