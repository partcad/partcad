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
    ownAppearance,
    parseColor,
    primitiveAppearance,
    statedOneSided,
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

    test('a primitive the glTF colours keeps its colour, read back from the linear factors it was written in', () => {
        // What a part's glb carries for a face in '#C91A09' (see
        // 'wrapper_gltf._colored'), as three's loader reads the factor: linear.
        const material = new THREE.MeshStandardMaterial();
        material.color.setRGB(
            0.5840784311294556,
            0.01032982300966978,
            0.0027317428030073643,
            THREE.LinearSRGBColorSpace,
        );

        const own = ownAppearance(material, true);
        assert.deepStrictEqual(own, { color: 0xc91a09, opacity: 1 });
        // Its own colour wins over the node's, which is the part's or an
        // assembly's: a face is more specific than either.
        assert.deepStrictEqual(primitiveAppearance(own, DEFAULT_APPEARANCE), own);
        material.dispose();
    });

    test('a primitive with no material of its own keeps the colour of its node', () => {
        // three hands such a primitive a white default material, which is not a
        // colour anybody stated.
        const fallback = new THREE.MeshStandardMaterial({ color: 0xffffff });
        assert.strictEqual(ownAppearance(fallback, false), undefined);
        assert.strictEqual(ownAppearance(undefined, true), undefined);
        assert.strictEqual(ownAppearance([fallback], true), undefined);

        const red = parseColor('#C91A09')!;
        assert.deepStrictEqual(primitiveAppearance(undefined, red), red);
        fallback.dispose();
    });

    test("a see-through primitive is as see-through as its file blends it, and an opaque one's alpha means nothing", () => {
        const blended = new THREE.MeshStandardMaterial({ color: 0x00ff00, transparent: true, opacity: 0.5 });
        assert.deepStrictEqual(ownAppearance(blended, true), { color: 0x00ff00, opacity: 0.5 });

        const opaque = new THREE.MeshStandardMaterial({ color: 0x00ff00, transparent: false, opacity: 0.5 });
        assert.deepStrictEqual(ownAppearance(opaque, true), { color: 0x00ff00, opacity: 1 });
        blended.dispose();
        opaque.dispose();
    });

    test('a shape is drawn from both sides unless it says it is one-sided', () => {
        assert.strictEqual(DEFAULT_APPEARANCE.oneSided, undefined);
        assert.strictEqual(appearanceOf({ name: 'cube' }).oneSided, undefined);
        assert.deepStrictEqual(appearanceOf({ name: 'wall', properties: { oneSided: true } }), {
            ...DEFAULT_APPEARANCE,
            oneSided: true,
        });
        // Only a boolean says anything; a node stating something else is drawn as
        // if it had stated nothing.
        for (const value of ['true', 1, null, {}]) {
            const properties = { oneSided: value as unknown as boolean };
            assert.strictEqual(statedOneSided({ name: 'x', properties }), undefined, String(value));
        }
    });

    test('one-sidedness reaches the nodes under it, independently of the colour', () => {
        const drawn = drawnAs({
            name: 'room',
            properties: { oneSided: true },
            assembly: [
                { name: 'wall-1', properties: { color: '#E4DED4' } },
                { name: 'wall-2' },
                { name: 'sofa', properties: { oneSided: false, color: '#336699' } },
            ],
        });
        assert.deepStrictEqual(drawn.get('wall-1'), { color: 0xe4ded4, opacity: 1, oneSided: true });
        assert.deepStrictEqual(drawn.get('wall-2'), { ...DEFAULT_APPEARANCE, oneSided: true });
        assert.deepStrictEqual(drawn.get('sofa'), { color: 0x336699, opacity: 1 });

        // A colour stated above a one-sided wall colours it, and leaves it one-sided.
        const coloured = drawnAs({
            name: 'scene',
            properties: { color: '#FF0000' },
            assembly: [{ name: 'wall', properties: { oneSided: true } }],
        });
        assert.deepStrictEqual(coloured.get('wall'), { color: 0xff0000, opacity: 1, oneSided: true });
    });

    test('a one-sided shape has a material of its own', () => {
        // It culls the backs of faces, which no two-sided shape of the same colour
        // may share.
        const wall = appearanceOf({ name: 'wall', properties: { oneSided: true } });
        assert.strictEqual(appearanceKey(wall), 'daa520ff/front');
        assert.notStrictEqual(appearanceKey(wall), appearanceKey(DEFAULT_APPEARANCE));
    });

    test('a primitive in a colour of its own on a one-sided shape is one-sided too', () => {
        // A wall whose CMF colours one face differently is still a wall: the
        // colour is the face's, and which side it is seen from is the wall's.
        const own = { color: 0xc91a09, opacity: 1 };
        const wall = appearanceOf({ name: 'wall', properties: { oneSided: true } });
        assert.deepStrictEqual(primitiveAppearance(own, wall), { ...own, oneSided: true });
        assert.deepStrictEqual(primitiveAppearance(own, DEFAULT_APPEARANCE), own);
    });

    test('a primitive drawn with an image keeps the image, and the colour it is drawn as elsewhere', () => {
        // What a part's glb carries for faces in a colour drawn with an image (see
        // 'wrapper_gltf._with_textures'): the image as the base colour texture,
        // white under it, and the colour in the material's extras.
        const map = new THREE.Texture();
        const material = new THREE.MeshStandardMaterial({ color: 0xffffff, map });
        material.userData.partcadColor = '#781478';

        const own = ownAppearance(material, true);
        assert.deepStrictEqual(own, { color: 0x781478, opacity: 1, map });
        assert.deepStrictEqual(primitiveAppearance(own, DEFAULT_APPEARANCE), own);
        // A material per image: the same colour without it, or with another, is another look.
        assert.notStrictEqual(appearanceKey(own!), appearanceKey({ color: 0x781478, opacity: 1 }));
        const other = new THREE.Texture();
        assert.notStrictEqual(appearanceKey(own!), appearanceKey({ color: 0x781478, opacity: 1, map: other }));

        // A file that does not say what it stands for is drawn as white elsewhere.
        const unsaid = new THREE.MeshStandardMaterial({ color: 0xffffff, map });
        assert.strictEqual(ownAppearance(unsaid, true)?.color, 0xffffff);
        for (const disposable of [material, unsaid, map, other]) {
            disposable.dispose();
        }
    });

    test('a wall drawn with an image is one-sided and keeps its image', () => {
        // Wallpaper: the image is the face's, and which side it is seen from is the
        // wall's - and a material of its own, for each of the two.
        const map = new THREE.Texture();
        const own = { color: 0x781478, opacity: 1, map };
        const wall = appearanceOf({ name: 'wall', properties: { oneSided: true } });
        const drawn = primitiveAppearance(own, wall);
        assert.deepStrictEqual(drawn, { ...own, oneSided: true });
        assert.strictEqual(appearanceKey(drawn), `781478ff:${map.uuid}/front`);
        map.dispose();
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
