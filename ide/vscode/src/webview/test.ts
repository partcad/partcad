//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "Test" tab, the first of Validation.
//
// What 'pc test' says of the object on screen, check by check. A list on the
// left - every check 'pc test' runs, in the order it runs them, with a mark for
// how each came out - and the check selected in the middle: what it found this
// time, what it left behind to be looked at, and what it is, when it applies
// and what to do when it fails.
//
// Nothing here decides anything. The daemon's 'test.report' runs the checks
// 'pc test <object>' runs, through the same cache, and answers with each
// verdict, what each check said, and its entry in 'partcad.test.catalog' - the
// same text the documentation lists the checks with. This file draws the answer.
//
// Asked for twice, in a row (see 'viewer.ts'): once without running anything,
// which is a read of declarations and lists every check with the ones that do
// not apply saying why, and once running them, which takes as long as the
// slowest check. The list is on screen, every other mark pending, for as long as
// that takes.
//

import { el, empty, placeholder } from './dom';
import { TestArtifact, TestData, TestDoc, TestFinding, TestResult, TestStatus } from './messages';

export interface TestCallbacks {
    /** "Run again" was pressed: the checks have to be asked for once more. */
    onRun: () => void;
    /** An artifact's button was pressed: show that object in the panel. */
    onShow: (artifact: TestArtifact) => void;
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

const MARK_TEXT: Record<TestMark, string> = {
    passed: '✓',
    failed: '✗',
    warned: '!',
    skipped: '↷',
    // eslint-disable-next-line @typescript-eslint/naming-convention
    'not-applicable': '–',
    pending: '…',
    unknown: '?',
};

const MARK_TITLE: Record<TestMark, string> = {
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
 * backticks - the one thing 'partcad.test.catalog' marks up inside a line.
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

const VERDICT: Record<TestStatus, string> = {
    passed: 'Passed',
    failed: 'Failed',
    warned: 'Passed, with findings: on an object nobody is going to make, what a check finds is reported rather than failed',
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

    constructor(
        root: HTMLElement,
        private readonly callbacks: TestCallbacks,
    ) {
        root.classList.add('test');
        this.rows.setAttribute('role', 'listbox');
        this.rows.setAttribute('aria-label', 'Checks');
        this.runButton.title = "Run every check again, as 'pc test' does";
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
            this.showMain(placeholder('Select a check on the left.'));
            return;
        }
        const page = el('div', 'sheet test-page');
        if (this.error !== undefined) {
            page.appendChild(el('p', 'error', this.error));
        }
        page.appendChild(el('h2', undefined, result.doc?.title ?? result.name));
        const command = el('p', 'subtitle');
        command.append(el('code', undefined, `pc test -f ${result.name}`));
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
        if (result.artifacts.length > 0) {
            box.appendChild(el('h3', undefined, 'Left behind to look at'));
            for (const artifact of result.artifacts) {
                box.appendChild(this.artifact(artifact));
            }
        }
        return box;
    }

    private artifact(artifact: TestArtifact): HTMLElement {
        const node = el('div', 'test-artifact');
        node.appendChild(el('p', 'name', artifact.title ?? artifact.name));
        if (artifact.desc) {
            node.appendChild(el('p', 'description', artifact.desc));
        }
        const button = el('button', undefined, 'Show in the Digital Thread');
        button.title = `${artifact.package}:${artifact.name}`;
        button.addEventListener('click', () => this.callbacks.onShow(artifact));
        node.appendChild(button);
        return node;
    }

    private showMain(content: HTMLElement): void {
        empty(this.main);
        this.main.appendChild(content);
    }
}

function findings(found: TestFinding[]): HTMLElement {
    const list = el('ul', 'test-findings');
    for (const finding of found) {
        // Said as the check said it: a failure is often several lines - a
        // solver's report, a list of what is missing - and 'pre-wrap' keeps them.
        list.appendChild(el('li', finding.level, finding.text));
    }
    return list;
}

/** A check's entry of 'partcad.test.catalog', as the documentation lists it. */
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
