//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What colour a shape is drawn in.
//
// A shape is drawn in the colour its properties state, else in the colour of the
// nearest node above it that states one, else in goldenrod - the colour OCCT and
// PartCAD's own 2D projections draw an uncoloured shape in. None of that can be
// checked by eye here ('scene.ts' builds its renderer at import), so what decides
// it - 'appearance.ts' - is pinned instead: the default, what counts as a colour,
// how one reaches the nodes under it, and the shade the lines across it are drawn
// in. The default's agreement with the Python side is held by a test there, which
// reads 'appearance.ts' itself.
//

import * as assert from 'assert';
import * as THREE from 'three';

import {
    Appearance,
    DEFAULT_APPEARANCE,
    DEFAULT_COLOR,
    DEFAULT_EDGE_COLOR,
    appearanceKey,
    appearanceOf,
    edgeColor,
    parseColor,
} from '../../webview/appearance';
import { ShowNode } from '../../webview/messages';
import { walk } from '../../webview/nodes';

/** What every node of 'root' is drawn as, by name, worked out as 'buildNode' does it. */
function drawnAs(root: ShowNode): Map<string, Appearance> {
    const byPath = new Map<string, Appearance>();
    const drawn = new Map<string, Appearance>();
    walk(root, (node, path) => {
        const parent = path.length === 0 ? DEFAULT_APPEARANCE : byPath.get(path.slice(0, -1).join('/'));
        const appearance = appearanceOf(node, parent);
        byPath.set(path.join('/'), appearance);
        drawn.set(node.name ?? path.join('/'), appearance);
    });
    return drawn;
}

suite('What colour a shape is drawn in', () => {
    test('a shape that states nothing is goldenrod, and solid', () => {
        assert.strictEqual(DEFAULT_COLOR, 0xdaa520);
        assert.deepStrictEqual(DEFAULT_APPEARANCE, { color: 0xdaa520, opacity: 1 });
        assert.deepStrictEqual(appearanceOf({ name: '//pkg:cube' }), DEFAULT_APPEARANCE);
        assert.deepStrictEqual(
            appearanceOf({ name: '//pkg:cube', properties: { material: 'pla' } }),
            DEFAULT_APPEARANCE,
        );
    });

    test('the default is goldenrod as CSS names it, once three has converted it', () => {
        // A hex colour is sRGB to three and is kept linear; reading it back as sRGB
        // has to give the very colour CSS calls goldenrod, or the 3D view and a 2D
        // drawing in "rgb(218,165,32)" are two different yellows.
        const color = new THREE.Color(DEFAULT_COLOR);
        assert.strictEqual(color.getHexString(THREE.SRGBColorSpace), 'daa520');
        assert.strictEqual(color.getStyle(THREE.SRGBColorSpace), 'rgb(218,165,32)');
    });

    test('a colour is "#RRGGBB" or "#RRGGBBAA", in either case, with or without the "#"', () => {
        assert.deepStrictEqual(parseColor('#FF0000'), { color: 0xff0000, opacity: 1 });
        assert.deepStrictEqual(parseColor('#ff0000'), { color: 0xff0000, opacity: 1 });
        assert.deepStrictEqual(parseColor('00ff00'), { color: 0x00ff00, opacity: 1 });
        assert.deepStrictEqual(parseColor(' #0000FF '), { color: 0x0000ff, opacity: 1 });
        assert.deepStrictEqual(parseColor('#0000FF80'), { color: 0x0000ff, opacity: 128 / 255 });
        assert.deepStrictEqual(parseColor('#0000FFFF'), { color: 0x0000ff, opacity: 1 });
    });

    test('anything else is no colour at all', () => {
        // "red" is what a part's free-form 'color' parameter may say; the property
        // it is not is "#RRGGBB", and guessing would draw a colour nobody stated.
        for (const text of ['red', '#FFF', '#FFFF', '#FF00000', '#GG0000', '', '#', 'rgb(255,0,0)']) {
            assert.strictEqual(parseColor(text), undefined, text);
        }
        for (const value of [undefined, null, 0xff0000, ['#FF0000'], { color: '#FF0000' }]) {
            assert.strictEqual(parseColor(value), undefined, String(value));
        }
    });

    test('a node is drawn in the colour it states', () => {
        assert.deepStrictEqual(appearanceOf({ name: 'x', properties: { color: '#336699' } }), {
            color: 0x336699,
            opacity: 1,
        });
    });

    test('a colour reaches every node under it that states none, and stops at one that does', () => {
        const drawn = drawnAs({
            name: 'robot',
            properties: { color: '#FF0000' },
            assembly: [
                { name: 'arm', assembly: [{ name: 'bolt' }, { name: 'gripper', properties: { color: '#0000FF' } }] },
                { name: 'base', properties: { color: 'not a colour' } },
            ],
        });
        assert.strictEqual(drawn.get('robot')?.color, 0xff0000);
        assert.strictEqual(drawn.get('arm')?.color, 0xff0000);
        assert.strictEqual(drawn.get('bolt')?.color, 0xff0000);
        assert.strictEqual(drawn.get('gripper')?.color, 0x0000ff);
        // A colour that is not one is not stated: the node takes its parent's.
        assert.strictEqual(drawn.get('base')?.color, 0xff0000);
    });

    test('nothing above a node states a colour, and it is goldenrod however deep it is', () => {
        const drawn = drawnAs({
            name: 'frame',
            assembly: [{ name: 'corner', assembly: [{ name: 'bolt' }] }, { name: 'plate' }],
        });
        for (const name of ['frame', 'corner', 'bolt', 'plate']) {
            assert.deepStrictEqual(drawn.get(name), DEFAULT_APPEARANCE, name);
        }
    });

    test('stating the default colour is the same as stating nothing, down to the material', () => {
        // One material per key: a part that says "#DAA520" looks exactly like one
        // that says nothing, so it must not cost a material of its own.
        assert.strictEqual(appearanceKey(parseColor('#DAA520')!), appearanceKey(DEFAULT_APPEARANCE));
        assert.strictEqual(appearanceKey(DEFAULT_APPEARANCE), 'daa520ff');
        assert.notStrictEqual(appearanceKey(parseColor('#DAA52080')!), appearanceKey(DEFAULT_APPEARANCE));
        assert.notStrictEqual(appearanceKey(parseColor('#DAA521')!), appearanceKey(DEFAULT_APPEARANCE));
    });

    test('a line across a shape is a deeper shade of it, and still a line on a dark one', () => {
        // The default has a name for its deeper shade.
        assert.strictEqual(DEFAULT_EDGE_COLOR, 0xb8860b);
        assert.strictEqual(edgeColor(DEFAULT_COLOR), DEFAULT_EDGE_COLOR);

        const lightness = (color: number) => {
            const hsl = { h: 0, s: 0, l: 0 };
            new THREE.Color().setHex(color, THREE.SRGBColorSpace).getHSL(hsl, THREE.SRGBColorSpace);
            return hsl.l;
        };
        // Any other light colour is darkened...
        for (const color of [0xff0000, 0x336699, 0xffffff, 0xc0c0c0]) {
            assert.ok(lightness(edgeColor(color)) < lightness(color), color.toString(16));
        }
        // ...and a dark one, which a darker line would vanish into, is lightened.
        for (const color of [0x000000, 0x202020, 0x101040]) {
            assert.ok(lightness(edgeColor(color)) > lightness(color), color.toString(16));
        }
    });
});
