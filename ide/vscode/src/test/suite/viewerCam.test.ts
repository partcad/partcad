//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The CAM tab's control pane ('webview/cam.ts'): what a field sends, and what the
// pane says of how a part is made and of what its machine made.
//
// What a setting is and which a machine takes are the daemon's ('cam.settings',
// read off the configuration schema), so what is held in place here is the pane's
// own half: that a field left as the part states it sends nothing, that one
// emptied takes the setting out, that what is typed is sent as typed - PartCAD
// reads '20%' as it reads the file - and that the sentences say what the answer
// says.
//

import * as assert from 'assert';

import { editsOf, keptOf, labelOf, makingOf, stated, statsLines } from '../../webview/cam';
import { CamControl, CamSettingsData } from '../../webview/messages';

const CONTROLS: CamControl[] = [
    { key: 'layerHeight', type: 'length', value: null, default: 0.2 },
    { key: 'walls', type: 'count', value: 3, default: 2 },
    { key: 'infill', type: 'fraction', value: '20%', default: 0.15 },
    { key: 'toolAxis', type: 'axis', choices: ['-Z', '+Z'], value: null, default: '-Z' },
];

const PRINT: CamSettingsData = {
    object: '//demo:print',
    method: 'additive',
    machine: 'fff',
    machines: ['fff'],
    declared: true,
    design: 'block',
    controls: CONTROLS,
    materialized: { path: 'print.brep', exists: false },
};

suite('The CAM tab: its fields', () => {
    test('a field starts out as what the part states, as it is written', () => {
        assert.deepStrictEqual(CONTROLS.map(stated), ['', '3', '20%', '']);
    });

    test('only what differs from what the part states is sent: as typed, or null where it is emptied', () => {
        assert.deepStrictEqual(editsOf(CONTROLS, {}), {});
        assert.deepStrictEqual(editsOf(CONTROLS, { infill: '20%', walls: ' 3 ' }), {});
        assert.deepStrictEqual(editsOf(CONTROLS, { infill: '40%', layerHeight: '0.3 mm', toolAxis: '-Z' }), {
            infill: '40%',
            layerHeight: '0.3 mm',
            toolAxis: '-Z',
        });
        assert.deepStrictEqual(editsOf(CONTROLS, { walls: '' }), { walls: null });
    });

    test('a key reads as the words it is made of', () => {
        assert.strictEqual(labelOf('layerHeight'), 'Layer height');
        assert.strictEqual(labelOf('depth_per_pass'), 'Depth per pass');
        assert.strictEqual(labelOf('toolAxis'), 'Tool axis');
    });
});

suite('The CAM tab: what it says', () => {
    test('how a part is made: by what, on what, after what', () => {
        assert.strictEqual(makingOf(PRINT), "Printed on a filament printer ('fff'), after its design 'block'.");
        assert.strictEqual(
            makingOf({ ...PRINT, declared: false }),
            "Printed on a filament printer ('fff'), its usual settings, since the part names none, after its design 'block'.",
        );
        assert.strictEqual(
            makingOf({ ...PRINT, method: 'subtractive', machine: 'laser', design: 'sheet', instructions: 'outline' }),
            "Cut on a laser cutter ('laser') from its stock 'sheet', along 'outline'.",
        );
        assert.strictEqual(
            makingOf({ ...PRINT, method: 'forming', machine: 'mold', design: 'cavity' }),
            "Molded in a mold ('mold'), from its cavity 'cavity'.",
        );
    });

    test('where its geometry is kept', () => {
        assert.match(keptOf(PRINT), /made on demand.*print\.brep/);
        assert.match(keptOf({ ...PRINT, materialized: { path: 'print.brep', exists: true } }), /kept in print\.brep/);
        assert.match(keptOf({ ...PRINT, materialized: null }), /geometry of its own/);
    });

    test('what the product came to', () => {
        // As 'Shape.materialize_async' says it, in its own words.
        /* eslint-disable @typescript-eslint/naming-convention */
        const printed = { layers: 25, volume: 651.10156, solid_volume: 1000, filament_length: 270.69 };
        const cut = { cut_length: 1234.5 };
        /* eslint-enable @typescript-eslint/naming-convention */
        assert.deepStrictEqual(statsLines(printed), [
            'Layers: 25',
            "Deposited: 651 mm³ of the design's 1000 mm³ (65%)",
            'Filament: 0.271 m',
        ]);
        assert.deepStrictEqual(statsLines(cut), ['Route: 1.23 m']);
        assert.deepStrictEqual(statsLines(undefined), []);
    });
});
