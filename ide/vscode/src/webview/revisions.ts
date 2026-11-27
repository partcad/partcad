//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Operations group's Revisions tab: the history of what is on screen, what
// of it is not committed yet, and a new revision made of what is staged.
//
// Laid out as the Simulation tab is, because it is the same shape of page: a
// list down the left ('ScenarioList'), the selected row on the right, and
// folded views along the bottom, a strip of their titles with one open at a
// time.
//
// The list is the revisions, newest first, each as the first eight characters
// of its commit id: every commit of a package - one that changed only
// sub-packages of it says which - and only the commits that changed an object,
// each saying how ('ops.rev.list'). A page at a time; "Load more" asks for the
// page after the last one. Above them, when they apply, two rows that are not
// commits ('ops.rev.status'): WORKTREE, what is on disk and not staged, with
// Stage all ('ops.rev.stage') and the sentence to hand an agent that would
// stage it instead; and STAGED, what a new revision would commit, with the form
// that makes one ('ops.rev.new').
//
// What is on the right is the selected row compared with another state, side
// by side, in the colours the editor's own diff uses: what the row changed
// (a commit with its parent, STAGED with HEAD, WORKTREE with STAGED), or
// everything since it (the row with the files on disk). The daemon writes both
// sides out as 'pc copy' would - for a package, takes its 'partcad.yaml' as
// rendered, and says which objects and files changed - and compares them
// ('ops.rev.diff'); nothing is diffed here.
//
// The folded views are about the package or the object at that row: what it
// depended on, what used it, and what changing it since has reached
// ('ops.deps.list', 'ops.used_by', 'ops.impact'). Each is asked for the first
// time it is opened for a row, not before: what something uses is a walk over
// its dependencies, which may download one, and nobody who only wanted the
// comparison should wait for that.
//
// A new revision is signed by the host with this machine's git identity, never
// the daemon's (see 'src/viewer/operations.ts'). The daemon may refuse it on
// its first attempt - something else is staged too, changes of it are not
// staged, lint or the tests failed - and the form then says why and lets the
// user agree to it and send it again.
//
// A package that is in no repository, or none of whose files were ever
// committed, has no history, and the tab says that it is not published yet.
//

import { renderDependencies } from './dependencies';
import { el, empty, placeholder } from './dom';
import { renderImpact } from './impact';
import {
    CompareRow,
    DepsData,
    DiffData,
    ImpactData,
    OpsQuery,
    OpsReadMethod,
    PackageChanges,
    RevNewData,
    RevRefusal,
    RevStageData,
    RevStatusData,
    RevisionEntry,
    RevisionsData,
    STAGED,
    StatusFile,
    UsedByData,
    WORKTREE,
} from './messages';
import {
    Answer,
    OpsCallbacks,
    OpsSubject,
    button,
    chips,
    grid,
    isPackage,
    objectCell,
    thisSubject,
    when,
} from './operations';
import { ScenarioList, ScenarioRow } from './scenarioList';
import { renderUsedBy } from './usedBy';

/** The text shown where the package has no history. */
export const NOT_PUBLISHED = 'This package is not published yet';

/** A row of the list: a commit by its full id, or one of the two states that are not commits. */
export type RowId = string;

/** What the comparison of a row is: what the row changed, or everything since it. */
export type CompareMode = 'change' | 'since';

/** The folded views, in the order their titles run along the bottom. */
type RevisionsDetail = 'deps' | 'usedBy' | 'impact';
const DETAILS: RevisionsDetail[] = ['deps', 'usedBy', 'impact'];

/** Whether a row is one of the two states that are not commits. */
export function isState(row: RowId | undefined): boolean {
    return row === STAGED || row === WORKTREE;
}

/** The files of the status that are the subject's: all of a package's, or the files an object is built from. */
export function subjectFiles(status: RevStatusData): StatusFile[] {
    const own = status.own_files;
    const files = status.files ?? [];
    return own === null || own === undefined ? files : files.filter((entry) => own.includes(entry.path));
}

/** Whether anything of the subject is on disk and not staged: what the WORKTREE row is shown for. */
export function hasUnstaged(status: RevStatusData): boolean {
    return (
        (status.unstaged ?? []).length > 0 ||
        subjectFiles(status).some(
            (entry) => entry.sections.includes('unstaged') || entry.sections.includes('untracked'),
        )
    );
}

/** Whether anything of the subject is staged: what the STAGED row is shown for. */
export function hasStaged(status: RevStatusData): boolean {
    return (status.staged ?? []).length > 0 || subjectFiles(status).some((entry) => entry.sections.includes('staged'));
}

/**
 * A first draft of a new revision's message, from what is staged: each object
 * and how it changed ("bracket: declaration, source"), or the files where no
 * object did.
 */
export function draftMessage(status: RevStatusData): string {
    const objects = (status.staged ?? []).map((row) => `${row.name}: ${(row.how ?? []).join(', ')}`);
    if (objects.length > 0) {
        return objects.join('; ');
    }
    const files = subjectFiles(status)
        .filter((entry) => entry.sections.includes('staged'))
        .map((entry) => entry.path);
    return files.length > 0 ? `Update ${files.join(', ')}` : '';
}

/**
 * The two states a row is compared between: what it changed ('change') - a
 * commit against its parent, STAGED against HEAD, WORKTREE against STAGED - or
 * everything since it ('since'), which for WORKTREE is nothing.
 */
export function comparedStates(row: RowId, mode: CompareMode): { from: string; to: string } | undefined {
    if (row === WORKTREE) {
        return mode === 'change' ? { from: STAGED, to: WORKTREE } : undefined;
    }
    if (row === STAGED) {
        return mode === 'change' ? { from: 'HEAD', to: STAGED } : { from: STAGED, to: WORKTREE };
    }
    return mode === 'change' ? { from: `${row}~1`, to: row } : { from: row, to: WORKTREE };
}

/** How many of something, in words: "1 object", "3 files". */
function count(n: number, what: string): string {
    return `${n} ${what}${n === 1 ? '' : 's'}`;
}

/** What a state row holds, in a few words: "2 objects, 1 file". */
function stateSummary(status: RevStatusData, row: RowId): string {
    const objects = row === STAGED ? (status.staged ?? []) : (status.unstaged ?? []);
    const sections = row === STAGED ? ['staged'] : ['unstaged', 'untracked'];
    const files = subjectFiles(status).filter((entry) => entry.sections.some((each) => sections.includes(each)));
    return [
        objects.length > 0 ? count(objects.length, 'object') : '',
        files.length > 0 ? count(files.length, 'file') : '',
    ]
        .filter(Boolean)
        .join(', ');
}

/**
 * A comparison, once it is in: the daemon's answer - or, for the first commit
 * of a repository, which has no parent, its own side drawn as all added.
 */
type Compared = { data: DiffData; first?: boolean } | { error: string } | 'pending';

/** The New revision form, as filled in so far, and what came of sending it. */
interface RevisionForm {
    message: string;
    skipChecks: boolean;
    includeOthers: boolean;
    yes: boolean;
    sending: boolean;
    /** Why the daemon would not make it, in its words, and which reason. */
    refused?: { message: string; refusal: RevRefusal };
    error?: string;
}

export class RevisionsView {
    private readonly list: ScenarioList;
    private readonly listFooter: HTMLElement;
    private readonly main: HTMLElement;
    private readonly header: HTMLElement;
    private readonly content: HTMLElement;
    private readonly details: HTMLElement;
    private subject: OpsSubject | undefined;
    /** The revisions listed so far, every page of them; undefined until the daemon has said. */
    private history: Answer<RevisionsData> | undefined;
    /** Why the last "Load more" failed, if it did. */
    private moreError: string | undefined;
    /** A page of revisions in flight. */
    private listing = false;
    /** What is staged and what is not; undefined until the daemon has said. */
    private status: Answer<RevStatusData> | undefined;
    /** The row selected. */
    private selected: RowId | undefined;
    /** What the comparison is of, kept across rows. */
    private mode: CompareMode = 'change';
    /** Which folded view is open, kept across rows as the Simulation tab keeps its. */
    private detail: RevisionsDetail | undefined;
    /** Comparisons, by the two states compared: '<from>..<to>'. */
    private readonly compared = new Map<string, Compared>();
    /** The folded views' answers, by view and row: '<detail>:<row>'. */
    private readonly folded = new Map<string, Answer<unknown>>();
    private form: RevisionForm | undefined;
    /** A Stage all in flight. */
    private staging = false;
    /** What the last change did, said over the page until the next one. */
    private note: { text: string; error: boolean } | undefined;

    constructor(
        private readonly pane: HTMLElement,
        private readonly callbacks: OpsCallbacks,
    ) {
        this.pane.classList.add('revisions');
        this.list = new ScenarioList('revisions', (name) => this.select(this.rowOf(name)));
        this.listFooter = el('div', 'revisions-footer');
        this.list.element.appendChild(this.listFooter);
        this.main = el('div', 'revisions-main');
        this.header = el('div', 'render-header revisions-toolbar');
        this.content = el('div', 'revisions-content');
        this.details = el('div', 'simulation-details revisions-details');
        this.main.append(this.header, this.content, this.details);
        this.pane.append(this.list.element, this.main);
        this.setBusy('Select this tab to see the revisions of this object.');
    }

    /** Forget everything about the last object, and say 'text' where the page goes. */
    public setBusy(text: string): void {
        this.subject = undefined;
        this.history = undefined;
        this.moreError = undefined;
        this.listing = false;
        this.status = undefined;
        this.selected = undefined;
        this.compared.clear();
        this.folded.clear();
        this.form = undefined;
        this.staging = false;
        this.note = undefined;
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

    /** The tab has been opened on 'subject': ask for its revisions and for what is not committed. */
    public start(subject: OpsSubject): void {
        this.setBusy(`Asking PartCAD for the revisions of ${thisSubject(subject)}…`);
        this.subject = subject;
        this.askList();
        this.askStatus();
    }

    /** The rows on offer, top to bottom - WORKTREE and STAGED by those names - for 'pc ide state' and the tests. */
    public get offered(): string[] {
        return this.rows().map((row) => this.nameOf(row));
    }

    /** The row on screen: a commit's full id, or WORKTREE or STAGED. */
    public get current(): RowId | undefined {
        return this.selected;
    }

    /** What 'pc ide state' says of the tab: the row selected, what it is compared with, the view open. */
    public state(): Record<string, unknown> {
        return {
            selected: this.selected === undefined ? null : this.nameOf(this.selected),
            compare: this.mode,
            detail: this.detail ?? null,
            rows: this.offered,
        };
    }

    /** Select a row: compare it, asking if this is the first look at it. */
    public select(row: RowId | undefined): void {
        if (row === undefined || !this.rows().includes(row)) {
            return;
        }
        if (row !== this.selected && this.form !== undefined && !this.form.sending) {
            // A form is for the row it was opened on.
            this.form = undefined;
        }
        this.selected = row;
        if (comparedStates(row, this.mode) === undefined) {
            // Nothing comes after the files on disk: WORKTREE is what it changed.
            this.mode = 'change';
        }
        this.askComparison();
        if (this.detail !== undefined) {
            this.ensure(this.detail, row);
        }
        this.draw();
    }

    /** Compare the selected row with the other state: what it changed, or everything since. */
    public compare(mode: CompareMode): void {
        if (this.selected === undefined || comparedStates(this.selected, mode) === undefined) {
            return;
        }
        this.mode = mode;
        this.askComparison();
        this.draw();
    }

    /** Open a folded view, or fold it away again: what the strip's titles do. */
    public toggleDetail(detail: RevisionsDetail): void {
        this.detail = this.detail === detail ? undefined : detail;
        if (this.detail !== undefined && this.selected !== undefined) {
            this.ensure(this.detail, this.selected);
        }
        this.drawDetails();
    }

    private rows(): RowId[] {
        const rows: RowId[] = [];
        const status = this.statusData();
        if (status !== undefined && hasUnstaged(status)) {
            rows.push(WORKTREE);
        }
        if (status !== undefined && hasStaged(status)) {
            rows.push(STAGED);
        }
        for (const entry of this.revisions()) {
            rows.push(entry.sha);
        }
        return rows;
    }

    private revisions(): RevisionEntry[] {
        return this.history !== undefined && this.history !== 'pending' && 'data' in this.history
            ? (this.history.data.revisions ?? [])
            : [];
    }

    private statusData(): RevStatusData | undefined {
        return this.status !== undefined && this.status !== 'pending' && 'data' in this.status
            ? this.status.data
            : undefined;
    }

    private entryOf(row: RowId | undefined): RevisionEntry | undefined {
        return this.revisions().find((entry) => entry.sha === row);
    }

    /** What a row is listed as: a commit by its short id, a state by its name. */
    private nameOf(row: RowId): string {
        return isState(row) ? row : (this.entryOf(row)?.short ?? row.slice(0, 8));
    }

    private rowOf(name: string): RowId | undefined {
        return isState(name) ? name : this.revisions().find((entry) => entry.short === name)?.sha;
    }

    /** What a row is called in a sentence. */
    private labelOf(row: RowId): string {
        return row === WORKTREE ? 'the files on disk' : row === STAGED ? 'what is staged' : this.nameOf(row);
    }

    /** Whether a commit is the first of the repository, as far as the list knows: the oldest, with nothing after it. */
    private isFirstCommit(row: RowId): boolean {
        const revisions = this.revisions();
        const history = this.history;
        const more = history !== undefined && history !== 'pending' && 'data' in history && history.data.more;
        return !isState(row) && !more && revisions.length > 0 && revisions[revisions.length - 1].sha === row;
    }

    // ---- Asking ------------------------------------------------------------

    private ask(query: OpsQuery<OpsReadMethod>, answer: (data: unknown, error?: string) => void): void {
        const subject = this.subject;
        this.callbacks.ask(query, (data, error) => {
            // For an object no longer on screen: the panel drops those, and so
            // does this, for a tab asked again on the same one.
            if (this.subject === subject) {
                answer(data, error);
            }
        });
    }

    private askList(after?: string): void {
        this.listing = true;
        this.moreError = undefined;
        // Read again after a change, the revisions on screen stay until the new
        // ones are in, as the status does.
        if (after === undefined && this.revisions().length === 0) {
            this.history = 'pending';
        }
        this.ask({ method: 'ops.rev.list', params: after !== undefined ? { after } : undefined }, (data, error) => {
            this.listing = false;
            const page = data as RevisionsData | undefined;
            if (after === undefined) {
                this.history =
                    error !== undefined
                        ? { error }
                        : page
                          ? { data: page }
                          : { error: 'PartCAD had nothing to say about the history of this.' };
            } else if (error !== undefined) {
                this.moreError = error;
            } else if (page && this.history !== undefined && this.history !== 'pending' && 'data' in this.history) {
                const known = new Set(this.revisions().map((entry) => entry.sha));
                this.history = {
                    data: {
                        ...this.history.data,
                        more: page.more,
                        revisions: [
                            ...this.revisions(),
                            ...(page.revisions ?? []).filter((entry) => !known.has(entry.sha)),
                        ],
                    },
                };
            }
            this.answered();
        });
    }

    private askStatus(): void {
        // Read again after a change, the status on screen stays until the new
        // one is in: the rows it decides would otherwise blink out and back.
        if (this.statusData() === undefined) {
            this.status = 'pending';
        }
        this.ask({ method: 'ops.rev.status' }, (data, error) => {
            this.status =
                error !== undefined
                    ? { error }
                    : data
                      ? { data: data as RevStatusData }
                      : { error: 'PartCAD had nothing to say about what is staged.' };
            this.answered();
        });
    }

    /**
     * An answer about the list has arrived: once both the revisions and the
     * status are in, the first row is selected - not before, so that the page
     * does not open on a commit and then jump to WORKTREE a moment later.
     */
    private answered(): void {
        const settled =
            this.history !== undefined &&
            this.history !== 'pending' &&
            this.status !== undefined &&
            this.status !== 'pending';
        if (settled && this.selected !== undefined && !this.rows().includes(this.selected)) {
            // Staged since, or committed: the row is gone.
            this.selected = undefined;
        }
        if (this.selected === undefined && settled && this.rows().length > 0) {
            this.select(this.rows()[0]);
            return;
        }
        this.draw();
    }

    private askComparison(): void {
        const row = this.selected;
        const states = row === undefined ? undefined : comparedStates(row, this.mode);
        if (row === undefined || states === undefined) {
            return;
        }
        const key = `${states.from}..${states.to}`;
        // Asked again while still pending: the host cancels a comparison a newer
        // one replaces, and a cancelled one is never answered.
        const known = this.compared.get(key);
        if (known !== undefined && known !== 'pending') {
            return;
        }
        this.compared.set(key, 'pending');
        this.ask({ method: 'ops.rev.diff', params: states }, (data, error) => {
            if (error !== undefined && states.from === `${row}~1` && this.isFirstCommit(row)) {
                // The first commit of the repository has no parent to be
                // compared with: everything in it is what it added. Asked as
                // itself on both sides, and drawn as its right side alone.
                this.ask({ method: 'ops.rev.diff', params: { from: row, to: row } }, (itself, failed) => {
                    this.compared.set(
                        key,
                        failed !== undefined ? { error: failed } : { data: asAdded(itself as DiffData), first: true },
                    );
                    this.drawComparison();
                });
                return;
            }
            this.compared.set(key, error !== undefined ? { error } : { data: data as DiffData });
            this.drawComparison();
        });
    }

    /** The folded view's question about a row. */
    private detailQuery(detail: RevisionsDetail, row: RowId): OpsQuery<OpsReadMethod> {
        // The package at the row's state - a commit, or the index - and as it is
        // loaded for the files on disk, which is what WORKTREE is.
        const at = row === WORKTREE ? undefined : row;
        if (detail === 'deps') {
            return { method: 'ops.deps.list', at };
        }
        if (detail === 'usedBy') {
            // What uses the package at a commit: what pins it there. Nothing
            // refers to the index, so the states are asked as the package is.
            return { method: 'ops.used_by', at: isState(row) ? undefined : row, whole: true };
        }
        const states = isState(row) ? comparedStates(row, 'change') : { from: row, to: WORKTREE };
        return { method: 'ops.impact', params: states };
    }

    /** Ask for a folded view's contents for 'row', the first time it is opened for it. */
    private ensure(detail: RevisionsDetail, row: RowId): void {
        const key = `${detail}:${row}`;
        const known = this.folded.get(key);
        if (known !== undefined && known !== 'pending') {
            return;
        }
        this.folded.set(key, 'pending');
        this.ask(this.detailQuery(detail, row), (data, error) => {
            this.folded.set(key, error !== undefined ? { error } : { data });
            if (this.selected === row) {
                this.drawDetails();
            }
        });
    }

    // ---- Changing ----------------------------------------------------------

    /** What is staged, and the files on disk, have changed: every comparison and view of them is stale. */
    private forgetStates(): void {
        for (const key of [...this.compared.keys()]) {
            if (key.includes(STAGED) || key.includes(WORKTREE) || key.includes('HEAD')) {
                this.compared.delete(key);
            }
        }
        for (const key of [...this.folded.keys()]) {
            if (isState(key.slice(key.indexOf(':') + 1)) || key.startsWith('impact:')) {
                this.folded.delete(key);
            }
        }
    }

    /** Stage all: every change of the subject not staged yet ('ops.rev.stage'). */
    private stage(): void {
        const subject = this.subject;
        if (subject === undefined || this.staging) {
            return;
        }
        this.staging = true;
        this.note = undefined;
        this.draw();
        this.callbacks.write({ method: 'ops.rev.stage' }, ({ data, error }) => {
            if (this.subject !== subject) {
                return;
            }
            this.staging = false;
            if (error !== undefined) {
                this.note = { text: error, error: true };
                this.draw();
                return;
            }
            const staged = data as RevStageData;
            const said =
                (staged.staged ?? []).length > 0 ? `Staged ${staged.staged.join(', ')}.` : 'Nothing was left to stage.';
            this.note = { text: [said, ...(staged.notes ?? [])].join(' '), error: false };
            this.forgetStates();
            if (!staged.status) {
                this.askStatus();
                return;
            }
            this.status = { data: staged.status };
            if (this.selected !== undefined && this.rows().includes(this.selected)) {
                // Still on screen, and compared afresh: what it holds moved.
                this.askComparison();
                if (this.detail !== undefined) {
                    this.ensure(this.detail, this.selected);
                }
            }
            // A WORKTREE with nothing left in it is gone, and the first row is
            // selected in its place.
            this.answered();
        });
    }

    /** Make the revision the form says, of what is staged ('ops.rev.new'). */
    private makeRevision(): void {
        const subject = this.subject;
        const form = this.form;
        const status = this.statusData();
        if (subject === undefined || form === undefined || form.sending) {
            return;
        }
        if (!form.message.trim()) {
            form.error = 'A new revision needs a message.';
            this.draw();
            return;
        }
        form.sending = true;
        form.error = undefined;
        // What the user agreed to stays ticked; why it was refused is for the
        // attempt it was said about.
        form.refused = undefined;
        this.draw();
        this.callbacks.write(
            {
                method: 'ops.rev.new',
                params: {
                    message: form.message,
                    expectIndex: status?.index ?? null,
                    includeOthers: form.includeOthers || undefined,
                    yes: form.yes || undefined,
                    skipChecks: form.skipChecks || undefined,
                },
            },
            ({ data, error, refusal }) => {
                if (this.subject !== subject || this.form !== form) {
                    return;
                }
                form.sending = false;
                if (error !== undefined) {
                    if (refusal !== undefined) {
                        form.refused = { message: error, refusal };
                        if (refusal.code === 'index-changed') {
                            // What is staged moved under the form: read it
                            // again, and the next attempt expects that.
                            this.forgetStates();
                            this.askStatus();
                        }
                    } else {
                        form.error = error;
                    }
                    this.draw();
                    return;
                }
                this.made(data as RevNewData);
            },
            status?.repository ?? null,
        );
    }

    /** A revision was made: say so, and read the list and the status again, which it changed. */
    private made(data: RevNewData): void {
        const author = data.author?.name
            ? ` as ${data.author.name}${data.author.email ? ` <${data.author.email}>` : ''}`
            : '';
        const checks = (data.checks ?? []).map((check) => check.summary).join('; ');
        this.note = {
            text: `Made the revision ${data.short}: ${data.summary}${author}.${checks ? ` ${checks}.` : ''}`,
            error: false,
        };
        this.form = undefined;
        this.selected = undefined;
        this.forgetStates();
        // Nothing is selected until the new status is in: what was staged is
        // committed now, and the first row will be another.
        this.status = 'pending';
        this.askList();
        this.askStatus();
        this.draw();
    }

    // ---- Drawing -----------------------------------------------------------

    private draw(): void {
        this.drawList();
        this.drawHeader();
        this.drawComparison();
        this.drawDetails();
    }

    private drawList(): void {
        const rows = this.rows();
        this.list.element.hidden = rows.length === 0;
        const head =
            this.history !== undefined && this.history !== 'pending' && 'data' in this.history
                ? this.history.data.head
                : null;
        const status = this.statusData();
        const object = !isPackage(this.subject);
        const listed: ScenarioRow[] = rows.map((row) => {
            if (row === WORKTREE) {
                return {
                    name: WORKTREE,
                    desc: `What is on disk and not staged: ${status ? stateSummary(status, row) : ''}`,
                    // The list's marks say how a run went on the other tabs; here,
                    // which state a row is (see 'revisions-running' in the CSS).
                    verdict: { state: 'running', mark: '✎', label: 'Changed on disk, not staged' },
                    chips: status ? [stateSummary(status, row)].filter(Boolean) : [],
                };
            }
            if (row === STAGED) {
                return {
                    name: STAGED,
                    desc: `What a new revision would commit: ${status ? stateSummary(status, row) : ''}`,
                    verdict: { state: 'passed', mark: '+', label: 'Staged: what a new revision would commit' },
                    chips: status ? [stateSummary(status, row)].filter(Boolean) : [],
                };
            }
            const entry = this.entryOf(row) as RevisionEntry;
            return {
                name: entry.short,
                desc: describe(entry),
                verdict:
                    entry.sha === head
                        ? { state: 'ran', mark: '●', label: 'Checked out: what the files on disk are, before any edit' }
                        : { state: 'unrun', mark: '', label: '' },
                chips: object ? entry.how : entry.in?.map((directory) => `in ${directory}`),
            };
        });
        this.list.draw(listed, this.selected === undefined ? undefined : this.nameOf(this.selected));
        empty(this.listFooter);
        const history = this.history;
        if (history !== undefined && history !== 'pending' && 'data' in history) {
            if (!history.data.published || history.data.revisions.length === 0) {
                this.listFooter.appendChild(
                    placeholder(
                        history.data.published
                            ? `No revision has changed ${thisSubject(this.subject)} yet.`
                            : 'No revisions yet.',
                    ),
                );
            }
            if (history.data.more) {
                const more = this.listFooter.appendChild(
                    button('Load more', 'small secondary revisions-more', 'List the revisions before these', () => {
                        const last = this.revisions()[this.revisions().length - 1];
                        if (last !== undefined && !this.listing) {
                            this.askList(last.sha);
                            this.drawList();
                        }
                    }),
                );
                more.disabled = this.listing;
            }
        }
        if (history !== undefined && history !== 'pending' && 'error' in history) {
            // WORKTREE or STAGED is listed, and the revisions could not be.
            this.listFooter.appendChild(el('p', 'error', history.error));
        }
        if (this.moreError !== undefined) {
            this.listFooter.appendChild(el('p', 'error', this.moreError));
        }
        if (this.status !== undefined && this.status !== 'pending' && 'error' in this.status) {
            // No repository, say: why there is no WORKTREE or STAGED row.
            this.listFooter.appendChild(el('p', 'placeholder revisions-status-error', this.status.error));
        }
    }

    private drawHeader(): void {
        empty(this.header);
        const row = this.selected;
        this.header.hidden = row === undefined;
        if (row === undefined) {
            return;
        }
        const status = this.statusData();
        if (isState(row)) {
            this.header.appendChild(el('span', 'revisions-sha', row));
            this.header.appendChild(
                el(
                    'span',
                    'revisions-summary',
                    row === WORKTREE
                        ? `Not staged${status ? `: ${stateSummary(status, row)}` : ''}`
                        : `Staged${status ? `: ${stateSummary(status, row)}` : ''}`,
                ),
            );
            if (row === WORKTREE) {
                const stage = this.header.appendChild(
                    button(
                        this.staging ? 'Staging…' : 'Stage all',
                        'small revisions-stage',
                        `Stage every change of ${thisSubject(this.subject)} that is not staged yet (pc ops rev stage)`,
                        () => this.stage(),
                    ),
                );
                stage.disabled = this.staging;
            } else {
                const open = this.header.appendChild(
                    button(
                        'New revision…',
                        'small revisions-new',
                        'Commit what is staged as a new revision (pc ops rev new)',
                        () => {
                            if (this.form === undefined && status !== undefined) {
                                this.form = {
                                    message: draftMessage(status),
                                    skipChecks: false,
                                    includeOthers: false,
                                    yes: false,
                                    sending: false,
                                };
                                this.draw();
                            }
                        },
                    ),
                );
                open.disabled = this.form !== undefined || status === undefined;
            }
        } else {
            const entry = this.entryOf(row) as RevisionEntry;
            this.header.appendChild(el('span', 'revisions-sha', entry.short));
            if (entry.summary) {
                this.header.appendChild(el('span', 'revisions-summary', entry.summary));
            }
            const by = [entry.author, when(entry.time)].filter(Boolean).join(', ');
            if (by) {
                this.header.appendChild(el('span', 'render-label revisions-by', by));
            }
        }
        this.header.appendChild(this.modeToggle(row));
    }

    /** "This change" and "Since then": what the row is compared with. */
    private modeToggle(row: RowId): HTMLElement {
        const toggle = el('span', 'ops-toggle revisions-mode');
        toggle.setAttribute('role', 'group');
        toggle.setAttribute('aria-label', 'Compare');
        const choices: { mode: CompareMode; label: string; title: string }[] = [
            {
                mode: 'change',
                label: 'This change',
                title:
                    row === WORKTREE
                        ? 'What is on disk against what is staged'
                        : row === STAGED
                          ? 'What is staged against HEAD'
                          : 'This revision against the one before it',
            },
            {
                mode: 'since',
                label: 'Since then',
                title:
                    row === WORKTREE
                        ? 'Nothing comes after the files on disk'
                        : `${row === STAGED ? 'What is staged' : 'This revision'} against the files on disk`,
            },
        ];
        for (const choice of choices) {
            const on = this.mode === choice.mode;
            const node = toggle.appendChild(
                button(choice.label, `small ${on ? '' : 'secondary '}revisions-mode-${choice.mode}`, choice.title, () =>
                    this.compare(choice.mode),
                ),
            );
            node.setAttribute('aria-pressed', String(on));
            node.disabled = comparedStates(row, choice.mode) === undefined;
        }
        return toggle;
    }

    private drawComparison(): void {
        empty(this.content);
        if (this.note !== undefined) {
            this.content.appendChild(
                el('p', `requirements-note revisions-note${this.note.error ? ' error' : ''}`, this.note.text),
            );
        }
        const row = this.selected;
        if (row === undefined) {
            this.content.appendChild(this.emptyPage());
            return;
        }
        const status = this.statusData();
        if (row === WORKTREE && status?.advice) {
            this.content.appendChild(this.advice(status.advice));
        }
        if (row === STAGED && status !== undefined) {
            for (const warning of stagedWarnings(status)) {
                this.content.appendChild(el('p', 'requirements-note revisions-warning', warning));
            }
            if (this.form !== undefined) {
                this.content.appendChild(this.formOf(this.form, status));
            }
        }
        const states = comparedStates(row, this.mode);
        const answer = states === undefined ? undefined : this.compared.get(`${states.from}..${states.to}`);
        if (answer === undefined || answer === 'pending') {
            this.content.appendChild(
                placeholder(
                    `Comparing ${this.labelOf(row)} with ${this.mode === 'change' ? 'what came before it' : 'the files on disk'}…`,
                ),
            );
            return;
        }
        if ('error' in answer) {
            this.content.appendChild(el('p', 'error', answer.error));
            return;
        }
        this.content.appendChild(renderComparison(answer.data, this.callbacks, answer.first === true));
    }

    /** What the page says where no row is selected: still asking, nothing to list, or why not. */
    private emptyPage(): HTMLElement {
        const history = this.history;
        if (history === undefined || history === 'pending' || this.status === 'pending') {
            return placeholder(`Asking PartCAD for the revisions of ${thisSubject(this.subject)}…`);
        }
        if ('error' in history) {
            return el('p', 'error', history.error);
        }
        if (!history.data.published) {
            return placeholder(NOT_PUBLISHED);
        }
        return placeholder(
            `No revision has changed ${thisSubject(this.subject)}, and nothing of it is changed on disk.`,
        );
    }

    /** The sentence to hand an agent that would stage the changes instead, and a button that copies it. */
    private advice(text: string): HTMLElement {
        const box = el('div', 'requirements-form revisions-advice');
        box.appendChild(el('p', 'revisions-advice-text', text));
        box.appendChild(
            button(
                'Copy for your agent',
                'small secondary revisions-copy',
                'Copy this sentence, to paste into your agent',
                () => this.callbacks.copy(text),
            ),
        );
        return box;
    }

    private formOf(form: RevisionForm, status: RevStatusData): HTMLElement {
        const box = el('div', 'requirements-form revisions-form');
        box.appendChild(el('h3', undefined, 'New revision'));
        const message = box.appendChild(el('textarea', 'requirements-input revisions-message')) as HTMLTextAreaElement;
        message.value = form.message;
        message.rows = 3;
        message.spellcheck = true;
        message.disabled = form.sending;
        message.setAttribute('aria-label', 'Message');
        message.addEventListener('input', () => (form.message = message.value));
        box.appendChild(
            this.checkbox(
                'Skip lint and tests',
                'revisions-skip-checks',
                form.skipChecks,
                form.sending,
                (on) => (form.skipChecks = on),
            ),
        );
        box.appendChild(
            el(
                'p',
                'requirements-note',
                `Author: your git user.name and user.email, as git says them on this machine` +
                    `${status.branch ? `. On ${status.branch}` : status.detached ? '. On no branch: HEAD is detached' : ''}.`,
            ),
        );
        if (form.refused !== undefined) {
            box.appendChild(this.refusalOf(form, form.refused.message, form.refused.refusal));
        }
        if (form.error !== undefined) {
            box.appendChild(el('p', 'requirements-note error', form.error));
        }
        const buttons = box.appendChild(el('div', 'requirements-buttons'));
        const make = buttons.appendChild(
            button(
                form.sending ? (form.skipChecks ? 'Making it…' : 'Running lint and tests…') : 'Make revision',
                'revisions-make',
                form.skipChecks ? 'Commit what is staged' : 'Lint what is staged and test what changed, then commit it',
                () => this.makeRevision(),
            ),
        );
        make.disabled = form.sending;
        const cancel = buttons.appendChild(
            button('Cancel', 'secondary', 'Make no revision', () => {
                this.form = undefined;
                this.draw();
            }),
        );
        cancel.disabled = form.sending;
        return box;
    }

    /** Why the daemon would not make the revision, and what the user can agree to before sending it again. */
    private refusalOf(form: RevisionForm, message: string, refusal: RevRefusal): HTMLElement {
        const box = el('div', 'revisions-refusal');
        box.dataset.code = String(refusal.code);
        box.appendChild(el('p', 'requirements-note error', message));
        if (refusal.code === 'others-staged') {
            box.appendChild(
                this.checkbox(
                    'Include them in this revision',
                    'revisions-include-others',
                    form.includeOthers,
                    form.sending,
                    (on) => (form.includeOthers = on),
                ),
            );
        } else if (refusal.code === 'warnings') {
            box.appendChild(
                this.checkbox('Make it anyway', 'revisions-yes', form.yes, form.sending, (on) => (form.yes = on)),
            );
        } else if (refusal.code === 'checks-failed') {
            const checks = refusal.status?.checks ?? [];
            if (checks.length > 0) {
                const list = box.appendChild(el('ul', 'revisions-checks'));
                for (const check of checks) {
                    const item = list.appendChild(el('li', check.passed ? 'passed' : 'failed'));
                    const mark = item.appendChild(el('span', 'revisions-check-mark', check.passed ? '✓' : '✗'));
                    mark.setAttribute('aria-label', check.passed ? 'passed' : 'failed');
                    item.appendChild(el('span', undefined, ` ${check.summary}`));
                }
            }
            box.appendChild(
                el('p', 'requirements-note', "Fix what failed, or tick 'Skip lint and tests' to make it anyway."),
            );
        } else if (refusal.code === 'index-changed') {
            box.appendChild(
                el(
                    'p',
                    'requirements-note',
                    'What is staged has been read again: look at it, and make the revision again.',
                ),
            );
        }
        return box;
    }

    private checkbox(
        label: string,
        className: string,
        checked: boolean,
        disabled: boolean,
        onChange: (on: boolean) => void,
    ): HTMLElement {
        const row = el('label', `ops-check ${className}`);
        const box = row.appendChild(el('input')) as HTMLInputElement;
        box.type = 'checkbox';
        box.checked = checked;
        box.disabled = disabled;
        box.addEventListener('change', () => onChange(box.checked));
        row.appendChild(el('span', undefined, ` ${label}`));
        return row;
    }

    /** The title of a folded view, for the row it is about. */
    private detailLabel(detail: RevisionsDetail, row: RowId): string {
        if (detail === 'deps') {
            return row === WORKTREE ? 'Dependencies' : 'Dependencies at it';
        }
        if (detail === 'usedBy') {
            return isState(row) ? 'Used By' : 'Used By at it';
        }
        return isState(row) ? 'Impact of this change' : 'Impact since it';
    }

    /**
     * The folded views: a strip of their titles, and under it the one that is
     * open - the Simulation tab's strip, as it is drawn there. A title opens its
     * view, which asks for what it shows the first time, and closes it again.
     */
    private drawDetails(): void {
        // The title with the focus, by the view it is of, to be given it again
        // once the strip is drawn anew: drawing replaces the buttons, and a
        // keyboard user who opened a view must not be dropped onto the page.
        const active = typeof document === 'undefined' ? null : (document.activeElement as HTMLElement | null);
        const focused = active !== null && this.details.contains?.(active) ? active.dataset?.detail : undefined;
        empty(this.details);
        const row = this.selected;
        if (row === undefined) {
            return;
        }
        const strip = el('div', 'tabs sub-tabs simulation-detail-tabs revisions-detail-tabs');
        strip.setAttribute('role', 'tablist');
        for (const detail of DETAILS) {
            const open = detail === this.detail;
            const label = this.detailLabel(detail, row);
            const title = el('button', `tab simulation-detail-tab${open ? ' current' : ''}`, label);
            title.type = 'button';
            title.dataset.detail = detail;
            title.setAttribute('role', 'tab');
            title.setAttribute('aria-selected', String(open));
            title.setAttribute('aria-expanded', String(open));
            title.title = open ? `Fold ${label} away` : `Show ${label}`;
            if (open) {
                const chevron = el('span', 'simulation-detail-chevron', '▾');
                chevron.setAttribute('aria-hidden', 'true');
                title.appendChild(chevron);
            }
            title.addEventListener('click', () => this.toggleDetail(detail));
            strip.appendChild(title);
        }
        this.details.appendChild(strip);
        if (focused !== undefined) {
            Array.from(strip.children as HTMLCollectionOf<HTMLElement>)
                .find((title) => title.dataset.detail === focused)
                ?.focus?.();
        }
        if (this.detail === undefined) {
            return;
        }
        const view = el('div', 'simulation-detail revisions-detail');
        view.setAttribute('role', 'tabpanel');
        view.dataset.detail = this.detail;
        const at = this.labelOf(row);
        const what = thisSubject(this.subject);
        const answer = this.folded.get(`${this.detail}:${row}`);
        if (answer === undefined || answer === 'pending') {
            view.appendChild(
                placeholder(
                    this.detail === 'deps'
                        ? `Asking PartCAD what ${what} depended on at ${at}…`
                        : this.detail === 'usedBy'
                          ? `Asking PartCAD what uses the package${isState(row) ? '' : ` at ${at}`}…`
                          : `Asking PartCAD what ${isState(row) ? 'this change' : `changing it since ${at}`} reaches…`,
                ),
            );
        } else if ('error' in answer) {
            view.appendChild(el('p', 'error', answer.error));
        } else if (this.detail === 'deps') {
            renderDependencies(view, answer.data as DepsData, this.callbacks, `At ${at}, ${what}`);
        } else if (this.detail === 'usedBy') {
            renderUsedBy(
                view,
                (answer.data as UsedByData | undefined) ?? { objects: [] },
                this.callbacks,
                isState(row) ? 'the package' : `the package at ${at}`,
            );
        } else {
            renderImpact(view, answer.data as ImpactData, this.callbacks, this.subject);
        }
        this.details.appendChild(view);
    }
}

/** What a revision's row says when hovered: its summary, who made it and when. */
function describe(entry: RevisionEntry): string {
    return [entry.summary, [entry.author, when(entry.time)].filter(Boolean).join(', ')].filter(Boolean).join(' - ');
}

/** What the STAGED row warns of before a revision is made: what the daemon would ask the user to agree to. */
function stagedWarnings(status: RevStatusData): string[] {
    const found: string[] = [];
    if (status.state) {
        found.push(`A ${status.state} is in progress: finish it before making a revision.`);
    }
    if ((status.conflicted ?? []).length > 0) {
        found.push(`Conflicts in ${status.conflicted.join(', ')}: resolve them before making a revision.`);
    }
    if ((status.partial ?? []).length > 0) {
        found.push(`Changed again since staged: ${status.partial.map((name) => `:${name}`).join(', ')}.`);
    }
    const others = [
        ...(status.others_staged ?? []).map((row) => row.object),
        ...(status.elsewhere ?? [])
            .filter((entry) => entry.staged > 0)
            .map((entry) => entry.package ?? (entry.directory || 'files in no package')),
    ];
    if (others.length > 0) {
        found.push(`Also staged, and would be in this revision: ${others.join(', ')}.`);
    }
    return found;
}

/**
 * The first commit of a repository as what it added: its side, asked as itself,
 * drawn on the right with nothing on the left.
 */
export function asAdded(data: DiffData): DiffData {
    return {
        ...data,
        left: { label: '', missing: true },
        same: false,
        rows: (data.rows ?? []).map((row) => {
            const text = row.right ?? row.left;
            const line = row.rightLine ?? row.leftLine;
            return { tag: 'insert', left: null, right: text, leftLine: null, rightLine: line } as CompareRow;
        }),
    };
}

/** What changed in a package, object by object and file by file, over the comparison of its 'partcad.yaml'. */
function changesOf(changes: PackageChanges, callbacks: Pick<OpsCallbacks, 'showObject'> | undefined): HTMLElement {
    const host = el('div', 'revisions-changes');
    const objects = changes.objects ?? [];
    const files = changes.files ?? [];
    if (objects.length === 0 && files.length === 0) {
        host.appendChild(placeholder('No object and no file of the package changed.'));
        return host;
    }
    if (objects.length > 0) {
        const { table, body } = grid(['Object', 'Kind', 'How'], 'revisions-changed-objects');
        for (const row of objects) {
            const tr = body.appendChild(el('tr'));
            const package_ =
                row.object.slice(0, Math.max(0, row.object.length - row.name.length - 1)) || changes.package;
            if (callbacks !== undefined && !(row.how ?? []).includes('removed')) {
                tr.appendChild(
                    objectCell({ object: row.object, package: package_, name: row.name, kind: row.kind }, callbacks),
                );
            } else {
                tr.appendChild(el('td', 'name', row.object));
            }
            tr.appendChild(el('td', undefined, row.kind));
            tr.appendChild(el('td')).appendChild(chips(row.how));
        }
        host.appendChild(table);
    }
    if (files.length > 0) {
        const { table, body } = grid(['File', 'How'], 'revisions-changed-files');
        for (const file of files) {
            const tr = body.appendChild(el('tr'));
            tr.appendChild(el('td', 'name', file.path));
            tr.appendChild(el('td')).appendChild(chips([file.how]));
        }
        host.appendChild(table);
    }
    return host;
}

/**
 * Two states side by side: the earlier on the left and the later on the right,
 * a line of each per row with its number, a line that changed, went or came
 * coloured as the editor's diff colours it - with, for a package, what changed
 * in it object by object and file by file over its 'partcad.yaml'.
 */
export function renderComparison(
    data: DiffData,
    callbacks?: Pick<OpsCallbacks, 'showObject'>,
    first = false,
): HTMLElement {
    const page = el('div', 'revisions-compare');
    const left = data.left?.label ?? data.from;
    const right = data.right?.label ?? data.to;
    let note: string | undefined;
    if (first) {
        note = `The first revision of the repository: all of this came with ${right}.`;
    } else if (data.left.missing && data.right.missing) {
        note = `There at neither ${left} nor ${right}.`;
    } else if (data.left.missing) {
        note = `Not there at ${left}: all of it is new at ${right}.`;
    } else if (data.right.missing) {
        note = `Not there any more at ${right}: this is what it was at ${left}.`;
    } else if (data.same) {
        note = `No change between ${left} and ${right}.`;
    }
    if (note !== undefined) {
        page.appendChild(placeholder(note));
    }
    if (data.changes !== undefined) {
        page.appendChild(changesOf(data.changes, callbacks));
    }
    const table = el('table', 'revisions-diff');
    const colgroup = table.appendChild(el('colgroup'));
    for (const className of ['diff-number', 'diff-text', 'diff-number', 'diff-text']) {
        colgroup.appendChild(el('col', className));
    }
    const head = table.appendChild(el('thead')).appendChild(el('tr'));
    const leftHead = head.appendChild(el('th', 'diff-side', first ? '' : left));
    leftHead.colSpan = 2;
    leftHead.title = first ? 'Nothing: the repository had no revision before it' : data.from;
    const rightHead = head.appendChild(el('th', 'diff-side', right));
    rightHead.colSpan = 2;
    rightHead.title = data.to;
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
