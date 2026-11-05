//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The callout boxes under the tree of the 3D and 2D tabs: "Component names",
// "Component prices", "Port names" and "Interface names".
//
// What is pinned here is what the boxes start out as, that the two tabs show one
// answer, and what the 2D tab sends with a render for it - the 'pc render'
// options the boxes are. What the 3D view writes for them is 'scene.ts', which
// cannot be loaded here; what its callouts say is 'viewerCallouts.test.ts'.
//
// The widget runs in the webview and this suite in the extension host, which has
// no DOM, so it is given the handful of things 'dom.ts' and the widget ask of
// an element.
//

import * as assert from 'assert';

import { LABEL_BOXES, LABEL_DEFAULTS, LabelBoxes, LabelKey, Labels, renderOptions } from '../../webview/labels';

class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public type = '';
    public checked = false;
    public readonly attributes: Record<string, string> = {};
    public readonly classList = {
        add: (...names: string[]) => {
            this.className = [...this.className.split(' ').filter(Boolean), ...names].join(' ');
        },
    };
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

/** The boxes one widget drew, by what each is labelled, and the note under them. */
function drawn(host: FakeElement): { boxes: Map<string, FakeElement>; note: FakeElement } {
    const boxes = new Map<string, FakeElement>();
    for (const row of host.children.filter((child) => child.tagName === 'label')) {
        const box = row.children.find((child) => child.tagName === 'input');
        const text = row.children.find((child) => child.tagName === '#text');
        boxes.set((text?.textContent ?? '').trim(), box!);
    }
    const note = host.children.find((child) => child.className === 'label-note')!;
    return { boxes, note };
}

function widget(labels: Labels): { host: FakeElement; boxes: LabelBoxes } {
    const host = new FakeElement('div');
    return { host, boxes: new LabelBoxes(host as unknown as HTMLElement, labels) };
}

/** Tick or untick a box as the user does: the property, then the event. */
function set(box: FakeElement, checked: boolean): void {
    box.checked = checked;
    box.fire('change');
}

suite('The callout boxes under the tree', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tagName: string) => new FakeElement(tagName),
            createTextNode: (text: string) => {
                const node = new FakeElement('#text');
                node.textContent = text;
                return node;
            },
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('they start out writing the names of what is drawn, and nothing about the components or materials', () => {
        const { host } = widget(new Labels());
        const { boxes, note } = drawn(host);

        assert.deepStrictEqual(
            [...boxes.entries()].map(([label, box]) => [label, box.checked]),
            [
                ['Component names', false],
                ['Component prices', false],
                ['Materials', false],
                ['Port names', true],
                ['Interface names', true],
            ],
        );
        assert.deepStrictEqual(
            LABEL_BOXES.map(({ key }) => LABEL_DEFAULTS[key]),
            [false, false, false, true, true],
        );
        // What each box is called is the thing it writes, with nothing in front of it.
        for (const { label } of LABEL_BOXES) {
            assert.doesNotMatch(label, /^Show /);
            assert.match(label, /^[A-Z]/);
        }
        assert.strictEqual(note.hidden, true);
        // Each says what it is on the command line too.
        for (const row of host.children.filter((child) => child.tagName === 'label')) {
            assert.match(row.title, /pc render --with/);
        }
    });

    test('the two tabs show one answer', () => {
        const labels = new Labels();
        const told: LabelKey[] = [];
        labels.onChange((key) => told.push(key));
        const threeD = widget(labels);
        const twoD = widget(labels);

        set(drawn(threeD.host).boxes.get('Component prices')!, true);
        set(drawn(twoD.host).boxes.get('Port names')!, false);

        assert.strictEqual(drawn(twoD.host).boxes.get('Component prices')!.checked, true);
        assert.strictEqual(drawn(threeD.host).boxes.get('Port names')!.checked, false);
        assert.deepStrictEqual(told, ['componentPrices', 'portNames']);
        assert.deepStrictEqual(labels.current, {
            componentNames: false,
            componentPrices: true,
            materials: false,
            portNames: false,
            interfaceNames: true,
        });
    });

    test('saying again what a box says is not a change', () => {
        const labels = new Labels();
        let told = 0;
        labels.onChange(() => (told += 1));

        labels.set('portNames', true);
        labels.set('componentNames', false);

        assert.strictEqual(told, 0);
    });

    test('a note under them says what the prices are doing, and goes', () => {
        const { host, boxes } = widget(new Labels());

        boxes.setNote('Asking the suppliers what each component costs…');
        assert.strictEqual(drawn(host).note.hidden, false);
        assert.strictEqual(drawn(host).note.textContent, 'Asking the suppliers what each component costs…');

        boxes.setNote(undefined);
        assert.strictEqual(drawn(host).note.hidden, true);
    });

    test('the prices and the materials each have a line of the note', () => {
        const { host, boxes } = widget(new Labels());

        boxes.setNote('Finding where each material is…', 'materials');
        boxes.setNote('Asking the suppliers what each component costs…');
        // In the order the boxes are listed, whichever said so first.
        assert.strictEqual(
            drawn(host).note.textContent,
            'Asking the suppliers what each component costs…\nFinding where each material is…',
        );

        boxes.setNote(undefined);
        assert.strictEqual(drawn(host).note.textContent, 'Finding where each material is…');
        boxes.setNote(undefined, 'materials');
        assert.strictEqual(drawn(host).note.hidden, true);
    });

    test('a render as the boxes start is asked for in the words it always was', () => {
        assert.deepStrictEqual(renderOptions({ ...LABEL_DEFAULTS }), {});
    });

    test('a render is sent each box that says something it would not do anyway', () => {
        assert.deepStrictEqual(
            renderOptions({
                componentNames: true,
                componentPrices: true,
                materials: true,
                portNames: false,
                interfaceNames: false,
            }),
            {
                withComponentNames: true,
                withComponentPrices: true,
                withMaterials: true,
                withPortNames: false,
                withInterfaceNames: false,
            },
        );
        assert.deepStrictEqual(
            renderOptions({
                componentNames: false,
                componentPrices: true,
                materials: false,
                portNames: true,
                interfaceNames: true,
            }),
            { withComponentPrices: true },
        );
    });
});
