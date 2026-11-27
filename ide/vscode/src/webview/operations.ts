//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the four Operations tabs share: how each asks the daemon, and the few
// pieces every one of them draws.
//
// Operations is four questions asked of the object on screen, or of a package:
// Revisions (its history, and what is not committed yet), Dependencies (what it
// uses), Used By (what uses it) and Impact (what a change to it reaches). Each
// is a daemon method or a few ('ops.*', see 'partcad_utils.ops_views'), and
// what the daemon answers is drawn as it comes: nothing here works out a
// dependency, a user or an impact of its own.
//
// Every tab asks through 'OpsCallbacks', and is answered through the callback
// it asked with, which the panel calls with the answer quoting the question's
// token - or never, for a question about an object no longer on screen. That
// is what lets the Revisions tab ask about one revision, then another, and draw
// each answer where it belongs; and what lets these tabs be tested in the
// extension host, which has no panel, with callbacks of the test's own.
//

import { el } from './dom';
import { OpsQuery, OpsReadMethod, OpsWriteMethod, RevRefusal } from './messages';

/** What an Operations tab is about: the object on screen, or a package ('kind' is 'package'). */
export interface OpsSubject {
    package: string;
    name: string;
    kind: string;
}

/** The daemon's answer to a question: what it said, or why it could not. */
export type OpsAnswer = (data: unknown, error?: string) => void;

/** The daemon's answer to a change: what it did, or why not - and, for a revision it would not make, which reason. */
export type OpsWritten = (answer: { data?: unknown; error?: string; refusal?: RevRefusal }) => void;

/** What the panel does for an Operations tab. */
export interface OpsCallbacks {
    /** Ask the daemon one question about the object on screen, or its package. */
    ask: (query: OpsQuery<OpsReadMethod>, answer: OpsAnswer) => void;
    /** Ask it to change something; 'directory' is where the author of a new revision is read. */
    write: (query: OpsQuery<OpsWriteMethod>, answer: OpsWritten, directory?: string | null) => void;
    /** A package - a dependency, a package that depends on this one, either at a commit - in the Package Explorer. */
    openPackage: (name: string) => void;
    /** An object a row names, in the panel. */
    showObject: (object: { package: string; name: string; kind: string }) => void;
    /** Text for the user to paste somewhere: the advice for an agent. */
    copy: (text: string) => void;
}

/** An answer to one question, once it is in. */
export type Answer<T> = { data: T } | { error: string } | 'pending';

/**
 * The kinds of object the panel can show, and so the kinds a row can open: the
 * object kinds of the host's 'INSPECT_COMMANDS'. Any other is named, not linked.
 */
export const SHOWN_KINDS = ['part', 'assembly', 'scene', 'sketch', 'interface'];

/** Whether the subject is a package rather than one object of it. */
export function isPackage(subject: OpsSubject | undefined): boolean {
    return subject?.kind === 'package';
}

/**
 * Whether two subjects are the same object. A show of the object on screen
 * again - a save, say - starts a tab over with a subject equal to the last one
 * and not the same value, and a change asked before it is still about it: what
 * came of the change is said on the tab started over, not dropped.
 */
export function sameSubject(a: OpsSubject | undefined, b: OpsSubject | undefined): boolean {
    return a !== undefined && b !== undefined && a.package === b.package && a.name === b.name && a.kind === b.kind;
}

/** What the subject is called in a sentence: "this package", "this part". */
export function thisSubject(subject: OpsSubject | undefined): string {
    return `this ${subject?.kind ?? 'object'}`;
}

/** A sentence's first letter in capitals: "This package declares...". */
export function capitalized(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A commit time, in this reader's own time zone. */
export function when(seconds: number | undefined): string {
    if (!seconds) {
        return '';
    }
    const date = new Date(seconds * 1000);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

/** A revision as it is shown: a commit id's first eight characters, and anything else - a tag, a branch - as it is. */
export function shortRevision(revision: string | null | undefined): string {
    if (!revision) {
        return '';
    }
    return /^[0-9a-f]{40}$/i.test(revision) ? revision.slice(0, 8) : revision;
}

/** A few words beside a name - how a commit changed an object, how one object uses another - each a chip. */
export function chips(words: string[] | null | undefined, className = ''): HTMLElement {
    const host = el('span', `ops-chips ${className}`.trim());
    for (const word of words ?? []) {
        host.appendChild(el('span', 'ops-chip', word));
    }
    return host;
}

/** A button, in the editor's colours ('secondary', 'small' as the Requirements tab draws its own). */
export function button(text: string, className: string, title: string, onClick: () => void): HTMLButtonElement {
    const node = el('button', `requirements-button ops-button ${className}`.trim(), text) as HTMLButtonElement;
    node.type = 'button';
    node.title = title;
    node.addEventListener('click', onClick);
    return node;
}

/** A name in a table that opens what it names: a link's look, a button's keys. */
export function linkButton(text: string, className: string, title: string, onClick: () => void): HTMLButtonElement {
    const node = el('button', `link-button ${className}`.trim(), text) as HTMLButtonElement;
    node.type = 'button';
    node.title = title;
    node.addEventListener('click', onClick);
    return node;
}

/**
 * An object a row names: a link that shows it in the panel where the panel can
 * show one of its kind, and its name otherwise.
 */
export function objectCell(
    row: { object: string; package: string; name: string; kind: string | null },
    callbacks: Pick<OpsCallbacks, 'showObject'>,
    className = 'ops-object',
): HTMLElement {
    const cell = el('td', className);
    if (row.kind && SHOWN_KINDS.includes(row.kind)) {
        const open = linkButton(row.object, 'ops-open', `Show ${row.object}`, () =>
            callbacks.showObject({ package: row.package, name: row.name, kind: row.kind as string }),
        );
        open.dataset.object = row.object;
        cell.appendChild(open);
    } else {
        cell.appendChild(el('span', 'name', row.object));
    }
    return cell;
}

/** A package a row names, opening it in the Package Explorer. */
export function packageButton(
    text: string,
    target: string,
    callbacks: Pick<OpsCallbacks, 'openPackage'>,
    className = 'ops-package',
    title = `Open ${target} in the Package Explorer`,
): HTMLButtonElement {
    const open = linkButton(text, className, title, () => callbacks.openPackage(target));
    open.dataset.package = target;
    return open;
}

/** A table in the panes' 'grid' look: its header row, and the body to add rows to. */
export function grid(columns: string[], className: string): { table: HTMLElement; body: HTMLElement } {
    const table = el('table', `grid ${className}`);
    const head = table.appendChild(el('thead')).appendChild(el('tr'));
    for (const column of columns) {
        head.appendChild(el('th', undefined, column));
    }
    const body = table.appendChild(el('tbody'));
    return { table, body };
}

/**
 * A section that folds, under a title that says how many it holds: the
 * Dependencies and Used By tabs' lists. The title is a button that folds and
 * unfolds it, and 'open' is the view's own state, kept across a redraw.
 */
export function section(
    id: string,
    title: string,
    open: boolean,
    onToggle: (id: string) => void,
    fill: (body: HTMLElement) => void,
): HTMLElement {
    const host = el('div', `ops-section${open ? ' open' : ''}`);
    host.dataset.section = id;
    const heading = host.appendChild(el('button', 'ops-section-title')) as HTMLButtonElement;
    heading.type = 'button';
    heading.dataset.section = id;
    heading.setAttribute('aria-expanded', String(open));
    heading.title = open ? `Fold ${title} away` : `Show ${title}`;
    const chevron = heading.appendChild(el('span', 'ops-section-chevron', open ? '▾' : '▸'));
    chevron.setAttribute('aria-hidden', 'true');
    heading.appendChild(el('span', undefined, title));
    heading.addEventListener('click', () => onToggle(id));
    if (open) {
        const body = host.appendChild(el('div', 'ops-section-body'));
        fill(body);
    }
    return host;
}

/**
 * The focus back on a section's title once 'pane', which the sections are drawn
 * straight into, is drawn again: folding one replaces the title the keyboard was
 * on, and the user would be dropped onto the page.
 */
export function focusSection(pane: HTMLElement, id: string): void {
    const host = Array.from(pane.children as HTMLCollectionOf<HTMLElement>).find(
        (child) => child.dataset?.section === id,
    );
    (host?.children[0] as HTMLElement | undefined)?.focus?.();
}

/**
 * What Used By and Impact say under what they found: that they looked only at
 * what PartCAD has loaded, so that an empty list reads as "nothing loaded" and
 * not as "nothing", and a button that loads the rest of the workspace first.
 */
export function loadedNote(loaded: boolean, onLoad?: () => void): HTMLElement {
    const note = el('p', 'usedby-note placeholder ops-loaded');
    note.appendChild(
        el(
            'span',
            undefined,
            loaded
                ? 'Of every package of the workspace, loaded to answer this. '
                : 'Of what PartCAD has loaded: an object not loaded yet is not looked at, and an assembly not built yet is counted by what its declaration names. ',
        ),
    );
    if (!loaded && onLoad !== undefined) {
        note.appendChild(
            button(
                'Load workspace',
                'small secondary ops-load',
                'Load every package of the workspace, then ask again (it may download what they import)',
                onLoad,
            ),
        );
    }
    return note;
}
