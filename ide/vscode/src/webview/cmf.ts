//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "CMF" tab, and the Color, Material and Finish columns of the bill of
// materials and of the Build vs Buy table.
//
// CMF is shown one way everywhere (docs/design/cmf.md, "One presentation"): as
// its three components in the order colour, material, finish, each by the
// declaration it names, with a swatch of what it is drawn in, marked when it is
// only a picture ('display only') and when it is not there at all
// ('unspecified'). This file is that one way, for the three views that show it:
// the tab draws whole sets, and a column draws one component of every set an
// item has.
//
// What it shows is the daemon's: 'cmf.info' for the tab, which reads each item's
// CMF the way 'pc info' says it and judges it the way the 'cmf' check of 'pc
// test' does, the incomplete items first; and the 'cmf' of each line of 'bom'
// and 'manufacturing.tree' for the columns. Nothing here decides what is
// specified, what is display-only or what comes first - a second copy of those
// rules is a copy that comes to disagree with the check.
//
// The tab has two kinds of thing to show. An object - a part, an assembly, a
// scene - is a list of items, each with its sets: a part is its one item, an
// assembly every part it holds and every sub-assembly in it that is bought
// whole. A CMF declaration opened from the explorer - a colour, a material or a
// finish - has no items: it is what an item is *in*, and the tab says what it
// is called, what it is drawn in, whether it is a claim that it can be had, and
// what other systems call it. For a declaration the tab is the whole panel (see
// 'isDeclaration' in 'messages.ts').
//
// Only 'dom.ts' and 'messages.ts' are imported, so that the extension host's
// tests can import this file (see 'viewerCmf.test.ts').
//

import { el, empty, link, placeholder } from './dom';
import { CmfComponent, CmfData, CmfDeclaration, CmfInfo, CmfItem, CmfSet } from './messages';

/** The three components, in the order every view lists them. */
export const COMPONENTS: CmfComponent[] = ['color', 'material', 'finish'];

/** What each component is called where a person reads it: a column's heading, a set's cell. */
export const COMPONENT_LABELS: Record<CmfComponent, string> = {
    color: 'Color',
    material: 'Material',
    finish: 'Finish',
};

/** What is left unspecified is said of what it is missing on: a colour on faces, a material on solids. */
const MISSING_ON: Partial<Record<CmfComponent, [string, string]>> = {
    color: ['colour', 'face'],
    material: ['material', 'solid'],
};

/** What a reader calls a declaration a reference names: its name, without the package, the escapes read. */
export function referenceName(reference: string): string {
    // A reference is '<package>:<name>', and a package path holds no ':' - so
    // the first one is the split, even when a parameter value is a reference
    // of its own ('brick;color=//pub/std/color:rgba;color=C91A09FF').
    const split = reference.indexOf(':');
    const name = split < 0 ? reference : reference.slice(split + 1);
    // The characters a name escapes are the ones a reference gives a meaning
    // to ('partcad_utils.utils.escape_name'), each as '%XX'; read back here,
    // because a name is shown the way the specification it comes from writes
    // it ('PA12, glass filled').
    return name.replace(/%([0-9A-Fa-f]{2})/g, (_match, hex: string) => String.fromCharCode(parseInt(hex, 16)));
}

/** A finish's look, as it is said beside it: 'roughness 0.6, metallic 0'. */
export function finishLook(entry: { roughness?: number; metallic?: number }): string {
    const hints: string[] = [];
    if (entry.roughness !== undefined && entry.roughness !== null) {
        hints.push(`roughness ${round(entry.roughness)}`);
    }
    if (entry.metallic !== undefined && entry.metallic !== null) {
        hints.push(`metallic ${round(entry.metallic)}`);
    }
    return hints.join(', ');
}

function round(value: number): string {
    return String(Number(value.toFixed(2)));
}

/** "all faces", "some faces", "3 faces": how much of something is meant. */
function howMany(count: number | 'all' | 'some' | undefined, things: string): string {
    if (count === 'all') {
        return `all ${things}s`;
    }
    if (count === 'some') {
        return `some ${things}s`;
    }
    return count === 1 ? `1 ${things}` : `${count} ${things}s`;
}

/** What one component of an item says, in one cell: a value, or the mark that there is none. */
export interface CmfCell {
    /** What is written: the declaration's name, or 'unspecified'. */
    text: string;
    /** What is said when pointed at: the reference in full, and what the marks mean. */
    title: string;
    /** What it is drawn in, '#RRGGBB[AA]', for a colour that says. */
    swatch?: string;
    /** It is only a picture: an 'rgba' colour, or a declaration saying 'manufacturable: false'. */
    displayOnly?: boolean;
    /** Nothing states it, on some or all of what it belongs on. */
    unspecified?: boolean;
}

/**
 * One component of an item's CMF, as a column of a bill of materials shows it.
 *
 * Every value the item's sets name for it, once each, in the order of the
 * sets - a two-colour moulding is one line in two colours - and then, where
 * some of the item states none, the mark that says so. A finish nobody states
 * is as produced, which is no gap, and gets no mark. 'info' read off an item's
 * declaration rather than its geometry ('declared') is said so in each title,
 * since what its source states is not known until it is built.
 */
export function cmfCells(info: CmfInfo | null | undefined, component: CmfComponent): CmfCell[] {
    if (!info) {
        return [];
    }
    const declared = info.declared ? '\n(As declared: what its source states is known once it is built.)' : '';
    const cells: CmfCell[] = [];
    const seen = new Set<string>();
    for (const set of info.sets ?? []) {
        const reference = set[component];
        if (!reference || seen.has(reference)) {
            continue;
        }
        seen.add(reference);
        const displayOnly = (set.displayOnly ?? []).includes(component);
        const look = component === 'finish' ? finishLook(set) : '';
        cells.push({
            text: referenceName(reference),
            title:
                reference +
                (look ? `\n${look}` : '') +
                (displayOnly ? '\nDisplay only: a picture of it, not a specification anybody can make it to.' : '') +
                declared,
            swatch: component === 'color' ? set.display : undefined,
            displayOnly,
        });
    }
    const missing = MISSING_ON[component];
    const count = info.unspecified?.[component];
    if (missing !== undefined && count) {
        cells.push({
            text: 'unspecified',
            title: `No ${missing[0]} on ${howMany(count, missing[1])}.${declared}`,
            unspecified: true,
        });
    }
    return cells;
}

/** A colour's swatch: a small square of it, with a border so that white on white is still a square. */
export function swatch(color: string | undefined, className = 'cmf-swatch'): HTMLElement {
    const square = el('span', className);
    if (color) {
        square.style.backgroundColor = color;
        square.title = color;
    } else {
        square.classList.add('cmf-swatch-none');
    }
    return square;
}

/** One cell's value, drawn: the swatch, the name, and its mark. */
function drawCell(cell: CmfCell): HTMLElement {
    const value = el('span', cell.unspecified ? 'cmf-value cmf-unspecified' : 'cmf-value');
    value.title = cell.title;
    if (cell.swatch) {
        value.appendChild(swatch(cell.swatch));
    }
    value.appendChild(el('span', 'cmf-name', cell.text));
    if (cell.displayOnly) {
        value.appendChild(el('span', 'badge cmf-display-only', 'display only'));
    }
    return value;
}

/** What a column of a table holds for one item: its cells, one under another. */
export function drawCells(cells: CmfCell[]): HTMLElement {
    const column = el('span', 'cmf-cells');
    for (const cell of cells) {
        column.appendChild(drawCell(cell));
    }
    return column;
}

/** The column headings the bill of materials and Build vs Buy add, with the class each is drawn with. */
export const CMF_COLUMNS: [string, string][] = COMPONENTS.map((component) => [COMPONENT_LABELS[component], 'cmf']);

/** An item's three cells, for a table row: one 'td' per component. */
export function cmfColumns(info: CmfInfo | null | undefined): HTMLElement[] {
    return COMPONENTS.map((component) => {
        const cell = el('td', 'cmf');
        cell.appendChild(drawCells(cmfCells(info, component)));
        return cell;
    });
}

/** What an item's mark says: how it stands with the 'cmf' check. */
export type ItemStanding = 'error' | 'incomplete' | 'exempt' | 'specified';

export function standingOf(item: CmfItem): ItemStanding {
    if (item.error) {
        return 'error';
    }
    if (item.findings.length > 0) {
        return 'incomplete';
    }
    return item.exempt ? 'exempt' : 'specified';
}

const STANDING_LABELS: Record<ItemStanding, string> = {
    error: 'Could not be read',
    incomplete: 'Incomplete',
    exempt: 'Not required',
    specified: 'Specified',
};

/** The CMF tab. */
export class CmfView {
    constructor(private readonly root: HTMLElement) {}

    /** Forget what was shown, and say what the pane is waiting for. */
    public setBusy(text: string): void {
        this.reset().appendChild(placeholder(text));
    }

    public showError(message: string): void {
        this.reset().appendChild(el('p', 'error', message));
    }

    public show(data: CmfData): void {
        const root = this.reset();
        root.classList.add('sheet', 'cmf-tab');
        if (data.declaration !== undefined) {
            root.appendChild(drawDeclaration(data.declaration));
            return;
        }
        // No title, as on the Bill of Materials: the tab and the panel already
        // say what this is and what it is of.
        if (data.own !== undefined && (data.own.findings.length > 0 || data.own.cmf)) {
            root.appendChild(drawOwn(data.own));
        }
        const items = data.items ?? [];
        if (items.length === 0) {
            root.appendChild(placeholder('This holds nothing that is made in a colour, a material or a finish.'));
            return;
        }
        if (items.length > 1) {
            const incomplete = items.filter((item) => standingOf(item) === 'incomplete').length;
            root.appendChild(
                el(
                    'p',
                    'cmf-summary',
                    incomplete === 0
                        ? `All ${items.length} items are specified, or not required to be.`
                        : `${incomplete} of ${items.length} items are not specified: they are listed first.`,
                ),
            );
        }
        for (const item of items) {
            root.appendChild(drawItem(item));
        }
    }

    private reset(): HTMLElement {
        empty(this.root);
        this.root.className = 'pane';
        return this.root;
    }
}

/** What an assembly sets itself, which is how it is drawn and not what it holds is made in. */
function drawOwn(own: { cmf: CmfInfo | null; findings: string[] }): HTMLElement {
    const section = el('div', own.findings.length > 0 ? 'cmf-own warning' : 'cmf-own');
    section.appendChild(el('h3', undefined, 'Set by this assembly'));
    for (const finding of own.findings) {
        section.appendChild(el('p', undefined, finding));
    }
    if (own.cmf) {
        section.appendChild(drawSets(own.cmf));
    }
    return section;
}

/** One item: its name, how many, how it stands, what keeps it from being specified, and its sets. */
function drawItem(item: CmfItem): HTMLElement {
    const standing = standingOf(item);
    const section = el('div', `cmf-item cmf-${standing}`);
    const heading = el('div', 'cmf-item-heading');
    heading.appendChild(el('span', 'name', item.name));
    heading.appendChild(el('span', 'badge', item.kind));
    if (item.count > 1) {
        heading.appendChild(el('span', 'cmf-count', `× ${item.count}`));
    }
    const mark = el('span', `cmf-standing cmf-standing-${standing}`, STANDING_LABELS[standing]);
    if (item.exempt) {
        mark.title = `The 'cmf' check does not ask this to be specified: ${item.exempt}.`;
    }
    heading.appendChild(mark);
    section.appendChild(heading);
    if (item.desc) {
        section.appendChild(el('div', 'cmf-desc', item.desc));
    }
    if (item.error) {
        section.appendChild(el('p', 'error', item.error));
        return section;
    }
    if (item.findings.length > 0) {
        const list = el('ul', 'cmf-findings');
        for (const finding of item.findings) {
            list.appendChild(el('li', undefined, finding));
        }
        section.appendChild(list);
    }
    if (item.cmf) {
        section.appendChild(drawSets(item.cmf));
    } else {
        section.appendChild(placeholder('It states no colour, no material and no finish.'));
    }
    return section;
}

/**
 * An item's sets, a row each: colour, material and finish, then how many faces
 * and solids are in it and where it came from; and under them what is left
 * unspecified.
 */
export function drawSets(info: CmfInfo): HTMLElement {
    const block = el('div', 'cmf-sets');
    const table = el('table', 'grid');
    const head = el('tr');
    for (const [column, className] of [
        ...COMPONENTS.map((component) => [COMPONENT_LABELS[component], 'cmf']),
        ['Faces', 'numeric'],
        ['Solids', 'numeric'],
        ['From', ''],
    ] as [string, string][]) {
        head.appendChild(el('th', className, column));
    }
    table.appendChild(el('thead')).appendChild(head);
    const body = el('tbody');
    for (const set of info.sets ?? []) {
        body.appendChild(drawSet(set, info.declared === true));
    }
    table.appendChild(body);
    if ((info.sets ?? []).length > 0) {
        block.appendChild(table);
    }
    const gaps = unspecifiedText(info);
    if (gaps) {
        block.appendChild(el('p', 'cmf-unspecified', gaps));
    }
    if (info.declared) {
        block.appendChild(
            el('p', 'cmf-note', 'As declared: what its source states is known once it is built (show it in 3D).'),
        );
    }
    return block;
}

function drawSet(set: CmfSet, declared: boolean): HTMLElement {
    const row = el('tr');
    for (const component of COMPONENTS) {
        const cell = el('td', 'cmf');
        const one: CmfInfo = { sets: [set], declared };
        const cells = cmfCells(one, component);
        if (cells.length > 0) {
            cell.appendChild(drawCells(cells));
            if (component === 'finish' && finishLook(set)) {
                cell.appendChild(el('div', 'cmf-look', finishLook(set)));
            }
        } else if (component === 'finish') {
            // None stated is as produced, which is a finish too.
            cell.appendChild(el('span', 'cmf-implied', 'as produced'));
        } else {
            cell.appendChild(el('span', 'cmf-implied', '—'));
        }
        row.appendChild(cell);
    }
    row.appendChild(el('td', 'numeric', count(set.faces)));
    row.appendChild(el('td', 'numeric', count(set.solids)));
    row.appendChild(el('td', undefined, set.origin ?? ''));
    return row;
}

function count(value: number | 'all' | undefined): string {
    return value === undefined ? '' : String(value);
}

/** What is left unspecified, in a sentence, or '' when nothing is. */
export function unspecifiedText(info: CmfInfo): string {
    const gaps: string[] = [];
    for (const component of COMPONENTS) {
        const missing = MISSING_ON[component];
        const amount = info.unspecified?.[component];
        if (missing !== undefined && amount) {
            gaps.push(`no ${missing[0]} on ${howMany(amount, missing[1])}`);
        }
    }
    return gaps.length > 0 ? `Unspecified: ${gaps.join('; ')}.` : '';
}

/** A colour, a material or a finish: what it is called, what it looks like, what it claims. */
export function drawDeclaration(declaration: CmfDeclaration): HTMLElement {
    const block = el('div', 'cmf-declaration');
    const heading = el('div', 'cmf-declaration-heading');
    if (declaration.display !== undefined || declaration.kind !== 'finish') {
        heading.appendChild(swatch(declaration.display, 'cmf-swatch cmf-swatch-large'));
    }
    heading.appendChild(el('span', 'cmf-declaration-name', declaration.name));
    heading.appendChild(el('span', 'badge', declaration.kind));
    heading.appendChild(
        el(
            'span',
            declaration.manufacturable ? 'cmf-standing cmf-standing-specified' : 'badge cmf-display-only',
            declaration.manufacturable ? 'Manufacturable' : 'display only',
        ),
    );
    block.appendChild(heading);
    block.appendChild(
        el(
            'p',
            'cmf-claim',
            declaration.manufacturable
                ? 'A claim: it can be sourced or made as it is declared.'
                : "Display only: a picture, not a specification. An item in it is not specified, and the 'cmf' " +
                      'check of pc test says so.',
        ),
    );

    const table = el('table', 'grid cmf-facts');
    const row = (label: string, value: string | HTMLElement) => {
        const line = el('tr');
        line.appendChild(el('th', undefined, label));
        const cell = el('td');
        if (typeof value === 'string') {
            cell.textContent = value;
        } else {
            cell.appendChild(value);
        }
        line.appendChild(cell);
        table.appendChild(line);
    };
    row('Reference', declaration.reference);
    if (declaration.aliasOf) {
        row('Alias of', declaration.aliasOf);
    }
    if (declaration.desc) {
        row('Description', declaration.desc);
    }
    if (declaration.displayText !== undefined) {
        // As written, which may name another colour; the swatch is what that
        // comes to.
        const shown = el('span', 'cmf-value');
        shown.appendChild(swatch(declaration.display));
        shown.appendChild(el('span', 'cmf-name', declaration.displayText));
        if (declaration.display !== undefined) {
            shown.title = `Drawn in ${declaration.display}`;
        }
        row('Display', shown);
    }
    if (declaration.colorClaim) {
        // A material with no look of its own is drawn in the colour it claims.
        const claim = el('span', 'cmf-value');
        claim.title = declaration.colorClaim;
        if (declaration.displayText === undefined) {
            claim.appendChild(swatch(declaration.display));
        }
        claim.appendChild(el('span', 'cmf-name', referenceName(declaration.colorClaim)));
        row('Its colour', claim);
    }
    const look = finishLook(declaration);
    if (look) {
        row('Display', look);
    }
    if (declaration.parametric && declaration.parametric.length > 0) {
        row('Parameters', `${declaration.parametric.join(', ')} (shown with their defaults)`);
    }
    if (declaration.ids && Object.keys(declaration.ids).length > 0) {
        row(
            'Ids',
            Object.entries(declaration.ids)
                .map(([system, id]) => `${system}: ${id}`)
                .join(', '),
        );
    }
    if (declaration.aliases && declaration.aliases.length > 0) {
        row('Aliases', declaration.aliases.join(', '));
    }
    for (const [label, value] of Object.entries(declaration.facts ?? {})) {
        row(label, typeof value === 'string' ? value : JSON.stringify(value));
    }
    if (declaration.url) {
        row('Url', link(declaration.url, declaration.url));
    }
    block.appendChild(table);
    for (const error of declaration.errors ?? []) {
        block.appendChild(el('p', 'error', error));
    }
    return block;
}
