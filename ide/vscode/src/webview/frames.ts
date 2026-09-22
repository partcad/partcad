//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// PartCAD's coordinate frame, and glTF's, and the one conversion between them.
//
// glTF's unit is the metre and its up axis is Y; PartCAD states everything in
// millimetres about a Z-up frame. 'build123d.export_gltf' applies the conversion
// to the geometry it writes, so the glTF of every node arrives already converted
// and must not be converted again - but nothing applies it to the *placements* a
// shape tree carries, and a tree carries a placement on every node and on every
// port.
//
// So this is where those are converted, and it is a conjugation rather than a
// multiplication: a placement L moves points in PartCAD's frame, and the same
// motion expressed in glTF's frame is TO_GLTF * L * FROM_GLTF - convert the point
// back into PartCAD's frame, move it there, convert the answer forward. Getting it
// wrong by a multiplication lays the model on its side or puts it a thousand times
// too far away; getting the order wrong moves a port to somewhere plausible and
// wrong, which is worse.
//
// It lives in a file of its own because it is arithmetic worth testing, and
// 'scene.ts' cannot be imported outside a browser - it builds a WebGL renderer as
// it loads.
//

import * as THREE from 'three';

import { Placement } from './messages';

export const MM_TO_M = 0.001;
export const Z_UP_TO_Y_UP = -Math.PI / 2;

/** PartCAD's frame expressed in glTF's, and back. */
export const TO_GLTF = new THREE.Matrix4()
    .makeRotationX(Z_UP_TO_Y_UP)
    .multiply(new THREE.Matrix4().makeScale(MM_TO_M, MM_TO_M, MM_TO_M));
export const FROM_GLTF = TO_GLTF.clone().invert();

/** The matrix a packed PartCAD placement is, in PartCAD's own frame. */
export function asMatrix(location: Placement): THREE.Matrix4 {
    const [translation, axis, angle] = location;
    const matrix = new THREE.Matrix4();
    const direction = new THREE.Vector3(axis[0], axis[1], axis[2]);
    if (direction.lengthSq() > 0) {
        // Rotation about an axis through the origin, then the translation: the
        // order 'geom.Location' builds the same transform in.
        matrix.makeRotationAxis(direction.normalize(), (angle * Math.PI) / 180);
    }
    matrix.setPosition(translation[0], translation[1], translation[2]);
    return matrix;
}

/** The transform a packed PartCAD placement is, in the frame the scene is drawn in. */
export function placement(location: Placement | null | undefined): THREE.Matrix4 {
    if (!location) {
        return new THREE.Matrix4();
    }
    return TO_GLTF.clone().multiply(asMatrix(location)).multiply(FROM_GLTF);
}

/**
 * A group carrying 'matrix' as its own transform.
 *
 * Decomposed rather than assigned, so the group keeps three's ordinary
 * 'matrixAutoUpdate': a group whose matrix is set by hand ignores every later
 * change to its position, and the renderer centres the model by moving one. Every
 * matrix this is given is a rotation, a uniform scale and a translation, which a
 * decomposition carries exactly.
 */
export function transformed(matrix: THREE.Matrix4): THREE.Group {
    const group = new THREE.Group();
    matrix.decompose(group.position, group.quaternion, group.scale);
    return group;
}
