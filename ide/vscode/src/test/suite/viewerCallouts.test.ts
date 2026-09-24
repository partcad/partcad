//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the 3D view pins to a shape out of its metadata.
//
// A sheet metal drawing says, against each bend line, how far and which way it
// bends - and nothing about the two lines themselves says which is which. That
// arrives as the node's 'metadata.annotations', one record per element, and
// 'callouts.ts' turns it into the text the viewer pins to each element. Drawing
// the callouts is 'scene.ts', which cannot be loaded here; what they say and
// where they go is this.
//

import * as assert from 'assert';

import { calloutsOf } from '../../webview/callouts';
import { ShowNode } from '../../webview/messages';

/** The node the sheet metal example's drawing arrives as, as far as this reads it. */
function bends(): ShowNode {
    return {
        name: '//pub/examples/partcad/produce_part_sheet_metal:panel',
        gltfRef: 'lines',
        metadata: {
            annotations: [
                {
                    type: 'LWPOLYLINE',
                    layer: 'OUTLINE',
                    points: [
                        [0, 0, 0],
                        [120, 0, 0],
                        [120, 40, 0],
                        [0, 40, 0],
                    ],
                    metadata: {},
                },
                {
                    type: 'LINE',
                    layer: 'BEND_UP',
                    points: [
                        [30, 0, 0],
                        [30, 40, 0],
                    ],
                    metadata: { angle: '90', radius: '2', direction: 'up' },
                },
                {
                    type: 'LINE',
                    layer: 'BEND_DOWN',
                    points: [
                        [80, 0, 0],
                        [80, 40, 0],
                    ],
                    metadata: { angle: 90, direction: 'down' },
                },
            ],
            measurements: { bbox: [0, 0, 0, 120, 40, 0] },
        },
    };
}

suite('The callouts a node pins to its elements', () => {
    test('one per element something was said about, and none for the rest', () => {
        const callouts = calloutsOf(bends());
        assert.deepStrictEqual(
            callouts.map((callout) => callout.title),
            ['BEND_UP', 'BEND_DOWN'],
        );
    });

    test('each says what was said, as a line per key', () => {
        const [up, down] = calloutsOf(bends());
        assert.deepStrictEqual(up.lines, ['angle: 90', 'radius: 2', 'direction: up']);
        // A number reads the way the file stated it.
        assert.deepStrictEqual(down.lines, ['angle: 90', 'direction: down']);
    });

    test('each is pinned to the middle of its element, in millimetres', () => {
        const [up, down] = calloutsOf(bends());
        assert.deepStrictEqual(up.position, [30, 20, 0]);
        assert.deepStrictEqual(down.position, [80, 20, 0]);
    });

    test('a point stated in two dimensions lies in the plane of the drawing', () => {
        const [callout] = calloutsOf({
            metadata: {
                annotations: [
                    {
                        points: [
                            [0, 0],
                            [10, 0],
                        ],
                        metadata: { note: 'x' },
                    },
                ],
            },
        });
        assert.deepStrictEqual(callout.position, [5, 0, 0]);
        assert.strictEqual(callout.title, undefined);
    });

    test('a record with nowhere to be pinned is left out', () => {
        const node: ShowNode = {
            metadata: {
                annotations: [
                    { points: [], metadata: { angle: 90 } },
                    { metadata: { angle: 90 } },
                    { points: [['a', 'b'] as unknown as number[]], metadata: { angle: 90 } },
                ],
            },
        };
        assert.deepStrictEqual(calloutsOf(node), []);
    });

    test('a node with no metadata, or none about its elements, pins nothing', () => {
        assert.deepStrictEqual(calloutsOf({ name: 'plain' }), []);
        assert.deepStrictEqual(calloutsOf({ metadata: { measurements: {} } }), []);
        assert.deepStrictEqual(calloutsOf({ metadata: { annotations: 'not a list' as unknown as [] } }), []);
    });
});
