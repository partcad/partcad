//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What a node's metadata says about its individual elements, as text to pin to
// them.
//
// A shape's source can state things its geometry cannot: a sheet metal drawing
// writes the angle, the radius and the direction of a bend against the line it
// is folded along, and two identical lines are then a bend up and a bend down.
// PartCAD carries that beside the geometry as the node's 'metadata.annotations'
// (see 'partcad/shape_envelope.py'), one record per element, and it reaches this
// side with the rest of the node. This reads the records into callouts - a place
// to pin one, and the lines of text to pin there - and 'scene.ts' draws them.
//
// Two fields of a record are read and nothing else is assumed of it: 'points',
// where the element is, in the node's own frame and in millimetres; and
// 'metadata', what was said about it, as key/value pairs. An element nothing was
// said about gets no callout - a drawing of a few thousand lines would otherwise
// bury the few that say something. 'layer' is used as a heading where a record
// has one, because it is what the person who made the drawing called the thing.
//
// Free of three.js, so that it can be tested outside a browser; see
// 'src/test/suite/viewerCallouts.test.ts'.
//

import { ShowNode } from './messages';
import { walk } from './nodes';

/** One callout: where it is pinned, and what it says. */
export interface Callout {
    /** In the node's own frame, in millimetres - PartCAD's frame, not glTF's. */
    position: [number, number, number];
    /** What the element is called, where its record names it. */
    title?: string;
    /** One line per thing said about it, as 'key: value'. */
    lines: string[];
}

function isPoint(value: unknown): value is number[] {
    return (
        Array.isArray(value) &&
        value.length >= 2 &&
        value.length <= 3 &&
        value.every((ordinate) => typeof ordinate === 'number' && Number.isFinite(ordinate))
    );
}

/** A value as it reads in a callout: as it was stated, and structure as JSON. */
function text(value: unknown): string {
    if (value === null || value === undefined) {
        return '';
    }
    if (typeof value === 'object') {
        return JSON.stringify(value);
    }
    return String(value);
}

/**
 * The callouts one node's metadata asks for, in the order its records state them.
 *
 * A record with no points has nowhere to be pinned and is left out, as is one
 * with nothing said about it. The callout goes at the middle of the element's
 * points - the midpoint of a line, the centre of a circle - which is where a
 * reader looks for what a line is.
 */
export function calloutsOf(node: ShowNode): Callout[] {
    const annotations = node.metadata?.annotations;
    if (!Array.isArray(annotations)) {
        return [];
    }
    const callouts: Callout[] = [];
    for (const record of annotations) {
        if (record === null || typeof record !== 'object') {
            continue;
        }
        const said = record.metadata;
        if (said === null || typeof said !== 'object' || Array.isArray(said)) {
            continue;
        }
        const lines = Object.entries(said).map(([key, value]) => `${key}: ${text(value)}`);
        if (lines.length === 0) {
            continue;
        }
        const points = Array.isArray(record.points) ? record.points.filter(isPoint) : [];
        if (points.length === 0) {
            continue;
        }
        const position: [number, number, number] = [0, 1, 2].map(
            (axis) => points.reduce((sum, point) => sum + (point[axis] ?? 0), 0) / points.length,
        ) as [number, number, number];
        const callout: Callout = { position, lines };
        if (typeof record.layer === 'string' && record.layer !== '') {
            callout.title = record.layer;
        }
        callouts.push(callout);
    }
    return callouts;
}

/**
 * Whether anything in this object's tree has a callout to show.
 *
 * What decides whether the Metadata box is offered at all: a box that switches
 * nothing on or off is a question the model has no answer to. Every node the
 * renderer draws is asked, not just the root, because an assembly's metadata is
 * its parts'.
 */
export function hasCallouts(root: ShowNode | null | undefined): boolean {
    if (!root) {
        return false;
    }
    let found = false;
    walk(root, (node) => {
        found = found || calloutsOf(node).length > 0;
    });
    return found;
}

/**
 * What a component is called in its callout.
 *
 * Its label - what the assembly holding it calls that link, which is the row
 * the tree lists it as - and, where it has none (the object shown on its own),
 * the name of the object it is without the package: every callout of one model
 * would carry the same package, and only be longer for it. The twin of
 * 'component_name' in 'src/partcad/builtin/render/render_svg.py', so that the
 * 2D tab's picture and the 3D view call one part one thing.
 */
export function componentName(node: ShowNode): string {
    if (node.label) {
        return node.label;
    }
    const name = node.name ?? '';
    return name.split(':').pop() || name;
}

/**
 * Whether a node is a component: one that holds no other node - a part,
 * wherever it is placed. What the "Component names" and "Component prices"
 * callouts are on, here and on the 2D tab's picture.
 */
export function isComponent(node: ShowNode): boolean {
    return (node.assembly ?? []).length === 0;
}

/**
 * The rows of one component's callout, top first: its name where names are
 * asked for, and its price where prices are and it has one. No rows is no
 * callout - a part nobody quoted, with only the prices asked for.
 */
export function componentRows(
    name: string,
    price: string | undefined,
    choices: { componentNames: boolean; componentPrices: boolean },
): string[] {
    const rows: string[] = [];
    if (choices.componentNames) {
        rows.push(name);
    }
    if (choices.componentPrices && price !== undefined) {
        rows.push(price);
    }
    return rows;
}

/**
 * The rows of the callout of a node that holds others, top first: none unless
 * prices are asked for and it has one - an assembly sold assembled, which is
 * priced as one thing to order while the parts inside it are not priced at all
 * - and then its name where names are asked for, over its price. Without a
 * price it has nothing of its own to say: its parts carry their names. The
 * twin of what '_components' in 'render_svg.py' writes on the 2D tab's picture.
 */
export function assemblyRows(
    name: string,
    price: string | undefined,
    choices: { componentNames: boolean; componentPrices: boolean },
): string[] {
    if (!choices.componentPrices || price === undefined) {
        return [];
    }
    return choices.componentNames ? [name, price] : [price];
}
