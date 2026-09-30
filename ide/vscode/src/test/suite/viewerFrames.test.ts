//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// PartCAD's coordinate frame against glTF's.
//
// A shape tree states every placement - a node's location and a port's - in
// millimetres about a Z-up frame, while the geometry at its nodes arrives in
// metres about a Y-up one, already converted by the exporter. The conversion
// between the two is therefore applied to the placements and not to the geometry,
// and it is a conjugation; see 'src/webview/frames.ts'.
//
// This is the one piece of arithmetic in the viewer that can be wrong without
// looking wrong. A missing scale or a flipped axis is obvious on screen - the
// model is a thousand times too big, or on its side - but a placement conjugated
// in the wrong order moves a part, or a port, to somewhere plausible and wrong. So
// it is checked here rather than by eye.
//

import * as assert from 'assert';
import * as THREE from 'three';

import { FROM_GLTF, TO_GLTF, asMatrix, placement, transformed } from '../../webview/frames';
import { Placement } from '../../webview/messages';

/** Where a point of PartCAD's frame lands once 'location' is applied, in glTF's. */
function moved(location: Placement | null, point: [number, number, number]): THREE.Vector3 {
    return new THREE.Vector3(...point).applyMatrix4(TO_GLTF).applyMatrix4(placement(location));
}

function near(got: THREE.Vector3, want: [number, number, number]): void {
    const expected = new THREE.Vector3(...want);
    assert.ok(got.distanceTo(expected) < 1e-9, `expected (${expected.toArray()}) but got (${got.toArray()})`);
}

suite('PartCAD placements in the glTF frame', () => {
    test("PartCAD's Z up is glTF's Y up, in metres", () => {
        // 20 mm up the Z axis is 0.02 m up the Y axis, and nowhere else.
        near(new THREE.Vector3(0, 0, 20).applyMatrix4(TO_GLTF), [0, 0.02, 0]);
        // And back again, which is what the conjugation's other half does.
        near(new THREE.Vector3(0, 0.02, 0).applyMatrix4(FROM_GLTF), [0, 0, 20]);
    });

    test('a node placed 20mm up is drawn 0.02 up, not 20', () => {
        near(moved([[0, 0, 20], [0, 0, 1], 0], [0, 0, 0]), [0, 0.02, 0]);
    });

    test('a port on a placed node composes with it', () => {
        // A port 5 mm up, on a node 20 mm up: 25 mm up.
        const node = placement([[0, 0, 20], [0, 0, 1], 0]);
        const port = new THREE.Vector3(0, 0, 5).applyMatrix4(TO_GLTF);
        near(port.applyMatrix4(node), [0, 0.025, 0]);
    });

    test('a rotation about Z is drawn as a rotation about Y', () => {
        // Turning 90 degrees about PartCAD's up axis takes +X to +Y there; in
        // glTF's frame that is +X to -Z. Anything else is a model that turns the
        // wrong way about the wrong axis.
        near(moved([[0, 0, 0], [0, 0, 1], 90], [10, 0, 0]), [0, 0, -0.01]);
    });

    test('a rotation and a translation are applied in that order', () => {
        // 'geom.Location' rotates about an axis through the origin and then
        // translates: (10,0,0) turned 90 degrees about Z is (0,10,0), and moved by
        // (10,0,0) it is (10,10,0). Applied the other way round it would be
        // (0,20,0), which is a plausible place and the wrong one.
        near(moved([[10, 0, 0], [0, 0, 1], 90], [10, 0, 0]), [0.01, 0, -0.01]);
    });

    test('the packed form is read the way PartCAD writes it', () => {
        // Straight from 'geom.Location.as_packed()': translation, axis, degrees.
        const matrix = asMatrix([[1, 2, 3], [0, 0, 1], 0]);
        near(new THREE.Vector3(0, 0, 0).applyMatrix4(matrix), [1, 2, 3]);
    });

    test('nothing said is nothing applied', () => {
        assert.ok(placement(null).equals(new THREE.Matrix4()));
        assert.ok(placement(undefined).equals(new THREE.Matrix4()));
    });

    test('a group carries a placement without giving up its own position', () => {
        const group = transformed(placement([[0, 0, 20], [0, 0, 1], 0]));
        near(group.position, [0, 0.02, 0]);
        // The renderer centres the model by moving a group, which a group whose
        // matrix was assigned by hand would ignore.
        assert.strictEqual(group.matrixAutoUpdate, true);
        near(group.scale, [1, 1, 1]);
    });

    test('a port sits under the conversion itself, not under a per-port one', () => {
        // Its own transform therefore stays expressed exactly as PartCAD stated it.
        const frame = transformed(TO_GLTF);
        frame.updateMatrix();
        near(new THREE.Vector3(0, 0, 20).applyMatrix4(frame.matrix), [0, 0.02, 0]);
    });
});
