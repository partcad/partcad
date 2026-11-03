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

import {
    assemblyRows,
    calloutsOf,
    componentName,
    componentRows,
    hasCallouts,
    isComponent,
} from '../../webview/callouts';
import { ShowNode } from '../../webview/messages';
import { formatPrice } from '../../webview/supply';

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

    test('the Metadata box is offered for a model with something to pin, and only then', () => {
        assert.strictEqual(hasCallouts(bends()), true);
        assert.strictEqual(hasCallouts({ name: 'plain', gltfRef: 'solid' }), false);
        assert.strictEqual(hasCallouts(null), false);
        assert.strictEqual(hasCallouts(undefined), false);
        // Annotated elements that say nothing are not something to pin.
        assert.strictEqual(hasCallouts({ metadata: { annotations: [{ points: [[0, 0, 0]], metadata: {} }] } }), false);
    });

    test('an assembly offers it when any part it holds has something to pin', () => {
        const assembly: ShowNode = { name: 'bracket-assembly', assembly: [{ name: 'bolt' }, bends()] };
        assert.strictEqual(hasCallouts(assembly), true);
    });
});

// What the "Component names" and "Component prices" boxes put on a component:
// one callout, its name over its price. The name is the 2D tab's too - see
// 'component_name' in 'render_svg.py', whose test pins the same two cases.
suite('What a component callout says', () => {
    test('a component is named by its link, and otherwise by its object without the package', () => {
        assert.strictEqual(componentName({ name: '//pkg:cube', label: 'left' }), 'left');
        assert.strictEqual(componentName({ name: '//pub/robotics:bolt', label: null }), 'bolt');
        assert.strictEqual(componentName({ name: 'bare' }), 'bare');
    });

    test('a component is a node that holds no other', () => {
        assert.strictEqual(isComponent({ name: '//pkg:bolt' }), true);
        assert.strictEqual(isComponent({ name: '//pkg:top', assembly: [{ name: '//pkg:bolt' }] }), false);
    });

    test('the name is over the price, each where its box is ticked', () => {
        const both = { componentNames: true, componentPrices: true };
        assert.deepStrictEqual(componentRows('bolt', '$0.25', both), ['bolt', '$0.25']);
        assert.deepStrictEqual(componentRows('bolt', '$0.25', { ...both, componentPrices: false }), ['bolt']);
        assert.deepStrictEqual(componentRows('bolt', '$0.25', { ...both, componentNames: false }), ['$0.25']);
    });

    test('a component nobody quoted has no price row, and with only prices asked no callout', () => {
        assert.deepStrictEqual(componentRows('bolt', undefined, { componentNames: true, componentPrices: true }), [
            'bolt',
        ]);
        assert.deepStrictEqual(componentRows('bolt', undefined, { componentNames: false, componentPrices: true }), []);
    });
});

// An assembly sold assembled is one thing to order: its price goes on a callout
// of its own, and the parts inside it have none. Pinned on the 2D tab's picture
// by '_components' in 'render_svg.py', which test_render_callouts.py holds to
// the same rows.
suite('What the callout of an assembly says', () => {
    const both = { componentNames: true, componentPrices: true };

    test('an assembly sold assembled is named over its price', () => {
        assert.deepStrictEqual(assemblyRows('gearbox', '$120.00', both), ['gearbox', '$120.00']);
        assert.deepStrictEqual(assemblyRows('gearbox', '$120.00', { ...both, componentNames: false }), ['$120.00']);
    });

    test('an assembly with no price of its own says nothing: its parts carry their names', () => {
        assert.deepStrictEqual(assemblyRows('frame', undefined, both), []);
        assert.deepStrictEqual(assemblyRows('gearbox', '$120.00', { ...both, componentPrices: false }), []);
    });
});

// What a price is written as on screen: a component's callout and the Buy tab
// both write it through 'formatPrice', and the 2D tab's picture writes it the
// same way ('price_label' in 'render_overlay.py').
suite('How a price is written on screen', () => {
    test('dollars are written as dollars, whatever the locale', () => {
        assert.strictEqual(formatPrice(0.4, 'USD'), '$0.40');
        assert.strictEqual(formatPrice(1234.5, 'usd'), '$1,234.50');
    });

    test('a price nobody said the currency of is a number', () => {
        assert.strictEqual(formatPrice(2, null), '2.00');
        assert.strictEqual(formatPrice(undefined, 'USD'), '');
    });
});
