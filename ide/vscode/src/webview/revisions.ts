//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Operations group's Revisions tab: the history of the package of what is on
// screen, and what is on screen compared with any revision in it.
//
// Laid out as the Simulation tab is, because it is the same shape of page: a
// list down the left ('ScenarioList', the commits that changed the package,
// newest first, each as the first eight characters of its id), the selected
// one on the right, and folded views along the bottom, a strip of their titles
// with one open at a time - here "Uses (Dependencies)" and "Used By".
//
// What is on the right is the object - or, for a package, its 'partcad.yaml' -
// at the selected revision beside it as it is now, line by line, in the colours
// the editor's own diff uses. The daemon writes both sides out as 'pc copy'
// would (or, for a package, takes the file as Jinja2 rendered it when it was
// read) and compares them (see 'partcad/revisions.py'); nothing is diffed here.
//
// The two folded views are about the package at that revision, and are asked
// for the first time each is opened for it, not before: what it uses is a walk
// over its dependencies, which may download one, and nobody who only wanted the
// comparison should wait for that. Each is kept for the revision it was asked
// for while the object stays on screen.
//
// A package that is in no repository, or none of whose files were ever
// committed, has no history, and the tab says that it is not published yet.
//

import { el, empty, placeholder } from './dom';
import {
    CompareData,
    CompareRow,
    DependencyRow,
    RevisionEntry,
    RevisionsData,
    RevisionsQuery,
    UsedByData,
    UsedByRow,
    UsesData,
} from './messages';
import { ScenarioList, ScenarioRow } from './scenarioList';
import { renderUsedBy } from './usedBy';

/** What the panel does for the tab: ask the daemon, and open what a row names. */
export interface RevisionsCallbacks {
    /** Ask one of the tab's questions about 'revision'; the answer comes back through 'answer'. */
    ask: (query: Exclude<RevisionsQuery, 'list'>, revision: string) => void;
    /** A dependency, or a dependency at a commit: listed in the Package Explorer. */
    openPackage: (name: string) => void;
    /** An object that uses the package at the revision: shown in the panel. */
    showObject: (row: UsedByRow) => void;
}

/** The folded views, in the order their titles run along the bottom. */
type RevisionsDetail = 'uses' | 'usedBy';
const DETAILS: { id: RevisionsDetail; label: string }[] = [
    { id: 'uses', label: 'Uses (Dependencies)' },
    { id: 'usedBy', label: 'Used By' },
];

/** The text shown where the package has no history. */
export const NOT_PUBLISHED = 'This package is not published yet';

/** An answer to one question about one revision, once it is in. */
type Answer<T> = { data: T } | { error: string } | 'pending';

export class RevisionsView {
    private readonly list: ScenarioList;
    private readonly main: HTMLElement;
    private readonly header: HTMLElement;
    private readonly content: HTMLElement;
    private readonly details: HTMLElement;
    /** The history on screen; undefined until the daemon has said. */
    private history: RevisionsData | undefined;
    /** The commit selected, as its full id. */
    private selected: string | undefined;
    /** Which folded view is open, kept across revisions as the Simulation tab keeps its. */
    private detail: RevisionsDetail | undefined;
    private readonly compared = new Map<string, Answer<CompareData>>();
    private readonly uses = new Map<string, Answer<UsesData>>();
    private readonly usedBy = new Map<string, Answer<UsedByData>>();

    constructor(
        private readonly pane: HTMLElement,
        private readonly callbacks: RevisionsCallbacks,
    ) {
        this.pane.classList.add('revisions');
        this.list = new ScenarioList('revisions', (name) => this.select(this.shaOf(name)));
        this.main = el('div', 'revisions-main');
        this.header = el('div', 'render-header revisions-toolbar');
        this.content = el('div', 'revisions-content');
        this.details = el('div', 'simulation-details revisions-details');
        this.main.append(this.header, this.content, this.details);
        this.pane.append(this.list.element, this.main);
        this.setBusy('Select this tab to see the history of this package.');
    }

    /** Forget everything about the last object, and say 'text' where the page goes. */
    public setBusy(text: string): void {
        this.history = undefined;
        this.selected = undefined;
        this.compared.clear();
        this.uses.clear();
        this.usedBy.clear();
        this.list.element.hidden = true;
        this.header.hidden = true;
        empty(this.header);
        empty(this.details);
        empty(this.content);
        this.content.appendChild(placeholder(text));
    }

    public showError(text: string): void {
        this.setBusy('');
        empty(this.content);
        this.content.appendChild(el('p', 'error', text));
    }

    /** The history has arrived: list it, and compare with the newest revision. */
    public showHistory(data: RevisionsData): void {
        this.history = data;
        const revisions = data.revisions ?? [];
        if (!data.published || revisions.length === 0) {
            this.list.element.hidden = true;
            this.header.hidden = true;
            empty(this.details);
            empty(this.content);
            this.content.appendChild(placeholder(NOT_PUBLISHED));
            return;
        }
        this.list.element.hidden = false;
        this.select(revisions[0].sha);
    }

    /** The revisions on offer, newest first, for 'pc ide state' and the tests. */
    public get offered(): string[] {
        return (this.history?.revisions ?? []).map((entry) => entry.short);
    }

    /** The revision on screen, as its full id. */
    public get current(): string | undefined {
        return this.selected;
    }

    /** Select a revision: compare with it, asking if this is the first look at it. */
    public select(sha: string | undefined): void {
        const entry = this.entryOf(sha);
        if (entry === undefined) {
            return;
        }
        this.selected = entry.sha;
        this.drawList();
        this.drawHeader(entry);
        if (!this.compared.has(entry.sha)) {
            this.compared.set(entry.sha, 'pending');
            this.callbacks.ask('compare', entry.sha);
        }
        this.drawComparison();
        if (this.detail !== undefined) {
            this.ensure(this.detail, entry.sha);
        }
        this.drawDetails();
    }

    /** One of the tab's answers has arrived, for 'revision'. */
    public answer(query: Exclude<RevisionsQuery, 'list'>, revision: string, data: unknown, error?: string): void {
        const answer = error !== undefined ? { error } : { data };
        if (query === 'compare') {
            this.compared.set(revision, answer as Answer<CompareData>);
            if (revision === this.selected) {
                this.drawComparison();
            }
            return;
        }
        (query === 'uses' ? this.uses : this.usedBy).set(revision, answer as Answer<never>);
        if (revision === this.selected) {
            this.drawDetails();
        }
    }

    private entryOf(sha: string | undefined): RevisionEntry | undefined {
        return (this.history?.revisions ?? []).find((entry) => entry.sha === sha);
    }

    private shaOf(short: string): string | undefined {
        return (this.history?.revisions ?? []).find((entry) => entry.short === short)?.sha;
    }

    private drawList(): void {
        const head = this.history?.head ?? undefined;
        const rows: ScenarioRow[] = (this.history?.revisions ?? []).map((entry) => ({
            name: entry.short,
            desc: describe(entry),
            verdict:
                entry.sha === head
                    ? { state: 'ran', mark: '●', label: 'Checked out: what the files on disk are, before any edit' }
                    : { state: 'unrun', mark: '', label: '' },
        }));
        this.list.draw(rows, this.entryOf(this.selected)?.short);
    }

    private drawHeader(entry: RevisionEntry): void {
        empty(this.header);
        this.header.hidden = false;
        this.header.appendChild(el('span', 'revisions-sha', entry.short));
        if (entry.summary) {
            this.header.appendChild(el('span', 'revisions-summary', entry.summary));
        }
        const by = [entry.author, when(entry.time)].filter(Boolean).join(', ');
        if (by) {
            this.header.appendChild(el('span', 'render-label revisions-by', by));
        }
    }

    private drawComparison(): void {
        empty(this.content);
        const answer = this.selected === undefined ? undefined : this.compared.get(this.selected);
        if (answer === undefined || answer === 'pending') {
            this.content.appendChild(placeholder('Loading this revision and comparing it with what is on screen…'));
            return;
        }
        if ('error' in answer) {
            this.content.appendChild(el('p', 'error', answer.error));
            return;
        }
        this.content.appendChild(renderComparison(answer.data));
    }

    /** Ask for a folded view's contents for 'sha', the first time it is opened for it. */
    private ensure(detail: RevisionsDetail, sha: string): void {
        const answers = detail === 'uses' ? this.uses : this.usedBy;
        if (!answers.has(sha)) {
            answers.set(sha, 'pending');
            this.callbacks.ask(detail, sha);
        }
    }

    /**
     * The folded views: a strip of their titles, and under it the one that is
     * open - the Simulation tab's strip, as it is drawn there. A title opens its
     * view, which asks for what it shows the first time, and closes it again.
     */
    private drawDetails(): void {
        empty(this.details);
        const sha = this.selected;
        if (sha === undefined) {
            return;
        }
        const strip = el('div', 'tabs sub-tabs simulation-detail-tabs revisions-detail-tabs');
        strip.setAttribute('role', 'tablist');
        for (const detail of DETAILS) {
            const open = detail.id === this.detail;
            const title = el('button', `tab simulation-detail-tab${open ? ' current' : ''}`, detail.label);
            title.type = 'button';
            title.dataset.detail = detail.id;
            title.setAttribute('role', 'tab');
            title.setAttribute('aria-selected', String(open));
            title.setAttribute('aria-expanded', String(open));
            title.title = open ? `Fold ${detail.label} away` : `Show ${detail.label}`;
            if (open) {
                const chevron = el('span', 'simulation-detail-chevron', '▾');
                chevron.setAttribute('aria-hidden', 'true');
                title.appendChild(chevron);
            }
            title.addEventListener('click', () => {
                this.detail = open ? undefined : detail.id;
                if (this.detail !== undefined && this.selected !== undefined) {
                    this.ensure(this.detail, this.selected);
                }
                this.drawDetails();
            });
            strip.appendChild(title);
        }
        this.details.appendChild(strip);
        if (this.detail === undefined) {
            return;
        }
        const view = el('div', 'simulation-detail revisions-detail');
        view.setAttribute('role', 'tabpanel');
        view.dataset.detail = this.detail;
        const short = this.entryOf(sha)?.short ?? sha.slice(0, 8);
        if (this.detail === 'uses') {
            const answer = this.uses.get(sha);
            if (answer === undefined || answer === 'pending') {
                view.appendChild(
                    placeholder(`Asking PartCAD what the package declares as its dependencies at ${short}…`),
                );
            } else if ('error' in answer) {
                view.appendChild(el('p', 'error', answer.error));
            } else {
                view.appendChild(this.renderUses(answer.data, short));
            }
        } else {
            const answer = this.usedBy.get(sha);
            if (answer === undefined || answer === 'pending') {
                view.appendChild(placeholder(`Asking PartCAD what uses the package at ${short}…`));
            } else if ('error' in answer) {
                view.appendChild(el('p', 'error', answer.error));
            } else {
                renderUsedBy(view, answer.data, this.callbacks.showObject, `the package at ${short}`);
            }
        }
        this.details.appendChild(view);
    }

    /** The dependencies, two columns: the dependency, and the commit it is at - each opening it in the explorer. */
    private renderUses(data: UsesData, short: string): HTMLElement {
        const rows = data.dependencies ?? [];
        if (rows.length === 0) {
            return placeholder(`At ${short}, the package declares no dependencies.`);
        }
        const table = el('table', 'grid revisions-uses');
        const head = table.appendChild(el('thead')).appendChild(el('tr'));
        head.appendChild(el('th', undefined, 'Dependency'));
        head.appendChild(el('th', undefined, 'SHA'));
        const body = table.appendChild(el('tbody'));
        for (const row of rows) {
            const tr = body.appendChild(el('tr', 'revisions-dependency'));
            const name = row.current ?? row.package;
            tr.appendChild(el('td')).appendChild(
                this.openButton(row.name, name, `Open ${name} in the Package Explorer`, 'revisions-dependency-name'),
            );
            const cell = tr.appendChild(el('td'));
            if (row.short && row.versioned) {
                cell.appendChild(
                    this.openButton(
                        row.short,
                        row.versioned,
                        `Open ${row.versioned} - the dependency at this commit - in the Package Explorer`,
                        'revisions-dependency-sha name',
                    ),
                );
            } else {
                cell.appendChild(el('span', 'placeholder', dependencyWithoutSha(row)));
            }
        }
        return table;
    }

    private openButton(text: string, target: string, title: string, className: string): HTMLButtonElement {
        const button = el('button', `link-button ${className}`, text) as HTMLButtonElement;
        button.type = 'button';
        button.dataset.package = target;
        button.title = title;
        button.addEventListener('click', () => this.callbacks.openPackage(target));
        return button;
    }
}

/** What a revision's row says when hovered: its summary, who made it and when. */
function describe(entry: RevisionEntry): string {
    return [entry.summary, [entry.author, when(entry.time)].filter(Boolean).join(', ')].filter(Boolean).join(' - ');
}

/** A commit time, in this reader's own time zone. */
function when(seconds: number | undefined): string {
    if (!seconds) {
        return '';
    }
    const date = new Date(seconds * 1000);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

function dependencyWithoutSha(row: DependencyRow): string {
    if (row.sha === null && row.type !== 'git') {
        return 'not in a repository';
    }
    return 'not known';
}

/**
 * The two sides of a comparison, side by side: the revision on the left and the
 * object as it is now on the right, a line of each per row with its number, a
 * line that changed, went or came coloured as the editor's diff colours it.
 */
export function renderComparison(data: CompareData): HTMLElement {
    const page = el('div', 'revisions-compare');
    const notes: string[] = [];
    if (data.left.missing && data.right.missing) {
        notes.push('Declared neither now nor at this revision.');
    } else if (data.left.missing) {
        notes.push(`Not declared at ${data.short}: everything here is new since.`);
    } else if (data.right.missing) {
        notes.push(`Not declared any more: this is what it was at ${data.short}.`);
    } else if (data.same) {
        notes.push(`No change since ${data.short}: it is declared now as it was then.`);
    }
    for (const note of notes) {
        page.appendChild(placeholder(note));
    }
    const table = el('table', 'revisions-diff');
    const colgroup = table.appendChild(el('colgroup'));
    for (const className of ['diff-number', 'diff-text', 'diff-number', 'diff-text']) {
        colgroup.appendChild(el('col', className));
    }
    const head = table.appendChild(el('thead')).appendChild(el('tr'));
    const left = head.appendChild(el('th', 'diff-side', data.left.label));
    left.colSpan = 2;
    left.title = `${data.loaded}: the revision`;
    const right = head.appendChild(el('th', 'diff-side', data.right.label));
    right.colSpan = 2;
    right.title = 'What is loaded now';
    const body = table.appendChild(el('tbody'));
    for (const row of data.rows ?? []) {
        body.appendChild(renderRow(row));
    }
    page.appendChild(table);
    return page;
}

function renderRow(row: CompareRow): HTMLElement {
    const tr = el('tr', `diff-row diff-${row.tag}`);
    const leftClass = row.left === null ? 'diff-empty' : row.tag === 'equal' ? '' : 'diff-removed';
    const rightClass = row.right === null ? 'diff-empty' : row.tag === 'equal' ? '' : 'diff-added';
    tr.appendChild(el('td', `diff-number ${leftClass}`, row.leftLine === null ? '' : String(row.leftLine)));
    tr.appendChild(el('td', `diff-text ${leftClass}`, row.left ?? ''));
    tr.appendChild(el('td', `diff-number ${rightClass}`, row.rightLine === null ? '' : String(row.rightLine)));
    tr.appendChild(el('td', `diff-text ${rightClass}`, row.right ?? ''));
    return tr;
}
