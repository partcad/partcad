//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Qualification tabs drawn from 'qual.report': Basic, Topology and Other.
//
// What 'pc qual test' says of the object on screen, test by test, for one
// subtype of qualification each. A list on the left - every test of the
// subtype, in the order they run, with a mark for how each came out - and the
// test selected in the middle: what it found this time, and what it is, when it
// applies and what to do when it fails. What else is shown is what the subtype
// produces:
//
// - Basic: nothing else. Its findings are words.
// - Topology: where the finding is. A failure leaves an object behind - the two
//   parts that overlap and what they share, the part and the faces nothing
//   tolerances - and "Show" opens it in the 3D view with the finding in a colour
//   of its own and the rest faded (see 'TopologyFocus').
// - Other: the report the plugin's tool wrote, as a table.
//
// Nothing here decides anything. The daemon's 'qual.report' runs the tests 'pc
// qual test --<subtype> <object>' runs, through the same cache, and answers with
// each verdict, what each test said, and its entry in 'partcad.qual.catalog' -
// the same text the documentation lists the tests with. This file draws the
// answer.
//
// Asked for twice, in a row (see 'viewer.ts'): once without running anything,
// which is a read of declarations and lists every test with the ones that do
// not apply saying why, and once running them, which takes as long as the
// slowest test. The list is on screen, every other mark pending, for as long as
// that takes.
//

import { el, empty, placeholder } from './dom';
import {
    TestArtifact,
    TestData,
    TestDoc,
    TestFinding,
    TestReport,
    TestResult,
    TestStatus,
    TopologyFeature,
    TopologyFocus,
} from './messages';

export interface TestCallbacks {
    /** "Run again" was pressed: the checks have to be asked for once more. */
    onRun: () => void;
    /**
     * An artifact's button was pressed: show that object in the panel - with
     * the check that left it, whose verdict and words go on being shown with it
     * (see 'findingOf').
     */
    onShow: (artifact: TestArtifact, result: TestResult) => void;
}

/** Which subtype of qualification a view shows, and what it says where it has nothing to show. */
export interface TestOptions {
    /** 'basic', 'topology' or 'other', as 'pc qual test' takes it ('--basic'). */
    subtype: string;
    /** What the tab says when the object has no test of its subtype at all. */
    none?: string;
}

/** How a check is marked: its verdict, or 'pending' while it is running, or 'unknown' when it never came back. */
export type TestMark = TestStatus | 'pending' | 'unknown';

/** What a check's mark is, given whether the checks are being run. */
export function markOf(result: TestResult, running: boolean): TestMark {
    if (result.status !== null && result.status !== undefined) {
        return result.status;
    }
    return running ? 'pending' : 'unknown';
}

export const MARK_TEXT: Record<TestMark, string> = {
    passed: '✓',
    failed: '✗',
    warned: '!',
    skipped: '↷',
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'not-applicable': '–',
    pending: '…',
    unknown: '?',
};

export const MARK_TITLE: Record<TestMark, string> = {
    passed: 'Passed',
    failed: 'Failed',
    warned: 'Passed, with a finding',
    skipped: 'Skipped: it could not be asked on this machine',
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'not-applicable': 'Not applicable: nothing to ask of this object',
    pending: 'Running…',
    unknown: 'Not run',
};

/** What the list says it is about, above itself. */
export function summaryOf(data: TestData, running: boolean): string {
    if (running) {
        const left = data.tests.filter((result) => result.status === null).length;
        return left > 0 ? `Running ${left} of ${data.tests.length} checks…` : 'Running the checks…';
    }
    const counts: [TestStatus, string][] = [
        ['failed', 'failed'],
        ['warned', 'warned'],
        ['skipped', 'skipped'],
        ['passed', 'passed'],
        ['not-applicable', 'not applicable'],
    ];
    const parts = counts
        .map(([status, label]) => [data.tests.filter((result) => result.status === status).length, label] as const)
        .filter(([count]) => count > 0)
        .map(([count, label]) => `${count} ${label}`);
    return parts.length > 0 ? parts.join(', ') : 'Nothing was checked';
}

/**
 * Which check to open on: the first failure, or else the first finding, or else
 * the first check that applies - what somebody opening the tab came to read.
 */
export function defaultSelection(tests: TestResult[]): string | undefined {
    const first = (wanted: (result: TestResult) => boolean) => tests.find(wanted)?.name;
    return (
        first((result) => result.status === 'failed') ??
        first((result) => result.status === 'warned') ??
        first((result) => result.status !== 'not-applicable') ??
        tests[0]?.name
    );
}

/**
 * A line of the catalog's markup, as nodes: text, and code where it is between
 * backticks - the one thing 'partcad.qual.catalog' marks up inside a line.
 */
export function inline(text: string): (string | HTMLElement)[] {
    const nodes: (string | HTMLElement)[] = [];
    text.split('`').forEach((part, index) => {
        if (part === '') {
            return;
        }
        nodes.push(index % 2 === 1 ? el('code', undefined, part) : part);
    });
    return nodes;
}

function paragraph(tag: 'p' | 'li' | 'h3', text: string, className?: string): HTMLElement {
    const node = el(tag, className);
    for (const part of inline(text)) {
        node.append(part);
    }
    return node;
}

export const VERDICT: Record<TestStatus, string> = {
    passed: 'Passed',
    failed: 'Failed',
    warned: 'Passed, with findings: what the check found is reported rather than failed - on an object nobody is going to make, or a caution rather than a fault',
    skipped: 'Skipped: the question could not be asked on this machine',
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'not-applicable': 'Not applicable',
};

export class TestView {
    private readonly list = el('div', 'test-list');
    private readonly summary = el('p', 'test-summary');
    private readonly rows = el('div', 'test-rows');
    private readonly runButton = el('button', 'test-run', 'Run again');
    private readonly main = el('div', 'test-main');
    private readonly rowOf = new Map<string, HTMLElement>();
    private data: TestData | undefined;
    private running = false;
    private error: string | undefined;
    private chosen: string | undefined;
    /** Whether 'chosen' is the reader's, by a click, rather than this view's guess at what to open on. */
    private picked = false;
    /**
     * A check to open on the next time checks arrive, whatever object they are
     * of: the one a finding shown in 3D was of, when "Back" takes the reader
     * to it again (see 'prefer').
     */
    private preferred: string | undefined;

    constructor(
        root: HTMLElement,
        private readonly callbacks: TestCallbacks,
        private readonly options: TestOptions = { subtype: 'basic' },
    ) {
        root.classList.add('test', `test-${options.subtype}`);
        this.rows.setAttribute('role', 'listbox');
        this.rows.setAttribute('aria-label', 'Checks');
        this.runButton.title = `Run every test again, as 'pc qual test --${options.subtype}' does`;
        this.runButton.addEventListener('click', () => this.callbacks.onRun());
        this.list.append(this.summary, this.rows, this.runButton);
        root.append(this.list, this.main);
    }

    /** The check on screen, if any. */
    public get selected(): string | undefined {
        return this.chosen;
    }

    public setBusy(text: string): void {
        this.data = undefined;
        this.error = undefined;
        this.running = false;
        // Another object, or the same one changed: what was open on the last
        // one is still a fine thing to open, but no longer a choice to keep.
        this.picked = false;
        empty(this.rows);
        this.rowOf.clear();
        this.summary.textContent = '';
        this.runButton.hidden = true;
        this.showMain(placeholder(text));
    }

    /**
     * The checks could not be run. The list stays when there is one, since what
     * the checks are is still right; the error is said above whichever is open.
     */
    public showError(text: string): void {
        if (this.data === undefined) {
            this.setBusy('');
            this.showMain(el('p', 'error', text));
            // Nothing else on the tab would ask again: the tab has been asked
            // for, and reopening it does not ask twice.
            this.runButton.textContent = 'Try again';
            this.runButton.hidden = false;
            this.runButton.disabled = false;
            return;
        }
        this.error = text;
        this.running = false;
        this.drawList();
        this.showSelected();
    }

    /** Draw the checks; 'running' says the verdicts of those still unset are on the way. */
    public show(data: TestData, running: boolean): void {
        this.data = data;
        this.running = running;
        this.error = undefined;
        const names = new Set(data.tests.map((result) => result.name));
        // The check the reader opened, while it is there - a re-run should not
        // move them - and otherwise the one most worth reading, worked out
        // again as the verdicts that decide which that is come in.
        if (this.preferred !== undefined && names.has(this.preferred)) {
            this.chosen = this.preferred;
            this.picked = true;
        }
        this.preferred = undefined;
        if (!this.picked || this.chosen === undefined || !names.has(this.chosen)) {
            this.chosen = defaultSelection(data.tests);
            this.picked = false;
        }
        this.drawList();
        this.showSelected();
    }

    /**
     * The checks are being run again: every verdict but "not applicable" is
     * taken back until the new ones arrive, since it is no longer the answer.
     */
    public markRunning(): void {
        const data = this.data;
        if (data === undefined) {
            return;
        }
        const pending = data.tests.map((result) =>
            result.status === 'not-applicable' ? result : { ...result, status: null, findings: [], artifacts: [] },
        );
        this.show({ ...data, verified: false, tests: pending }, true);
    }

    /**
     * Open on this check when the checks next arrive, as if it had been
     * clicked: for an object that is about to be shown, whose checks have not
     * been asked for yet. Kept through 'setBusy', which the show starts with.
     */
    public prefer(name: string): void {
        this.preferred = name;
    }

    /** Open a check by name, as clicking it does. */
    public select(name: string): void {
        if (this.data === undefined || !this.data.tests.some((result) => result.name === name)) {
            return;
        }
        this.chosen = name;
        this.picked = true;
        for (const [other, row] of this.rowOf) {
            const on = other === name;
            row.classList.toggle('selected', on);
            row.setAttribute('aria-selected', String(on));
        }
        this.showSelected();
    }

    private drawList(): void {
        const data = this.data;
        empty(this.rows);
        this.rowOf.clear();
        if (data === undefined) {
            return;
        }
        this.summary.textContent = summaryOf(data, this.running);
        this.runButton.textContent = 'Run again';
        this.runButton.hidden = false;
        this.runButton.disabled = this.running;
        data.tests.forEach((result, index) => {
            const mark = markOf(result, this.running);
            const on = result.name === this.chosen;
            const row = el('div', `test-row ${mark}${on ? ' selected' : ''}`);
            row.setAttribute('role', 'option');
            row.setAttribute('aria-selected', String(on));
            row.tabIndex = 0;
            row.title = `${MARK_TITLE[mark]}: ${result.name}`;
            const markNode = el('span', `mark ${mark}`, MARK_TEXT[mark]);
            markNode.setAttribute('aria-label', MARK_TITLE[mark]);
            row.append(markNode, el('span', 'test-title', result.doc?.title ?? result.name));
            row.addEventListener('click', () => this.select(result.name));
            row.addEventListener('keydown', (event: KeyboardEvent) => this.onKey(event, index));
            this.rowOf.set(result.name, row);
            this.rows.appendChild(row);
        });
    }

    private onKey(event: KeyboardEvent, index: number): void {
        const tests = this.data?.tests ?? [];
        let next: number | undefined;
        if (event.key === 'ArrowDown') {
            next = Math.min(index + 1, tests.length - 1);
        } else if (event.key === 'ArrowUp') {
            next = Math.max(index - 1, 0);
        } else if (event.key === 'Enter' || event.key === ' ') {
            next = index;
        }
        if (next === undefined) {
            return;
        }
        event.preventDefault();
        const name = tests[next].name;
        this.select(name);
        this.rowOf.get(name)?.focus();
    }

    private showSelected(): void {
        const result = this.data?.tests.find((test) => test.name === this.chosen);
        if (result === undefined) {
            const none = this.data !== undefined && this.data.tests.length === 0;
            this.showMain(
                placeholder(
                    none
                        ? (this.options.none ?? `This has no ${this.options.subtype} tests.`)
                        : 'Select a check on the left.',
                ),
            );
            return;
        }
        const page = el('div', 'sheet test-page');
        if (this.error !== undefined) {
            page.appendChild(el('p', 'error', this.error));
        }
        page.appendChild(el('h2', undefined, result.doc?.title ?? result.name));
        const command = el('p', 'subtitle');
        command.append(el('code', undefined, commandOf(this.options.subtype, result.name)));
        if (result.doc?.applies) {
            command.append(' · applies to ', ...inline(result.doc.applies));
        }
        page.appendChild(command);
        page.appendChild(this.verdict(result));
        if (result.doc !== null && result.doc !== undefined) {
            page.appendChild(documentation(result.doc));
        }
        this.showMain(page);
    }

    /** How the check came out this time: its verdict, what it said, and what it left behind. */
    private verdict(result: TestResult): HTMLElement {
        const mark = markOf(result, this.running);
        const box = el('div', `test-verdict ${mark}`);
        const status = result.status;
        box.appendChild(
            el(
                'p',
                'test-status',
                status !== null && status !== undefined
                    ? VERDICT[status]
                    : this.running
                      ? 'Running… The geometry checks build the object, and the analyses and simulations run a solver.'
                      : 'Not run.',
            ),
        );
        if (result.findings.length > 0) {
            box.appendChild(findings(result.findings));
        }
        for (const report of result.reports ?? []) {
            box.appendChild(reportTable(report));
        }
        if (result.artifacts.length > 0) {
            const topology = result.artifacts.some((artifact) => artifact.focus);
            box.appendChild(el('h3', undefined, topology ? 'Where it is' : 'Left behind to look at'));
            for (const artifact of result.artifacts) {
                box.appendChild(this.artifact(artifact, result));
            }
        }
        return box;
    }

    private artifact(artifact: TestArtifact, result: TestResult): HTMLElement {
        const node = el('div', artifact.focus ? 'test-artifact topology' : 'test-artifact');
        node.appendChild(el('p', 'name', artifact.title ?? artifact.name));
        if (artifact.desc) {
            node.appendChild(el('p', 'description', artifact.desc));
        }
        // A finding with a place on the object is shown there, with the rest
        // faded; anything else is shown as the object it is.
        const button = el('button', undefined, artifact.focus ? 'Show' : 'Show in the Digital Thread');
        button.title = artifact.focus
            ? `${artifact.package}:${artifact.name}: in the 3D view, with the finding singled out`
            : `${artifact.package}:${artifact.name}`;
        button.addEventListener('click', () => this.callbacks.onShow(artifact, result));
        node.appendChild(button);
        return node;
    }

    private showMain(content: HTMLElement): void {
        empty(this.main);
        this.main.appendChild(content);
    }
}

/**
 * What the 3D view singles out of a topology artifact once it is shown: the node
 * that is the finding, as the tree names nodes ('<package>:<name>/<focus>');
 * undefined for an artifact that is not a topology finding.
 */
export function focusOf(artifact: TestArtifact): TopologyFocus | undefined {
    if (!artifact.focus) {
        return undefined;
    }
    return {
        object: `${artifact.package}:${artifact.name}`,
        item: `${artifact.package}:${artifact.name}/${artifact.focus}`,
        label: artifact.title ?? artifact.focus,
    };
}

/** The object a finding is on, to go back to: as 'ShowObjectMessage' names one. */
export interface FindingSubject {
    package: string;
    name: string;
    kind: string;
}

/**
 * A topology finding as it is shown in 3D: what to single out, where to pin a
 * callout, and everything the Topology tab said about it - the check, its
 * verdict and its words - so that the 3D view can go on saying it (see
 * 'finding.ts'), and the object to go back to.
 */
export interface Finding {
    focus: TopologyFocus;
    features: TopologyFeature[];
    /** The check, by name, as 'pc qual test -f' takes it. */
    check: string;
    /** The check's title, from its entry of the catalog, or its name. */
    title: string;
    subtype: string;
    status: TestStatus | null;
    findings: TestFinding[];
    /** What the artifact says it is. */
    desc?: string;
    subject?: FindingSubject;
}

/**
 * What showing a topology artifact keeps on screen with it; undefined for an
 * artifact that is not a topology finding.
 */
export function findingOf(
    artifact: TestArtifact,
    result: TestResult,
    subtype: string,
    subject: FindingSubject | undefined,
): Finding | undefined {
    const focus = focusOf(artifact);
    if (focus === undefined) {
        return undefined;
    }
    return {
        focus,
        features: (artifact.features ?? []).filter(
            (feature) => Array.isArray(feature.at) && feature.at.length === 3 && feature.at.every(Number.isFinite),
        ),
        check: result.name,
        title: result.doc?.title ?? result.name,
        subtype,
        status: result.status,
        findings: result.findings,
        desc: artifact.desc,
        subject,
    };
}

/** The command that runs one test alone, as the tab's subtype is selected on the command line. */
export function commandOf(subtype: string, name: string): string {
    return `pc qual test --${subtype === 'sim' ? 'simulation' : subtype} -f ${name}`;
}

/** The severity a report's row is marked with: 'error', 'warning' or 'info', from the tool's own word for it. */
export function severityOf(row: Record<string, unknown>): 'error' | 'warning' | 'info' {
    const said = String(row.severity ?? row.level ?? '').toLowerCase();
    if (['error', 'violation', 'failed', 'fail', 'no-go', 'no_go', 'refused'].includes(said)) {
        return 'error';
    }
    if (['warning', 'warn', 'note', 'notes', 'not_scored', 'not-scored'].includes(said)) {
        return 'warning';
    }
    return 'info';
}

/** The columns of a report: what it declares, or else every key its rows use, in the order they first appear. */
export function columnsOf(report: TestReport): { key: string; title: string }[] {
    if (report.columns && report.columns.length > 0) {
        return report.columns.map((column) => ({ key: column.key, title: column.title ?? column.key }));
    }
    const keys: string[] = [];
    for (const row of report.rows ?? []) {
        for (const key of Object.keys(row)) {
            if (!keys.includes(key)) {
                keys.push(key);
            }
        }
    }
    return keys.map((key) => ({ key, title: key }));
}

/** An 'other' test's report, as its tool wrote it: a heading, a summary and a table, row by row. */
export function reportTable(report: TestReport): HTMLElement {
    const node = el('div', 'test-report');
    node.appendChild(el('h3', undefined, report.title ?? 'Report'));
    if (report.verdict) {
        node.appendChild(el('p', 'test-report-verdict', report.verdict));
    }
    if (report.summary) {
        node.appendChild(el('p', 'test-report-summary', report.summary));
    }
    const rows = report.rows ?? [];
    if (rows.length === 0) {
        node.appendChild(el('p', 'description', 'Nothing to report.'));
        return node;
    }
    const columns = columnsOf(report);
    const table = el('table', 'test-report-table');
    const head = el('tr');
    for (const column of columns) {
        head.appendChild(el('th', undefined, column.title));
    }
    table.appendChild(el('thead')).appendChild(head);
    const body = table.appendChild(el('tbody'));
    for (const row of rows) {
        const line = el('tr', severityOf(row));
        for (const column of columns) {
            const value = row[column.key];
            line.appendChild(
                el(
                    'td',
                    undefined,
                    value === undefined || value === null
                        ? ''
                        : typeof value === 'object'
                          ? JSON.stringify(value)
                          : String(value),
                ),
            );
        }
        body.appendChild(line);
    }
    node.appendChild(table);
    return node;
}

/** What a check said, line by line, as the tab and the finding card over the 3D view both list it. */
export function findings(found: TestFinding[]): HTMLElement {
    const list = el('ul', 'test-findings');
    for (const finding of found) {
        // Said as the check said it: a failure is often several lines - a
        // solver's report, a list of what is missing - and 'pre-wrap' keeps them.
        list.appendChild(el('li', finding.level, finding.text));
    }
    return list;
}

/** A check's entry of 'partcad.qual.catalog', as the documentation lists it. */
export function documentation(doc: TestDoc): HTMLElement {
    const node = el('div', 'test-doc');
    for (const block of doc.blocks) {
        if (block.type === 'heading') {
            node.appendChild(paragraph('h3', block.text));
        } else if (block.type === 'paragraph') {
            node.appendChild(paragraph('p', block.text));
        } else if (block.type === 'list') {
            const list = el('ul');
            for (const item of block.items) {
                list.appendChild(paragraph('li', item));
            }
            node.appendChild(list);
        } else if (block.type === 'code') {
            const pre = el('pre');
            pre.appendChild(el('code', block.language ? `language-${block.language}` : undefined, block.text));
            node.appendChild(pre);
        }
    }
    return node;
}
