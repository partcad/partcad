//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Colour, material and finish, as the Digital Thread shows them: the CMF tab of
// an object and of a declaration, and the Color, Material and Finish columns of
// the bill of materials and of Build vs Buy.
//
// What is specified, what is only a picture and which item comes first are the
// daemon's to say ('cmf.info', 'partcad.cmf'), and are tested there. What is
// pinned here is that this side draws what it is told the one way every view
// draws CMF (docs/design/cmf.md, "One presentation"): colour, material and
// finish in that order, each by the name of what it names, with a swatch of
// what it is drawn in, and marked when it is display-only or unspecified.
//

// The keys below are PartCAD's own field names and object names.
/* eslint-disable @typescript-eslint/naming-convention */

import * as assert from 'assert';

import { renderBom } from '../../webview/bom';
import { lineCmf } from '../../webview/bvb';
import { CmfView, cmfCells, finishLook, referenceName, standingOf, unspecifiedText } from '../../webview/cmf';
import { BomData, CmfData, CmfInfo, CmfItem, TreeNode, isDeclaration } from '../../webview/messages';

/** Just enough of an element for 'dom.ts' and the panes drawn with it. */
class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public href = '';
    public hidden = false;
    public readonly style: Record<string, string> = {};
    public readonly attributes: Record<string, string> = {};
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

    public setAttribute(name: string, value: string): void {
        this.attributes[name] = value;
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

/** All the text under 'root', in the order drawn. */
function text(root: FakeElement): string {
    return [root.textContent, ...root.children.map(text)].filter((part) => part.length > 0).join(' ');
}

/** Every element under 'root' of one tag. */
function tags(root: FakeElement, tagName: string): FakeElement[] {
    const found: FakeElement[] = [];
    const walk = (node: FakeElement) => {
        if (node.tagName === tagName) {
            found.push(node);
        }
        node.children.forEach(walk);
    };
    walk(root);
    return found;
}

/** A two-colour moulding: red and preview-green faces of one material, and some of it in no colour. */
const MOULDING: CmfInfo = {
    sets: [
        {
            color: '//vendor:Bright Red',
            material: '//vendor:ABS',
            display: '#C91A09FF',
            origin: 'source:step',
            faces: 4,
            solids: 1,
        },
        {
            color: '//pub/std/color:rgba;color=00FF00FF',
            material: '//vendor:ABS',
            finish: '//vendor:satin',
            displayOnly: ['color'],
            display: '#00FF00FF',
            roughness: 0.6,
            metallic: 0,
            origin: 'source:step',
            faces: 2,
            solids: 0,
        },
    ],
    unspecified: { color: 3 },
};

function item(overrides: Partial<CmfItem> = {}): CmfItem {
    return { name: '//pkg:housing', kind: 'part', count: 1, cmf: MOULDING, findings: [], ...overrides };
}

suite('CMF in the Digital Thread', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tagName: string) => new FakeElement(tagName),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('a declaration is named as its specification writes it: no package, and its escapes read', () => {
        assert.strictEqual(referenceName('//vendor:Medium Stone Grey'), 'Medium Stone Grey');
        assert.strictEqual(referenceName('//vendor:PA12%2C glass filled'), 'PA12, glass filled');
        // A parameter value that is a reference of its own does not move the split.
        assert.strictEqual(referenceName('//pub/std/color:rgba;color=C91A09FF'), 'rgba;color=C91A09FF');
        assert.strictEqual(referenceName('bare'), 'bare');
    });

    test('a column holds each value once, in the order of the sets, then the mark that some of it has none', () => {
        const colors = cmfCells(MOULDING, 'color');
        assert.deepStrictEqual(
            colors.map((cell) => [cell.text, cell.swatch, cell.displayOnly === true, cell.unspecified === true]),
            [
                ['Bright Red', '#C91A09FF', false, false],
                ['rgba;color=00FF00FF', '#00FF00FF', true, false],
                ['unspecified', undefined, false, true],
            ],
        );
        assert.match(colors[2].title, /No colour on 3 faces/);

        // One material for both sets is one value, with no swatch: a swatch is a colour's.
        assert.deepStrictEqual(
            cmfCells(MOULDING, 'material').map((cell) => [cell.text, cell.swatch]),
            [['ABS', undefined]],
        );

        // A finish says how it looks when pointed at, and one nobody states is
        // as produced, which is no gap to mark.
        const finishes = cmfCells(MOULDING, 'finish');
        assert.deepStrictEqual(
            finishes.map((cell) => cell.text),
            ['satin'],
        );
        assert.match(finishes[0].title, /roughness 0\.6, metallic 0/);
    });

    test('a column read off a declaration says that its source is still to be read', () => {
        const declared: CmfInfo = { sets: [{ color: '//pkg:red', display: '#C91A09' }], declared: true };
        assert.match(cmfCells(declared, 'color')[0].title, /As declared/);
        assert.deepStrictEqual(cmfCells(null, 'color'), []);
        assert.deepStrictEqual(cmfCells(undefined, 'material'), []);
    });

    test('what is unspecified is said of what it is missing on', () => {
        assert.strictEqual(
            unspecifiedText({ sets: [], unspecified: { color: 'all', material: 2 } }),
            'Unspecified: no colour on all faces; no material on 2 solids.',
        );
        assert.strictEqual(
            unspecifiedText({ sets: [], unspecified: { color: 'some' } }),
            'Unspecified: no colour on some faces.',
        );
        assert.strictEqual(unspecifiedText({ sets: [] }), '');
        assert.strictEqual(finishLook({ roughness: 0.25 }), 'roughness 0.25');
    });

    test('an item stands as the check says it does, and one that could not be read says so first', () => {
        assert.strictEqual(standingOf(item()), 'specified');
        assert.strictEqual(standingOf(item({ findings: ['no material on any solid'] })), 'incomplete');
        assert.strictEqual(standingOf(item({ exempt: 'it is bought' })), 'exempt');
        assert.strictEqual(standingOf(item({ error: 'it did not build', findings: ['x'] })), 'error');
    });

    test("a part's tab is its sets: colour, material, finish, then its faces, its solids and where they came from", () => {
        const pane = new FakeElement('div');
        new CmfView(pane as unknown as HTMLElement).show({ object: '//pkg:housing', kind: 'part', items: [item()] });

        const [table] = tags(pane, 'table');
        assert.deepStrictEqual(
            tags(table, 'th').map((cell) => cell.textContent),
            ['Color', 'Material', 'Finish', 'Faces', 'Solids', 'From'],
        );
        const rows = tags(tags(table, 'tbody')[0], 'tr');
        assert.strictEqual(rows.length, 2);
        assert.strictEqual(text(rows[0]), 'Bright Red ABS as produced 4 1 source:step');
        assert.match(text(rows[1]), /^rgba;color=00FF00FF display only ABS satin roughness 0\.6, metallic 0 2 0/);
        // The swatch is the colour itself.
        assert.deepStrictEqual(
            find(rows[0], 'cmf-swatch').map((square) => square.style.backgroundColor),
            ['#C91A09FF'],
        );
        assert.match(text(pane), /Unspecified: no colour on 3 faces\./);
        // One item is no list: no summary over it.
        assert.strictEqual(find(pane, 'cmf-summary').length, 0);
    });

    test("an assembly's tab says how many items are not specified, and draws each with its findings", () => {
        const pane = new FakeElement('div');
        const data: CmfData = {
            object: '//pkg:case',
            kind: 'assembly',
            own: { cmf: null, findings: [] },
            items: [
                item({ name: '//pkg:base', cmf: null, findings: ['it states no colour and no material'] }),
                item({ name: '//pkg:lid', count: 2 }),
                item({ name: '//pkg:screw', exempt: 'it is bought, in whatever its vendor sells it in' }),
            ],
        };
        new CmfView(pane as unknown as HTMLElement).show(data);

        assert.strictEqual(
            find(pane, 'cmf-summary')[0].textContent,
            '1 of 3 items are not specified: they are listed first.',
        );
        assert.deepStrictEqual(
            find(pane, 'cmf-item').map((section) => section.className),
            ['cmf-item cmf-incomplete', 'cmf-item cmf-specified', 'cmf-item cmf-exempt'],
        );
        assert.deepStrictEqual(
            find(pane, 'cmf-findings').map((list) => text(list)),
            ['it states no colour and no material'],
        );
        assert.strictEqual(find(pane, 'cmf-count')[0].textContent, '× 2');
        // An assembly that sets nothing itself has nothing to say about itself.
        assert.strictEqual(find(pane, 'cmf-own').length, 0);
    });

    test('an assembly that sets CMF itself is told so above its items', () => {
        const pane = new FakeElement('div');
        new CmfView(pane as unknown as HTMLElement).show({
            object: '//pkg:wall',
            kind: 'assembly',
            own: { cmf: null, findings: ["it sets CMF itself (the link 'b' sets 'color')"] },
            items: [item()],
        });
        const [own] = find(pane, 'cmf-own');
        assert.strictEqual(own.className, 'cmf-own warning');
        assert.match(text(own), /the link 'b' sets 'color'/);
    });

    test("a colour's tab is what it is: its swatch, whether it is a claim, its reference and its ids", () => {
        const pane = new FakeElement('div');
        new CmfView(pane as unknown as HTMLElement).show({
            object: '//pkg:stone',
            kind: 'color',
            declaration: {
                name: 'stone',
                kind: 'color',
                package: '//pkg',
                reference: '//vendor:Medium Stone Grey',
                aliasOf: '//vendor:Medium Stone Grey',
                manufacturable: true,
                display: '#969696',
                displayText: '#969696',
                ids: { bricklink: '86', lego: '194' },
                aliases: ['Light Bluish Gray'],
            },
        });

        assert.strictEqual(find(pane, 'cmf-declaration-name')[0].textContent, 'stone');
        assert.strictEqual(find(pane, 'cmf-swatch-large')[0].style.backgroundColor, '#969696');
        assert.strictEqual(find(pane, 'cmf-standing-specified')[0].textContent, 'Manufacturable');
        const rows = tags(pane, 'tr').map((row) => text(row));
        assert.deepStrictEqual(rows, [
            'Reference //vendor:Medium Stone Grey',
            'Alias of //vendor:Medium Stone Grey',
            'Display #969696',
            'Ids bricklink: 86, lego: 194',
            'Aliases Light Bluish Gray',
        ]);
    });

    test('a display-only colour, a material and a finish each say what they are', () => {
        const draw = (declaration: CmfData['declaration']) => {
            const pane = new FakeElement('div');
            new CmfView(pane as unknown as HTMLElement).show({ object: '', kind: '', declaration });
            return pane;
        };

        const preview = draw({
            name: 'rgba',
            kind: 'color',
            package: '//pub/std/color',
            reference: '//pub/std/color:rgba',
            manufacturable: false,
            parametric: ['color'],
            display: '#000000',
            displayText: '#000000FF',
        });
        assert.strictEqual(find(preview, 'cmf-display-only')[0].textContent, 'display only');
        assert.match(text(preview), /Parameters color \(shown with their defaults\)/);

        const alu = draw({
            name: 'alu',
            kind: 'material',
            package: '//pkg',
            reference: '//pkg:alu',
            manufacturable: true,
            display: '#A8A9AD',
            colorClaim: '//pkg:natural',
            facts: { Density: '2700 kg/m^3' },
        });
        // Drawn in the colour it claims, beside the claim.
        const claim = tags(alu, 'tr').find((row) => row.children[0].textContent === 'Its colour') as FakeElement;
        assert.strictEqual(text(claim), 'Its colour natural');
        assert.strictEqual(find(claim, 'cmf-swatch')[0].style.backgroundColor, '#A8A9AD');
        assert.match(text(alu), /Density 2700 kg\/m\^3/);

        const satin = draw({
            name: 'satin',
            kind: 'finish',
            package: '//pkg',
            reference: '//pkg:satin',
            manufacturable: true,
            roughness: 0.6,
            metallic: 0,
        });
        // A finish draws no colour, so it has no swatch.
        assert.strictEqual(find(satin, 'cmf-swatch').length, 0);
        assert.match(text(satin), /Display roughness 0\.6, metallic 0/);
    });

    test('the bill of materials has Color, Material and Finish columns, after what to order it as', () => {
        const pane = new FakeElement('div');
        const data: BomData = {
            assembly: '//pkg:case',
            total: 3,
            items: [
                { name: '//pkg:housing', kind: 'part', count: 1, cmf: MOULDING },
                { name: '//pkg:screw', kind: 'part', count: 2, vendor: 'acme', sku: 'M3', cmf: null },
            ],
        };
        renderBom(pane as unknown as HTMLElement, data);

        assert.deepStrictEqual(
            tags(pane, 'th').map((cell) => cell.textContent),
            ['Item', 'Count', 'Order as', 'Color', 'Material', 'Finish', 'Description'],
        );
        const [housing, screw] = tags(tags(pane, 'tbody')[0], 'tr');
        assert.deepStrictEqual(
            find(housing, 'cmf').map((cell) => text(cell)),
            ['Bright Red rgba;color=00FF00FF display only unspecified', 'ABS', 'satin'],
        );
        assert.deepStrictEqual(
            find(screw, 'cmf').map((cell) => text(cell)),
            ['', '', ''],
        );
    });

    test('a Build vs Buy line is in what the daemon says, and in its material from a daemon too old to say', () => {
        const node = (fields: Partial<TreeNode>): TreeNode => ({
            id: '0',
            name: '//pkg:bracket',
            kind: 'part',
            buy: false,
            build: true,
            ...fields,
        });
        assert.strictEqual(lineCmf(node({ cmf: MOULDING })), MOULDING);
        assert.strictEqual(lineCmf(node({ cmf: null, material: '//pkg:alu' })), null);
        assert.deepStrictEqual(lineCmf(node({ material: '//pkg:alu' })), { sets: [{ material: '//pkg:alu' }] });
        assert.strictEqual(lineCmf(node({})), null);
    });

    test('only a colour, a material and a finish are declarations', () => {
        assert.ok(isDeclaration('color'));
        assert.ok(isDeclaration('material'));
        assert.ok(isDeclaration('finish'));
        for (const kind of ['part', 'assembly', 'interface', 'cmf', '', null, undefined]) {
            assert.ok(!isDeclaration(kind), String(kind));
        }
    });
});
