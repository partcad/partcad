//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The 3D view's control pane: what it lists for an object's tree, and which of it
// ends up drawn.
//
// The widget runs in the webview and this suite runs in the extension host, which
// has no DOM, so it is given one - just the handful of things 'dom.ts' asks of an
// element. That is enough because the part worth testing is not the markup. It is
// that the rows are read out of the object's own tree with no per-kind case in it,
// that a port is listed under the interface it belongs to and nowhere else, that a
// box switches its item *and everything under it* off without forgetting what was
// under it, and that showing the same object again keeps what the user switched
// off. The rest of the webview is not reachable from here at all - 'scene.ts'
// builds a WebGL renderer as it loads.
//

import * as assert from 'assert';

import { FLICKER_HZ, ItemId, flickerOn } from '../../webview/nodes';
import { ShowNode } from '../../webview/messages';
import { Tree } from '../../webview/tree';

/** Just enough of an element for 'dom.ts' and for the widget's own use of one. */
class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public type = '';
    public checked = false;
    public indeterminate = false;
    public readonly attributes: Record<string, string> = {};
    private readonly listeners: Record<string, (() => void)[]> = {};

    constructor(public readonly tagName: string) {}

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

    public addEventListener(name: string, handler: () => void): void {
        (this.listeners[name] ??= []).push(handler);
    }

    /** Raise an event the way the user would. */
    public fire(name: string): void {
        (this.listeners[name] ?? []).forEach((handler) => handler());
    }
}

/**
 * The element the pane is drawn into, and the widget's view of it.
 *
 * Two references to one object: the widget takes an 'HTMLElement' and this is a
 * stand-in for one, so the cast is what a DOM would otherwise supply.
 */
function host(): [FakeElement, HTMLElement] {
    const element = new FakeElement('div');
    return [element, element as unknown as HTMLElement];
}

/** Everything in the pane of one tag name, in the order it is drawn. */
function descendants(root: FakeElement, tagName: string): FakeElement[] {
    const found: FakeElement[] = [];
    const walk = (element: FakeElement) => {
        if (element.tagName === tagName) {
            found.push(element);
        }
        element.children.forEach(walk);
    };
    walk(root);
    return found;
}

/** Tick or untick a box as the user does: the property, then the event. */
function set(box: FakeElement, checked: boolean): void {
    box.checked = checked;
    box.fire('change');
}

/** A placement that is not the identity, so that losing one would show. */
const SOMEWHERE: [[number, number, number], [number, number, number], number] = [[0, 0, 20], [0, 0, 1], 0];

/**
 * What PartCAD sends for an assembly: itself, a node per thing it holds, and the
 * ports and interfaces each of them declares.
 *
 * The plate's 'TL-thru-m3' belongs to an interface instance and its 'origin' does
 * not, which is the division the pane has to make.
 */
function assembly(): ShowNode {
    return {
        name: '//pkg:mount',
        label: 'mount',
        ports: [{ name: 'hold', location: SOMEWHERE }],
        assembly: [
            {
                name: '//pkg:plate',
                label: 'bottom',
                location: SOMEWHERE,
                gltf: 'Z2xURg==',
                ports: [
                    {
                        name: 'TL-thru-m3',
                        location: SOMEWHERE,
                        interface: '//pkg:m3-thru',
                        instance: 'TL',
                    },
                    { name: 'origin', location: SOMEWHERE },
                ],
                interfaces: [{ name: '//pkg:m3-thru', instance: 'TL', ports: ['TL-thru-m3'] }],
            },
        ],
    };
}

/** What PartCAD sends for a part: the same thing, one node deep. */
function part(): ShowNode {
    return {
        name: '//pkg:bracket',
        label: 'bracket',
        gltf: 'Z2xURg==',
        ports: [{ name: 'thru-m3', location: SOMEWHERE, interface: '//pkg:m3-thru', instance: '' }],
        interfaces: [{ name: '//pkg:m3-thru', instance: '', ports: ['thru-m3'] }],
    };
}

/** The elements of one class, in the order they are drawn. */
function byClass(root: FakeElement, className: string): FakeElement[] {
    const found: FakeElement[] = [];
    const walk = (element: FakeElement) => {
        if (element.className === className) {
            found.push(element);
        }
        element.children.forEach(walk);
    };
    walk(root);
    return found;
}

/** Every row that folds, as "<kind> <name> open|folded", in the order drawn. */
function folding(pane: FakeElement): string[] {
    const found: string[] = [];
    const walk = (element: FakeElement) => {
        if (element.className.startsWith('tree-item ')) {
            const line = element.children.find((child) => child.className === 'tree-line');
            const twisty = line?.children.find((child) => child.className === 'tree-twisty');
            const name = line && descendants(line, 'span').find((span) => span.className === 'tree-name');
            if (twisty !== undefined) {
                const kind = element.className.replace('tree-item tree-', '');
                const open = twisty.attributes['aria-expanded'] === 'true';
                found.push(`${kind} ${name?.textContent ?? ''} ${open ? 'open' : 'folded'}`);
            }
        }
        element.children.forEach(walk);
    };
    walk(pane);
    return found;
}

/** The rows of the pane, in the order they are drawn, as "<kind> <name>". */
function rows(pane: FakeElement): string[] {
    const found: string[] = [];
    const walk = (element: FakeElement) => {
        if (element.className.startsWith('tree-item ')) {
            const name = descendants(element, 'span').find((span) => span.className === 'tree-name');
            found.push(`${element.className.replace('tree-item tree-', '')} ${name?.textContent ?? ''}`);
        }
        element.children.forEach(walk);
    };
    walk(pane);
    return found;
}

suite("The 3D view's control tree", () => {
    let created: string[] = [];

    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tagName: string) => {
                created.push(tagName);
                return new FakeElement(tagName);
            },
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    setup(() => {
        created = [];
    });

    test("an assembly is listed as the hierarchy it is, with each node's own ports", () => {
        const [pane, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(assembly());

        assert.deepStrictEqual(rows(pane), [
            'object mount',
            'node bottom',
            'ports ports',
            'port origin',
            'interfaces interfaces',
            'interface m3-thru (TL)',
            'port TL-thru-m3',
            'ports ports',
            'port hold',
        ]);
    });

    test('a part is the same thing one node deep, with nothing special about it', () => {
        const [pane, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(part());

        assert.deepStrictEqual(rows(pane), [
            'object bracket',
            'interfaces interfaces',
            'interface m3-thru',
            'port thru-m3',
        ]);
        // Its own ports, so they are drawn from the start - the same rule the
        // assembly's own ports get, applied at the same depth.
        assert.deepStrictEqual([...tree.visible()].sort(), ['n', 'n:i0', 'n:interfaces', 'n:p0']);
    });

    test('a port is listed under the interface it belongs to and nowhere else', () => {
        const [pane, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(assembly());

        // One triad, one box: 'TL-thru-m3' appears once, under its instance, and
        // the plate's 'ports' group holds only the port that belongs to none.
        assert.strictEqual(rows(pane).filter((row) => row === 'port TL-thru-m3').length, 1);
        assert.deepStrictEqual(
            rows(pane).filter((row) => row.startsWith('port ')),
            ['port origin', 'port TL-thru-m3', 'port hold'],
        );
    });

    test("only the object's own ports start out drawn", () => {
        const [, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(assembly());

        // 'n:ports' and its 'hold' are the assembly's own; 'n0:ports' and
        // 'n0:interfaces' are a node inside it and start out off, along with
        // everything under them.
        assert.deepStrictEqual([...tree.visible()].sort(), ['n', 'n0', 'n:p0', 'n:ports']);
    });

    test('a ticked box hiding something below it is shown indeterminate', () => {
        const [pane, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(assembly());

        const [root, node, innerPorts] = descendants(pane, 'input');
        // The only way a collapsed row can say that something under it is off.
        assert.strictEqual(root.indeterminate, true);
        assert.strictEqual(node.indeterminate, true);
        // An unticked box is not also indeterminate.
        assert.strictEqual(innerPorts.indeterminate, false);
    });

    test('switching a node off does not forget what was under it', () => {
        const [pane, element] = host();
        let visible = new Set<string>();
        const tree = new Tree(element, () => (visible = tree.visible()));
        tree.setObject(assembly());

        const [, node, innerPorts] = descendants(pane, 'input');
        set(innerPorts, true);
        assert.ok(visible.has('n0:ports'));

        set(node, false);
        assert.deepStrictEqual([...visible].sort(), ['n', 'n:p0', 'n:ports']);
        set(node, true);
        // The ports group the user switched on is on again, rather than back to
        // the state it started in.
        assert.ok(visible.has('n0:ports'));
    });

    test('the root box switches the whole model off', () => {
        const [pane, element] = host();
        let visible = new Set<string>();
        const tree = new Tree(element, () => (visible = tree.visible()));
        tree.setObject(assembly());

        set(descendants(pane, 'input')[0], false);
        assert.deepStrictEqual([...visible], []);
    });

    test('showing the same object again keeps what the user switched off', () => {
        const [pane, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(assembly());

        const boxes = descendants(pane, 'input');
        set(boxes[2], true); // the plate's 'ports' group, off by default
        set(boxes[boxes.length - 1], false); // the assembly's own 'hold'

        // What 'viewer.ts' does when the show says to keep the camera: the same
        // object after an edit, where losing the selection is as unwelcome as
        // losing the camera. Both directions are kept.
        tree.setObject(assembly(), tree.state());
        const visible = tree.visible();
        assert.ok(visible.has('n0:ports'));
        assert.ok(!visible.has('n:p0'));

        // And a show that is not the same object starts from the defaults.
        tree.setObject(assembly());
        assert.deepStrictEqual([...tree.visible()].sort(), ['n', 'n0', 'n:p0', 'n:ports']);
    });

    test('collapsing a row changes what is listed and not what is drawn', () => {
        const [pane, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(assembly());

        const twisty = descendants(pane, 'button')[0];
        twisty.fire('click');
        assert.strictEqual(twisty.attributes['aria-expanded'], 'false');
        assert.deepStrictEqual([...tree.visible()].sort(), ['n', 'n0', 'n:p0', 'n:ports']);

        twisty.fire('click');
        assert.strictEqual(twisty.attributes['aria-expanded'], 'true');
    });

    test('the ports and interfaces of a node start folded up', () => {
        const [pane, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(assembly());

        // The hierarchy is what the pane is for, so the object and its nodes are
        // open; the two group rows run to a dozen rows for a part and hundreds for
        // an assembly, and unfolded they bury what they are attached to. An
        // interface *instance* is not one of those groups - it is one interface,
        // with the ports it is made of - so it stays open inside the folded group.
        assert.deepStrictEqual(folding(pane), [
            'object mount open',
            'node bottom open',
            'ports ports folded',
            'interfaces interfaces folded',
            'interface m3-thru (TL) open',
            'ports ports folded',
        ]);

        // Folded is about the rows, not about what is drawn: the ports of the
        // assembly itself are still shown.
        assert.ok(tree.visible().has('n:p0'));
    });

    test('a folded group still opens', () => {
        const [pane, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(assembly());

        const group = byClass(pane, 'tree-twisty')[2];
        assert.strictEqual(group.attributes['aria-expanded'], 'false');
        group.fire('click');
        assert.strictEqual(group.attributes['aria-expanded'], 'true');
    });

    test('pointing at a part or a sub-assembly singles out its shape', () => {
        const [pane, element] = host();
        let singled: Set<ItemId> | undefined;
        const tree = new Tree(
            element,
            () => undefined,
            (items) => (singled = items),
        );
        tree.setObject(assembly());

        const [root, node] = byClass(pane, 'tree-line');

        // A sub-assembly has no geometry of its own - what is drawn is what is
        // inside it - so the whole subtree is singled out, and the ports and
        // interfaces in it are not: what is being pointed at is the shape.
        root.fire('mouseenter');
        assert.deepStrictEqual([...(singled ?? [])].sort(), ['n', 'n0']);

        node.fire('mouseenter');
        assert.deepStrictEqual([...(singled ?? [])], ['n0']);

        node.fire('mouseleave');
        assert.strictEqual(singled, undefined);
    });

    test('pointing at a port or a group singles out nothing', () => {
        const [pane, element] = host();
        const seen: (Set<ItemId> | undefined)[] = [];
        const tree = new Tree(
            element,
            () => undefined,
            (items) => seen.push(items),
        );
        tree.setObject(assembly());

        // A port is already told apart by the triad and the boundary drawn at it,
        // and a group row stands for no shape at all.
        for (const line of byClass(pane, 'tree-line').slice(2)) {
            line.fire('mouseenter');
        }
        assert.deepStrictEqual(seen, []);
    });

    test('a flicker is seven on and seven off a second', () => {
        // Driven by the clock rather than by a frame count, so the rate holds
        // whatever the renderer manages.
        const half = 1000 / FLICKER_HZ / 2;
        assert.strictEqual(flickerOn(0), true);
        assert.strictEqual(flickerOn(half * 0.9), true);
        assert.strictEqual(flickerOn(half * 1.1), false);
        assert.strictEqual(flickerOn(half * 2.1), true);

        // Seven full cycles in a second, counted rather than asserted by arithmetic.
        let changes = 0;
        let previous = flickerOn(0);
        for (let ms = 1; ms <= 1000; ms++) {
            const now = flickerOn(ms);
            if (now !== previous) {
                changes += 1;
                previous = now;
            }
        }
        assert.strictEqual(changes, FLICKER_HZ * 2);
    });

    test('an emptied pane has nothing to draw', () => {
        const [pane, element] = host();
        const tree = new Tree(element, () => undefined);
        tree.setObject(assembly());
        tree.clear();

        assert.deepStrictEqual([...tree.visible()], []);
        assert.strictEqual(pane.children.length, 0);
    });

    test('nothing is built as markup', () => {
        // Every name in the pane is a part's or a port's, out of a package's
        // configuration, and none of it is escaped anywhere on the way here.
        const tree = new Tree(host()[1], () => undefined);
        tree.setObject(assembly());

        assert.deepStrictEqual([...new Set(created)].sort(), ['button', 'div', 'input', 'label', 'span']);
    });
});
