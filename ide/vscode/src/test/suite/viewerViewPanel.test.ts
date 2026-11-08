//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The view panel down the right of the Digital Thread's tabs: where a view is
// looked at from, what the object is cut to, and the widget that says both.
//
// Three things are worth holding in place here, because each is plausible on
// screen when it is wrong. That the axis views, the turntable and the gizmo's
// projection agree about which way X is - a mirrored axis still looks like an
// axis. That the section sliders span the object as its tree says it is placed,
// and that what is sent names only the axes that cut. And that the panel reports
// what was asked for, once it is settled, and nothing it cannot do on a tab.
// And, for the projection beside the viewpoint, that an isometric view is one -
// a diagonal, all three axes alike - and that a view drawn without perspective
// is the size, at what it looks at, that it was in perspective.
//
// The widget is exercised through a stand-in DOM, as the control tree's is (see
// 'viewerTree.test.ts'): this suite runs in the extension host, which has none.
//

import * as assert from 'assert';
import * as THREE from 'three';

import { enclosingRadius, fitDistance, fitProgress, matchOrthographic } from '../../webview/cameraView';
import { ShowNode } from '../../webview/messages';
import {
    boundsOf,
    describeSection,
    rangeOf,
    sameSection,
    sectionFrom,
    sectionOf,
    sectionRequest,
} from '../../webview/section';
import { isExpanded, onToggle, setExpanded } from '../../webview/sidePanel';
import { ViewCapabilities, ViewPanel } from '../../webview/viewPanel';
import {
    AXIS_VIEWS,
    DEFAULT_VIEWPOINT,
    Projection,
    Vec3,
    Viewpoint,
    Y_POLE,
    Z_POLE,
    axisOf,
    axisView,
    basis,
    dot,
    formatVector,
    fromTurntable,
    isIsometric,
    isometricView,
    length,
    orbit,
    parseVector,
    problemWith,
    projectAxes,
    sameViewpoint,
    toTurntable,
} from '../../webview/viewpoint';

function near(actual: Vec3, expected: Vec3, message?: string): void {
    const off = Math.hypot(actual[0] - expected[0], actual[1] - expected[1], actual[2] - expected[2]);
    assert.ok(off < 1e-6, `${message ?? ''} ${actual.join(', ')} is not ${expected.join(', ')}`);
}

/** Just enough of an element for 'dom.ts', the panel, the gizmo and the side panel's button. */
class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public type = '';
    public value = '';
    public min = '';
    public max = '';
    public step = '';
    public id = '';
    public checked = false;
    public disabled = false;
    public spellcheck = true;
    public tabIndex = 0;
    public readonly attributes: Record<string, string> = {};
    public readonly properties: Record<string, string> = {};
    public readonly style = {
        width: '',
        height: '',
        cursor: '',
        setProperty: (name: string, value: string) => {
            this.properties[name] = value;
        },
    };
    private readonly classes = new Set<string>();
    private readonly listeners: Record<string, ((event?: unknown) => void)[]> = {};

    constructor(public readonly tagName: string) {}

    public readonly classList = {
        add: (...names: string[]) => names.forEach((name) => this.classes.add(name)),
        remove: (...names: string[]) => names.forEach((name) => this.classes.delete(name)),
        toggle: (name: string, on?: boolean) => {
            const wanted = on ?? !this.classes.has(name);
            if (wanted) {
                this.classes.add(name);
            } else {
                this.classes.delete(name);
            }
            return wanted;
        },
        contains: (name: string) => this.classes.has(name) || this.className.split(' ').includes(name),
    };

    public appendChild(child: FakeElement): FakeElement {
        this.children.push(child);
        return child;
    }

    public append(...children: FakeElement[]): void {
        this.children.push(...children);
    }

    public replaceChildren(): void {
        this.children.length = 0;
    }

    public setAttribute(name: string, value: string): void {
        this.attributes[name] = value;
    }

    public addEventListener(name: string, handler: (event?: unknown) => void): void {
        (this.listeners[name] ??= []).push(handler);
    }

    public blur(): void {}

    /** Raise an event the way the user would. */
    public fire(name: string, event?: unknown): void {
        (this.listeners[name] ?? []).forEach((handler) => handler(event));
    }
}

function all(root: FakeElement, test: (element: FakeElement) => boolean): FakeElement[] {
    const found: FakeElement[] = [];
    const walk = (element: FakeElement) => {
        if (test(element)) {
            found.push(element);
        }
        element.children.forEach(walk);
    };
    walk(root);
    return found;
}

function byClass(root: FakeElement, name: string): FakeElement[] {
    return all(root, (element) => element.classList.contains(name));
}

const EVERYTHING: ViewCapabilities = { viewpoint: true, projection: true, section: true, animate: true, opacity: true };

/** A part 10 x 20 x 30 mm with its corner on the origin, as its tree records it. */
function brick(location?: ShowNode['location']): ShowNode {
    return {
        name: '//pkg:brick',
        label: 'brick',
        location: location ?? null,
        metadata: { measurements: { bbox: [0, 0, 0, 10, 20, 30] } },
    };
}

suite('The view panel: where a view is looked at from', () => {
    test("each axis view is the view 'pc render --view' names, from that side", () => {
        near(axisView('x').origin, [100, 0, 0]);
        near(axisView('-y').origin, [0, -100, 0]);
        near(axisView('-y').up, [0, 0, 1]);
        // Looking down, +Y is up in the picture: the top view of a drawing.
        near(axisView('z').up, [0, 1, 0]);
        near(axisView('-z').up, [0, -1, 0]);
        for (const axis of AXIS_VIEWS) {
            assert.strictEqual(axisOf(axisView(axis)), axis);
        }
    });

    test('an axis view keeps how far away the view was, and what it looked at', () => {
        const current: Viewpoint = { origin: [300, -400, 0], up: [0, 0, 1], target: [5, 6, 7] };
        const chosen = axisView('z', current);
        near(chosen.origin, [0, 0, 500]);
        near(chosen.target, [5, 6, 7]);
    });

    test('the turntable reads a view back as the view it was, off the pole and on it', () => {
        const views: Viewpoint[] = [
            { origin: [100, -100, 100], up: [0, 0, 1], target: [1, 2, 3] },
            axisView('x'),
            axisView('-y'),
            // On the pole, the up vector is what says which way round the camera is.
            axisView('z'),
            axisView('-z'),
            { origin: [0, 0, 50], up: [1, 0, 0], target: [0, 0, 0] },
        ];
        for (const view of views) {
            const back = fromTurntable(toTurntable(view), view.target);
            near(back.origin, view.origin, 'origin');
            // The same picture: its up is the one the view's up says, made
            // square to the line of sight.
            near(basis(back).up, basis(view).up, 'up');
            near(basis(back).right, basis(view).right, 'right');
        }
    });

    test('turning the view keeps its distance and its target, and stops at the poles', () => {
        const start = axisView('-y', { origin: [0, -250, 0], up: [0, 0, 1], target: [1, 1, 1] });
        const turned = orbit(start, Math.PI / 2, 0);
        assert.ok(Math.abs(length(turned.origin) - 250) < 1e-9);
        near(turned.target, [1, 1, 1]);
        // A quarter turn about Z from the front is the right-hand side.
        near(turned.origin, [250, 0, 0]);
        near(turned.up, [0, 0, 1]);

        const over = orbit(start, 0, -Math.PI);
        near(over.origin, [0, 0, 250]);
        // Came from the front: +Y is up in the picture, as the top view's is.
        near(over.up, [0, 1, 0]);
    });

    test('a frame that is Y up turns about Y', () => {
        const turned = orbit({ origin: [0, 0, 10], up: [0, 1, 0], target: [0, 0, 0] }, Math.PI / 2, 0, Y_POLE);
        near(turned.origin, [10, 0, 0]);
        near(turned.up, [0, 1, 0]);
        near(orbit(axisView('-y'), 0, 0, Z_POLE).origin, axisView('-y').origin);
    });

    test('a fit keeps every side of the model in the narrower field however it turns, and no further out', () => {
        // A bar three times as long as it is wide and six times as long as it
        // is deep: end-on it is a sixth of its length across, and it comes round.
        const box = new THREE.Box3(new THREE.Vector3(-30, -10, -5), new THREE.Vector3(30, 10, 5));
        const radius = enclosingRadius(box);
        assert.ok(Math.abs(radius - Math.sqrt(60 * 60 + 20 * 20 + 10 * 10) / 2) < 1e-9);
        assert.strictEqual(enclosingRadius(new THREE.Box3()), 0);

        for (const aspect of [0.5, 1, 2]) {
            const fov = 50;
            const vertical = (fov * Math.PI) / 360;
            const half = Math.min(vertical, Math.atan(Math.tan(vertical) * aspect));
            const distance = fitDistance(radius, fov, aspect);
            // The sphere holding the model just touches the edges of the
            // narrower field: no margin on top of it.
            assert.ok(Math.abs(Math.asin(radius / distance) - half) < 1e-9, `aspect ${aspect}`);
            // And every corner of the model, however the model is turned about
            // the turntable's axis or tumbled over, is inside it.
            const corners = [-1, 1].flatMap((x) =>
                [-1, 1].flatMap((y) => [-1, 1].map((z) => new THREE.Vector3(30 * x, 10 * y, 5 * z))),
            );
            let widest = 0;
            for (let turn = 0; turn < 360; turn += 5) {
                for (let tumble = 0; tumble < 180; tumble += 15) {
                    const rotation = new THREE.Euler((tumble * Math.PI) / 180, (turn * Math.PI) / 180, 0);
                    for (const corner of corners) {
                        // The camera on +Z, looking at the middle.
                        const at = corner.clone().applyEuler(rotation);
                        widest = Math.max(widest, Math.atan2(Math.hypot(at.x, at.y), distance - at.z));
                    }
                }
            }
            assert.ok(widest <= half + 1e-12, `aspect ${aspect}: ${widest} is outside ${half}`);
            // And the fit is tight: as the bar turns, a corner comes close to the
            // edge, so the sphere is all the room left round the model.
            assert.ok(widest > 0.9 * half, `aspect ${aspect}: ${widest} leaves more room than the sphere`);
        }
        // Only the narrower field decides: a wide canvas is fitted by its height,
        // a narrow one by its width.
        assert.strictEqual(fitDistance(radius, 50, 2), fitDistance(radius, 50, 1));
        assert.ok(fitDistance(radius, 50, 0.5) > fitDistance(radius, 50, 1));
    });

    test('a fit takes a second, and starts and ends gently', () => {
        assert.strictEqual(fitProgress(-10), 0);
        assert.strictEqual(fitProgress(0), 0);
        assert.strictEqual(fitProgress(500), 0.5);
        assert.strictEqual(fitProgress(1000), 1);
        assert.strictEqual(fitProgress(5000), 1);
        assert.ok(fitProgress(100) < 0.1 && fitProgress(900) > 0.9);
        for (let elapsed = 0; elapsed < 1000; elapsed += 50) {
            assert.ok(fitProgress(elapsed + 50) > fitProgress(elapsed));
        }
    });

    test('an isometric view is the corner of the octant the view looks from, upright, at its distance', () => {
        const third = 1 / Math.sqrt(3);
        const from: Viewpoint = { origin: [-300, 400, -10], up: [0, 0, 1], target: [1, 2, 3] };
        const corner = isometricView(from);
        const away = length(from.origin) * third;
        near(corner.origin, [-away, away, -away]);
        near(corner.target, [1, 2, 3]);
        // Upright: up is square to the line of sight, and Z is up in the picture.
        assert.ok(Math.abs(dot(corner.up, corner.origin)) < 1e-9);
        assert.ok(corner.up[2] > 0);
        assert.ok(isIsometric(corner));
        assert.strictEqual(problemWith(corner), undefined);

        // An axis view is square to two axes, which say nothing about which
        // side to look from: the opening view's side is taken.
        near(isometricView(axisView('-y')).origin, [100 * third, -100 * third, 100 * third]);
        near(isometricView(axisView('z')).origin, [100 * third, -100 * third, 100 * third]);
        // As is a rounding error of the rest: the front view read off a camera.
        near(isometricView({ ...axisView('-y'), origin: [-1e-12, -100, 1e-12] }).origin, [
            100 * third,
            -100 * third,
            100 * third,
        ]);
        // The opening view is one, and no axis view is.
        assert.ok(isIsometric(DEFAULT_VIEWPOINT));
        assert.ok(AXIS_VIEWS.every((axis) => !isIsometric(axisView(axis))));
        assert.ok(!isIsometric(orbit(DEFAULT_VIEWPOINT, 0.01, 0)));
        assert.ok(
            isometricView(undefined).origin.every(
                (component, axis) => component === isometricView(DEFAULT_VIEWPOINT).origin[axis],
            ),
        );

        // About Y, the picture is upright about Y.
        const yUp = isometricView({ origin: [5, 5, 5], up: [0, 1, 0], target: [0, 0, 0] }, Y_POLE);
        near(yUp.origin, [5, 5, 5]);
        assert.ok(Math.abs(dot(yUp.up, yUp.origin)) < 1e-9 && yUp.up[1] > 0);
    });

    test('drawn without perspective, what the view looks at stays the size it was in perspective', () => {
        for (const [aspect, distance, reach] of [
            [1, 10, 2],
            [2, 3, 8],
            [0.5, 50, 1],
        ]) {
            const camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 1000);
            const target = new THREE.Vector3(1, 2, 3);
            camera.position.copy(target).add(new THREE.Vector3(0.6, 0.5, 0.8).normalize().multiplyScalar(distance));
            camera.lookAt(target);
            camera.updateProjectionMatrix();
            camera.updateMatrixWorld();
            const flat = new THREE.OrthographicCamera();
            matchOrthographic(flat, camera, target, reach);

            // The same line of sight, and at the target the same width and height.
            const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
            const up = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
            for (const point of [
                target.clone(),
                target.clone().addScaledVector(right, distance * 0.3),
                target
                    .clone()
                    .addScaledVector(up, -distance * 0.2)
                    .addScaledVector(right, distance * 0.1),
            ]) {
                const seen = point.clone().project(camera);
                const drawn = point.clone().project(flat);
                assert.ok(Math.abs(seen.x - drawn.x) < 1e-9 && Math.abs(seen.y - drawn.y) < 1e-9, `aspect ${aspect}`);
            }
            // Everything within reach of the target is in front of it, behind
            // where the perspective camera stands included.
            const back = camera.position.clone().sub(target).normalize();
            for (const along of [-reach, 0, reach * 0.999]) {
                const depth = target.clone().addScaledVector(back, along).project(flat).z;
                assert.ok(depth >= -1 && depth <= 1, `aspect ${aspect}: ${along} along is clipped (${depth})`);
            }
        }
    });

    test("the gizmo's axes lie as they are seen: from the front, X right, Z up, -Y towards the reader", () => {
        const ends = new Map(projectAxes(axisView('-y')).map((end) => [end.axis, end]));
        assert.ok(Math.abs(ends.get('x')!.x - 1) < 1e-9);
        assert.ok(Math.abs(ends.get('z')!.y - 1) < 1e-9);
        assert.ok(Math.abs(ends.get('-y')!.depth - 1) < 1e-9);
        // Drawn farthest first, so that what points at the reader is on top.
        const order = projectAxes(axisView('-y')).map((end) => end.depth);
        assert.deepStrictEqual(
            order,
            [...order].sort((a, b) => a - b),
        );
    });

    test('a vector is written as it is pasted, and read whichever way it is pasted', () => {
        assert.strictEqual(formatVector([100, -1e-12, 100.25]), '100, 0, 100.25');
        assert.strictEqual(formatVector([0, -0, 1]), '0, 0, 1');
        near(parseVector('1, 2, 3')!, [1, 2, 3]);
        near(parseVector('[1, -2.5, 3e2]')!, [1, -2.5, 300]);
        near(parseVector('1 2 3')!, [1, 2, 3]);
        assert.strictEqual(parseVector('1, 2'), undefined);
        assert.strictEqual(parseVector('1, two, 3'), undefined);
        assert.strictEqual(parseVector(''), undefined);
    });

    test('a viewpoint that names no orientation is refused, as PartCAD refuses one', () => {
        assert.strictEqual(problemWith(axisView('x')), undefined);
        assert.ok(problemWith({ origin: [0, 0, 0], up: [0, 0, 1], target: [0, 0, 0] }));
        assert.ok(problemWith({ origin: [0, 0, 5], up: [0, 0, 1], target: [0, 0, 0] }));
        assert.ok(sameViewpoint(axisView('z'), axisView('z')));
        assert.ok(!sameViewpoint(axisView('z'), axisView('-z')));
    });
});

suite('The view panel: what the object is cut to', () => {
    test("the object's bounds are its nodes' boxes, placed down the tree", () => {
        assert.deepStrictEqual(boundsOf(brick()), { min: [0, 0, 0], max: [10, 20, 30] });
        // Moved 100 mm along X and turned a quarter about Z: X now runs the
        // other way along Y.
        const assembly: ShowNode = {
            name: '//pkg:pile',
            assembly: [brick([[100, 0, 0], [0, 0, 1], 90])],
        };
        const bounds = boundsOf(assembly)!;
        near(bounds.min, [80, 0, 0]);
        near(bounds.max, [100, 10, 30]);
        assert.strictEqual(boundsOf({ name: '//pkg:nothing' }), undefined);
        assert.strictEqual(boundsOf(null), undefined);
    });

    test('only the axes that keep less than the object are sent, held inside it', () => {
        const bounds = boundsOf(brick())!;
        assert.strictEqual(sectionOf({ x: [0, 10], y: [0, 20], z: [0, 30] }, bounds), null);
        assert.deepStrictEqual(sectionOf({ x: [-5, 4], y: [0, 20] }, bounds), { x: [0, 4] });
        // Nothing left between the two ends is not a section.
        assert.strictEqual(sectionOf({ z: [7, 7] }, bounds), null);
        assert.deepStrictEqual(rangeOf({ x: [0, 4] }, 'y', bounds), [0, 20]);
    });

    test('a section travels as PartCAD reads it, and is read back from what PartCAD said', () => {
        assert.strictEqual(sectionRequest(null), null);
        assert.strictEqual(sectionRequest({}), null);
        assert.deepStrictEqual(sectionRequest({ z: [0, 2.5] }), { z: [0, 2.5] });
        assert.deepStrictEqual(sectionFrom({ x: [0, 5], y: null, w: [0, 1] }), { x: [0, 5] });
        assert.strictEqual(sectionFrom({ x: [5, 0] }), null);
        assert.strictEqual(sectionFrom(null), null);
        assert.ok(sameSection(null, {}));
        assert.ok(sameSection({ x: [0, 5] }, { x: [0, 5.0000000001] }));
        assert.ok(!sameSection({ x: [0, 5] }, { x: [0, 6] }));
        assert.strictEqual(describeSection({ x: [0, 25], z: [0, 12.5] }), 'x 0 to 25 mm, z 0 to 12.5 mm');
    });
});

suite('The view panel: the widget', () => {
    let saved: unknown;

    suiteSetup(() => {
        saved = (globalThis as unknown as { document?: unknown }).document;
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tagName: string) => new FakeElement(tagName),
            createElementNS: (_namespace: string, tagName: string) => new FakeElement(tagName),
            activeElement: undefined,
        };
    });

    suiteTeardown(() => {
        (globalThis as unknown as { document?: unknown }).document = saved;
        setExpanded('right', false);
    });

    function panel() {
        const asked = {
            viewpoints: [] as [Viewpoint, boolean][],
            sections: [] as unknown[],
            resets: 0,
            fits: 0,
            projections: [] as Projection[],
            animate: [] as boolean[],
            autoFit: [] as boolean[],
            opacity: [] as number[],
        };
        const view = new ViewPanel(
            {
                onViewpoint: (viewpoint, final) => asked.viewpoints.push([viewpoint, final]),
                onResetView: () => (asked.resets += 1),
                onFit: () => (asked.fits += 1),
                onProjection: (projection) => asked.projections.push(projection),
                onSection: (section) => asked.sections.push(section),
                onAnimate: (animate) => asked.animate.push(animate),
                onAutoFit: (autoFit) => asked.autoFit.push(autoFit),
                onOpacity: (opacity) => asked.opacity.push(opacity),
            },
            {
                target: true,
                autoFit: true,
                ids: { animate: 'animate-checkbox', autoFit: 'autofit-checkbox', opacity: 'opacity-slider' },
            },
        );
        return { view, root: view.element as unknown as FakeElement, asked };
    }

    test('it starts folded away, and every panel of the side comes out together', () => {
        const one = panel();
        const other = panel();
        assert.strictEqual(isExpanded('right'), false);
        assert.ok(one.view.side.body.hidden);
        const heard: boolean[] = [];
        onToggle((side, expanded) => heard.push(side === 'right' && expanded));

        const [toggle] = byClass(one.root, 'side-panel-toggle');
        assert.strictEqual(toggle.attributes['aria-expanded'], 'false');
        toggle.fire('click');

        assert.strictEqual(isExpanded('right'), true);
        assert.ok(!other.view.side.body.hidden, 'the panel of another tab comes out too');
        assert.strictEqual(toggle.attributes['aria-expanded'], 'true');
        assert.deepStrictEqual(heard, [true]);
        setExpanded('right', false);
        assert.ok(other.view.side.body.hidden);
    });

    test('an axis button looks along its axis, from where the view was', () => {
        const { view, root, asked } = panel();
        view.setCapabilities(EVERYTHING);
        view.setViewpoint({ origin: [0, -200, 0], up: [0, 0, 1], target: [1, 2, 3] });
        const buttons = byClass(root, 'view-axis');
        assert.deepStrictEqual(
            buttons.map((button) => button.textContent),
            ['X', '-X', 'Y', '-Y', 'Z', '-Z'],
        );
        buttons[4].fire('click');

        assert.strictEqual(asked.viewpoints.length, 1);
        const [chosen, final] = asked.viewpoints[0];
        assert.strictEqual(final, true);
        near(chosen.origin, [0, 0, 200]);
        near(chosen.up, [0, 1, 0]);
        near(chosen.target, [1, 2, 3]);
        // And the fields say so.
        const [origin] = byClass(root, 'view-vector');
        assert.strictEqual(origin.value, '0, 0, 200');
    });

    test('the viewpoint comes before the section, with the projection right after its title', () => {
        const { view } = panel();
        const body = view.side.body as unknown as FakeElement;
        const groups = body.children.filter((child) => child.classList.contains('view-group'));
        assert.deepStrictEqual(
            groups.map((group) => group.className),
            ['view-group view-viewpoint', 'view-group view-section', 'view-group view-display'],
        );
        const titles = groups.map((group) => byClass(group, 'view-title').map((title) => title.textContent));
        assert.deepStrictEqual(titles, [['Viewpoint'], ['Section'], []]);

        // In the viewpoint's heading: its title, then the projection; Fit and
        // Reset at the far end.
        const [heading] = byClass(groups[0], 'view-heading');
        const [start, end] = heading.children;
        assert.deepStrictEqual(
            start.children.map((child) => child.tagName),
            ['span', 'select'],
        );
        const select = start.children[1];
        assert.deepStrictEqual(
            select.children.map((option) => [option.value, option.textContent]),
            [
                ['orthographic', 'Orthographic'],
                ['isometric', 'Isometric'],
                ['perspective', 'Perspective'],
            ],
        );
        assert.strictEqual(select.value, 'perspective', 'in perspective unless the tab says otherwise');
        assert.strictEqual(view.projection, 'perspective');
        assert.deepStrictEqual(
            end.children.map((child) => child.textContent),
            ['Fit', 'Reset'],
        );
    });

    test('a projection chosen is reported; Isometric turns the view to the nearest corner, and off it is Orthographic', () => {
        const { view, root, asked } = panel();
        view.setCapabilities(EVERYTHING);
        view.setViewpoint({ origin: [-50, -200, 30], up: [0, 0, 1], target: [1, 2, 3] });
        const [select] = byClass(root, 'view-projection');

        select.value = 'orthographic';
        select.fire('change');
        assert.deepStrictEqual(asked.projections, ['orthographic']);
        assert.strictEqual(asked.viewpoints.length, 0, 'orthographic is drawn from where the view is');

        select.value = 'isometric';
        select.fire('change');
        assert.deepStrictEqual(asked.projections, ['orthographic', 'isometric']);
        assert.strictEqual(asked.viewpoints.length, 1);
        const [corner, final] = asked.viewpoints[0];
        assert.strictEqual(final, true);
        const distance = length([-50, -200, 30]) / Math.sqrt(3);
        near(corner.origin, [-distance, -distance, distance]);
        near(corner.target, [1, 2, 3]);
        assert.strictEqual(view.projection, 'isometric');
        // The fields say where it went.
        const [origin] = byClass(root, 'view-vector');
        assert.strictEqual(origin.value, formatVector(corner.origin));

        // The view read back from there is still the corner.
        view.setViewpoint(corner);
        assert.strictEqual(view.projection, 'isometric');
        // Turned off it - an axis button, here - it is drawn as it was, without
        // perspective, and that is what it is called now.
        byClass(root, 'view-axis')[0].fire('click');
        assert.strictEqual(view.projection, 'orthographic');
        assert.strictEqual(select.value, 'orthographic');
        assert.deepStrictEqual(asked.projections, ['orthographic', 'isometric', 'orthographic']);

        select.value = 'perspective';
        select.fire('change');
        assert.strictEqual(asked.projections[asked.projections.length - 1], 'perspective');
        // Turning the view in perspective says nothing about the projection.
        byClass(root, 'view-axis')[1].fire('click');
        assert.strictEqual(asked.projections.length, 4);
    });

    test('where the projection cannot change it says why, and where the view cannot turn there is no corner', () => {
        const { view, root, asked } = panel();
        const [select] = byClass(root, 'view-projection');
        const corner = select.children.find((option) => option.value === 'isometric')!;
        view.setCapabilities({ ...EVERYTHING, projection: 'PartCAD draws the picture' });
        assert.strictEqual(select.disabled, true);
        assert.strictEqual(select.title, 'PartCAD draws the picture');
        select.value = 'orthographic';
        select.fire('change');
        assert.deepStrictEqual(asked.projections, []);
        assert.strictEqual(select.value, 'perspective', 'it goes on saying what the view is drawn in');

        view.setCapabilities({ ...EVERYTHING, viewpoint: 'Nothing is shown' });
        assert.strictEqual(select.disabled, false);
        assert.strictEqual(corner.disabled, true);
        select.value = 'isometric';
        select.fire('change');
        assert.deepStrictEqual(asked.projections, []);
        assert.deepStrictEqual(asked.viewpoints, []);
        view.setCapabilities(EVERYTHING);
        assert.strictEqual(corner.disabled, false);

        // A tab that draws without perspective says so from the start.
        const picture = new ViewPanel(
            { onViewpoint: () => {}, onResetView: () => {}, onSection: () => {} },
            { target: false, projection: 'orthographic' },
        );
        assert.strictEqual(picture.projection, 'orthographic');
        assert.strictEqual(
            byClass(picture.element as unknown as FakeElement, 'view-projection')[0].value,
            'orthographic',
        );
    });

    test('a viewpoint typed in is what is asked for, and one that is not one is refused there', () => {
        const { view, root, asked } = panel();
        view.setCapabilities(EVERYTHING);
        view.setViewpoint(axisView('x'));
        const [origin, up, target] = byClass(root, 'view-vector');
        origin.value = '[0, -50, 0]';
        origin.fire('change');
        assert.strictEqual(asked.viewpoints.length, 1);
        near(asked.viewpoints[0][0].origin, [0, -50, 0]);
        near(asked.viewpoints[0][0].target, [0, 0, 0]);

        up.value = '0, 1';
        up.fire('change');
        assert.strictEqual(asked.viewpoints.length, 1, 'nothing is asked for a field that is not three numbers');
        assert.ok(up.classList.contains('invalid'));

        up.value = '0, -1, 0';
        up.fire('change');
        assert.strictEqual(asked.viewpoints.length, 1, 'nor for an up along the line of sight');
        const notes = byClass(root, 'view-note').filter((element) => !element.hidden);
        assert.ok(notes.some((note) => note.textContent.includes('line of sight')));
        assert.strictEqual(target.value, '0, 0, 0');
    });

    test('a section slider let go reports the section, and Reset the whole object', () => {
        const { view, root, asked } = panel();
        view.setCapabilities(EVERYTHING);
        view.setBounds(boundsOf(brick()));
        const rows = byClass(root, 'range-pair');
        assert.strictEqual(rows.length, 3);
        const [low, high] = rows[2].children;
        // The top end of Z moved down to halfway: half the brick is kept.
        high.value = '500';
        high.fire('input');
        assert.deepStrictEqual(asked.sections, [], 'nothing is asked while it is being moved');
        high.fire('change');
        assert.deepStrictEqual(asked.sections, [{ z: [0, 15] }]);
        assert.ok(low !== undefined);
        const readout = byClass(root, 'view-slider-value')[2];
        assert.strictEqual(readout.textContent, '0 – 15');

        // The two ends cannot pass each other.
        low.value = '900';
        low.fire('input');
        assert.strictEqual(low.value, '499');

        // The section's own Reset, under the viewpoint's Fit and Reset.
        const [reset] = byClass(byClass(root, 'view-section')[0], 'view-reset');
        reset.fire('click');
        assert.deepStrictEqual(asked.sections[asked.sections.length - 1], null);
    });

    test('Fit is there where the view has a camera to move, and asks for a fit', () => {
        const { view, root, asked } = panel();
        const [fit] = byClass(root, 'view-fit');
        assert.strictEqual(fit.hidden, false);
        assert.strictEqual(fit.textContent, 'Fit');
        fit.fire('click');
        assert.deepStrictEqual([asked.fits, asked.resets], [1, 0]);
        view.setCapabilities({ ...EVERYTHING, viewpoint: 'Nothing is shown' });
        assert.strictEqual(fit.disabled, true);
        view.setCapabilities(EVERYTHING);
        assert.strictEqual(fit.disabled, false);

        // A picture has no camera to bring in: no Fit at all, rather than one
        // that does nothing.
        const picture = new ViewPanel(
            { onViewpoint: () => {}, onResetView: () => {}, onSection: () => {} },
            { target: false },
        );
        assert.strictEqual(byClass(picture.element as unknown as FakeElement, 'view-fit')[0].hidden, true);
    });

    test('Auto-fit sits right after Animate, starts ticked, says when it changes, and goes with Animate', () => {
        const { view, root, asked } = panel();
        const animate = all(root, (element) => element.id === 'animate-checkbox')[0];
        const autoFit = all(root, (element) => element.id === 'autofit-checkbox')[0];
        // The rows of the display group, in order: the box after Animate's is Auto-fit's.
        const rows = byClass(root, 'control-label');
        const row = rows.findIndex((label) => label.children.includes(autoFit));
        assert.ok(row > 0 && rows[row - 1].children.includes(animate), 'Auto-fit is the row after Animate');
        assert.strictEqual(rows[row].hidden, false);
        assert.strictEqual(rows[row].children[1].textContent, 'Auto-fit');
        assert.strictEqual(autoFit.checked, true);
        assert.strictEqual(view.autoFitting, true);

        autoFit.checked = false;
        autoFit.fire('change');
        assert.deepStrictEqual(asked.autoFit, [false]);
        assert.strictEqual(view.autoFitting, false);

        // Where the 3D view cannot start, neither can be changed.
        view.setCapabilities({ ...EVERYTHING, animate: 'The 3D view could not start' });
        assert.strictEqual(autoFit.disabled, true);
        assert.strictEqual(rows[row].title, 'The 3D view could not start');

        // A view that does not fit on a show has no Auto-fit at all.
        const picture = new ViewPanel(
            { onViewpoint: () => {}, onResetView: () => {}, onSection: () => {} },
            { target: false, ids: { autoFit: 'autofit-checkbox' } },
        );
        const pictureRoot = picture.element as unknown as FakeElement;
        const box = all(pictureRoot, (element) => element.id === 'autofit-checkbox')[0];
        const label = byClass(pictureRoot, 'control-label').find((element) => element.children.includes(box));
        assert.strictEqual(label?.hidden, true);
    });

    test('what a tab cannot do is disabled, and says why', () => {
        const { view, root, asked } = panel();
        view.setBounds(boundsOf(brick()));
        view.setCapabilities({
            viewpoint: 'A drawing lays its views out itself',
            projection: 'A drawing lays its views out itself',
            section: true,
            animate: 'A picture holds still',
            opacity: 'A picture holds still',
        });
        for (const button of byClass(root, 'view-axis')) {
            assert.strictEqual(button.disabled, true);
        }
        byClass(root, 'view-axis')[0].fire('click');
        assert.deepStrictEqual(asked.viewpoints, []);
        const notes = byClass(root, 'view-note').filter((element) => !element.hidden);
        assert.ok(notes.some((note) => note.textContent === 'A drawing lays its views out itself'));
        const animate = all(root, (element) => element.id === 'animate-checkbox')[0];
        assert.strictEqual(animate.disabled, true);
        const sliders = byClass(root, 'range-low');
        assert.ok(
            sliders.every((slider) => !slider.disabled),
            'the section still works',
        );
    });

    test('why a part does not work goes once it does, and gives back what it had to say', () => {
        const { view, root } = panel();
        view.setBounds(boundsOf(brick()));
        view.setSectionNote('Cutting…');
        view.setCapabilities({ ...EVERYTHING, viewpoint: 'The 3D view is starting', section: 'Nothing is shown' });
        const visible = () =>
            byClass(root, 'view-note')
                .filter((note) => !note.hidden)
                .map((note) => note.textContent);
        // The viewpoint's first: it is above the section.
        assert.deepStrictEqual(visible(), ['The 3D view is starting', 'Nothing is shown']);

        view.setCapabilities(EVERYTHING);
        assert.deepStrictEqual(visible(), ['Cutting…']);
        view.setSectionNote(undefined);
        assert.deepStrictEqual(visible(), []);
    });

    test('without the size of the object there is nothing to slide across', () => {
        const { view, root } = panel();
        view.setCapabilities(EVERYTHING);
        view.setBounds(undefined);
        assert.ok(byClass(root, 'range-low').every((slider) => slider.disabled));
    });

    test('Animate and Opacity say what they are set to', () => {
        const { root, asked, view } = panel();
        view.setCapabilities(EVERYTHING);
        const animate = all(root, (element) => element.id === 'animate-checkbox')[0];
        animate.checked = false;
        animate.fire('change');
        const opacity = all(root, (element) => element.id === 'opacity-slider')[0];
        opacity.value = '40';
        opacity.fire('input');
        assert.deepStrictEqual(asked.animate, [false]);
        assert.deepStrictEqual(asked.opacity, [0.4]);
        assert.strictEqual(view.opacityFraction, 0.4);
    });
});
