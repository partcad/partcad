//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A 3Dconnexion SpaceMouse, driving the 3D view's camera.
//
// The device reaches this renderer by one of two roads, and which one depends on
// the platform rather than on anything the user chose:
//
//   * The Gamepad API. Chromium enumerates HID "multi-axis controllers" (usage
//     page 1, usage 8) as gamepads on Windows and macOS, which is what every
//     SpaceMouse is, and does not blocklist 3Dconnexion's vendor ids. VS Code
//     does not grant a webview 'gamepad' in its iframe's 'allow', and does not
//     need to: Chromium's default allowlist for that feature is '*'. It needs no
//     driver at all, and it is the only road that works when the extension host
//     is remote, because the webview is always drawn on the user's machine.
//
//   * spacenavd, on Linux. The kernel reports a SpaceMouse's axes as relative
//     motion rather than as a joystick, so Chromium does not see it there, and
//     spacenavd holds the device besides. The extension host reads spacenavd's
//     socket ('src/viewer/spacenav.ts') and forwards what it says. Its values
//     arrive in spacenavd's own frame and scale, and are converted here, so that
//     every convention about the device lives in this one file.
//
// Either way the result is one 'Motion': how the user is pushing and twisting the
// cap, in the camera's frame. The navigation is 3Dconnexion's "object mode" - the
// cap is the model: push it left and the model goes left, twist it and the model
// turns - which is what 3Dconnexion ships as the default and what every CAD
// package that supports the device does out of the box.
//
// Nothing here draws. Every 3D view of the panel - the 3D tab ('scene.ts') and the
// model of an analysis ('cae.ts') - attaches itself as a 'Navigable', and asks the
// device once a frame to move its camera; only the view on screen is moved. Kept
// free of the renderers so that the conventions, which are the part that can be
// wrong without anything failing, can be tested.
//

import * as THREE from 'three';

/** One axis of the device, as the settings name it. */
export type Axis = 'tx' | 'ty' | 'tz' | 'rx' | 'ry' | 'rz';

export const AXES: readonly Axis[] = ['tx', 'ty', 'tz', 'rx', 'ry', 'rz'];

/**
 * What the cap is doing, in the camera's frame: x right, y up, z toward the viewer.
 *
 * 't' is where it is being pushed and 'r' is the axis it is being twisted about
 * (right-handed, length how hard), both normalized so that the cap at its stop is
 * about 1. Each is what the *model* should do, because the navigation is object
 * mode.
 */
export interface Motion {
    t: [number, number, number];
    r: [number, number, number];
}

/** The 'partcad.spaceMouse.*' settings, as the host hands them over. */
export interface SpaceMouseSettings {
    enabled: boolean;
    /** Multiplies every rate below; 1 is the default feel. */
    sensitivity: number;
    /** Axes whose direction is reversed, for a device or a taste this file got wrong. */
    invert: Axis[];
}

export const DEFAULT_SETTINGS: SpaceMouseSettings = { enabled: true, sensitivity: 1, invert: [] };

/**
 * How far spacenavd reports a cap at its stop.
 *
 * spacenavd passes the device's raw counts through (times its own sensitivity,
 * which is 1 unless configured). 3Dconnexion devices report +-350 at the stop,
 * or more - a SpaceMouse Pro Wireless reaches 500 - so this is the smallest of
 * them, and every device reaches full speed before its stop rather than some
 * never reaching it.
 */
export const SPACENAV_FULL_SCALE = 350;

/**
 * How far from rest the cap has to be before it moves anything.
 *
 * A released cap does not settle at exactly zero, and without this the model
 * would creep. 3Dconnexion's own driver has one too.
 */
export const DEAD_ZONE = 0.04;

/** Degrees per second at full twist, and model-sizes per second at full push. */
const ROTATE_RATE = THREE.MathUtils.degToRad(120);
const PAN_RATE = 1.0;
/** Pushing the cap in all the way halves the distance to the model in this many seconds... */
const ZOOM_RATE = Math.LN2 / 0.5;

/**
 * Whether a gamepad is a 3Dconnexion device.
 *
 * Chromium names a gamepad after the device and appends its USB ids -
 * "SpaceMouse Compact (Vendor: 256f Product: c635)" - and the vendor is enough:
 * 256f is 3Dconnexion's own, and the Logitech-era devices (SpaceNavigator,
 * SpaceExplorer, SpacePilot, SpaceTraveler, SpaceBall 5000) are 046d:c603 to
 * 046d:c62b, a range Logitech gave the 3Dconnexion line and nothing else. The
 * name is checked as well, for a platform that leaves the ids out.
 */
export function isSpaceMouse(id: string): boolean {
    const lower = id.toLowerCase();
    if (/vendor:\s*256f\b/.test(lower) || /^256f-/.test(lower)) {
        return true;
    }
    const logitech = /vendor:\s*046d\s+product:\s*([0-9a-f]{4})/.exec(lower) ?? /^046d-([0-9a-f]{4})-/.exec(lower);
    if (logitech !== null) {
        const product = parseInt(logitech[1], 16);
        return product >= 0xc603 && product <= 0xc62b;
    }
    return /3dconnexion|space ?mouse|space ?navigator|space ?pilot|space ?explorer|space ?traveler|spaceball/.test(
        lower,
    );
}

/**
 * A HID report's six axes, as the Gamepad API hands them over, in the camera's frame.
 *
 * Chromium orders a HID device's axes by usage - X, Y, Z, Rx, Ry, Rz - and scales
 * each to -1..1 from the logical range the device declares. 3Dconnexion's HID
 * frame is x right, y toward the user, z down (right-handed), for the push and
 * the twist alike, so the camera's frame is that one turned a quarter about x:
 * (x, -z, y), which as a proper rotation carries the twist axis the same way.
 */
export function fromHid(axes: readonly number[]): Motion {
    const [x, y, z, rx, ry, rz] = axes;
    return {
        t: [x ?? 0, -(z ?? 0), y ?? 0],
        r: [rx ?? 0, -(rz ?? 0), ry ?? 0],
    };
}

/**
 * A spacenavd motion event's six values, in the camera's frame.
 *
 * spacenavd has already turned the device's frame into its own - x right, y up,
 * z away from the user - which is the camera's frame with z reversed. libspnav's
 * own examples apply it to an OpenGL modelview as (x, y, -z) and rotate by
 * (rx, ry, -rz), and the two agree with 'fromHid' through spacenavd's default
 * axis map, which swaps the device's y and z and reverses both.
 */
export function fromSpacenav(values: readonly number[]): Motion {
    const s = (index: number) => (values[index] ?? 0) / SPACENAV_FULL_SCALE;
    return {
        t: [s(0), s(1), -s(2)],
        r: [s(3), s(4), -s(5)],
    };
}

/**
 * The motion the settings make of it: the dead zone taken off, the axes the user
 * reversed reversed, and nothing at all while the device is turned off.
 *
 * Undefined when nothing moves, so that a released cap costs the frame nothing.
 */
export function shaped(motion: Motion, settings: SpaceMouseSettings): Motion | undefined {
    if (!settings.enabled) {
        return undefined;
    }
    const values = [...motion.t, ...motion.r].map((value, index) => {
        const magnitude = Math.abs(value);
        if (!(magnitude > DEAD_ZONE)) {
            return 0;
        }
        // Rescaled from the edge of the dead zone rather than cut at it, so the
        // model starts moving from nothing instead of jumping to a crawl.
        const rescaled = (Math.min(magnitude, 1) - DEAD_ZONE) / (1 - DEAD_ZONE);
        return Math.sign(value) * rescaled * (settings.invert.includes(AXES[index]) ? -1 : 1);
    });
    if (values.every((value) => value === 0)) {
        return undefined;
    }
    return { t: [values[0], values[1], values[2]], r: [values[3], values[4], values[5]] };
}

/**
 * Move a camera about what it is looking at, the way the cap says the model moves.
 *
 * Object mode, so everything is the inverse applied to the camera: the model going
 * left is the camera going right, the model turning is the camera orbiting the
 * other way about 'target'. Rates are per second and scale with the distance to
 * 'target', so a 5 mm part and a 2 m assembly both cross the screen in the same
 * time. 'target' is moved with the camera by a pan, which is what keeps an orbit
 * after a pan centred on what is now in front of it.
 *
 * The camera's orientation is turned along with its position, but the caller's
 * controls may impose an up direction of their own afterwards; for the orbit
 * controls the view uses, that makes the navigation a turntable - a twist about
 * the line of sight is dropped, and a tilt stops at the poles.
 */
export function navigate(
    camera: THREE.Camera,
    target: THREE.Vector3,
    motion: Motion,
    seconds: number,
    sensitivity: number,
): void {
    const rate = seconds * sensitivity;
    const offset = camera.position.clone().sub(target);
    const distance = offset.length() || 1;

    // Pan: the model goes the way the cap is pushed, so the camera goes the other.
    const pan = new THREE.Vector3(motion.t[0], motion.t[1], 0)
        .multiplyScalar(-PAN_RATE * distance * rate)
        .applyQuaternion(camera.quaternion);
    camera.position.add(pan);
    target.add(pan);

    // Zoom: pushing the cap into the screen pushes the model away.
    offset.multiplyScalar(Math.exp(-ZOOM_RATE * motion.t[2] * rate));

    // Orbit: the model turns about the twist axis, so the camera turns the other way.
    const axis = new THREE.Vector3(...motion.r);
    const strength = axis.length();
    if (strength > 0) {
        axis.divideScalar(strength).applyQuaternion(camera.quaternion);
        const turn = new THREE.Quaternion().setFromAxisAngle(axis, -ROTATE_RATE * strength * rate);
        offset.applyQuaternion(turn);
        camera.quaternion.premultiply(turn);
    }
    camera.position.copy(target).add(offset);
}

/**
 * The "Fit" key, as the Gamepad API numbers it.
 *
 * Chromium orders a HID device's buttons by usage, and on every 3Dconnexion
 * device the first two usages are "Menu" and "Fit" - the left and right buttons
 * of a two-button SpaceMouse, and the keys labelled so on the larger ones.
 */
export const GAMEPAD_FIT = 1;

/** spacenavd's 'DEV_*' numbers for the devices whose buttons it renumbers. */
const DEV_SMPRO = 0x20a;
const DEV_SMPROW = 0x20d;
const DEV_SMENT = 0x20e;

/**
 * The "Fit" key, as spacenavd numbers it on 'device'.
 *
 * spacenavd passes a device's buttons through in HID order - so "Fit" is 1, as
 * on the Gamepad API - except on the SpaceMouse Pro and the Enterprise, whose
 * buttons are scattered across the HID range and which it renumbers into a
 * contiguous one of its own ('bnhack_smpro' and 'bnhack_sment' in its 'dev.c'),
 * putting the numbered keys first. A spacenavd that could not be asked is older
 * than that renumbering, so HID order is right for it too.
 */
export function spacenavFit(device: number | null): number {
    switch (device) {
        case DEV_SMPRO:
        case DEV_SMPROW:
            return 5;
        case DEV_SMENT:
            return 13;
        default:
            return 1;
    }
}

/**
 * A view the device moves: an orbit camera, and how to frame what it shows.
 *
 * The panel has more than one - the 3D tab, and the model of each analysis - and
 * each draws in a loop of its own, so each asks the device once a frame
 * ('SpaceMouse.drive'). Only the one on screen is moved. The others go on drawing
 * in hidden panes, and a push meant for the model in front of the user that turns
 * a camera behind it instead is a push lost twice.
 */
export interface Navigable {
    readonly camera: THREE.Camera;
    /** What the camera orbits about; a pan moves it along with the camera. */
    readonly target: THREE.Vector3;
    /** Whether the view is the one on screen (see 'onScreen'). */
    shown(): boolean;
    /** What the "Fit" key does here. */
    fit(): void;
    /**
     * The cap started or stopped moving this view, the way a drag starts and
     * ends. A view that draws differently while its camera moves - the painter
     * draws a big model as boxes - hears about the device as it does about a
     * mouse.
     */
    moving?(moving: boolean): void;
}

/** Whether an element is laid out at all, which a pane the tabs have hidden is not. */
export function onScreen(element: Element): boolean {
    return element.isConnected && element.getClientRects().length > 0;
}

/** The longest frame a push is applied over, so that a stall does not fling the model. */
const MAX_FRAME_SECONDS = 0.1;

/**
 * The device, whichever road it arrives by, and the views it moves.
 *
 * The host says which road is open: while spacenavd is connected the Gamepad API
 * is not consulted, so a device both of them can see does not move the model
 * twice. The host also says whether this panel is where the user is - a visible
 * panel in the focused window - because spacenavd tells every client about every
 * push, and a SpaceMouse moving the model in a window behind this one is not
 * something anybody asked for.
 *
 * There is one for the panel ('spaceMouse', below), and it belongs to no view: the
 * host says all of the above once, whichever views exist yet - the 3D view's
 * module finishes loading only when its surface does, which can be after the host
 * has spoken - and every view is moved by the same device.
 */
export class SpaceMouse {
    public settings: SpaceMouseSettings = DEFAULT_SETTINGS;
    /** Whether the panel is where the user is working. */
    public active = true;
    /** Whether the host is reading spacenavd, which then speaks for the device. */
    public spacenavd = false;
    /** The device spacenavd serves, which says which of its buttons is "Fit". */
    public spacenavdDevice: number | null = null;

    private forwarded: Motion | undefined;
    private forwardedAt = 0;
    private pressed: boolean[] = [];
    /** The views there are to move, and when each was last driven. */
    private readonly views = new Map<Navigable, number | undefined>();
    /** The view the cap is moving, which has been told so. */
    private moved: Navigable | undefined;

    /** Offer a view to the device, until it is detached. */
    public attach(view: Navigable): void {
        this.views.set(view, undefined);
    }

    /** Stop offering a view: it is going away. */
    public detach(view: Navigable): void {
        this.views.delete(view);
        if (this.moved === view) {
            this.moved = undefined;
        }
    }

    /**
     * Move 'view' as the cap says, if it is the view on screen.
     *
     * Called by the view's own render loop once a frame, before its controls are
     * updated. Says whether the cap moved it, which is what pauses a turntable.
     */
    public drive(view: Navigable, now: number): boolean {
        if (!this.views.has(view)) {
            return false;
        }
        const last = this.views.get(view);
        this.views.set(view, now);
        // Clamped, so that the first frame after the panel was hidden - or after a
        // stall - does not fling the model by however long that was.
        const seconds = last === undefined ? 0 : Math.min(Math.max(now - last, 0) / 1000, MAX_FRAME_SECONDS);
        const motion = view.shown() ? this.sample(now) : undefined;
        if (motion !== undefined) {
            navigate(view.camera, view.target, motion, seconds, this.settings.sensitivity);
        }
        this.setMoving(view, motion !== undefined);
        return motion !== undefined;
    }

    /** What spacenavd last said about the cap, forwarded by the host. */
    public spacenavMotion(values: readonly number[], now: number): void {
        this.forwarded = fromSpacenav(values);
        this.forwardedAt = now;
    }

    /**
     * A button spacenavd reported, forwarded by the host.
     *
     * Only "Fit" does anything. The other keys of the larger devices (views,
     * rotation lock, the programmable keys) are left alone rather than guessed at.
     */
    public spacenavButton(button: number, pressed: boolean): void {
        if (pressed && this.active && button === spacenavFit(this.spacenavdDevice)) {
            this.fit();
        }
    }

    /** "Fit" frames the model of whichever view is on screen. */
    private fit(): void {
        if (!this.settings.enabled) {
            return;
        }
        for (const view of this.views.keys()) {
            if (view.shown()) {
                view.fit();
                return;
            }
        }
    }

    private setMoving(view: Navigable, moving: boolean): void {
        if (moving && this.moved !== view) {
            this.moved?.moving?.(false);
            this.moved = view;
            view.moving?.(true);
        } else if (!moving && this.moved === view) {
            this.moved = undefined;
            view.moving?.(false);
        }
    }

    /** How the cap is being moved right now, or undefined when it is at rest. */
    private sample(now: number): Motion | undefined {
        if (!this.active) {
            return undefined;
        }
        if (this.spacenavd) {
            // spacenavd sends an event when the cap moves and a zero when it comes
            // to rest; a device dropped mid-push sends neither, so a value that has
            // not been repeated for a while is taken to be a cap nobody is holding.
            if (this.forwarded === undefined || now - this.forwardedAt > STALE_MS) {
                return undefined;
            }
            return shaped(this.forwarded, this.settings);
        }
        return this.gamepad();
    }

    private gamepad(): Motion | undefined {
        // Absent in a context with no Gamepad API, and it throws where a
        // permissions policy forbids it; either way there is no device here.
        let pads: (Gamepad | null)[];
        try {
            pads = typeof navigator.getGamepads === 'function' ? navigator.getGamepads() : [];
        } catch {
            return undefined;
        }
        for (const pad of pads) {
            if (pad === null || !pad.connected || pad.axes.length < 6 || !isSpaceMouse(pad.id)) {
                continue;
            }
            pad.buttons.forEach((button, index) => {
                if (button.pressed && !this.pressed[index] && index === GAMEPAD_FIT) {
                    this.fit();
                }
                this.pressed[index] = button.pressed;
            });
            return shaped(fromHid(pad.axes), this.settings);
        }
        return undefined;
    }
}

/** How long a forwarded spacenavd value is believed without being repeated. */
const STALE_MS = 500;

/** The panel's SpaceMouse: 'viewer.ts' hands it what the host says, and each 3D view attaches to it. */
export const spaceMouse = new SpaceMouse();
