//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Build vs Buy table's lines: which are needed, how many of each, and what
// each switch shows - given an object's tree and what the user chose.
//
// The rule is shared with the daemon's build plan ('partcad.build_plan'), which
// orders the steps of what this table says is built; the two disagreeing would
// be a Build tab listing a part this table says is bought.
//

// The keys below are PartCAD object names ('//pkg:arm', ':gear'), which no
// naming convention is going to describe.
/* eslint-disable @typescript-eslint/naming-convention */

import * as assert from 'assert';

import {
    BvbRow,
    MISSING_HINT,
    computeRows,
    effectiveChoice,
    isMissing,
    massOf,
    pruneChoices,
    visibleRows,
} from '../../webview/bvb';
import { Choices, ItemDetails, TreeNode } from '../../webview/messages';

let ids = 0;

function part(name: string, declares: { buy?: boolean; build?: boolean; stock?: TreeNode } = {}): TreeNode {
    return {
        id: String((ids += 1)),
        name,
        kind: 'part',
        buy: declares.buy ?? false,
        build: declares.build ?? false,
        stock: declares.stock,
    };
}

function assembly(
    name: string,
    children: TreeNode[],
    declares: { buy?: boolean; build?: boolean; embedded?: boolean } = {},
): TreeNode {
    return {
        id: String((ids += 1)),
        name,
        kind: 'assembly',
        buy: declares.buy ?? false,
        build: declares.build ?? children.length > 0,
        embedded: declares.embedded,
        children,
    };
}

/** The lines as [name, needed, count, switch, can it be moved]. */
function lines(rows: BvbRow[]): [string, boolean, number, string, boolean][] {
    return rows.map((row) => [row.name, row.active, row.count, row.choice, row.locked === undefined]);
}

suite('The Build vs Buy table', () => {
    test('a part with no stock is one line', () => {
        const { rows, anyBuild, anyBuy } = computeRows(part(':bolt', { buy: true }), {});

        assert.deepStrictEqual(lines(rows), [[':bolt', true, 1, 'buy', false]]);
        assert.strictEqual(anyBuild, false);
        assert.strictEqual(anyBuy, true);
    });

    test('a part that can only be built is built, and its switch says why it cannot be moved', () => {
        const { rows } = computeRows(part(':bracket', { build: true }), {});

        assert.strictEqual(rows[0].choice, 'build');
        assert.match(rows[0].locked ?? '', /no vendor or SKU/);
    });

    test('a part that can be neither bought nor built is missing, and says what it takes', () => {
        const { rows } = computeRows(part(':thing'), {});

        assert.strictEqual(rows[0].choice, 'buy');
        assert.strictEqual(isMissing(rows[0].node), true);
        assert.strictEqual(
            rows[0].locked,
            `${MISSING_HINT}\nIt declares neither a vendor and an SKU nor manufacturing instructions.`,
        );
        assert.strictEqual(MISSING_HINT, "Can't be manufacturable until it can be either bought or built");
    });

    test('a stock reference that resolves to nothing is missing too, and nothing that can be either is', () => {
        assert.strictEqual(isMissing({ ...part(':gone'), missing: true }), true);
        assert.strictEqual(isMissing(part(':bolt', { buy: true })), false);
        assert.strictEqual(isMissing(part(':bracket', { build: true })), false);
    });

    test('an assembly that can be neither bought nor put together is missing the same way', () => {
        const empty = assembly(':kit', [], {});
        const { rows } = computeRows(assembly(':robot', [empty]), {});

        assert.strictEqual(isMissing(rows[1].node), true);
        assert.match(rows[1].locked ?? '', /nor links to put together/);
        assert.strictEqual(isMissing(assembly(':motor', [], { buy: true })), false);
        assert.strictEqual(isMissing(assembly(':robot', [part(':bolt', { buy: true })])), false);
        // One nested in its parent's file is always put together, and never a line.
        assert.strictEqual(isMissing({ ...assembly(':robot/head', []), embedded: true }), false);
    });

    test("one declared 'manufacturable: false' is missing, and hides what it is made of", () => {
        const bracket = { ...part(':bracket', { buy: true, build: true, stock: part(':plate', { buy: true }) }) };
        const tree = assembly(':robot', [{ ...bracket, manufacturable: false }]);

        const { rows } = computeRows(tree, { ':bracket': 'build' });

        assert.strictEqual(isMissing(rows[1].node), true);
        assert.match(rows[1].locked ?? '', /manufacturable: false/);
        assert.strictEqual(effectiveChoice(rows[1].node, { ':bracket': 'build' }), 'buy');
        assert.deepStrictEqual(
            visibleRows(computeRows(tree, { ':bracket': 'build' })).map((row) => row.name),
            [':robot', ':bracket'],
        );
    });

    test('instructions that do not hold up are no way to build it, and say why', () => {
        const problems = ['No manufacturing tolerance is specified'];
        const onlyMade = { ...part(':bracket'), problems };
        const alsoSold = { ...part(':bracket', { buy: true }), problems };

        assert.strictEqual(isMissing(onlyMade), true);
        assert.match(computeRows(onlyMade, {}).rows[0].locked ?? '', /No manufacturing tolerance/);
        // Sold too: bought, saying what is wrong with making it.
        assert.strictEqual(isMissing(alsoSold), false);
        assert.match(computeRows(alsoSold, {}).rows[0].locked ?? '', /do not hold up.*\n.*tolerance/s);
    });

    test('a line used both where it is overridden into being made and where it is not is needed', () => {
        const screw = part(':screw', { buy: true });
        const tree = assembly(':robot', [
            { ...screw, manufacturable: false },
            { ...screw, manufacturable: true },
        ]);

        const { rows } = computeRows(tree, {});

        assert.strictEqual(rows[1].count, 2);
        assert.strictEqual(isMissing(rows[1].node), false);
    });

    test('a stock chain is needed as far as it is built, and no further', () => {
        const roll = part(':roll', { buy: true });
        const sheet = part(':sheet', { buy: true, build: true, stock: roll });
        const blank = part(':blank', { build: true, stock: sheet });

        // The sheet can go either way and is bought until chosen otherwise: the
        // roll it would be cut from is not needed.
        assert.deepStrictEqual(lines(computeRows(blank, {}).rows), [
            [':blank', true, 1, 'build', false],
            [':sheet', true, 1, 'buy', true],
            [':roll', false, 0, 'buy', false],
        ]);

        assert.deepStrictEqual(lines(computeRows(blank, { ':sheet': 'build' }).rows), [
            [':blank', true, 1, 'build', false],
            [':sheet', true, 1, 'build', true],
            [':roll', true, 1, 'buy', false],
        ]);
    });

    test('an assembly lists itself, then everything in it, counted', () => {
        const tree = assembly(':robot', [
            part(':motor', { buy: true }),
            part(':bracket', { build: true, stock: part(':plate', { buy: true }) }),
            part(':motor', { buy: true }),
            part(':bracket', { build: true, stock: part(':plate', { buy: true }) }),
            part(':cover', { buy: true, build: true }),
        ]);
        const result = computeRows(tree, {});

        assert.deepStrictEqual(lines(result.rows), [
            [':robot', true, 1, 'build', false],
            [':motor', true, 2, 'buy', false],
            [':bracket', true, 2, 'build', false],
            [':plate', true, 2, 'buy', false],
            [':cover', true, 1, 'buy', true],
        ]);
        assert.strictEqual(result.anyBuild, true);
        assert.strictEqual(result.anyBuy, true);
    });

    test('a bought sub-assembly hides what is in it, and building it brings it back', () => {
        const gearbox = () =>
            assembly(':gearbox', [part(':gear', { buy: true, build: true }), part(':shaft', { buy: true })], {
                buy: true,
            });
        const tree = assembly(':robot', [gearbox(), gearbox()]);

        const bought = computeRows(tree, { ':gear': 'build' });
        assert.deepStrictEqual(lines(bought.rows), [
            [':robot', true, 1, 'build', false],
            [':gearbox', true, 2, 'buy', true],
            [':gear', false, 0, 'buy', true],
            [':shaft', false, 0, 'buy', false],
        ]);
        // Only what is needed is shown: the gearbox's insides come with it.
        assert.deepStrictEqual(
            visibleRows(bought).map((row) => row.name),
            [':robot', ':gearbox'],
        );
        // The choice under it is not kept: it is a decision nobody can see.
        assert.deepStrictEqual(pruneChoices(bought, { ':gear': 'build' }), {});

        const built = computeRows(tree, { ':gearbox': 'build', ':gear': 'build' });
        assert.deepStrictEqual(lines(built.rows), [
            [':robot', true, 1, 'build', false],
            [':gearbox', true, 2, 'build', true],
            [':gear', true, 2, 'build', true],
            [':shaft', true, 2, 'buy', false],
        ]);
        assert.deepStrictEqual(
            visibleRows(built).map((row) => row.name),
            [':robot', ':gearbox', ':gear', ':shaft'],
        );
        assert.deepStrictEqual(pruneChoices(built, { ':gearbox': 'build', ':gear': 'build' }), {
            ':gearbox': 'build',
            ':gear': 'build',
        });
    });

    test('a part used in several sub-assemblies is one line, counting only where it is needed', () => {
        const tree = assembly(':robot', [
            assembly(':arm', [part(':screw', { buy: true }), part(':screw', { buy: true })], { buy: true }),
            assembly(':base', [part(':screw', { buy: true })]),
            part(':screw', { buy: true }),
        ]);

        // The arm is bought: its two screws come with it.
        assert.deepStrictEqual(
            lines(computeRows(tree, {}).rows).find(([name]) => name === ':screw'),
            [':screw', true, 2, 'buy', false],
        );
        assert.deepStrictEqual(
            lines(computeRows(tree, { ':arm': 'build' }).rows).find(([name]) => name === ':screw'),
            [':screw', true, 4, 'buy', false],
        );
    });

    test('an assembly nested in its parent file is no line of its own, and is always put together', () => {
        const nested = assembly(':robot/head', [part(':eye', { buy: true }), part(':eye', { buy: true })], {
            embedded: true,
        });
        const tree = assembly(':robot', [nested, part(':eye', { buy: true })]);

        assert.strictEqual(effectiveChoice(nested, {}), 'build');
        assert.deepStrictEqual(lines(computeRows(tree, {}).rows), [
            [':robot', true, 1, 'build', false],
            [':eye', true, 3, 'buy', false],
        ]);
    });

    test('an assembly weighs what its parts do, and nothing when one of them is unknown', () => {
        const tree = assembly(':robot', [
            part(':motor', { buy: true }),
            part(':motor', { buy: true }),
            assembly(':head', [part(':eye', { buy: true })], { embedded: true }),
        ]);
        const robot = computeRows(tree, {} as Choices).rows[0];
        const details = new Map<string, ItemDetails>([
            [':motor', { name: ':motor', mass: 300 }],
            [':eye', { name: ':eye', mass: 15 }],
        ]);

        assert.strictEqual(massOf(robot, details), 615);
        details.set(':eye', { name: ':eye', mass: null });
        assert.strictEqual(massOf(robot, details), undefined);
    });
});
