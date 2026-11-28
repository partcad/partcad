//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What a change reaches: the Operations group's Impact tab, and the "Impact"
// view under a revision on the Revisions tab ('ops.impact').
//
// A change is what happened between two states of the repository the package
// is in, which the tab's selector names the way a person thinks of them: all
// that is not committed (HEAD to the files on disk), what is staged (HEAD to
// the index), what is not (the index to the files on disk), or everything
// since a revision. The daemon compares every loaded package of that
// repository at both and answers with what each object the change reaches now
// risks, worst first - breaking, changed, to verify, for information - which is
// drawn as it comes (see 'partcad/impact.py'): what it affects, for an object
// what it is affected by, the dependencies whose declaration changed, and the
// packages that pin this one by commit and so are not affected until they
// update.
//
// Measure and Test ask again with what costs more: how much each changed shape
// moved, and the tests of everything reached, both of which build shapes. Like
// Used By, it looks only at what is loaded, and can load the workspace first.
//

import { el, empty, placeholder } from './dom';
import { IMPACT_SEVERITIES, ImpactData, ImpactFinding, ImpactRow, STAGED, WORKTREE } from './messages';
import {
    Answer,
    OpsCallbacks,
    OpsSubject,
    button,
    capitalized,
    chips,
    grid,
    isPackage,
    loadedNote,
    objectCell,
    shortRevision,
    thisSubject,
} from './operations';
import { dependentsTable } from './usedBy';

/** Which change the Impact tab is about. */
export type ImpactRange = 'all' | 'staged' | 'unstaged' | 'since';

/** The selector's choices, in the order it offers them. */
export const IMPACT_RANGES: { id: ImpactRange; label: string; title: string }[] = [
    { id: 'all', label: 'All uncommitted', title: 'Everything not committed yet: HEAD to the files on disk' },
    { id: 'staged', label: 'Staged', title: 'What is staged: HEAD to the index' },
    { id: 'unstaged', label: 'Not staged', title: 'What is not staged: the index to the files on disk' },
    { id: 'since', label: 'Since a revision', title: 'Everything since a revision: it to the files on disk' },
];

/** The two states a choice of the selector compares; undefined for "since" with no revision typed yet. */
export function rangeStates(range: ImpactRange, revision = ''): { from: string; to: string } | undefined {
    switch (range) {
        case 'staged':
            return { from: 'HEAD', to: STAGED };
        case 'unstaged':
            return { from: STAGED, to: WORKTREE };
        case 'since':
            return revision.trim() ? { from: revision.trim(), to: WORKTREE } : undefined;
        default:
            return { from: 'HEAD', to: WORKTREE };
    }
}

/** How each severity is said in the summary and on a finding. */
const SEVERITY_WORDS: Record<string, string> = {
    breaking: 'breaking',
    changed: 'changed',
    verify: 'to verify',
    info: 'for information',
};

/** The counts of findings by severity, worst first, as one line. */
export function summaryLine(data: ImpactData): HTMLElement {
    const line = el('p', 'impact-summary');
    const summary = data.summary ?? {};
    for (const severity of IMPACT_SEVERITIES) {
        const count = summary[severity] ?? 0;
        const badge = line.appendChild(
            el(
                'span',
                `ops-severity ops-severity-${severity}${count === 0 ? ' none' : ''}`,
                `${count} ${SEVERITY_WORDS[severity]}`,
            ),
        );
        badge.dataset.severity = severity;
    }
    line.appendChild(
        el(
            'span',
            'placeholder impact-range',
            `${shortRevision(data.from)} → ${shortRevision(data.to)}: ` +
                `${data.changed?.length ?? 0} object${data.changed?.length === 1 ? '' : 's'} of ${data.package} changed`,
        ),
    );
    return line;
}

/** A number of 'pc compare''s, signed, with its unit: '+12.5 mm^3 (+3.1%)'. */
function amount(entry: unknown): string | undefined {
    if (typeof entry !== 'object' || entry === null) {
        return undefined;
    }
    const { difference, percent, unit } = entry as {
        difference?: number | null;
        percent?: number | null;
        unit?: string;
    };
    if (typeof difference !== 'number') {
        return undefined;
    }
    const signed = (value: number, digits: number) => `${value > 0 ? '+' : ''}${Number(value.toFixed(digits))}`;
    const share = typeof percent === 'number' ? ` (${signed(percent, 1)}%)` : '';
    return `${signed(difference, 3)}${unit ? ` ${unit}` : ''}${share}`;
}

/** What 'measure' found, in words: how much the volume and the mass moved, or why it could not be measured. */
export function describeMeasured(measured: Record<string, unknown>): string {
    if (typeof measured.error === 'string') {
        return `not measured: ${measured.error}`;
    }
    const parts: string[] = [];
    for (const key of ['volume', 'mass']) {
        const said = amount(measured[key]);
        if (said !== undefined) {
            parts.push(`${key} ${said}`);
        }
    }
    return parts.length > 0 ? `measured: ${parts.join(', ')}` : 'measured: nothing to compare';
}

/** What 'test' found, in words: passed, which failed, or why the tests were not run. */
export function describeTested(tested: Record<string, unknown>): string {
    if (typeof tested.error === 'string') {
        return `not tested: ${tested.error}`;
    }
    if (typeof tested.skipped === 'string') {
        return tested.skipped;
    }
    const failed = Array.isArray(tested.failed) ? (tested.failed as string[]) : [];
    if (tested.passed === true) {
        return 'tested: passed';
    }
    return failed.length > 0 ? `tested: failed ${failed.join(', ')}` : 'tested: failed';
}

/** One finding: its severity, what it says, and what measuring and testing added. */
function findingNode(finding: ImpactFinding): HTMLElement {
    const node = el('div', `impact-finding impact-${finding.severity}`);
    const badge = node.appendChild(
        el(
            'span',
            `ops-severity ops-severity-${finding.severity}`,
            SEVERITY_WORDS[finding.severity] ?? finding.severity,
        ),
    );
    badge.title = `Found by the ${finding.analyzer} analyzer`;
    node.appendChild(el('span', 'impact-finding-text', finding.summary));
    if (finding.measured) {
        node.appendChild(el('div', 'impact-measured placeholder', describeMeasured(finding.measured)));
    }
    if (finding.tested) {
        node.appendChild(el('div', 'impact-tested placeholder', describeTested(finding.tested)));
    }
    if (finding.users && finding.users.length > 0) {
        node.title = `Used by ${finding.users.join(', ')}`;
    }
    return node;
}

/** How an object was reached: changed itself, and how; or through the objects it uses that did. */
function reachedNode(row: ImpactRow): HTMLElement {
    if (row.reached === 'via') {
        const node = el('span', 'impact-via', `via ${(row.via ?? []).join(' → ')}`);
        node.title = 'It uses what changed, through these';
        return node;
    }
    const node = el('span', 'impact-changed');
    node.appendChild(el('span', undefined, 'changed '));
    node.appendChild(chips(row.how));
    return node;
}

/** The objects a change reaches, each with how and what it now risks. */
export function affectsTable(rows: ImpactRow[], callbacks: Pick<OpsCallbacks, 'showObject'>): HTMLElement {
    const { table, body } = grid(['Object', 'Kind', 'Reached', 'Findings'], 'impact-affects');
    for (const row of rows) {
        const tr = body.appendChild(el('tr', `impact-row impact-${row.reached}`));
        tr.appendChild(objectCell(row, callbacks));
        tr.appendChild(el('td', undefined, row.kind));
        tr.appendChild(el('td')).appendChild(reachedNode(row));
        const findings = tr.appendChild(el('td', 'impact-findings'));
        if ((row.findings ?? []).length === 0) {
            findings.appendChild(el('span', 'placeholder', 'nothing found'));
        }
        for (const finding of row.findings ?? []) {
            findings.appendChild(findingNode(finding));
        }
    }
    return table;
}

/**
 * What a change reaches, into 'host': the summary, what it affects and - for
 * an object - what it is affected by, and what became of the pins. The tab
 * draws this under its selector; the Revisions tab's "Impact" view as it is.
 */
export function renderImpact(
    host: HTMLElement,
    data: ImpactData,
    callbacks: Pick<OpsCallbacks, 'showObject' | 'openPackage'>,
    subject: OpsSubject | undefined,
): void {
    empty(host);
    host.appendChild(summaryLine(data));
    const affects = data.affects ?? [];
    host.appendChild(
        affects.length > 0
            ? affectsTable(affects, callbacks)
            : placeholder(
                  isPackage(subject)
                      ? `Nothing of ${data.package} changed between ${shortRevision(data.from)} and ${shortRevision(data.to)}.`
                      : `${capitalized(thisSubject(subject))} did not change between ${shortRevision(data.from)} and ${shortRevision(data.to)}.`,
              ),
    );
    if (!isPackage(subject)) {
        const affectedBy = data.affected_by ?? [];
        host.appendChild(el('p', 'ops-subtitle', 'Affected by'));
        if (affectedBy.length === 0) {
            host.appendChild(placeholder(`Nothing ${thisSubject(subject)} uses changed.`));
        } else {
            const { table, body } = grid(['Object', 'Kind', 'How', 'Through'], 'impact-affected-by');
            for (const row of affectedBy) {
                const tr = body.appendChild(el('tr'));
                tr.appendChild(
                    objectCell(
                        { object: row.object, package: row.package ?? data.package, name: row.name, kind: row.kind },
                        callbacks,
                    ),
                );
                tr.appendChild(el('td', undefined, row.kind));
                tr.appendChild(el('td')).appendChild(chips(row.how));
                tr.appendChild(el('td', 'impact-via', (row.path ?? []).join(' → ')));
            }
            host.appendChild(table);
        }
    }
    const pins = data.pins ?? [];
    if (pins.length > 0) {
        host.appendChild(el('p', 'ops-subtitle', 'Dependencies whose declaration changed'));
        const { table, body } = grid(['Dependency', 'How', 'From', 'To'], 'impact-pins');
        for (const pin of pins) {
            const tr = body.appendChild(el('tr'));
            tr.appendChild(el('td', 'name', pin.name));
            tr.appendChild(el('td', undefined, pin.how));
            tr.appendChild(el('td', 'name', shortRevision(pin.from)));
            tr.appendChild(el('td', 'name', shortRevision(pin.to)));
        }
        host.appendChild(table);
    }
    const pinned = data.pinned ?? [];
    if (pinned.length > 0) {
        host.appendChild(el('p', 'ops-subtitle', 'Pinned by commit: not affected until they update'));
        host.appendChild(dependentsTable(pinned, callbacks));
    }
}

/** The Impact tab: what a change to the object on screen, or to the package, reaches. */
export class ImpactView {
    private subject: OpsSubject | undefined;
    private answer: Answer<ImpactData> | undefined;
    private range: ImpactRange = 'all';
    /** What 'measure', 'test' and 'load' were asked with for the change on screen; a new change starts without the first two. */
    private readonly flags = { measure: false, test: false, load: false };
    /** The change 'measure' and 'test' were asked of, '<from>..<to>': a revision typed into the field is another. */
    private flagged: string | undefined;
    /** The question asked last: an answer to any other is for a change no longer chosen. */
    private asking = 0;
    /** Why the workspace could not be loaded, said under the answer from before, which stands. */
    private loadError: string | undefined;
    private readonly toolbar: HTMLElement;
    private readonly select: HTMLSelectElement;
    private readonly revision: HTMLInputElement;
    private readonly measure: HTMLButtonElement;
    private readonly test: HTMLButtonElement;
    private readonly content: HTMLElement;

    constructor(
        private readonly pane: HTMLElement,
        private readonly callbacks: OpsCallbacks,
    ) {
        this.pane.classList.add('impact');
        // Made once and kept, as every toolbar with a field is: an answer
        // arriving must not take the field from somebody typing a revision.
        this.toolbar = el('div', 'render-header impact-toolbar');
        const label = this.toolbar.appendChild(el('label', 'render-label', 'Changes'));
        this.select = el('select', 'render-select impact-range-select') as HTMLSelectElement;
        this.select.setAttribute('aria-label', 'Which changes');
        for (const range of IMPACT_RANGES) {
            const option = this.select.appendChild(el('option', undefined, range.label)) as HTMLOptionElement;
            option.value = range.id;
            option.title = range.title;
        }
        this.select.value = this.range;
        this.select.addEventListener('change', () => this.choose(this.select.value as ImpactRange));
        label.appendChild(this.select);
        this.revision = el('input', 'requirements-input impact-revision') as HTMLInputElement;
        this.revision.type = 'text';
        this.revision.spellcheck = false;
        this.revision.placeholder = 'a revision: v1.2, a commit id, HEAD~3';
        this.revision.setAttribute('aria-label', 'Since which revision');
        this.revision.hidden = true;
        // Asked on Enter and when the field is left, never while it is typed.
        this.revision.addEventListener('change', () => this.ask());
        this.revision.addEventListener('keydown', (event: KeyboardEvent) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                this.ask();
            }
        });
        this.toolbar.appendChild(this.revision);
        this.measure = this.toolbar.appendChild(
            button(
                'Measure',
                'small secondary impact-measure',
                'Ask again, measuring how much each changed part and assembly moved (builds both states)',
                () => this.ask({ measure: true }),
            ),
        );
        this.test = this.toolbar.appendChild(
            button(
                'Test',
                'small secondary impact-test',
                'Ask again, running the tests of every object the change reaches',
                () => this.ask({ test: true }),
            ),
        );
        this.content = el('div', 'impact-content');
        this.pane.append(this.toolbar, this.content);
        this.setBusy('Select this tab to see what a change reaches.');
    }

    /** Forget the last object, and say 'text' where the page goes. */
    public setBusy(text: string): void {
        this.subject = undefined;
        this.answer = undefined;
        this.flags.measure = false;
        this.flags.test = false;
        this.flags.load = false;
        this.flagged = undefined;
        this.loadError = undefined;
        this.asking += 1;
        this.toolbar.hidden = true;
        empty(this.content);
        this.content.appendChild(placeholder(text));
    }

    /** The tab has been opened on 'subject': ask what the change chosen reaches. */
    public start(subject: OpsSubject): void {
        this.subject = subject;
        this.toolbar.hidden = false;
        this.ask();
    }

    /** The choice of the selector on screen, for the tests. */
    public get current(): ImpactRange {
        return this.range;
    }

    /** Another change chosen: measuring and testing are asked of it afresh. */
    public choose(range: ImpactRange): void {
        this.range = range;
        this.select.value = range;
        this.revision.hidden = range !== 'since';
        this.flags.measure = false;
        this.flags.test = false;
        this.ask();
    }

    /**
     * Ask what the change chosen reaches, measuring or testing it too where
     * 'add' says, and where it was already - and loading the workspace first,
     * once 'add' has said so.
     */
    private ask(add: { measure?: boolean; test?: boolean; load?: boolean } = {}): void {
        const subject = this.subject;
        if (subject === undefined) {
            return;
        }
        const before = this.answer;
        this.loadError = undefined;
        // Whatever is in flight is for the change chosen before, even when this
        // asks nothing: "Since a revision" with no revision typed yet.
        const mine = (this.asking += 1);
        const states = rangeStates(this.range, this.revision.value);
        this.measure.disabled = states === undefined;
        this.test.disabled = states === undefined;
        if (states === undefined) {
            this.answer = undefined;
            empty(this.content);
            this.content.appendChild(
                placeholder('Type the revision to compare the files on disk with, and press Enter.'),
            );
            this.revision.focus?.();
            return;
        }
        const range = `${states.from}..${states.to}`;
        if (range !== this.flagged) {
            // Another change - a revision typed into the field never passes
            // through 'choose' - is measured and tested afresh, if asked.
            this.flags.measure = false;
            this.flags.test = false;
        }
        this.flagged = range;
        this.flags.measure = this.flags.measure || add.measure === true;
        this.flags.test = this.flags.test || add.test === true;
        this.flags.load = this.flags.load || add.load === true;
        this.answer = 'pending';
        this.draw();
        this.callbacks.ask(
            {
                method: 'ops.impact',
                params: {
                    ...states,
                    load: this.flags.load || undefined,
                    measure: this.flags.measure || undefined,
                    test: this.flags.test || undefined,
                },
            },
            (data, error) => {
                if (this.subject !== subject || this.asking !== mine) {
                    return;
                }
                if (
                    error !== undefined &&
                    add.load &&
                    before !== undefined &&
                    before !== 'pending' &&
                    'data' in before
                ) {
                    // The workspace could not be loaded: what was found among
                    // what is loaded still stands, and Load workspace is there
                    // to try again.
                    this.flags.load = false;
                    this.answer = before;
                    this.loadError = error;
                } else {
                    this.answer =
                        error !== undefined
                            ? { error }
                            : data
                              ? { data: data as ImpactData }
                              : { error: 'PartCAD had nothing to say about this change.' };
                }
                this.draw();
            },
        );
    }

    private draw(): void {
        empty(this.content);
        const answer = this.answer;
        if (answer === undefined || answer === 'pending') {
            const doing = [
                this.flags.load ? 'loading the workspace' : '',
                this.flags.measure ? 'measuring' : '',
                this.flags.test ? 'testing' : '',
            ].filter(Boolean);
            this.content.appendChild(
                placeholder(
                    `Asking PartCAD what this change reaches${doing.length > 0 ? `, ${doing.join(' and ')}` : ''}…`,
                ),
            );
            return;
        }
        if ('error' in answer) {
            this.content.appendChild(el('p', 'error', answer.error));
            return;
        }
        const body = this.content.appendChild(el('div', 'impact-body'));
        renderImpact(body, answer.data, this.callbacks, this.subject);
        this.content.appendChild(loadedNote(this.flags.load, () => this.ask({ load: true })));
        if (this.loadError !== undefined) {
            this.content.appendChild(el('p', 'error impact-load-error', this.loadError));
        }
    }
}
