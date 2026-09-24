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
