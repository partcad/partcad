//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the shared geometry table means to this side.
//
// PartCAD sends one entry per distinct shape with the nodes naming entries, so an
// assembly that places one bolt a hundred times arrives as a hundred nodes and one
// piece of geometry (see 'partcad/shape_envelope.py'). What that changes here is
// what there is to parse and therefore what the loading readout is a fraction of:
// counting a shared shape once per node would report a download that never happened
// and a bar that reached one percent of a model already on screen.
//
// The rest of the sharing - one upload, one material, a clone per node - lives in
// 'scene.ts', which builds a WebGL renderer at import and so cannot be loaded here.
//

import * as assert from 'assert';

import { ShowNode } from '../../webview/messages';
import { totalSize, walk } from '../../webview/nodes';

/** A tree of 'count' nodes all made of one shape, as PartCAD would send it. */
function repeated(count: number, size: number): ShowNode {
    const children: ShowNode[] = [];
    for (let index = 0; index < count; index++) {
        children.push({ name: `bolt-${index}`, gltfRef: 'one-shape' });
    }
    return {
        name: '//pkg:frame',
        assembly: children,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        geometry: { 'one-shape': { gltf: 'Z2xURg==', size } },
    };
}

suite('The shared geometry table', () => {
    test('a shape the tree holds many times is measured once', () => {
        // The number the readout divides by is what arrives, not what is drawn.
        assert.strictEqual(totalSize(repeated(100, 4096)), 4096);
    });

    test('every distinct shape is measured', () => {
        const tree: ShowNode = {
            name: '//pkg:frame',
            assembly: [{ gltfRef: 'a' }, { gltfRef: 'b' }, { gltfRef: 'a' }],
            geometry: { a: { gltf: '', size: 1000 }, b: { gltf: '', size: 250 } },
        };
        assert.strictEqual(totalSize(tree), 1250);
    });

    test('a node carrying its geometry outright is still counted', () => {
        // Which is what a hand-written message or a test does; PartCAD sends the
        // table, and both have to add up for the readout to mean anything.
        const tree: ShowNode = {
            name: '//pkg:part',
            gltf: 'Z2xURg==',
            size: 512,
            assembly: [{ gltfRef: 'a' }],
            geometry: { a: { gltf: '', size: 64 } },
        };
        assert.strictEqual(totalSize(tree), 576);
    });

    test('a tree with nothing to draw measures nothing', () => {
        assert.strictEqual(totalSize({ name: '//pkg:iface', assembly: [] }), 0);
    });

    test('naming a shape is not the same as being one', () => {
        // The nodes stay distinct: they share geometry, not identity, which is why
        // each keeps its own name, its own placement and its own row in the pane.
        const tree = repeated(3, 10);
        const named: string[] = [];
        walk(tree, (node) => {
            if (node.gltfRef !== undefined) {
                named.push(node.name ?? '');
            }
        });
        assert.deepStrictEqual(named, ['bolt-0', 'bolt-1', 'bolt-2']);
        assert.strictEqual(Object.keys(tree.geometry ?? {}).length, 1);
    });
});
