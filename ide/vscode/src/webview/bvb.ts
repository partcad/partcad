//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "Build vs Buy" tab: every part, piece of stock and sub-assembly the object
// is made of, and for each one whether it is made here or ordered.
//
// The structure is the daemon's ('manufacturing.tree': an assembly's links, a
// part's stock, what each declares) and the decision is the user's. Which lines
// that decision turns on and off, and how many of each are needed, is worked
// out here rather than asked for, because it changes on every click and a round
// trip per click through a daemon that answers one request at a time would make
// a switch feel broken. The rule is small and is written down once, in the
// contract the daemon's build plan follows too ('effectiveChoice' below and
// 'partcad.build_plan' have to agree on it):
//
//   * a line that can only be bought is bought, one that can only be built is
//     built, and one that declares neither is acquired as it is - its switch is
//     there, disabled, saying why;
//   * a line that can be both is what the user chose, and bought until they
//     choose otherwise - the same default procurement applies;
//   * a line that can be neither bought nor built is missing: it has no switch,
//     since there is no choice to make, and it is what stands between the object
//     and being manufacturable. So is one that is not meant to be made at all
//     ('manufacturable: false', which a manufacturable assembly it is used in
//     overrides) and a stock reference that names nothing. "Built" is what
//     'pc test -f manufacturability' would accept without looking at geometry
//     or asking a supplier: the daemon says what fails, in 'problems';
//   * what a line is made of - a sub-assembly's contents, a part's stock - is
//     needed only while that line is built. A line nothing needs is not shown:
//     it is not part of this build, and comes back as soon as what it is part of
//     is built again.
//
// The functions computing that are pure and do not touch the DOM; the view at
// the bottom draws them.
//

import { el, empty, placeholder } from './dom';
import { BvbData, Choices, ItemDetails, TreeNode } from './messages';

export type Choice = 'build' | 'buy';

/** One line of the table: one object, however many times it is used. */
export interface BvbRow {
    name: string;
    kind: 'part' | 'assembly';
    /** The first place it was found: what describes it. */
    node: TreeNode;
    /** The line is needed at all: some occurrence of it is under nothing that is bought. Only these are shown. */
    active: boolean;
    /** How many are needed, counting only the occurrences that are. */
    count: number;
    /** What the switch shows. */
    choice: Choice;
    /** The switch cannot be moved, and this is why. Undefined while it can be. */
    locked?: string;
    /** For an assembly: the parts in one of it, and how many of each, for its weight. */
    parts?: Map<string, number>;
}

export interface BvbResult {
    rows: BvbRow[];
    /** Some needed line is built: the Build tab has something to show. */
    anyBuild: boolean;
    /** Some needed line is bought: the Buy tab has something to show. */
    anyBuy: boolean;
}

/** Whether the user's choice decides this node: it can be both built and bought. */
export function isChoosable(node: TreeNode): boolean {
    return !node.embedded && node.buy && node.build;
}

/** What a node is, given what the user chose. See the rules at the top of this file. */
export function effectiveChoice(node: TreeNode, choices: Choices): Choice {
    if (node.embedded) {
        return 'build';
    }
    if (isMissing(node)) {
        // Neither: nothing is built out of it, so nothing under it is needed.
        return 'buy';
    }
    if (node.buy && node.build) {
        return choices[node.name] === 'build' ? 'build' : 'buy';
    }
    return node.build ? 'build' : 'buy';
}

/** What a part that can be neither bought nor built says, in place of its switch. */
export const MISSING_HINT = "Can't be manufacturable until it can be either bought or built";

/**
 * A line that can be neither bought nor built: no vendor and SKU to order it
 * by, and no instructions to build it by that hold up - or one not meant to be
 * made at all, or a stock reference that resolves to nothing. There is no
 * choice to offer, so it has no switch: it is what stands between the object
 * and being manufacturable, and is shown as that. 'partcad.build_plan.is_missing'
 * is the same rule.
 */
export function isMissing(node: TreeNode): boolean {
    if (node.embedded) {
        return false;
    }
    return node.missing === true || node.manufacturable === false || (!node.buy && !node.build);
}

/** How many of a line's problems a tooltip lists: an assembly can have one per step. */
const LISTED_PROBLEMS = 5;

function listed(problems: string[]): string {
    const shown = problems.slice(0, LISTED_PROBLEMS);
    const more = problems.length - shown.length;
    return shown.join('\n') + (more > 0 ? `\n… and ${more} more` : '');
}

/** Why a missing line is missing, for its tooltip. */
export function missingReason(node: TreeNode): string {
    const problems = node.problems ?? [];
    if (node.missing) {
        return listed(problems) || 'It is not found.';
    }
    if (node.manufacturable === false) {
        return (
            "It is declared 'manufacturable: false', on itself or on its package, and nothing manufacturable " +
            'it is used in overrides that.'
        );
    }
    if (problems.length > 0) {
        return listed(problems);
    }
    const instructions = node.kind === 'assembly' ? 'links to put together' : 'manufacturing instructions';
    return `It declares neither a vendor and an SKU nor ${instructions}.`;
}

/** Why a node's switch cannot be moved, or undefined when it can. */
export function lockReason(node: TreeNode): string | undefined {
    const instructions = node.kind === 'assembly' ? 'assembly instructions' : 'manufacturing instructions';
    if (isMissing(node)) {
        return `${MISSING_HINT}\n${missingReason(node)}`;
    }
    if (node.buy && !node.build) {
        const problems = node.problems ?? [];
        return problems.length > 0
            ? `Bought: its ${instructions} do not hold up.\n${listed(problems)}`
            : `Bought: it declares a vendor and an SKU, and no ${instructions} to build it with.`;
    }
    if (node.build && !node.buy) {
        return `Built: it declares ${instructions}, and no vendor or SKU to order it by.`;
    }
    return undefined;
}

/**
 * The table's lines for a tree, given the user's choices.
 *
 * One line per object, in the order the object is first met walking the tree -
 * a node, then its stock, then its contents - so that what a line is made of is
 * listed under it. An embedded assembly (one nested in its parent's file) has no
 * line: it is not an object anybody orders, and it is always put together, so
 * its contents are attributed to the assembly holding it.
 */
export function computeRows(tree: TreeNode, choices: Choices): BvbResult {
    const rows = new Map<string, BvbRow>();

    const visit = (node: TreeNode, multiplicity: number, active: boolean) => {
        if (node.embedded) {
            for (const child of node.children ?? []) {
                visit(child, multiplicity, active);
            }
            return;
        }
        let row = rows.get(node.name);
        if (row === undefined) {
            row = { name: node.name, kind: node.kind, node, active: false, count: 0, choice: 'buy' };
            if (node.kind === 'assembly') {
                row.parts = partsOf(node);
            }
            rows.set(node.name, row);
        }
        if (active) {
            row.active = true;
            row.count += multiplicity;
            // One object can be used where it is overridden into being made and
            // where it is not; it is needed, so it is the first that counts.
            if (row.node.manufacturable === false && node.manufacturable !== false) {
                row.node = node;
            }
        }

        const inner = active && effectiveChoice(node, choices) === 'build';
        if (node.stock !== undefined) {
            visit(node.stock, multiplicity, inner);
        }
        for (const child of node.children ?? []) {
            visit(child, multiplicity, inner);
        }
    };
    visit(tree, 1, true);

    const result: BvbRow[] = [];
    let anyBuild = false;
    let anyBuy = false;
    for (const row of rows.values()) {
        const effective = effectiveChoice(row.node, choices);
        // A line nothing needs reads as bought: it is not something to make, and
        // a switch left on "Build" under a bought parent would say otherwise
        // the moment that parent is built again and the line comes back.
        row.choice = row.active ? effective : isChoosable(row.node) ? 'buy' : effective;
        row.locked = lockReason(row.node);
        if (row.active) {
            anyBuild ||= effective === 'build';
            anyBuy ||= effective === 'buy';
        }
        result.push(row);
    }
    return { rows: result, anyBuild, anyBuy };
}

/** The lines the table shows: the ones that are needed. */
export function visibleRows(result: BvbResult): BvbRow[] {
    return result.rows.filter((row) => row.active);
}

/**
 * The choices worth keeping: the ones for lines that are needed and can go
 * either way.
 *
 * A line that a bought parent made unnecessary goes back to its default - the
 * switch is shown as "Buy" while it is greyed, and keeping a hidden "Build"
 * under it would spring back the moment the parent is built again, which is a
 * decision the user can no longer see.
 */
export function pruneChoices(result: BvbResult, choices: Choices): Choices {
    const kept: Choices = {};
    for (const row of result.rows) {
        const choice = choices[row.name];
        if (choice !== undefined && row.active && isChoosable(row.node)) {
            kept[row.name] = choice;
        }
    }
    return kept;
}

/** The parts physically in one of an assembly, by name: what its weight is the sum of. */
function partsOf(node: TreeNode): Map<string, number> {
    const parts = new Map<string, number>();
    const walk = (child: TreeNode) => {
        if (child.kind === 'part') {
            parts.set(child.name, (parts.get(child.name) ?? 0) + 1);
            return;
        }
        for (const grandchild of child.children ?? []) {
            walk(grandchild);
        }
    };
    for (const child of node.children ?? []) {
        walk(child);
    }
    return parts;
}

/**
 * How much one of a line weighs, in grams, or undefined when it is not known.
 *
 * An assembly is the sum of its parts, and only when every one of them is known:
 * a sum short by a part is a number nobody can tell is wrong.
 */
export function massOf(row: BvbRow, details: Map<string, ItemDetails>): number | undefined {
    const own = details.get(row.name)?.mass;
    if (own !== null && own !== undefined) {
        return own;
    }
    if (row.parts === undefined || row.parts.size === 0) {
        return undefined;
    }
    let total = 0;
    for (const [name, count] of row.parts) {
        const mass = details.get(name)?.mass;
        if (mass === null || mass === undefined) {
            return undefined;
        }
        total += mass * count;
    }
    return total;
}

export function formatMass(grams: number): string {
    return grams >= 1000 ? `${round(grams / 1000)} kg` : `${round(grams)} g`;
}

export function formatSize(size: [number, number, number]): string {
    return `${size.map(round).join(' × ')} mm`;
}

function round(value: number): string {
    const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
    return String(Number(value.toFixed(digits)));
}

/** A material reference, as a reader would say it: the name, not the package it is catalogued in. */
export function materialName(reference: string): string {
    return reference.split(':').pop() || reference;
}

/** The size the thumbnails are drawn at, and asked for at. */
export const THUMBNAIL_SIZE = 64;

export interface BvbCallbacks {
    /** The user moved a switch: the choices to keep, already pruned. */
    onChange: (choices: Choices) => void;
    /** These lines have no thumbnail or measurements yet. */
    requestDetails: (objects: { name: string; kind: string }[]) => void;
    /** A line's name was clicked: open the file it is made from. */
    openSource: (path: string) => void;
}

/** The Build vs Buy table. */
export class BvbView {
    private data: BvbData | undefined;
    private result: BvbResult | undefined;
    /** What the daemon said about each line, for the object on screen. */
    private readonly details = new Map<string, ItemDetails>();
    private readonly asked = new Set<string>();

    constructor(
        private readonly root: HTMLElement,
        private readonly callbacks: BvbCallbacks,
    ) {}

    /** The rows on screen, once there are any. */
    public get current(): BvbResult | undefined {
        return this.result;
    }

    /** Forget the object on screen, and say what the pane is waiting for. */
    public setBusy(text: string): void {
        this.data = undefined;
        this.result = undefined;
        this.details.clear();
        this.asked.clear();
        this.reset().appendChild(placeholder(text));
    }

    public showError(message: string): void {
        this.reset().appendChild(el('p', 'error', message));
    }

    /** Show an object's tree with the choices it was last left with. */
    public render(data: BvbData): BvbResult {
        this.data = data;
        const result = computeRows(data.tree, data.choices);
        // Choices saved before a parent was bought are dropped the same way a
        // click drops them, so that what is stored is what is on screen.
        data.choices = pruneChoices(result, data.choices);
        this.result = result;
        this.draw();
        this.askForDetails(result);
        return result;
    }

    /** Ask for the thumbnails and measurements of the lines on screen that have none yet. */
    private askForDetails(result: BvbResult): void {
        const missing = visibleRows(result)
            .filter((row) => !row.node.missing && !this.asked.has(row.name))
            .map((row) => ({ name: row.name, kind: row.kind }));
        for (const object of missing) {
            this.asked.add(object.name);
        }
        if (missing.length > 0) {
            this.callbacks.requestDetails(missing);
        }
    }

    /** What the daemon measured and drew, as it arrives. */
    public setDetails(items: ItemDetails[]): void {
        for (const item of items) {
            this.details.set(item.name, item);
        }
        if (this.data !== undefined) {
            this.draw();
        }
    }

    private reset(): HTMLElement {
        empty(this.root);
        this.root.className = 'pane';
        return this.root;
    }

    private toggle(row: BvbRow, build: boolean): void {
        if (this.data === undefined) {
            return;
        }
        const choices: Choices = { ...this.data.choices, [row.name]: build ? 'build' : 'buy' };
        const result = computeRows(this.data.tree, choices);
        this.data.choices = pruneChoices(result, choices);
        this.result = computeRows(this.data.tree, this.data.choices);
        this.draw();
        // Building something brings back what it is made of, whose pictures
        // were never asked for while it was hidden.
        this.askForDetails(this.result);
        this.callbacks.onChange(this.data.choices);
    }

    private draw(): void {
        const data = this.data;
        const result = this.result;
        if (data === undefined || result === undefined) {
            return;
        }
        const root = this.reset();
        root.classList.add('sheet', 'bvb');
        root.appendChild(el('h1', undefined, 'Build vs Buy'));
        root.appendChild(el('p', 'subtitle', data.object));

        const table = el('table', 'grid bvb-table');
        const head = el('tr');
        for (const [column, className] of [
            ['', 'bvb-picture'],
            ['Item', ''],
            ['Build or buy', 'bvb-choice'],
            ['Count', 'numeric'],
            ['Dimensions', 'numeric'],
            ['Weight', 'numeric'],
            ['Material', ''],
        ] as [string, string][]) {
            head.appendChild(el('th', className, column));
        }
        table.appendChild(el('thead')).appendChild(head);
        const body = el('tbody');
        for (const row of visibleRows(result)) {
            body.appendChild(this.drawRow(row));
        }
        table.appendChild(body);
        root.appendChild(table);
    }

    private drawRow(row: BvbRow): HTMLElement {
        const line = el('tr');
        const details = this.details.get(row.name);

        const picture = el('td', 'bvb-picture');
        const frame = el('div', 'thumbnail');
        if (details?.thumbnail) {
            const image = el('img');
            // Through an <img>, never inlined: an SVG in the DOM could carry
            // script or links the panel's CSP would not stop.
            image.src = `data:image/svg+xml;base64,${details.thumbnail}`;
            image.alt = row.name;
            image.width = THUMBNAIL_SIZE;
            image.height = THUMBNAIL_SIZE;
            frame.appendChild(image);
        } else if (details?.error) {
            frame.title = details.error;
        }
        picture.appendChild(frame);
        line.appendChild(picture);

        const name = el('td');
        name.appendChild(sourceLink(row, this.callbacks.openSource));
        name.appendChild(el('span', 'badge', row.node.missing ? 'missing' : row.kind));
        if (row.node.desc) {
            name.appendChild(el('div', 'bvb-desc', row.node.desc));
        }
        line.appendChild(name);

        line.appendChild(el('td', 'bvb-choice')).appendChild(
            isMissing(row.node) ? drawMissing(row.node) : this.drawToggle(row),
        );
        line.appendChild(el('td', 'numeric', String(row.count)));
        line.appendChild(el('td', 'numeric', details?.size ? formatSize(details.size) : ''));
        const mass = massOf(row, this.details);
        line.appendChild(el('td', 'numeric', mass === undefined ? '' : formatMass(mass)));
        line.appendChild(el('td', undefined, row.node.material ? materialName(row.node.material) : ''));
        return line;
    }

    /**
     * The switch, with what it is set to written above it.
     *
     * The tooltip is on the wrapper rather than on the input: a disabled input
     * takes no pointer events, and the reason it is disabled is the one thing
     * worth hovering over it for.
     */
    private drawToggle(row: BvbRow): HTMLElement {
        const wrapper = el('label', 'bvb-toggle');
        const build = row.choice === 'build';
        wrapper.appendChild(el('span', 'bvb-toggle-label', build ? 'Build' : 'Buy'));
        const input = el('input', 'switch');
        input.type = 'checkbox';
        input.setAttribute('role', 'switch');
        input.checked = build;
        input.disabled = row.locked !== undefined;
        input.setAttribute('aria-label', `${row.name}: ${build ? 'build' : 'buy'}`);
        if (row.locked !== undefined) {
            wrapper.title = row.locked;
            wrapper.classList.add('locked');
        } else {
            wrapper.title = build ? 'Built here. Switch off to buy it instead.' : 'Bought. Switch on to build it.';
        }
        input.addEventListener('change', () => this.toggle(row, input.checked));
        wrapper.appendChild(input);
        return wrapper;
    }
}

/** What stands in for the switch of a part that can be neither bought nor built. */
function drawMissing(node: TreeNode): HTMLElement {
    const label = el('span', 'bvb-missing', 'Missing');
    label.title = `${MISSING_HINT}\n${missingReason(node)}`;
    return label;
}

/**
 * A line's name: a link that opens the file the object is made from, where it
 * has one, and plain text where it has none.
 *
 * A button styled as a link rather than an <a href>: the panel has nowhere for
 * an href to go - its CSP forbids navigation - and the host is what opens
 * files. A button is also what the keyboard reaches.
 */
function sourceLink(row: BvbRow, openSource: (path: string) => void): HTMLElement {
    const source = row.node.source;
    if (!source) {
        return el('span', 'name', row.name);
    }
    const link = el('button', 'name source-link', row.name);
    link.title = `Open ${source}`;
    link.addEventListener('click', () => openSource(source));
    return link;
}
