//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A viewpoint ('viewpoint.ts') read off an orbit camera, and put back onto one.
//
// The view panel speaks PartCAD's frame - millimetres, Z up, the frame of the
// object's root - and a 3D pane draws in its own: the 3D view in glTF's (metres,
// Y up) with the model moved to the middle of the stage, an analysis's result in
// whatever its file states. 'SceneFrame' is the difference between the two, and
// these are the only functions that cross it, so the 3D view and the result view
// cannot come to disagree about which way X is.
//
// The camera's own up stays the stage's up, always: the orbit controls turn
// about it and keep it, which is what makes the navigation a turntable. A view
// straight down the pole is put a hair's breadth off it, on the side its up
// vector says (see 'viewpoint.ts'), which is the one place the controls let a
// camera be and still say which way round it is.
//

import * as THREE from 'three';

import {
    Pole,
    Vec3,
    Viewpoint,
    Y_POLE,
    Z_POLE,
    add,
    fromTurntable,
    normalize,
    scale,
    sub,
    toTurntable,
} from './viewpoint';

/**
 * How a stage's coordinates relate to PartCAD's: 'stage = rotate(point) * size
 * + offset', where the rotation is glTF's (x, z, -y) for a stage that is Y up
 * and none for one that is not.
 */
export interface SceneFrame {
    /** Stage units per millimetre: 0.001 for glTF's metres. */
    size: number;
    /** Whether the stage is Y up and PartCAD's Z is its Y, as glTF is. */
    yUp: boolean;
    /** Where PartCAD's origin is on the stage. */
    offset: Vec3;
}

/** The pole a stage's camera turns about, in PartCAD's terms: its Y, which is PartCAD's Z when the stage is glTF's. */
export function poleOf(frame: SceneFrame): Pole {
    return frame.yUp ? Z_POLE : Y_POLE;
}

function turn(vector: Vec3, frame: SceneFrame): Vec3 {
    return frame.yUp ? [vector[0], vector[2], -vector[1]] : vector;
}

function unturn(vector: Vec3, frame: SceneFrame): Vec3 {
    return frame.yUp ? [vector[0], -vector[2], vector[1]] : vector;
}

/** A point of PartCAD's frame, on the stage. */
export function toStage(point: Vec3, frame: SceneFrame): Vec3 {
    return add(scale(turn(point, frame), frame.size), frame.offset);
}

/** A point of the stage, in PartCAD's frame. */
export function fromStage(point: Vec3, frame: SceneFrame): Vec3 {
    return unturn(scale(sub(point, frame.offset), 1 / frame.size), frame);
}

/** A direction or a displacement of the stage, in PartCAD's frame: turned and scaled, never moved. */
export function vectorFromStage(vector: Vec3, frame: SceneFrame): Vec3 {
    return unturn(scale(vector, 1 / frame.size), frame);
}

/** How far off the pole a view straight down it is put, in radians: well clear of the controls' own limit. */
const OFF_POLE = 1e-4;

/** The stage's up, which every stage's camera turns about (see the header). */
const STAGE_UP = new THREE.Vector3(0, 1, 0);

/**
 * 'direction' turned about the stage's up to where 'heading' points round it,
 * its height above the turntable kept: how the 3D view frames a new object
 * while Animate is turning the camera, so that the new object comes in at the
 * angle the last one had reached and the turn carries on, rather than every
 * show starting again from the same side.
 *
 * Only the azimuth is taken from 'heading', and not its elevation or its
 * length, which are what framing decides. A 'heading' straight up or down the
 * pole has no azimuth to take, and 'direction' comes back as it was. The angle
 * is the orbit controls' own, measured about Y from +Z towards +X.
 */
export function turnedLike(direction: THREE.Vector3, heading: THREE.Vector3): THREE.Vector3 {
    const turned = direction.clone();
    if (Math.hypot(heading.x, heading.z) < 1e-9 || Math.hypot(direction.x, direction.z) < 1e-9) {
        return turned;
    }
    const by = Math.atan2(heading.x, heading.z) - Math.atan2(direction.x, direction.z);
    return turned.applyAxisAngle(STAGE_UP, by);
}

/** Where 'camera' is looking from, at 'target', in PartCAD's frame. */
export function readViewpoint(camera: THREE.Camera, target: THREE.Vector3, frame: SceneFrame): Viewpoint {
    const offset = camera.position.clone().sub(target);
    // The picture's up as the camera holds it, which is the pole as seen from
    // there - not the camera's 'up', which is the pole itself.
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
    const read: Viewpoint = {
        origin: vectorFromStage([offset.x, offset.y, offset.z], frame),
        up: normalize(vectorFromStage([up.x, up.y, up.z], frame)) ?? [0, 0, 1],
        target: fromStage([target.x, target.y, target.z], frame),
    };
    // A camera that 'placeCamera' put a hair's breadth off the pole is on it,
    // as far as anybody reading the view is concerned: the top view is
    // "0, 0, 100" and not "0, -0.008, 100".
    const pole = poleOf(frame);
    const turntable = toTurntable(read, pole);
    if (turntable.polar < 2 * OFF_POLE || turntable.polar > Math.PI - 2 * OFF_POLE) {
        turntable.polar = turntable.polar < Math.PI / 2 ? 0 : Math.PI;
        return fromTurntable(turntable, read.target, pole);
    }
    return read;
}

/**
 * Put 'camera' where 'viewpoint' says, looking at it from there, as the orbit
 * controls can hold it: on the turntable about the stage's up, a hair's breadth
 * off the pole when it is on it. A roll the turntable cannot hold is dropped.
 */
export function placeCamera(
    camera: THREE.Camera,
    target: THREE.Vector3,
    viewpoint: Viewpoint,
    frame: SceneFrame,
): void {
    const pole = poleOf(frame);
    const turntable = toTurntable(viewpoint, pole);
    turntable.polar = Math.max(OFF_POLE, Math.min(Math.PI - OFF_POLE, turntable.polar));
    const placed = fromTurntable(turntable, viewpoint.target, pole);
    const at = toStage(placed.target, frame);
    const from = toStage(add(placed.target, placed.origin), frame);
    target.set(at[0], at[1], at[2]);
    camera.position.set(from[0], from[1], from[2]);
    camera.lookAt(target);
}
