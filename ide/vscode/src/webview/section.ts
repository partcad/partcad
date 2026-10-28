//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A cross-section: how much of the object on screen is kept along each axis.
//
// Three ranges, one per axis of the object's frame - millimetres, Z up, the frame
// of its tree's root - each the slab to keep, and together a box. The view panel
// sets one slider per axis, its two ends starting at the two faces of the
// object's bounding box; an end moved inwards cuts from that side. The cut itself
// is PartCAD's: the box is sent with the request ('inspect.object' for the 3D
// view, 'render.inline' for a picture or a drawing) and the geometry comes back
// cut, because a cut is a CAD operation and this renderer has no CAD kernel (see
// 'partcad/shape_section.py').
//
// What is sent names only the axes that cut. An axis whose slider still spans the
// whole object says nothing, and a section that names no axis is no section at
// all - null, which is what every request sends for the whole object, and what
// keeps a show of an uncut object exactly the question it always was.
//
// The bounds are read off the tree rather than off the geometry on screen, for
// the reason 'shape_gltf.size_of' reads them there: every node carries the box
// it was measured in as it was built, in its own frame, so the object's is those
// boxes placed down the tree and bounded again. And a cut object reports the
// object's own boxes - PartCAD leaves what a node says about its size alone when
// it cuts it - so the sliders go on spanning the object rather than shrinking to
// whatever the last cut kept.
//
// No three.js here, for the reason 'viewpoint.ts' has none.
//

import { Placement, ShowNode } from './messages';
import { Vec3 } from './viewpoint';

/** The axes a section cuts along, in the order of a point's coordinates. */
export const SECTION_AXES = ['x', 'y', 'z'] as const;
export type SectionAxis = (typeof SECTION_AXES)[number];

/** What is kept along one axis: from, to. */
export type Range = [number, number];

/** A cross-section as it travels: the axes that cut, each with the slab it keeps. */
export type Section = Partial<Record<SectionAxis, Range>>;

/** A box, by its two corners. */
export interface Bounds {
    min: Vec3;
    max: Vec3;
}

/** A rotation and a translation: a placement, as arithmetic. */
interface Transform {
    rotation: number[];
    translation: Vec3;
}

const IDENTITY: Transform = { rotation: [1, 0, 0, 0, 1, 0, 0, 0, 1], translation: [0, 0, 0] };

/** A packed PartCAD placement - rotation about an axis, then translation - as a transform. */
function transformOf(location: Placement): Transform {
    const [translation, axis, angle] = location;
    const size = Math.hypot(axis[0], axis[1], axis[2]);
    if (size === 0 || angle === 0) {
        return { rotation: [...IDENTITY.rotation], translation: [...translation] as Vec3 };
    }
    const [x, y, z] = [axis[0] / size, axis[1] / size, axis[2] / size];
    const theta = (angle * Math.PI) / 180;
    const c = Math.cos(theta);
    const s = Math.sin(theta);
    const t = 1 - c;
    return {
        rotation: [
            t * x * x + c,
            t * x * y - s * z,
            t * x * z + s * y,
            t * x * y + s * z,
            t * y * y + c,
            t * y * z - s * x,
            t * x * z - s * y,
            t * y * z + s * x,
            t * z * z + c,
        ],
        translation: [...translation] as Vec3,
    };
}

function rotate(rotation: number[], point: Vec3): Vec3 {
    return [
        rotation[0] * point[0] + rotation[1] * point[1] + rotation[2] * point[2],
        rotation[3] * point[0] + rotation[4] * point[1] + rotation[5] * point[2],
        rotation[6] * point[0] + rotation[7] * point[1] + rotation[8] * point[2],
    ];
}

function apply(transform: Transform, point: Vec3): Vec3 {
    const turned = rotate(transform.rotation, point);
    return [
        turned[0] + transform.translation[0],
        turned[1] + transform.translation[1],
        turned[2] + transform.translation[2],
    ];
}

/** 'outer' after 'inner': a point placed by 'inner', then by 'outer'. */
function compose(outer: Transform, inner: Transform): Transform {
    const a = outer.rotation;
    const b = inner.rotation;
    const rotation: number[] = [];
    for (let row = 0; row < 3; row++) {
        for (let column = 0; column < 3; column++) {
            rotation.push(a[row * 3] * b[column] + a[row * 3 + 1] * b[3 + column] + a[row * 3 + 2] * b[6 + column]);
        }
    }
    return { rotation, translation: apply(outer, inner.translation) };
}

/** The box a node says it was measured in, in its own frame, or undefined. */
function measuredBox(node: ShowNode): number[] | undefined {
    const measurements = node.metadata?.measurements as { bbox?: unknown } | undefined;
    const box = measurements?.bbox;
    if (!Array.isArray(box) || box.length !== 6 || !box.every((value) => typeof value === 'number')) {
        return undefined;
    }
    return box as number[];
}

/**
 * What the object occupies, in the frame of its root, or undefined when its tree
 * records no size at all.
 *
 * The placements are composed on the way down, and a node's box is placed by its
 * eight corners rather than its two extremes, as 'shape_gltf.size_of' does it: a
 * turned box's extremes are not the extremes of the turned box. Only the nodes
 * count - a port's sketch sits at a port, inside the object it belongs to.
 */
export function boundsOf(object: ShowNode | null | undefined): Bounds | undefined {
    if (object === null || object === undefined) {
        return undefined;
    }
    const min: Vec3 = [Infinity, Infinity, Infinity];
    const max: Vec3 = [-Infinity, -Infinity, -Infinity];
    const walk = (node: ShowNode, parent: Transform) => {
        const placed = node.location ? compose(parent, transformOf(node.location)) : parent;
        const box = measuredBox(node);
        if (box !== undefined) {
            for (const x of [box[0], box[3]]) {
                for (const y of [box[1], box[4]]) {
                    for (const z of [box[2], box[5]]) {
                        const corner = apply(placed, [x, y, z]);
                        for (let axis = 0; axis < 3; axis++) {
                            min[axis] = Math.min(min[axis], corner[axis]);
                            max[axis] = Math.max(max[axis], corner[axis]);
                        }
                    }
                }
            }
        }
        for (const child of node.assembly ?? []) {
            walk(child, placed);
        }
    };
    walk(object, IDENTITY);
    if (!Number.isFinite(min[0])) {
        return undefined;
    }
    return { min, max };
}

/** How far inside the object's own face an end has to be before it counts as a cut: a part in a million of its size. */
function slack(bounds: Bounds, axis: number): number {
    return 1e-6 * Math.max(1, bounds.max[axis] - bounds.min[axis]);
}

/**
 * The section the three ranges are, against the object's bounds: only the axes
 * whose range keeps less than the object does, held inside the bounds. Null when
 * none does, which is the whole object.
 */
export function sectionOf(ranges: Partial<Record<SectionAxis, Range>>, bounds: Bounds): Section | null {
    const section: Section = {};
    SECTION_AXES.forEach((axis, index) => {
        const range = ranges[axis];
        if (range === undefined) {
            return;
        }
        const low = Math.max(Math.min(range[0], range[1]), bounds.min[index]);
        const high = Math.min(Math.max(range[0], range[1]), bounds.max[index]);
        const tolerance = slack(bounds, index);
        if (low <= bounds.min[index] + tolerance && high >= bounds.max[index] - tolerance) {
            return;
        }
        if (high - low <= tolerance) {
            // Nothing left between the two ends: a section keeps something.
            return;
        }
        section[axis] = [low, high];
    });
    return Object.keys(section).length > 0 ? section : null;
}

/** The range one axis keeps under 'section': its own, or the whole of the object. */
export function rangeOf(section: Section | null | undefined, axis: SectionAxis, bounds: Bounds): Range {
    const index = SECTION_AXES.indexOf(axis);
    return section?.[axis] ?? [bounds.min[index], bounds.max[index]];
}

/** Whether two sections cut the same, to a part in a million. */
export function sameSection(a: Section | null | undefined, b: Section | null | undefined): boolean {
    const left = a ?? {};
    const right = b ?? {};
    return SECTION_AXES.every((axis) => {
        const one = left[axis];
        const other = right[axis];
        if (one === undefined || other === undefined) {
            return one === other;
        }
        const tolerance = 1e-6 * Math.max(1, Math.abs(one[0]), Math.abs(one[1]));
        return Math.abs(one[0] - other[0]) <= tolerance && Math.abs(one[1] - other[1]) <= tolerance;
    });
}

/** What a section is as a request carries it: PartCAD's own form, or null for none. */
export function sectionRequest(section: Section | null | undefined): Section | null {
    if (!section) {
        return null;
    }
    const request: Section = {};
    for (const axis of SECTION_AXES) {
        const range = section[axis];
        if (range !== undefined) {
            request[axis] = [range[0], range[1]];
        }
    }
    return Object.keys(request).length > 0 ? request : null;
}

/** A section read back from what PartCAD said it cut to, or null when it is not one. */
export function sectionFrom(value: unknown): Section | null {
    if (value === null || typeof value !== 'object') {
        return null;
    }
    const section: Section = {};
    for (const axis of SECTION_AXES) {
        const range = (value as Record<string, unknown>)[axis];
        if (
            Array.isArray(range) &&
            range.length === 2 &&
            typeof range[0] === 'number' &&
            typeof range[1] === 'number' &&
            range[0] < range[1]
        ) {
            section[axis] = [range[0], range[1]];
        }
    }
    return Object.keys(section).length > 0 ? section : null;
}

/** A section as one line: 'x 0 to 25 mm, z 0 to 12.5 mm', or 'nothing cut'. */
export function describeSection(section: Section | null | undefined): string {
    if (!section) {
        return 'nothing cut';
    }
    const parts = SECTION_AXES.filter((axis) => section[axis] !== undefined).map((axis) => {
        const [low, high] = section[axis]!;
        return `${axis} ${formatLength(low)} to ${formatLength(high)} mm`;
    });
    return parts.length > 0 ? parts.join(', ') : 'nothing cut';
}

/** A length in millimetres, to a sensible number of places for its size. */
export function formatLength(value: number): string {
    const digits = Math.abs(value) >= 100 ? 1 : Math.abs(value) >= 1 ? 2 : 3;
    const text = value.toFixed(digits).replace(/\.?0+$/, '');
    return text === '-0' ? '0' : text;
}
