//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What uses something: the Operations group's Used By tab, and the "Used By at
// it" view under a revision on the Revisions tab ('ops.used_by').
//
// An object is used by the objects the daemon has loaded that refer to it, each
// with how and how many times: an assembly that places a bolt four times uses
// it four times. A package is used by two things, each a section of its own:
// the packages that declare it as a dependency, each with the revision it pins
// and how far behind that is, and the objects that use anything in it. Only
// what is loaded is looked at (see 'partcad/usage.py'), and the tab says so -
// with a way to load the rest of the workspace first - so that an empty list
// reads as "nothing loaded uses it" rather than as "nothing uses it". A row
// names an object, which it shows in the panel, or a package, which it opens in
// the Package Explorer.
//

import { el, empty, placeholder } from './dom';
import { DependentPackage, UsedByData, UsedByRow } from './messages';
import {
    Answer,
    OpsCallbacks,
    OpsSubject,
    chips,
    focusSection,
    grid,
    isPackage,
    loadedNote,
    objectCell,
    packageButton,
    section,
    shortRevision,
    thisSubject,
} from './operations';

/** The objects that use something: object, kind, how and how many times, each object a link. */
export function usersTable(rows: UsedByRow[], callbacks: Pick<OpsCallbacks, 'showObject'>): HTMLElement {
    const { table, body } = grid(['Object', 'Kind', 'How', 'Uses'], 'usedby-table');
    for (const row of rows) {
        const tr = body.appendChild(el('tr', 'usedby-row'));
        tr.appendChild(objectCell(row, callbacks, 'usedby-object'));
        tr.appendChild(el('td', 'usedby-kind', row.kind));
        tr.appendChild(el('td', 'usedby-how')).appendChild(chips(row.how));
        tr.appendChild(el('td', 'usedby-count numeric', String(row.count)));
    }
    return table;
}

/** How far a dependent's pin is behind this package's newest revision, in words. */
export function behind(row: DependentPackage): string {
    if (row.behind === null || row.behind === undefined) {
        return row.type === 'git' ? 'not known' : '';
    }
    if (row.behind === 0) {
        return 'up to date';
    }
    return `${row.behind} revision${row.behind === 1 ? '' : 's'} behind`;
}

/**
 * The packages that declare this one as a dependency: the package, the name it
 * declares this one under, how, the revision it pins and how far behind that is.
 */
export function dependentsTable(rows: DependentPackage[], callbacks: Pick<OpsCallbacks, 'openPackage'>): HTMLElement {
    const { table, body } = grid(['Package', 'Name', 'Type', 'Pinned', 'Behind'], 'usedby-packages');
    for (const row of rows) {
        const tr = body.appendChild(el('tr', 'usedby-package'));
        tr.appendChild(el('td')).appendChild(packageButton(row.package, row.package, callbacks));
        tr.appendChild(el('td', 'name', row.name));
        tr.appendChild(el('td', undefined, row.type ?? ''));
        tr.appendChild(el('td', 'name', row.short ?? shortRevision(row.pinned)));
        tr.appendChild(el('td', 'usedby-behind', behind(row)));
    }
    return table;
}

/**
 * What uses something, into 'host', without the tab's sections: what the
 * Revisions tab's "Used By at it" view is - the packages that depend on it, if
 * any, and the objects.
 */
export function renderUsedBy(
    host: HTMLElement,
    data: UsedByData,
    callbacks: Pick<OpsCallbacks, 'showObject' | 'openPackage'>,
    what: string,
): void {
    empty(host);
    const objects = data.objects ?? [];
    const packages = data.packages ?? [];
    if (objects.length === 0 && packages.length === 0) {
        host.appendChild(
            placeholder(`Nothing PartCAD has loaded uses ${what}. Objects not loaded yet are not looked at.`),
        );
        return;
    }
    if (packages.length > 0) {
        host.appendChild(dependentsTable(packages, callbacks));
    }
    if (objects.length > 0) {
        host.appendChild(usersTable(objects, callbacks));
    }
}

/** The Used By tab: what among the loaded objects and packages uses the one on screen. */
export class UsedByView {
    private subject: OpsSubject | undefined;
    private answer: Answer<UsedByData> | undefined;
    /** Whether the workspace was loaded for the answer on screen. */
    private loaded = false;
    /** Whether it is being loaded for the answer asked for. */
    private loading = false;
    /** Why it could not be loaded, said under the answer from before, which stands. */
    private loadError: string | undefined;
    /** The sections folded away, by id, kept from one object to the next. */
    private readonly folded = new Set<string>();

    constructor(
        private readonly pane: HTMLElement,
        private readonly callbacks: OpsCallbacks,
    ) {
        this.pane.classList.add('usedby');
    }

    /** Forget the last object, and say 'text' where the list goes. */
    public setBusy(text: string): void {
        this.subject = undefined;
        this.answer = undefined;
        this.loaded = false;
        this.loading = false;
        this.loadError = undefined;
        empty(this.pane);
        this.pane.appendChild(placeholder(text));
    }

    /** The tab has been opened on 'subject': ask what uses it. */
    public start(subject: OpsSubject): void {
        this.subject = subject;
        this.ask(false);
    }

    /** Ask again, having loaded the workspace first when 'load' says so. */
    private ask(load: boolean): void {
        const subject = this.subject;
        if (subject === undefined) {
            return;
        }
        const before = this.answer;
        this.loading = load;
        this.loadError = undefined;
        this.answer = 'pending';
        this.draw();
        this.callbacks.ask({ method: 'ops.used_by', params: load ? { load: true } : undefined }, (data, error) => {
            if (this.subject !== subject) {
                return;
            }
            this.loading = false;
            if (error !== undefined && load && before !== undefined && before !== 'pending' && 'data' in before) {
                // The workspace could not be loaded: what was found among what
                // is loaded still stands, and Load workspace is there to try again.
                this.answer = before;
                this.loadError = error;
            } else {
                this.answer = error !== undefined ? { error } : { data: (data as UsedByData) ?? { objects: [] } };
                // Of the whole workspace only once it has been loaded.
                this.loaded = this.loaded || (load && error === undefined);
            }
            this.draw();
        });
    }

    private draw(): void {
        empty(this.pane);
        const answer = this.answer;
        const what = thisSubject(this.subject);
        if (answer === undefined || answer === 'pending') {
            this.pane.appendChild(
                placeholder(
                    this.loading
                        ? `Loading every package of the workspace, then asking PartCAD what uses ${what}…`
                        : `Asking PartCAD what uses ${what}…`,
                ),
            );
            return;
        }
        if ('error' in answer) {
            this.pane.appendChild(el('p', 'error', answer.error));
            return;
        }
        const data = answer.data;
        const objects = data.objects ?? [];
        if (isPackage(this.subject)) {
            const packages = data.packages ?? [];
            this.pane.appendChild(
                this.section('packages', `Packages (${packages.length})`, (body) =>
                    body.appendChild(
                        packages.length > 0
                            ? dependentsTable(packages, this.callbacks)
                            : placeholder(`No package PartCAD has loaded declares ${what} as a dependency.`),
                    ),
                ),
            );
            this.pane.appendChild(
                this.section('objects', `Objects (${objects.length})`, (body) =>
                    body.appendChild(
                        objects.length > 0
                            ? usersTable(objects, this.callbacks)
                            : placeholder(`No object PartCAD has loaded uses anything in ${what}.`),
                    ),
                ),
            );
        } else if (objects.length > 0) {
            this.pane.appendChild(usersTable(objects, this.callbacks));
        } else {
            this.pane.appendChild(placeholder(`Nothing PartCAD has loaded uses ${what}.`));
        }
        this.pane.appendChild(loadedNote(this.loaded, () => this.ask(true)));
        if (this.loadError !== undefined) {
            this.pane.appendChild(el('p', 'error usedby-load-error', this.loadError));
        }
    }

    private section(id: string, title: string, fill: (body: HTMLElement) => void): HTMLElement {
        return section(
            id,
            title,
            !this.folded.has(id),
            (which) => {
                if (!this.folded.delete(which)) {
                    this.folded.add(which);
                }
                this.draw();
                focusSection(this.pane, which);
            },
            fill,
        );
    }
}
