//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Operations group's Revisions and Used By tabs: what the history of a
// package lists, which revision a comparison is asked for, how the comparison
// is drawn, and that the two folded views under it are asked for the first time
// they are opened and not before.
//
// The panes run in the webview and this suite in the extension host, which has
// no DOM, so it is given the handful of things 'dom.ts' and the panes ask of an
// element (as 'viewerSimulation.test.ts' is).
//

import * as assert from 'assert';

import { CompareData, RevisionsData, UsedByData, UsesData, groupOf } from '../../webview/messages';
import { NOT_PUBLISHED, RevisionsView, renderComparison } from '../../webview/revisions';
import { renderUsedBy } from '../../webview/usedBy';

class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public tabIndex = -1;
    public type = '';
    public colSpan = 1;
    public readonly dataset: Record<string, string> = {};
    public readonly attributes: Record<string, string> = {};
    public readonly classList = {
        add: (...names: string[]) => {
            this.className = [...this.className.split(' ').filter(Boolean), ...names].join(' ');
        },
        toggle: (name: string, on?: boolean) => {
            const names = this.className.split(' ').filter((existing) => existing && existing !== name);
            if (on ?? !this.className.split(' ').includes(name)) {
                names.push(name);
            }
            this.className = names.join(' ');
        },
    };
    private readonly listeners: Record<string, ((event?: unknown) => void)[]> = {};

    constructor(public readonly tagName: string) {}

    public appendChild(child: FakeElement): FakeElement {
        this.children.push(child);
        return child;
    }

    public append(...children: FakeElement[]): void {
        children.forEach((child) => this.appendChild(child));
    }

    public replaceChildren(): void {
        this.children.length = 0;
    }

    public setAttribute(name: string, value: string): void {
        this.attributes[name] = value;
    }

    public addEventListener(name: string, handler: (event?: unknown) => void): void {
        (this.listeners[name] ??= []).push(handler);
    }

    public fire(name: string): void {
        (this.listeners[name] ?? []).forEach((handler) => handler());
    }

    /** Everything under this element with this class, in the order it is drawn, hidden or not. */
    public find(className: string): FakeElement[] {
        const found: FakeElement[] = [];
        const walk = (element: FakeElement) => {
            if (element.className.split(' ').includes(className)) {
                found.push(element);
            }
            element.children.forEach(walk);
        };
        this.children.forEach(walk);
        return found;
    }

    public text(): string {
        return this.textContent + this.children.map((child) => child.text()).join('');
    }
}

const NEWEST = 'a06a1728eb8d3f0470c91e3dd6203e5f57aa1692';
const OLDEST = '9627b7284e7bb8e7dfe1b5265afbc648fa29882b';

const HISTORY: RevisionsData = {
    package: '//',
    published: true,
    head: NEWEST,
    revisions: [
        { sha: NEWEST, short: NEWEST.slice(0, 8), summary: 'second', author: 'A', time: 1_700_000_100 },
        { sha: OLDEST, short: OLDEST.slice(0, 8), summary: 'first', author: 'A', time: 1_700_000_000 },
    ],
};

const COMPARED: CompareData = {
    package: '//',
    revision: OLDEST,
    short: OLDEST.slice(0, 8),
    loaded: `//@${OLDEST}`,
    left: { label: OLDEST.slice(0, 8), missing: false },
    right: { label: 'Current', missing: false },
    same: false,
    rows: [
        { tag: 'equal', left: 'cube:', right: 'cube:', leftLine: 1, rightLine: 1 },
        { tag: 'replace', left: '  length: 10', right: '  length: 30', leftLine: 2, rightLine: 2 },
        { tag: 'insert', left: null, right: '  desc: new', leftLine: null, rightLine: 3 },
    ],
};

const USES: UsesData = {
    package: '//',
    revision: OLDEST,
    loaded: `//@${OLDEST}`,
    dependencies: [
        {
            name: 'std',
            package: `//@${OLDEST}/std`,
            current: '//std',
            sha: 'f00dfeed00000000000000000000000000000000',
            short: 'f00dfeed',
            versioned: '//std@f00dfeed00000000000000000000000000000000',
            type: 'git',
        },
    ],
};

const USERS: UsedByData = {
    objects: [{ object: '//sub2:pair', package: '//sub2', name: 'pair', kind: 'assembly', count: 2 }],
};

function pane() {
    const root = new FakeElement('div');
    const asked: [string, string][] = [];
    const opened: string[] = [];
    const shown: string[] = [];
    const view = new RevisionsView(root as unknown as HTMLElement, {
        ask: (query, revision) => asked.push([query, revision]),
        openPackage: (name) => opened.push(name),
        showObject: (row) => shown.push(row.object),
    });
    return { root, view, asked, opened, shown };
}

function title(root: FakeElement, detail: string): FakeElement {
    const found = root.find('simulation-detail-tab').find((tab) => tab.dataset.detail === detail);
    assert.ok(found, `no '${detail}' title`);
    return found;
}

suite('Digital Thread Operations tabs', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tag: string) => new FakeElement(tag),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('Revisions and Used By are the tabs of the Operations group', () => {
        assert.strictEqual(groupOf('revisions'), 'operations');
        assert.strictEqual(groupOf('usedby'), 'operations');
    });

    test('a package with no history is not published yet, and asks nothing more', () => {
        const { root, view, asked } = pane();

        view.showHistory({ package: '//', published: false, head: null, revisions: [] });

        assert.ok(root.text().includes(NOT_PUBLISHED));
        assert.deepStrictEqual(asked, []);
        assert.deepStrictEqual(view.offered, []);
    });

    test('lists the revisions by the first eight characters of their ids, newest first and selected', () => {
        const { root, view, asked } = pane();

        view.showHistory(HISTORY);

        const rows = root.find('revisions-item');
        assert.deepStrictEqual(
            rows.map((row) => row.dataset.name),
            ['a06a1728', '9627b728'],
        );
        assert.ok(rows[0].className.includes('selected'));
        assert.strictEqual(view.current, NEWEST);
        // The newest is compared with what is on screen, once.
        assert.deepStrictEqual(asked, [['compare', NEWEST]]);
        view.select(NEWEST);
        assert.deepStrictEqual(asked, [['compare', NEWEST]]);
    });

    test('selecting another revision compares with that one, and the answer is drawn side by side', () => {
        const { root, view, asked } = pane();
        view.showHistory(HISTORY);

        root.find('revisions-item')[1].fire('click');
        assert.deepStrictEqual(asked[asked.length - 1], ['compare', OLDEST]);
        assert.ok(root.text().includes('comparing'));

        view.answer('compare', OLDEST, COMPARED);

        const diff = root.find('revisions-diff');
        assert.strictEqual(diff.length, 1);
        assert.ok(root.find('diff-removed').some((cell) => cell.textContent === '  length: 10'));
        assert.ok(root.find('diff-added').some((cell) => cell.textContent === '  length: 30'));
        // A line only the current side has leaves the revision's side empty.
        assert.ok(root.find('diff-empty').length >= 2);
    });

    test('an answer for a revision no longer selected is kept, not drawn', () => {
        const { root, view } = pane();
        view.showHistory(HISTORY);

        view.answer('compare', OLDEST, COMPARED);

        assert.strictEqual(root.find('revisions-diff').length, 0);
        root.find('revisions-item')[1].fire('click');
        assert.strictEqual(root.find('revisions-diff').length, 1);
    });

    test('the folded views are asked for the first time each is opened, and not before', () => {
        const { root, view, asked, opened } = pane();
        view.showHistory(HISTORY);
        assert.ok(!asked.some(([query]) => query === 'uses' || query === 'usedBy'));

        title(root, 'uses').fire('click');
        assert.deepStrictEqual(asked[asked.length - 1], ['uses', NEWEST]);
        view.answer('uses', NEWEST, USES);

        // The dependency and its commit, each opening it in the Package Explorer.
        const name = root.find('revisions-dependency-name')[0];
        const sha = root.find('revisions-dependency-sha')[0];
        assert.strictEqual(name.textContent, 'std');
        assert.strictEqual(sha.textContent, 'f00dfeed');
        name.fire('click');
        sha.fire('click');
        assert.deepStrictEqual(opened, ['//std', USES.dependencies[0].versioned]);

        // Folded and opened again: not asked twice.
        title(root, 'uses').fire('click');
        title(root, 'uses').fire('click');
        assert.strictEqual(asked.filter(([query]) => query === 'uses').length, 1);

        title(root, 'usedBy').fire('click');
        assert.deepStrictEqual(asked[asked.length - 1], ['usedBy', NEWEST]);
    });

    test('Used By lists each object with how many times it uses this, and opens it', () => {
        const host = new FakeElement('div');
        const opened: string[] = [];

        renderUsedBy(host as unknown as HTMLElement, USERS, (row) => opened.push(row.object), 'this part');

        assert.ok(host.find('usedby-count').some((cell) => cell.textContent === '2'));
        host.find('usedby-open')[0].fire('click');
        assert.deepStrictEqual(opened, ['//sub2:pair']);
    });

    test('nothing loaded uses it, and the list says it only looked at what is loaded', () => {
        const host = new FakeElement('div');

        renderUsedBy(host as unknown as HTMLElement, { objects: [] }, () => undefined, 'this part');

        assert.ok(host.text().includes('Nothing PartCAD has loaded uses this part'));
    });

    test('an object declared at neither side, or the same at both, says so over the comparison', () => {
        const same = renderComparison({ ...COMPARED, same: true, rows: [] }) as unknown as FakeElement;
        assert.ok(same.text().includes('No change since'));
        const added = renderComparison({
            ...COMPARED,
            left: { label: 'x', missing: true },
        }) as unknown as FakeElement;
        assert.ok(added.text().includes('Not declared at'));
    });
});
