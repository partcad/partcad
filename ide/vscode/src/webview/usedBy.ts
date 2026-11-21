//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What uses an object: the Operations group's Used By tab, and the "Used By"
// view under a revision on the Revisions tab.
//
// Both are a list of the objects the daemon has loaded that refer to something
// - this object, or anything in a package at a revision - with how many times
// each does: an assembly that places a bolt four times uses it four times. Only
// what is loaded is looked at (see 'partcad/usage.py'), and the list says so,
// so that an empty one reads as "nothing loaded uses it" rather than as
// "nothing uses it". A row is clickable, and shows that object in the panel.
//

import { el, empty, placeholder } from './dom';
import { UsedByData, UsedByRow } from './messages';

/** What a row opens: the object it names, in the panel. */
export type OpenObject = (row: UsedByRow) => void;

/** The table of users, into 'host': object, kind and how many times, each object a link. */
export function renderUsedBy(host: HTMLElement, data: UsedByData, onOpen: OpenObject, what: string): void {
    empty(host);
    const rows = data.objects ?? [];
    if (rows.length === 0) {
        host.appendChild(
            placeholder(`Nothing PartCAD has loaded uses ${what}. Objects not loaded yet are not looked at.`),
        );
        return;
    }
    const table = el('table', 'grid usedby-table');
    const head = table.appendChild(el('thead')).appendChild(el('tr'));
    for (const title of ['Object', 'Kind', 'Uses']) {
        head.appendChild(el('th', undefined, title));
    }
    const body = table.appendChild(el('tbody'));
    for (const row of rows) {
        const tr = body.appendChild(el('tr', 'usedby-row'));
        const cell = tr.appendChild(el('td', 'usedby-object'));
        const button = cell.appendChild(el('button', 'link-button usedby-open', row.object)) as HTMLButtonElement;
        button.type = 'button';
        button.dataset.object = row.object;
        button.title = `Show ${row.object}`;
        button.addEventListener('click', () => onOpen(row));
        tr.appendChild(el('td', 'usedby-kind', row.kind));
        tr.appendChild(el('td', 'usedby-count number', String(row.count)));
    }
    host.appendChild(table);
    host.appendChild(
        el(
            'p',
            'usedby-note placeholder',
            'Of what PartCAD has loaded: an object not loaded yet is not looked at, and an assembly not built yet is counted by what its declaration names.',
        ),
    );
}

/** The Used By tab: what among the loaded objects uses the one on screen. */
export class UsedByView {
    constructor(
        private readonly pane: HTMLElement,
        private readonly onOpen: OpenObject,
    ) {
        this.pane.classList.add('usedby');
    }

    public setBusy(text: string): void {
        empty(this.pane);
        this.pane.appendChild(placeholder(text));
    }

    public showError(text: string): void {
        empty(this.pane);
        this.pane.appendChild(el('p', 'error', text));
    }

    public show(data: UsedByData, what: string): void {
        renderUsedBy(this.pane, data, this.onOpen, what);
    }
}
