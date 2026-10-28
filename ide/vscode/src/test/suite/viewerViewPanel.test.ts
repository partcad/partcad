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
//
// The widget is exercised through a stand-in DOM, as the control tree's is (see
// 'viewerTree.test.ts'): this suite runs in the extension host, which has none.
//

import * as assert from 'assert';

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
    Vec3,
    Viewpoint,
    Y_POLE,
    Z_POLE,
    axisOf,
    axisView,
    basis,
    formatVector,
    fromTurntable,
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

const EVERYTHING: ViewCapabilities = { viewpoint: true, section: true, animate: true, opacity: true };

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
            animate: [] as boolean[],
            opacity: [] as number[],
        };
        const view = new ViewPanel(
            {
                onViewpoint: (viewpoint, final) => asked.viewpoints.push([viewpoint, final]),
                onResetView: () => (asked.resets += 1),
                onSection: (section) => asked.sections.push(section),
                onAnimate: (animate) => asked.animate.push(animate),
                onOpacity: (opacity) => asked.opacity.push(opacity),
            },
            { target: true, ids: { animate: 'animate-checkbox', opacity: 'opacity-slider' } },
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

        const [reset] = byClass(root, 'view-reset');
        reset.fire('click');
        assert.deepStrictEqual(asked.sections[asked.sections.length - 1], null);
    });

    test('what a tab cannot do is disabled, and says why', () => {
        const { view, root, asked } = panel();
        view.setBounds(boundsOf(brick()));
        view.setCapabilities({
            viewpoint: 'A drawing lays its views out itself',
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
        assert.deepStrictEqual(visible(), ['Nothing is shown', 'The 3D view is starting']);

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
