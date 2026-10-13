//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The SpaceMouse: which gamepad is one, what its axes mean, and what they do to
// the camera.
//
// Every convention here can be wrong without anything failing - a reversed axis
// moves the model the other way, which is plausible, and a mapping that is
// right for one road and wrong for the other is only noticed by someone who
// owns both kinds of machine. So the two roads are held to each other: a push
// read through the Gamepad API and the same push read through spacenavd have to
// come out the same.
//

import * as assert from 'assert';
import * as fs from 'fs';
import * as net from 'net';
import * as os from 'os';
import * as path from 'path';
import * as THREE from 'three';

import {
    EVENT_BYTES,
    REQ_CHANGE_PROTO,
    REQ_DEV_TYPE,
    REQ_TAG,
    SpacenavClient,
    decodeMessages,
    protocolRequest,
    request,
    socketPaths,
} from '../../viewer/spacenav';
import {
    DEAD_ZONE,
    DEFAULT_SETTINGS,
    GAMEPAD_FIT,
    Motion,
    Navigable,
    SPACENAV_FULL_SCALE,
    SpaceMouse,
    fromHid,
    fromSpacenav,
    isSpaceMouse,
    navigate,
    shaped,
    spacenavFit,
} from '../../webview/spacemouse';

/**
 * What spacenavd makes of a raw HID report with its default axis map: the
 * device's y and z swapped, and y, z, ry and rz reversed. Scaled to its counts.
 */
function spacenavdOf(hid: number[]): number[] {
    const [x, y, z, rx, ry, rz] = hid.map((value) => value * SPACENAV_FULL_SCALE);
    return [x, -z, -y, rx, -rz, -ry];
}

function near(got: readonly number[], want: readonly number[]): void {
    assert.strictEqual(got.length, want.length);
    got.forEach((value, index) =>
        assert.ok(Math.abs(value - want[index]) < 1e-9, `expected (${want}) but got (${got})`),
    );
}

/** A camera at (0, 0, 10) looking at the origin, as the view's orbit controls leave it. */
function cameraAt(position: [number, number, number] = [0, 0, 10]): THREE.PerspectiveCamera {
    const camera = new THREE.PerspectiveCamera();
    camera.position.set(...position);
    camera.lookAt(0, 0, 0);
    return camera;
}

function motion(t: [number, number, number], r: [number, number, number] = [0, 0, 0]): Motion {
    return { t, r };
}

/** A view of the panel as the device sees one, and what the device did to it. */
function fakeView(shown: boolean): { view: Navigable; done: { shown: boolean; fits: number; moving: boolean[] } } {
    const done = { shown, fits: 0, moving: [] as boolean[] };
    const view: Navigable = {
        camera: cameraAt(),
        target: new THREE.Vector3(),
        shown: () => done.shown,
        fit: () => {
            done.fits += 1;
        },
        moving: (moving) => done.moving.push(moving),
    };
    return { view, done };
}

/** spacenavd saying the cap is pushed right to its stop, at 'now'. */
function pushRight(device: SpaceMouse, now: number): void {
    device.spacenavMotion([SPACENAV_FULL_SCALE, 0, 0, 0, 0, 0], now);
}

/** A device read through spacenavd, as on Linux. */
function spacenavdDevice(): SpaceMouse {
    const device = new SpaceMouse();
    device.spacenavd = true;
    return device;
}

/** Until 'condition' holds, or fail after 'ms'. */
async function waitFor(condition: () => boolean, what: string, ms = 5000): Promise<void> {
    const until = Date.now() + ms;
    while (!condition()) {
        if (Date.now() > until) {
            assert.fail(`timed out waiting for ${what}`);
        }
        await new Promise((resolve) => setTimeout(resolve, 20));
    }
}

suite('Digital Thread SpaceMouse', () => {
    test('3Dconnexion devices are recognised by their USB ids, and nothing else is', () => {
        assert.ok(isSpaceMouse('SpaceMouse Compact (Vendor: 256f Product: c635)'));
        assert.ok(isSpaceMouse('Wireless Receiver (Vendor: 256f Product: c652)'));
        // The Logitech-era devices, under Logitech's vendor id.
        assert.ok(isSpaceMouse('SpaceNavigator (Vendor: 046d Product: c626)'));
        // Firefox's spelling of the same, for a platform that names it that way.
        assert.ok(isSpaceMouse('046d-c626-SpaceNavigator'));
        // A Logitech gamepad is not one.
        assert.ok(!isSpaceMouse('Logitech Gamepad F310 (Vendor: 046d Product: c21d)'));
        assert.ok(!isSpaceMouse('Xbox 360 Controller (XInput STANDARD GAMEPAD)'));
    });

    test('the two roads agree about every axis', () => {
        // One push or twist at a time, each read both ways.
        for (let axis = 0; axis < 6; axis++) {
            for (const value of [0.5, -1]) {
                const hid = [0, 0, 0, 0, 0, 0];
                hid[axis] = value;
                const direct = fromHid(hid);
                const viaSpacenavd = fromSpacenav(spacenavdOf(hid));
                near([...direct.t, ...direct.r], [...viaSpacenavd.t, ...viaSpacenavd.r]);
            }
        }
    });

    test("the device's frame is the camera's turned a quarter about x", () => {
        // Pushed right, the model goes right.
        near(fromHid([1, 0, 0, 0, 0, 0]).t, [1, 0, 0]);
        // Pushed down (HID z is down), the model goes down.
        near(fromHid([0, 0, 1, 0, 0, 0]).t, [0, -1, 0]);
        // Pulled toward the user (HID y), the model comes toward the viewer.
        near(fromHid([0, 1, 0, 0, 0, 0]).t, [0, 0, 1]);
        // A twist about the device's vertical is a turn about the camera's.
        near(fromHid([0, 0, 0, 0, 0, 1]).r, [0, -1, 0]);
    });

    test('the dead zone holds a released cap still and does not jump past it', () => {
        assert.strictEqual(shaped(motion([DEAD_ZONE / 2, 0, 0], [0, -DEAD_ZONE / 2, 0]), DEFAULT_SETTINGS), undefined);
        const barely = shaped(motion([DEAD_ZONE * 1.01, 0, 0]), DEFAULT_SETTINGS);
        assert.ok(barely !== undefined && barely.t[0] > 0 && barely.t[0] < 0.01);
        near(shaped(motion([1, 0, 0]), DEFAULT_SETTINGS)?.t ?? [], [1, 0, 0]);
        // A value past the stop is the stop.
        near(shaped(motion([0, -3, 0]), DEFAULT_SETTINGS)?.t ?? [], [0, -1, 0]);
    });

    test('the settings reverse what they name and silence a disabled device', () => {
        const settings = { ...DEFAULT_SETTINGS, invert: ['tz' as const, 'ry' as const] };
        const got = shaped(motion([1, 1, 1], [1, 1, 1]), settings);
        near([...(got?.t ?? []), ...(got?.r ?? [])], [1, 1, -1, 1, -1, 1]);
        assert.strictEqual(shaped(motion([1, 0, 0]), { ...DEFAULT_SETTINGS, enabled: false }), undefined);
    });

    test('pushing the cap right moves the model right, which moves the camera left', () => {
        const camera = cameraAt();
        const target = new THREE.Vector3();
        navigate(camera, target, motion([1, 0, 0]), 0.1, 1);
        assert.ok(camera.position.x < 0, `camera went to ${camera.position.toArray()}`);
        // Target and camera go together, so the view direction is unchanged.
        near(camera.position.clone().sub(target).toArray(), [0, 0, 10]);
    });

    test('pushing the cap into the screen pushes the model away', () => {
        const camera = cameraAt();
        const target = new THREE.Vector3();
        navigate(camera, target, motion([0, 0, -1]), 0.1, 1);
        assert.ok(camera.position.z > 10, `camera went to ${camera.position.toArray()}`);
        near(target.toArray(), [0, 0, 0]);
    });

    test('twisting the cap turns the model about the target, keeping its distance', () => {
        const camera = cameraAt();
        const target = new THREE.Vector3();
        // The model turns counter-clockwise seen from above (about +y), so the
        // camera goes round the other way: toward -x.
        navigate(camera, target, motion([0, 0, 0], [0, 1, 0]), 0.1, 1);
        assert.ok(camera.position.x < 0, `camera went to ${camera.position.toArray()}`);
        assert.ok(Math.abs(camera.position.length() - 10) < 1e-9);
        // And it is still looking at the target.
        const looking = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
        near(looking.toArray(), camera.position.clone().negate().normalize().toArray());
    });

    test('the rates scale with the distance, so a part and an assembly move alike', () => {
        const near_ = cameraAt([0, 0, 0.01]);
        const far = cameraAt([0, 0, 10]);
        navigate(near_, new THREE.Vector3(), motion([1, 0, 0]), 0.1, 1);
        navigate(far, new THREE.Vector3(), motion([1, 0, 0]), 0.1, 1);
        assert.ok(Math.abs(near_.position.x / 0.01 - far.position.x / 10) < 1e-9);
    });

    test('sensitivity scales the motion', () => {
        const slow = cameraAt();
        const fast = cameraAt();
        navigate(slow, new THREE.Vector3(), motion([1, 0, 0]), 0.1, 1);
        navigate(fast, new THREE.Vector3(), motion([1, 0, 0]), 0.1, 2);
        assert.ok(Math.abs(fast.position.x - 2 * slow.position.x) < 1e-9);
    });

    test('only the view on screen is moved, and "Fit" frames that one', () => {
        // The 3D tab and an analysis each draw in a loop of their own, hidden or
        // not, and each asks the device once a frame.
        const device = spacenavdDevice();
        const design = fakeView(true);
        const analysis = fakeView(false);
        device.attach(design.view);
        device.attach(analysis.view);
        pushRight(device, 0);
        for (const now of [0, 16]) {
            device.drive(design.view, now);
            device.drive(analysis.view, now);
        }
        assert.ok(design.view.camera.position.x < 0, `camera went to ${design.view.camera.position.toArray()}`);
        near(analysis.view.camera.position.toArray(), [0, 0, 10]);
        device.spacenavButton(spacenavFit(null), true);
        assert.deepStrictEqual([design.done.fits, analysis.done.fits], [1, 0]);

        // The user switches to the analysis.
        design.done.shown = false;
        analysis.done.shown = true;
        const left = design.view.camera.position.x;
        pushRight(device, 32);
        device.drive(design.view, 32);
        device.drive(analysis.view, 32);
        assert.strictEqual(design.view.camera.position.x, left);
        assert.ok(analysis.view.camera.position.x < 0, `camera went to ${analysis.view.camera.position.toArray()}`);
        device.spacenavButton(spacenavFit(null), true);
        assert.deepStrictEqual([design.done.fits, analysis.done.fits], [1, 1]);

        // Nothing is framed with the device turned off.
        device.settings = { ...DEFAULT_SETTINGS, enabled: false };
        device.spacenavButton(spacenavFit(null), true);
        assert.deepStrictEqual([design.done.fits, analysis.done.fits], [1, 1]);
    });

    test('a view hears the cap start and stop moving it, as it would a drag', () => {
        const device = spacenavdDevice();
        const { view, done } = fakeView(true);
        device.attach(view);
        pushRight(device, 0);
        assert.strictEqual(device.drive(view, 0), true);
        assert.strictEqual(device.drive(view, 16), true);
        device.spacenavMotion([0, 0, 0, 0, 0, 0], 32);
        assert.strictEqual(device.drive(view, 32), false);
        assert.deepStrictEqual(done.moving, [true, false]);

        // A tab switched away from in the middle of a push ends the drag there.
        pushRight(device, 48);
        device.drive(view, 48);
        done.shown = false;
        device.drive(view, 64);
        assert.deepStrictEqual(done.moving, [true, false, true, false]);

        // So does a view going away in the middle of one - an analysis replaced
        // by the next run - and only once.
        done.shown = true;
        pushRight(device, 80);
        device.drive(view, 80);
        device.detach(view);
        device.detach(view);
        assert.deepStrictEqual(done.moving, [true, false, true, false, true, false]);
    });

    test('a view that has gone is not moved, and the panel being elsewhere moves nothing', () => {
        const device = spacenavdDevice();
        const { view, done } = fakeView(true);
        device.attach(view);
        device.detach(view);
        pushRight(device, 0);
        assert.strictEqual(device.drive(view, 0), false);
        device.spacenavButton(spacenavFit(null), true);
        assert.strictEqual(done.fits, 0);

        const other = fakeView(true);
        device.attach(other.view);
        device.active = false;
        device.drive(other.view, 0);
        device.drive(other.view, 16);
        near(other.view.camera.position.toArray(), [0, 0, 10]);
        device.spacenavButton(spacenavFit(null), true);
        assert.strictEqual(other.done.fits, 0);
    });
});

suite('spacenavd protocol', () => {
    /** One event or response, little-endian. */
    function message(values: number[]): Buffer {
        const buffer = Buffer.alloc(EVENT_BYTES);
        values.forEach((value, index) => buffer.writeInt32LE(value | 0, index * 4));
        return buffer;
    }

    test('motion and buttons are decoded, and an unknown event is skipped', () => {
        const buffer = Buffer.concat([
            message([0, 10, -20, 30, -40, 50, -60, 16]),
            message([1, 1]),
            message([7, 1, 2, 3]),
            message([2, 1]),
        ]);
        const { messages, rest } = decodeMessages(buffer, 'LE');
        assert.deepStrictEqual(messages, [
            { motion: [10, -20, 30, -40, 50, -60] },
            { button: 1, pressed: true },
            { button: 1, pressed: false },
        ]);
        assert.strictEqual(rest.length, 0);
    });

    test('a message split across two reads is decoded once it is whole', () => {
        const whole = message([0, 1, 2, 3, 4, 5, 6, 7]);
        const first = decodeMessages(whole.subarray(0, 13), 'LE');
        assert.deepStrictEqual(first.messages, []);
        assert.strictEqual(first.rest.length, 13);
        const second = decodeMessages(Buffer.concat([first.rest, whole.subarray(13)]), 'LE');
        assert.deepStrictEqual(second.messages, [{ motion: [1, 2, 3, 4, 5, 6] }]);
    });

    test('the protocol answer is found between events, and a response is told from an event', () => {
        // What a v1 spacenavd sends a client that asked while the cap was moving:
        // an event, the one-integer answer, and the device type it was then asked.
        const answer = Buffer.alloc(4);
        answer.writeInt32LE(REQ_TAG | REQ_CHANGE_PROTO | 1);
        const buffer = Buffer.concat([
            message([0, 1, 2, 3, 4, 5, 6, 16]),
            answer,
            message([REQ_TAG | REQ_DEV_TYPE, 0x20d, 0, 0, 0, 0, 0, 0]),
            message([3, 0, 0, 0x20d, 0x256f, 0xc631]),
        ]);
        assert.deepStrictEqual(decodeMessages(buffer, 'LE').messages, [
            { motion: [1, 2, 3, 4, 5, 6] },
            { protocol: 1 },
            { response: REQ_DEV_TYPE, data: [0x20d, 0, 0, 0, 0, 0], status: 0 },
            { deviceChanged: true },
        ]);
    });

    test('the requests are what libspnav sends', () => {
        assert.deepStrictEqual([...protocolRequest('LE')], [0x01, 0x55, 0xaa, 0x7f]);
        const devType = request(REQ_DEV_TYPE, 'LE');
        assert.strictEqual(devType.length, EVENT_BYTES);
        assert.strictEqual(devType.readInt32LE(0), REQ_TAG | REQ_DEV_TYPE);
        assert.ok(devType.subarray(4).every((byte) => byte === 0));
    });

    test('"Fit" is the key spacenavd numbers it as on each device', () => {
        // Held to what a SpaceMouse Pro Wireless did through spacenavd 1.2: its
        // "Fit" key arrived as button 5, and "Menu" as 4.
        assert.strictEqual(spacenavFit(0x20d), 5);
        assert.strictEqual(spacenavFit(0x20a), 5);
        assert.strictEqual(spacenavFit(0x20e), 13);
        // A SpaceMouse Compact, a SpaceNavigator, and a spacenavd too old to ask.
        assert.strictEqual(spacenavFit(0x20f), GAMEPAD_FIT);
        assert.strictEqual(spacenavFit(0x206), GAMEPAD_FIT);
        assert.strictEqual(spacenavFit(null), GAMEPAD_FIT);
    });

    test('a spacenavd at none of its paths is missing, and one that answers is not', async function () {
        if (process.platform === 'win32') {
            // spacenavd is a Unix daemon, and the extension does not look for it here.
            this.skip();
        }
        const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'spnav-'));
        const absent = path.join(directory, 'absent.sock');
        const present = path.join(directory, 'spnav.sock');
        const server = net.createServer((connection) => connection.on('data', () => undefined));
        let client = new SpacenavClient([absent]);
        try {
            await waitFor(() => client.missing, 'the client to give up on a socket that is not there');
            assert.strictEqual(client.connected, false);
            client.dispose();

            await new Promise<void>((resolve) => server.listen(present, resolve));
            client = new SpacenavClient([absent, present]);
            await waitFor(() => client.connected, 'the client to find the second path');
            assert.strictEqual(client.missing, false);
        } finally {
            client.dispose();
            server.close();
            fs.rmSync(directory, { recursive: true, force: true });
        }
    });

    test('the socket is looked for where libspnav looks', () => {
        assert.deepStrictEqual(socketPaths({}), ['/var/run/spnav.sock']);
        // eslint-disable-next-line @typescript-eslint/naming-convention
        assert.deepStrictEqual(socketPaths({ XDG_RUNTIME_DIR: '/run/user/1000' }), [
            '/var/run/spnav.sock',
            '/run/user/1000/spnav.sock',
        ]);
    });
});
