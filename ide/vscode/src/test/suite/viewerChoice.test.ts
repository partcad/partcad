//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the 3D view singles out when the CMF tab's "Show in 3D" is pressed: an
// item, or one of its sets ('choice.ts'). What is drawn is the scene's to say and
// cannot be checked here; what is chosen - which meshes, by which names and
// which sets - is pinned instead, with the buttons that ask for it.
//

import * as assert from 'assert';

import { CmfChoice, chosen, identityOf, sameSet, setLabel, setsOf } from '../../webview/choice';
import { CmfView, itemChoice, referenceName, setChoice } from '../../webview/cmf';
import { CmfItem } from '../../webview/messages';

/** Just enough of an element for 'dom.ts', the CMF tab, and a button to press. */
class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public type = '';
    public hidden = false;
    public readonly style: Record<string, string> = {};
    private readonly listeners: (() => void)[] = [];
    public readonly classList = {
        add: (...names: string[]) => {
            const classes = new Set(this.className.split(' ').filter((name) => name.length > 0));
            names.forEach((name) => classes.add(name));
            this.className = Array.from(classes).join(' ');
        },
    };

    constructor(public readonly tagName: string) {}

    public appendChild(child: FakeElement): FakeElement {
        this.children.push(child);
        return child;
    }

    public replaceChildren(): void {
        this.children.length = 0;
    }

    public setAttribute(): void {}

    public addEventListener(_type: string, listener: () => void): void {
        this.listeners.push(listener);
    }

    public click(): void {
        this.listeners.forEach((listener) => listener());
    }
}

/** Every element under 'root' whose class list holds 'className', in the order drawn. */
function find(root: FakeElement, className: string): FakeElement[] {
    const found: FakeElement[] = [];
    const walk = (node: FakeElement) => {
        if (node.className.split(' ').includes(className)) {
            found.push(node);
        }
        node.children.forEach(walk);
    };
    walk(root);
    return found;
}

const BRACKET: CmfItem = {
    name: '//pkg:bracket',
    kind: 'part',
    count: 2,
    findings: [],
    cmf: {
        sets: [
            { color: '//pkg:red', material: '//pkg:abs', origin: 'declared', faces: 4, solids: 1 },
            { color: '//pkg:red', material: '//pkg:pla', origin: 'declared', faces: 2, solids: 0 },
        ],
    },
};

suite('What the CMF tab singles out in the 3D view', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tagName: string) => new FakeElement(tagName),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('a set is known by its references and its origin, and nothing else', () => {
        const set = BRACKET.cmf!.sets[0];
        assert.deepStrictEqual(identityOf(set), { color: '//pkg:red', material: '//pkg:abs', origin: 'declared' });
        // What a mesh says of itself ('wrapper_gltf._face_sets'): the same keys.
        assert.ok(sameSet(identityOf(set), { color: '//pkg:red', material: '//pkg:abs', origin: 'declared' }));
        // Two sets of one colour are two sets.
        assert.ok(!sameSet(identityOf(set), identityOf(BRACKET.cmf!.sets[1])));
        // Nothing said is a set too: faces nobody coloured.
        assert.ok(sameSet(identityOf({}), {}));
        assert.ok(!sameSet({}, { color: '//pkg:red' }));
    });

    test('a mesh says its sets in its extras, or says nothing', () => {
        assert.deepStrictEqual(setsOf({ partcadSets: [{ material: '//m:abs', faces: 3 }, {}] }), [
            { material: '//m:abs' },
            {},
        ]);
        for (const nothing of [undefined, {}, { partcadSets: 'abs' }, { partcadSets: null }]) {
            assert.strictEqual(setsOf(nothing as Record<string, unknown> | undefined), undefined);
        }
        assert.deepStrictEqual(setsOf({ partcadSets: [null, 'red', { color: '//c:red' }] }), [{ color: '//c:red' }]);
    });

    test('an item is every node it is, and everything in one', () => {
        const item: CmfChoice = itemChoice(BRACKET);
        assert.strictEqual(item.item, '//pkg:bracket');
        assert.strictEqual(item.set, undefined);
        assert.ok(chosen(item, ['//pkg:assy', '//pkg:bracket'], undefined));
        // Inside an item: an assembly bought whole takes what it holds.
        assert.ok(chosen(item, ['//pkg:assy', '//pkg:bracket', '//pkg:insert'], [{ color: '//c:black' }]));
        assert.ok(!chosen(item, ['//pkg:assy', '//pkg:bolt'], undefined));
    });

    test('a set is the meshes that say they are in it, and every mesh of a part in one set', () => {
        const abs = setChoice(BRACKET, BRACKET.cmf!.sets[0]);
        const names = ['//pkg:assy', '//pkg:bracket'];
        const absMesh = [{ color: '//pkg:red', material: '//pkg:abs', origin: 'declared' }];
        const plaMesh = [{ color: '//pkg:red', material: '//pkg:pla', origin: 'declared' }];
        assert.ok(chosen(abs, names, absMesh));
        assert.ok(!chosen(abs, names, plaMesh));
        // A face in a set of its own and on a solid of another is in both.
        assert.ok(chosen(abs, names, [{ color: '//pkg:blue' }, absMesh[0]]));
        // A mesh that says nothing is a part in one set: whichever of it is chosen.
        assert.ok(chosen(abs, names, undefined));
        // Not another item's, whatever it says.
        assert.ok(!chosen(abs, ['//pkg:assy', '//pkg:other'], absMesh));
    });

    test('the chip says what is shown, by name', () => {
        assert.strictEqual(itemChoice(BRACKET).label, 'bracket');
        assert.strictEqual(setChoice(BRACKET, BRACKET.cmf!.sets[0]).label, 'red · abs of bracket');
        assert.strictEqual(setLabel({}, referenceName), 'the faces nothing is said of');
        assert.strictEqual(setLabel({ finish: '//f:brushed%2C%20satin' }, referenceName), 'brushed, satin');
    });

    test('each item and each of its sets has a "Show in 3D", which asks for it', () => {
        const root = new FakeElement('div');
        const asked: CmfChoice[] = [];
        new CmfView(root as unknown as HTMLElement, (choice) => asked.push(choice)).show({ items: [BRACKET] } as never);
        const buttons = find(root, 'cmf-show');
        assert.strictEqual(buttons.length, 3);
        assert.ok(buttons.every((button) => button.tagName === 'button' && button.textContent === 'Show in 3D'));
        buttons.forEach((button) => button.click());
        assert.deepStrictEqual(
            asked.map((choice) => choice.set),
            [undefined, identityOf(BRACKET.cmf!.sets[0]), identityOf(BRACKET.cmf!.sets[1])],
        );
        // A tab that cannot show anything in 3D offers no button.
        const quiet = new FakeElement('div');
        new CmfView(quiet as unknown as HTMLElement).show({ items: [BRACKET] } as never);
        assert.strictEqual(find(quiet, 'cmf-show').length, 0);
    });
});
