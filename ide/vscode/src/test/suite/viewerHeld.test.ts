//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// An answer about the object on screen, held until its geometry is on the stage
// ('held.ts'): what the 3D view's Materials callouts are pinned with.
//

import * as assert from 'assert';
import { HeldForShow } from '../../webview/held';

suite('An answer that has to wait for the geometry', () => {
    test('one that arrives before the geometry is applied once the geometry is on the stage', () => {
        const applied: string[][] = [];
        const held = new HeldForShow<string[]>((value) => applied.push(value));

        held.reset();
        held.arrive(['abs']);
        assert.deepStrictEqual(applied, []);

        held.onStage();
        assert.deepStrictEqual(applied, [['abs']]);
    });

    test('one that arrives after the geometry is applied at once', () => {
        const applied: string[][] = [];
        const held = new HeldForShow<string[]>((value) => applied.push(value));

        held.reset();
        held.onStage();
        assert.deepStrictEqual(applied, []);
        held.arrive(['steel']);
        held.arrive([]);

        assert.deepStrictEqual(applied, [['steel'], []]);
    });

    test("another show forgets the last one's answer", () => {
        const applied: string[][] = [];
        const held = new HeldForShow<string[]>((value) => applied.push(value));

        held.reset();
        held.arrive(['abs']);
        held.reset();
        held.onStage();

        assert.deepStrictEqual(applied, []);
    });
});
