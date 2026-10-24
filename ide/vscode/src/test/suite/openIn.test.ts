//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Which objects the "Open in > ..." menu is on, and which applications it offers
// for each.
//

import * as assert from 'assert';
import * as fs from 'fs';
import * as path from 'path';

import {
    ITEM_TYPE_ASSEMBLY,
    ITEM_TYPE_PART,
    ITEM_TYPE_SCENE,
    ITEM_TYPE_SKETCH,
    PartcadItem,
    isDrawing,
} from '../../PartcadItem';

type MenuEntry = { command?: string; submenu?: string; when?: string };

const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', '..', 'package.json'), 'utf8'));
const itemMenu: MenuEntry[] = manifest.contributes.menus['view/item/context'];
const openWithMenu: MenuEntry[] = manifest.contributes.menus['partcad.submenu.openWith'];

function contextOf(
    type: string,
    itemType: string,
    itemPath: string | undefined,
    file: string | null = '/pkg/thing.file',
): string | undefined {
    // The daemon's spelling of the field, which is not this language's.
    // eslint-disable-next-line @typescript-eslint/naming-convention
    const config = { name: 'thing', type: type, item_path: file ?? undefined };
    return new PartcadItem(undefined, 'thing', '//', config, itemPath, itemType).contextValue;
}

// Every `viewItem` value a sketch can have that has a file PartCAD can draw as a DXF.
const CONVERTIBLE_SKETCHES = ['sketchDrawing', 'sketchScript', 'sketchWithCode'];

// The `viewItem` values a clause names, `viewItem == x` only.
function named(when: string | undefined): Set<string> {
    return new Set([...(when ?? '').matchAll(/viewItem == (\w+)/g)].map((match) => match[1]));
}

function whenOf(menu: MenuEntry[], command: string): string {
    const entry = menu.find((e) => e.command === command || e.submenu === command);
    assert.ok(entry, `${command} is not on the menu`);
    return entry.when ?? '';
}

suite('Opening an object in another application', () => {
    test('a drawing is told apart from the rest of its kind', () => {
        assert.strictEqual(contextOf('dxf', ITEM_TYPE_SKETCH, '/pkg/outline.dxf'), 'sketchDrawing');
        assert.strictEqual(contextOf('svg', ITEM_TYPE_SKETCH, '/pkg/outline.svg'), 'sketchWithCode');
        // A script sketch has a file the tree does not open for editing, and PartCAD can still draw it.
        assert.strictEqual(contextOf('cadquery', ITEM_TYPE_SKETCH, undefined, '/pkg/slot.py'), 'sketchScript');
        assert.strictEqual(contextOf('build123d', ITEM_TYPE_SKETCH, undefined, '/pkg/slot.py'), 'sketchScript');
        // One with no file of its own has nothing to open.
        assert.strictEqual(contextOf('basic', ITEM_TYPE_SKETCH, undefined, null), 'sketch');
        assert.strictEqual(contextOf('cadquery', ITEM_TYPE_SKETCH, undefined, null), 'sketch');
        assert.strictEqual(contextOf('cadcraft:dwg', ITEM_TYPE_PART, undefined), 'partDrawing');
        assert.strictEqual(contextOf('//pub/feature/cad/cadcraft:dxf', ITEM_TYPE_PART, undefined), 'partDrawing');
        assert.strictEqual(contextOf('step', ITEM_TYPE_PART, undefined), 'part');
        assert.strictEqual(contextOf('kicad', ITEM_TYPE_PART, undefined), 'partKicad');
        assert.strictEqual(contextOf('cadcraft:dwg', ITEM_TYPE_ASSEMBLY, undefined), 'assemblyDrawing');
        assert.strictEqual(contextOf('assy', ITEM_TYPE_ASSEMBLY, '/pkg/thing.assy'), 'assemblyWithCode');
        assert.strictEqual(contextOf('sim-mujoco:mjcf', ITEM_TYPE_SCENE, '/pkg/thing.xml'), 'sceneMjcf');
    });

    test('a drawing is a DWG or a DXF, whoever implements it', () => {
        assert.ok(isDrawing('dxf'));
        assert.ok(isDrawing('cadcraft:DWG'));
        assert.ok(!isDrawing('step'));
        assert.ok(!isDrawing(undefined));
    });

    test('a narrow value is added back to every clause that names its kind', () => {
        // A world scene is a scene everywhere else, and a KiCad part is a part:
        // `viewItem` is one string compared exactly, so a value of its own for
        // the objects one application can open takes them off every other
        // entry unless each names it again.
        const narrow: { [broad: string]: string[] } = {
            part: ['partKicad', 'partDrawing'],
            assembly: ['assemblyDrawing'],
            sketch: ['sketchDrawing', 'sketchScript'],
            scene: ['sceneWorld', 'sceneMjcf'],
            sceneWithCode: ['sceneWorld', 'sceneMjcf'],
        };
        for (const entry of itemMenu) {
            const values = named(entry.when);
            for (const [broad, specific] of Object.entries(narrow)) {
                if (!values.has(broad)) {
                    continue;
                }
                for (const value of specific) {
                    assert.ok(
                        values.has(value),
                        `${entry.command ?? entry.submenu} names '${broad}' but not '${value}': ${entry.when}`,
                    );
                }
            }
        }
    });

    test('CADCraft is offered for drawings and for every sketch PartCAD can draw as one', () => {
        assert.deepStrictEqual(
            [...named(whenOf(openWithMenu, 'partcad.openInCADCraft'))].sort(),
            ['assemblyDrawing', 'partDrawing', ...CONVERTIBLE_SKETCHES].sort(),
        );
        // ...which puts the menu on each of those sketches.
        const submenu = named(whenOf(itemMenu, 'partcad.submenu.openWith'));
        for (const value of CONVERTIBLE_SKETCHES) {
            assert.ok(submenu.has(value), value);
        }
        // A sketch with no file of its own is not one: there is nothing to convert.
        assert.ok(!submenu.has('sketch'));
    });

    test('an application that opens solids is not offered a sketch', () => {
        for (const command of ['partcad.openInFreeCAD', 'partcad.openInBlender', 'partcad.openInSolidCraft']) {
            for (const value of CONVERTIBLE_SKETCHES) {
                assert.ok(whenOf(openWithMenu, command).includes(`viewItem != ${value}`), `${command}: ${value}`);
            }
        }
    });

    test('every scene an engine opens has the menu that offers the engine', () => {
        const submenu = named(whenOf(itemMenu, 'partcad.submenu.openWith'));
        assert.ok(submenu.has('sceneWorld'));
        assert.ok(submenu.has('sceneMjcf'));
    });
});
