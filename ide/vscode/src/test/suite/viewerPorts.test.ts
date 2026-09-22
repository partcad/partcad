//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// How a port is drawn: as a triad, and as the boundary it is drawn with.
//
// Both belong to the port, so both have to be named by it - one checkbox draws or
// hides the pair - and the boundary has to be the *same* blue as the Z axis beside
// it rather than a blue that looks close. Neither is something this machine can
// check by eye (the renderer needs WebGL, which 'scene.ts' builds at load), so the
// two facts are pinned here instead: the colour against what 'AxesHelper' actually
// puts in its geometry, and the naming against the ids the pane rows use.
//

import * as assert from 'assert';
import * as THREE from 'three';

import { ShowNode } from '../../webview/messages';
import { PORT_COLOR, groupPorts, portId } from '../../webview/nodes';

/** The colour 'AxesHelper' gives one end of one of its axes, in the working space. */
function axisColor(vertex: number): THREE.Color {
    const colors = new THREE.AxesHelper(1).geometry.getAttribute('color');
    return new THREE.Color(colors.getX(vertex), colors.getY(vertex), colors.getZ(vertex));
}

suite('How a port is drawn', () => {
    test('a boundary is drawn in the blue of the Z axis of its own triad', () => {
        // The Z line of an 'AxesHelper' runs from (0, 0, 1) at the origin to a
        // lighter blue at the tip; the base is the blue of the axis. Those numbers
        // go straight into the colour attribute, so they are in the working space -
        // and a hex colour converts into it, which is why the two compare at all.
        assert.ok(axisColor(4).equals(new THREE.Color(PORT_COLOR)));

        // Not the X or Y axis, so that a wrong constant cannot pass by matching
        // some axis or other.
        assert.ok(!axisColor(0).equals(new THREE.Color(PORT_COLOR)));
        assert.ok(!axisColor(2).equals(new THREE.Color(PORT_COLOR)));
    });

    test('the axis helper still bypasses tone mapping, which is why the material must', () => {
        // If three ever stopped doing this, the face and the axis would drift apart
        // without either of them changing colour: this scene tone-maps everything
        // that does not say otherwise.
        const material = new THREE.AxesHelper(1).material as THREE.LineBasicMaterial;
        assert.strictEqual(material.toneMapped, false);
    });

    test('a port that names a sketch is still one item with its triad', () => {
        // The renderer registers both under this id and the pane makes one row of
        // it, so a boundary cannot end up switchable separately from its frame.
        const node: ShowNode = {
            name: '//pkg:bracket',
            ports: [
                { name: 'thru-m3', location: [[0, 0, 0], [0, 0, 1], 0], sketch: '//pkg:m3' },
                { name: 'grip', location: [[0, 0, 0], [0, 0, 1], 0] },
            ],
        };

        // Neither belongs to an interface, so both are listed under 'ports' - and
        // the one with a sketch is named no differently for having one.
        const { loose } = groupPorts(node);
        assert.deepStrictEqual(loose, [0, 1]);
        assert.strictEqual(portId([], 0), 'n:p0');
        assert.notStrictEqual(portId([], 0), portId([], 1));
    });

    test('a sketch is named by the reference the port names', () => {
        // What the renderer looks the parsed geometry up by: PartCAD sends one
        // entry per sketch, keyed by exactly the string the ports carry.
        const node: ShowNode = {
            name: '//pkg:bracket',
            ports: [
                { name: 'a', location: [[0, 0, 0], [0, 0, 1], 0], sketch: '//pkg:m3' },
                { name: 'b', location: [[0, 0, 0], [0, 0, 1], 0], sketch: '//pkg:m3' },
            ],
            // A PartCAD reference is the key, not an identifier.
            // eslint-disable-next-line @typescript-eslint/naming-convention
            sketches: { '//pkg:m3': { name: '//pkg:m3', gltf: 'Z2xURg==' } },
        };

        // Two ports, one sketch: parsed once and drawn twice.
        const referenced = new Set((node.ports ?? []).map((port) => port.sketch));
        assert.deepStrictEqual([...referenced], ['//pkg:m3']);
        assert.deepStrictEqual(Object.keys(node.sketches ?? {}), ['//pkg:m3']);
    });
});
