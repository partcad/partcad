//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Where a view is looked at from, in the terms 'partcad.yaml' already uses.
//
// A viewpoint is three vectors in PartCAD's own frame - millimetres, Z up, the
// frame of the shown object's root:
//
//   * 'origin', where the camera is as seen from what it looks at. This is
//     'viewport_origin': a direction to look from, and in the 3D views also how
//     far away;
//   * 'up', which way is up in the picture: 'viewport_up';
//   * 'target', the point looked at. A rendered picture always looks at the
//     origin and is scaled to fit (see 'LOOK_AT' in 'render_svg.py'), so only
//     the 3D views have one to move.
//
// So what the view panel's fields say can be pasted into a 'render:' section or
// onto 'pc render --viewport-origin', and means the same picture there.
//
// The six axis views are 'render.VIEWS' - the X button is 'right', -Y is
// 'front', Z is 'top' and so on - with the same up vector each one names, so
// that the 2D tab's picture after "Z" is the one 'pc render --view top' draws.
//
// Turning a view by hand is a turntable, the way the 3D view's orbit controls
// turn: about a pole (Z, PartCAD's up), by an azimuth around it and a polar
// angle down from it, with the picture's up the pole as it looks from there.
// Written as two angles rather than as a rotation of the camera because that is
// what the orbit controls keep, and a view the panel produced has to be one
// they can hold. The one subtlety is at the poles: looking straight down Z, the
// line of sight says nothing about which way round the camera is, so there the
// up vector says it (the top view's up is +Y because the camera came from -Y),
// and the camera is put a hair's breadth off the pole that way when it is drawn.
//
// No three.js here: this is arithmetic the panel, the gizmo, the 2D tab and the
// tests all share, and 'scene.ts' cannot be imported outside a browser.
//

export type Vec3 = [number, number, number];

export interface Viewpoint {
    /** Where the camera is, as seen from 'target': 'viewport_origin', in millimetres. */
    origin: Vec3;
    /** Which way is up in the picture: 'viewport_up'. */
    up: Vec3;
    /** The point looked at, in the frame of the object's root, in millimetres. */
    target: Vec3;
}

/** One of the six views along an axis, by the axis and the side it is looked at from. */
export type AxisView = 'x' | '-x' | 'y' | '-y' | 'z' | '-z';

/** The six, in the order the panel's buttons are in. */
export const AXIS_VIEWS: readonly AxisView[] = ['x', '-x', 'y', '-y', 'z', '-z'];

/**
 * Each axis view as 'render.VIEWS' names it: where it looks from, which way is
 * up, and what 'pc render --view' calls it. The two must not drift apart - a
 * test reads 'src/partcad/render.py' to hold them together.
 */
export const AXIS_DIRECTIONS: Readonly<Record<AxisView, { origin: Vec3; up: Vec3; view: string }>> = {
    x: { origin: [100, 0, 0], up: [0, 0, 1], view: 'right' },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '-x': { origin: [-100, 0, 0], up: [0, 0, 1], view: 'left' },
    y: { origin: [0, 100, 0], up: [0, 0, 1], view: 'back' },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '-y': { origin: [0, -100, 0], up: [0, 0, 1], view: 'front' },
    z: { origin: [0, 0, 100], up: [0, 1, 0], view: 'top' },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '-z': { origin: [0, 0, -100], up: [0, -1, 0], view: 'bottom' },
};

/** The corner a part is looked at from when nothing says otherwise: 'render.VIEWS["iso"]'. */
export const DEFAULT_VIEWPOINT: Viewpoint = { origin: [100, -100, 100], up: [0, 0, 1], target: [0, 0, 0] };

/**
 * What a turntable turns about: its pole, and the direction in its equator the
 * azimuth is measured from. The azimuth runs from 'zero' towards
 * 'pole x zero'.
 */
export interface Pole {
    axis: Vec3;
    zero: Vec3;
}

/** PartCAD's up: the pole every PartCAD view turns about, azimuth from +X towards +Y. */
export const Z_POLE: Pole = { axis: [0, 0, 1], zero: [1, 0, 0] };

/**
 * Y as the pole, azimuth from +Z towards +X: three.js's own up and the way its
 * orbit controls measure the angle, for a model drawn in the frame its file
 * states rather than in PartCAD's (an STL an analysis wrote).
 */
export const Y_POLE: Pole = { axis: [0, 1, 0], zero: [0, 0, 1] };

/** A view as a turntable holds it: two angles about a pole, in radians, and a distance. */
export interface Turntable {
    azimuth: number;
    /** From the pole: 0 looks straight down it, pi straight up it. */
    polar: number;
    distance: number;
}

const EPSILON = 1e-9;

export function add(a: Vec3, b: Vec3): Vec3 {
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

export function sub(a: Vec3, b: Vec3): Vec3 {
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

export function scale(a: Vec3, factor: number): Vec3 {
    return [a[0] * factor, a[1] * factor, a[2] * factor];
}

export function dot(a: Vec3, b: Vec3): number {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

export function cross(a: Vec3, b: Vec3): Vec3 {
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

export function length(a: Vec3): number {
    return Math.sqrt(dot(a, a));
}

/** 'a' scaled to length one, or undefined for one too short to have a direction. */
export function normalize(a: Vec3): Vec3 | undefined {
    const size = length(a);
    return size > EPSILON ? scale(a, 1 / size) : undefined;
}

/** The axis view 'axis', at the distance 'current' is at and looking at what it looks at. */
export function axisView(axis: AxisView, current?: Viewpoint): Viewpoint {
    const { origin, up } = AXIS_DIRECTIONS[axis];
    const distance = current !== undefined ? length(current.origin) : length(origin);
    return {
        origin: scale(normalize(origin)!, distance > EPSILON ? distance : length(origin)),
        up: [...up] as Vec3,
        target: current !== undefined ? ([...current.target] as Vec3) : [0, 0, 0],
    };
}

/** The axis view 'viewpoint' is, if it is one: looking along an axis, with that view's up. */
export function axisOf(viewpoint: Viewpoint): AxisView | undefined {
    const back = normalize(viewpoint.origin);
    const up = normalize(viewpoint.up);
    if (back === undefined || up === undefined) {
        return undefined;
    }
    return AXIS_VIEWS.find((axis) => {
        const view = AXIS_DIRECTIONS[axis];
        return dot(back, normalize(view.origin)!) > 1 - 1e-6 && dot(up, view.up) > 1 - 1e-6;
    });
}

function equatorOf(pole: Pole): [Vec3, Vec3] {
    return [pole.zero, cross(pole.axis, pole.zero)];
}

/** 'viewpoint' as a turntable about 'pole' holds it. A roll the turntable cannot hold is dropped. */
export function toTurntable(viewpoint: Viewpoint, pole: Pole = Z_POLE): Turntable {
    const distance = length(viewpoint.origin);
    const back = normalize(viewpoint.origin) ?? normalize(DEFAULT_VIEWPOINT.origin)!;
    const along = Math.max(-1, Math.min(1, dot(back, pole.axis)));
    const [first, second] = equatorOf(pole);
    let heading = normalize(sub(back, scale(pole.axis, along)));
    if (heading === undefined) {
        // On the pole: the line of sight says nothing about which way round the
        // camera is, and the picture's up says it instead. Looking down the pole
        // up is away from where the camera came from; looking up it, towards.
        const upright = normalize(sub(viewpoint.up, scale(pole.axis, dot(viewpoint.up, pole.axis))));
        heading = upright === undefined ? scale(second, -1) : along > 0 ? scale(upright, -1) : upright;
    }
    return {
        azimuth: Math.atan2(dot(heading, second), dot(heading, first)),
        polar: Math.acos(along),
        distance: distance > EPSILON ? distance : length(DEFAULT_VIEWPOINT.origin),
    };
}

/**
 * The viewpoint a turntable about 'pole' is at, looking at 'target'.
 *
 * Its up is the pole as it is seen from there - 'sin(polar) * pole - cos(polar)
 * * heading', which is a unit vector at the poles too: straight down the pole,
 * up is away from the heading the camera came from.
 */
export function fromTurntable(turntable: Turntable, target: Vec3, pole: Pole = Z_POLE): Viewpoint {
    const [first, second] = equatorOf(pole);
    const heading = add(scale(first, Math.cos(turntable.azimuth)), scale(second, Math.sin(turntable.azimuth)));
    const sine = Math.sin(turntable.polar);
    const cosine = Math.cos(turntable.polar);
    const back = add(scale(heading, sine), scale(pole.axis, cosine));
    return {
        origin: scale(back, turntable.distance),
        up: sub(scale(pole.axis, sine), scale(heading, cosine)),
        target: [...target] as Vec3,
    };
}

/**
 * 'viewpoint' turned on the turntable: 'azimuth' about the pole and 'polar'
 * towards it, both in radians, the polar angle held between the two poles.
 */
export function orbit(viewpoint: Viewpoint, azimuth: number, polar: number, pole: Pole = Z_POLE): Viewpoint {
    const turntable = toTurntable(viewpoint, pole);
    turntable.azimuth += azimuth;
    turntable.polar = Math.max(0, Math.min(Math.PI, turntable.polar + polar));
    return fromTurntable(turntable, viewpoint.target, pole);
}

/** The picture's own axes, seen from 'viewpoint': to the right, up, and back towards the camera. */
export function basis(viewpoint: Viewpoint): { right: Vec3; up: Vec3; back: Vec3 } {
    const back = normalize(viewpoint.origin) ?? normalize(DEFAULT_VIEWPOINT.origin)!;
    const forward = scale(back, -1);
    let right = normalize(cross(forward, viewpoint.up));
    if (right === undefined) {
        // An up along the line of sight names no orientation; any will do.
        right = normalize(cross(forward, Math.abs(back[2]) < 0.9 ? [0, 0, 1] : [0, 1, 0]))!;
    }
    return { right, up: cross(right, forward), back };
}

/** Where one axis end lands on a picture taken from a viewpoint, and how near the viewer it is. */
export interface ProjectedAxis {
    axis: AxisView;
    /** To the right of the centre, in units of the axis's length. */
    x: number;
    /** Up from the centre, in the same units. */
    y: number;
    /** Towards the viewer: 1 points straight at them, -1 straight away. */
    depth: number;
}

/** The six axis ends as an orientation gizmo draws them: projected, farthest first. */
export function projectAxes(viewpoint: Viewpoint): ProjectedAxis[] {
    const { right, up, back } = basis(viewpoint);
    return AXIS_VIEWS.map((axis) => {
        const direction = normalize(AXIS_DIRECTIONS[axis].origin)!;
        return { axis, x: dot(direction, right), y: dot(direction, up), depth: dot(direction, back) };
    }).sort((a, b) => a.depth - b.depth);
}

/** Why 'viewpoint' cannot be looked from, or undefined when it can. The rules 'render.resolve_viewport' has. */
export function problemWith(viewpoint: Viewpoint): string | undefined {
    if (normalize(viewpoint.origin) === undefined) {
        return 'The origin is a direction to look from, and cannot be zero';
    }
    if (normalize(viewpoint.up) === undefined) {
        return 'Up is a direction, and cannot be zero';
    }
    if (normalize(cross(viewpoint.origin, viewpoint.up)) === undefined) {
        return 'Up cannot be along the line of sight: it would not say which way is up';
    }
    for (const vector of [viewpoint.origin, viewpoint.up, viewpoint.target]) {
        if (!vector.every(Number.isFinite)) {
            return 'Every coordinate has to be a number';
        }
    }
    return undefined;
}

/** Whether two viewpoints are the same one, to a part in a million of their size. */
export function sameViewpoint(a: Viewpoint | undefined, b: Viewpoint | undefined): boolean {
    if (a === undefined || b === undefined) {
        return a === b;
    }
    const tolerance = 1e-6 * Math.max(1, length(a.origin), length(a.target));
    return (['origin', 'up', 'target'] as const).every((key) => length(sub(a[key], b[key])) <= tolerance);
}

/**
 * A vector as the panel writes it: 'x, y, z', each to 'digits' places, with
 * what is only a rounding error of the rest written as 0 - a top view turned a
 * hair's breadth off the pole is "0, 0, 100" and not "0, -1e-4, 100".
 */
export function formatVector(vector: Vec3, digits = 3): string {
    const size = length(vector);
    return vector
        .map((component) => {
            const kept = Math.abs(component) <= 1e-6 * size ? 0 : component;
            const text = kept.toFixed(digits).replace(/\.?0+$/, '');
            return text === '-0' ? '0' : text;
        })
        .join(', ');
}

/**
 * A vector typed or pasted into the panel: three numbers, separated by commas
 * or spaces, in brackets or not - '1, 2, 3', '[1, 2, 3]' and '1 2 3' alike, so
 * that what YAML, the command line and the field itself write all read back.
 * Undefined for anything else.
 */
export function parseVector(text: string): Vec3 | undefined {
    const inner = text
        .trim()
        .replace(/^[[(]\s*/, '')
        .replace(/\s*[\])]$/, '');
    const parts = inner.split(/[\s,;]+/).filter((part) => part.length > 0);
    if (parts.length !== 3) {
        return undefined;
    }
    const numbers = parts.map((part) => (/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(part) ? Number(part) : NaN));
    return numbers.every(Number.isFinite) ? (numbers as Vec3) : undefined;
}
