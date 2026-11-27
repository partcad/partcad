//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Operations group's Revisions tab: what it asks the daemon when it is
// opened, which rows it lists - the revisions, and above them WORKTREE and
// STAGED when they apply - what each row is compared with, how the comparison
// is drawn, that the folded views under it are asked for the first time they
// are opened and not before, and how Stage all and a new revision go, refusals
// included.
//
// The panes run in the webview and this suite in the extension host, which has
// no DOM, so it is given the handful of things 'dom.ts' and the panes ask of an
// element (as 'viewerSimulation.test.ts' is).
//

import * as assert from 'assert';

import {
    DiffData,
    OpsQuery,
    OpsReadMethod,
    OpsWriteMethod,
    RevStatusData,
    RevisionsData,
    STAGED,
    TAB_GROUPS,
    WORKTREE,
    groupOf,
} from '../../webview/messages';
import { OpsAnswer, OpsSubject, OpsWritten } from '../../webview/operations';
import {
    NOT_PUBLISHED,
    RevisionsView,
    comparedStates,
    draftMessage,
    hasStaged,
    hasUnstaged,
    renderComparison,
} from '../../webview/revisions';

class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public disabled = false;
    public checked = false;
    public value = '';
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
const INDEX = '4b825dc642cb6eb9a060e54bf8d69288fbee4904';

const PACKAGE: OpsSubject = { package: '//', name: '//', kind: 'package' };
const PART: OpsSubject = { package: '//', name: 'bracket', kind: 'part' };

const HISTORY: RevisionsData = {
    package: '//',
    published: true,
    head: NEWEST,
    more: false,
    revisions: [
        { sha: NEWEST, short: NEWEST.slice(0, 8), summary: 'second', author: 'A', time: 1_700_000_100 },
        { sha: OLDEST, short: OLDEST.slice(0, 8), summary: 'first', author: 'A', time: 1_700_000_000, in: ['sub'] },
    ],
};

/** Nothing staged, nothing changed on disk. */
const CLEAN: RevStatusData = {
    package: '//',
    object: null,
    repository: '/work/repo',
    branch: 'main',
    head: NEWEST,
    detached: false,
    index: INDEX,
    state: null,
    conflicted: [],
    staged: [],
    unstaged: [],
    untracked: [],
    files: [],
    // eslint-disable-next-line @typescript-eslint/naming-convention
    own_files: null,
    partial: [],
    // eslint-disable-next-line @typescript-eslint/naming-convention
    others_staged: [],
    elsewhere: [],
    advice: null,
};

/** The same, for the part 'bracket', built from 'bracket.py'. */
const OBJECT_CLEAN: RevStatusData = {
    ...CLEAN,
    object: '//:bracket',
    // eslint-disable-next-line @typescript-eslint/naming-convention
    own_files: ['bracket.py'],
};

/** 'bracket' staged, and changed again on disk since; a file of the package not tracked yet. */
const CHANGED: RevStatusData = {
    ...CLEAN,
    staged: [{ kind: 'part', name: 'bracket', object: '//:bracket', how: ['declaration', 'source'] }],
    unstaged: [{ kind: 'part', name: 'bracket', object: '//:bracket', how: ['source'] }],
    untracked: ['notes.md'],
    files: [{ path: 'notes.md', sections: ['untracked'] }],
    partial: ['bracket'],
    advice: "Stage the changes to // that are not staged yet -- :bracket (source), notes.md -- for a new revision, and leave everything else as it is (or run 'pc ops rev stage //').",
};

function diff(from: string, to: string, extra: Partial<DiffData> = {}): DiffData {
    return {
        package: '//',
        object: null,
        from,
        to,
        fromRevision: null,
        toRevision: null,
        left: { label: from, missing: false },
        right: { label: to, missing: false },
        same: false,
        rows: [
            { tag: 'equal', left: 'cube:', right: 'cube:', leftLine: 1, rightLine: 1 },
            { tag: 'replace', left: '  length: 10', right: '  length: 30', leftLine: 2, rightLine: 2 },
            { tag: 'insert', left: null, right: '  desc: new', leftLine: null, rightLine: 3 },
        ],
        ...extra,
    };
}

interface Asked {
    query: OpsQuery<OpsReadMethod>;
    answer: OpsAnswer;
}

interface Written {
    query: OpsQuery<OpsWriteMethod>;
    answer: OpsWritten;
    directory?: string | null;
}

function pane(subject: OpsSubject = PACKAGE) {
    const root = new FakeElement('div');
    const asked: Asked[] = [];
    const written: Written[] = [];
    const opened: string[] = [];
    const shown: string[] = [];
    const copied: string[] = [];
    const view = new RevisionsView(root as unknown as HTMLElement, {
        ask: (query, answer) => asked.push({ query, answer }),
        write: (query, answer, directory) => written.push({ query, answer, directory }),
        openPackage: (name) => opened.push(name),
        showObject: (object) => shown.push(`${object.package}:${object.name}`),
        copy: (text) => copied.push(text),
    });
    view.start(subject);
    /** Answer the newest question asked with 'method'. */
    const reply = (method: OpsReadMethod, data: unknown, error?: string) => {
        const question = [...asked].reverse().find((each) => each.query.method === method);
        assert.ok(question, `nothing asked with ${method}`);
        question.answer(data, error);
    };
    const diffs = () => asked.filter((each) => each.query.method === 'ops.rev.diff').map((each) => each.query.params);
    const rows = () => root.find('revisions-item');
    const row = (name: string) => {
        const found = rows().find((each) => each.dataset.name === name);
        assert.ok(found, `no row '${name}'`);
        return found;
    };
    return { root, view, asked, written, opened, shown, copied, reply, diffs, rows, row };
}

function title(root: FakeElement, detail: string): FakeElement {
    const found = root.find('simulation-detail-tab').find((tab) => tab.dataset.detail === detail);
    assert.ok(found, `no '${detail}' title`);
    return found;
}

function only(root: FakeElement, className: string): FakeElement {
    const found = root.find(className);
    assert.strictEqual(found.length, 1, `expected one '${className}', found ${found.length}`);
    return found[0];
}

suite('Digital Thread Operations: Revisions', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tag: string) => new FakeElement(tag),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('Revisions, Dependencies, Used By and Impact are the tabs of the Operations group, in that order', () => {
        assert.deepStrictEqual(TAB_GROUPS.operations, ['revisions', 'dependencies', 'usedby', 'impact']);
        for (const tab of ['revisions', 'dependencies', 'usedby', 'impact']) {
            assert.strictEqual(groupOf(tab), 'operations');
        }
    });

    test('opened, it asks for the revisions and for what is staged, and nothing else', () => {
        const { asked } = pane();

        assert.deepStrictEqual(
            asked.map((each) => each.query.method),
            ['ops.rev.list', 'ops.rev.status'],
        );
    });

    test('a package with no history and no repository is not published yet, and asks nothing more', () => {
        const { root, view, asked, reply } = pane();

        reply('ops.rev.list', { package: '//', published: false, head: null, revisions: [] });
        reply('ops.rev.status', undefined, '// is not in a git repository');

        assert.ok(root.text().includes(NOT_PUBLISHED));
        assert.strictEqual(asked.length, 2);
        assert.deepStrictEqual(view.offered, []);
    });

    test('lists the revisions by the first eight characters of their ids, and compares the newest with its parent', () => {
        const { view, reply, rows, diffs } = pane();

        reply('ops.rev.list', HISTORY);
        // Nothing is selected until the status is in, too: the page would
        // otherwise open on a commit and jump to WORKTREE.
        assert.deepStrictEqual(diffs(), []);
        reply('ops.rev.status', CLEAN);

        assert.deepStrictEqual(
            rows().map((row) => row.dataset.name),
            ['a06a1728', '9627b728'],
        );
        assert.ok(rows()[0].className.includes('selected'));
        assert.strictEqual(view.current, NEWEST);
        assert.deepStrictEqual(diffs(), [{ from: `${NEWEST}~1`, to: NEWEST }]);
    });

    test("a package's revision that changed only sub-packages says which; an object's, how it changed it", () => {
        const packageTab = pane();
        packageTab.reply('ops.rev.list', HISTORY);
        packageTab.reply('ops.rev.status', CLEAN);
        assert.deepStrictEqual(
            packageTab
                .row('9627b728')
                .find('scenario-chip')
                .map((chip) => chip.textContent),
            ['in sub'],
        );

        const partTab = pane(PART);
        partTab.reply('ops.rev.list', {
            ...HISTORY,
            object: '//:bracket',
            revisions: [{ ...HISTORY.revisions[0], how: ['declaration', 'source'] }],
        });
        partTab.reply('ops.rev.status', OBJECT_CLEAN);
        assert.deepStrictEqual(
            partTab
                .row('a06a1728')
                .find('scenario-chip')
                .map((chip) => chip.textContent),
            ['declaration', 'source'],
        );
    });

    test('WORKTREE and STAGED are listed above the revisions when they apply, WORKTREE selected first', () => {
        const { root, view, reply, rows, diffs, copied } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CHANGED);

        assert.deepStrictEqual(view.offered, [WORKTREE, STAGED, 'a06a1728', '9627b728']);
        assert.ok(rows()[0].className.includes('selected'));
        // What it changed is what is on disk against what is staged.
        assert.deepStrictEqual(diffs(), [{ from: STAGED, to: WORKTREE }]);
        // Nothing comes after the files on disk.
        assert.strictEqual(only(root, 'revisions-mode-since').disabled, true);

        // The sentence for an agent, and a button that copies it.
        assert.ok(root.text().includes('Stage the changes to //'));
        only(root, 'revisions-copy').fire('click');
        assert.deepStrictEqual(copied, [CHANGED.advice]);
    });

    test("an object's rows are about its own files: a change of another file shows no WORKTREE", () => {
        const status: RevStatusData = { ...OBJECT_CLEAN, files: [{ path: 'other.py', sections: ['unstaged'] }] };
        assert.strictEqual(hasUnstaged(status), false);
        assert.strictEqual(hasUnstaged({ ...status, files: [{ path: 'bracket.py', sections: ['unstaged'] }] }), true);
        assert.strictEqual(hasStaged({ ...status, files: [{ path: 'bracket.py', sections: ['staged'] }] }), true);
        // A package's are all its files.
        assert.strictEqual(hasUnstaged({ ...CLEAN, files: [{ path: 'other.py', sections: ['untracked'] }] }), true);
    });

    test('each row is compared with what came before it, or with the files on disk since', () => {
        assert.deepStrictEqual(comparedStates(WORKTREE, 'change'), { from: STAGED, to: WORKTREE });
        assert.strictEqual(comparedStates(WORKTREE, 'since'), undefined);
        assert.deepStrictEqual(comparedStates(STAGED, 'change'), { from: 'HEAD', to: STAGED });
        assert.deepStrictEqual(comparedStates(STAGED, 'since'), { from: STAGED, to: WORKTREE });
        assert.deepStrictEqual(comparedStates(NEWEST, 'change'), { from: `${NEWEST}~1`, to: NEWEST });
        assert.deepStrictEqual(comparedStates(NEWEST, 'since'), { from: NEWEST, to: WORKTREE });
    });

    test('selecting another revision compares that one, side by side, and Since then with the files on disk', () => {
        const { root, reply, row, diffs, asked } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CLEAN);

        row('9627b728').fire('click');
        assert.deepStrictEqual(diffs().pop(), { from: `${OLDEST}~1`, to: OLDEST });
        assert.ok(root.text().includes('Comparing'));
        reply('ops.rev.diff', diff(`${OLDEST}~1`, OLDEST));

        assert.strictEqual(root.find('revisions-diff').length, 1);
        assert.ok(root.find('diff-removed').some((cell) => cell.textContent === '  length: 10'));
        assert.ok(root.find('diff-added').some((cell) => cell.textContent === '  length: 30'));
        // A line only the later side has leaves the earlier side empty.
        assert.ok(root.find('diff-empty').length >= 2);

        only(root, 'revisions-mode-since').fire('click');
        assert.deepStrictEqual(diffs().pop(), { from: OLDEST, to: WORKTREE });
        reply('ops.rev.diff', diff(OLDEST, WORKTREE));
        // Back to what it changed: answered already, not asked again.
        const before = asked.length;
        only(root, 'revisions-mode-change').fire('click');
        assert.strictEqual(asked.length, before);
        assert.strictEqual(root.find('revisions-diff').length, 1);
    });

    test('a comparison that never came back is asked again when its row is selected again', () => {
        // The host cancels a comparison a newer one replaces, and a cancelled
        // one is never answered: going back to it must not wait forever.
        const { reply, row, diffs } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CLEAN);
        row('9627b728').fire('click');

        row('a06a1728').fire('click');

        assert.deepStrictEqual(
            diffs().map((each) => each?.to),
            [NEWEST, OLDEST, NEWEST],
        );
        // Once answered, it is not asked again.
        reply('ops.rev.diff', diff(`${NEWEST}~1`, NEWEST));
        row('9627b728').fire('click');
        row('a06a1728').fire('click');
        assert.strictEqual(diffs().filter((each) => each?.to === NEWEST).length, 2);
    });

    test("a package's comparison lists what changed in it, object by object and file by file", () => {
        const { root, reply, shown } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CLEAN);

        reply(
            'ops.rev.diff',
            diff(`${NEWEST}~1`, NEWEST, {
                changes: {
                    package: '//',
                    from: `${NEWEST}~1`,
                    to: NEWEST,
                    objects: [
                        { kind: 'part', name: 'bracket', object: '//:bracket', how: ['declaration'] },
                        { kind: 'part', name: 'old', object: '//:old', how: ['removed'] },
                    ],
                    files: [{ path: 'bracket.py', how: 'modified' }],
                },
            }),
        );

        const objects = only(root, 'revisions-changed-objects');
        assert.ok(objects.text().includes('declaration'));
        // One that is gone cannot be shown; one that is there can.
        assert.strictEqual(objects.find('ops-open').length, 1);
        objects.find('ops-open')[0].fire('click');
        assert.deepStrictEqual(shown, ['//:bracket']);
        assert.ok(only(root, 'revisions-changed-files').text().includes('bracket.py'));
    });

    test('the first commit of the repository, which has no parent, is drawn as all it added', () => {
        const { root, reply, row, diffs } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CLEAN);
        row('9627b728').fire('click');

        reply('ops.rev.diff', undefined, `Unknown revision '${OLDEST}~1'`);

        assert.deepStrictEqual(diffs().pop(), { from: OLDEST, to: OLDEST });
        reply('ops.rev.diff', { ...diff(OLDEST, OLDEST), same: true });
        assert.ok(root.text().includes('The first revision of the repository'));
        assert.strictEqual(root.find('diff-removed').length, 0);
        assert.strictEqual(root.find('diff-insert').length, 3);
    });

    test('Load more asks for the page after the last revision, and lists it under the first', () => {
        const { root, view, reply, asked } = pane();
        reply('ops.rev.list', { ...HISTORY, more: true, revisions: [HISTORY.revisions[0]] });
        reply('ops.rev.status', CLEAN);

        only(root, 'revisions-more').fire('click');

        assert.deepStrictEqual(asked[asked.length - 1].query, { method: 'ops.rev.list', params: { after: NEWEST } });
        reply('ops.rev.list', { ...HISTORY, more: false, revisions: [HISTORY.revisions[1]] });
        assert.deepStrictEqual(view.offered, ['a06a1728', '9627b728']);
        assert.strictEqual(root.find('revisions-more').length, 0);
    });

    test('the folded views are asked about the row the first time each is opened, and not before', () => {
        const { root, asked, reply } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CLEAN);
        const folds = () => asked.filter((each) => !each.query.method.startsWith('ops.rev.')).map((each) => each.query);
        assert.deepStrictEqual(folds(), []);

        title(root, 'deps').fire('click');
        assert.deepStrictEqual(folds().pop(), { method: 'ops.deps.list', at: NEWEST });
        title(root, 'usedBy').fire('click');
        assert.deepStrictEqual(folds().pop(), { method: 'ops.used_by', at: NEWEST, whole: true });
        title(root, 'impact').fire('click');
        assert.deepStrictEqual(folds().pop(), { method: 'ops.impact', params: { from: NEWEST, to: WORKTREE } });

        // Folded and opened again: not asked twice once answered.
        reply('ops.impact', {
            package: '//',
            object: null,
            from: NEWEST,
            to: WORKTREE,
            changed: [],
            affects: [],
            // eslint-disable-next-line @typescript-eslint/naming-convention
            affected_by: [],
            pins: [],
            pinned: [],
            summary: {},
        });
        title(root, 'impact').fire('click');
        title(root, 'impact').fire('click');
        assert.strictEqual(folds().filter((query) => query.method === 'ops.impact').length, 1);
    });

    test('a dependency at a revision opens in the Package Explorer, at its commit too', () => {
        const { root, reply, opened } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CLEAN);
        title(root, 'deps').fire('click');

        reply('ops.deps.list', {
            package: `//@${NEWEST}`,
            object: null,
            kind: 'package',
            declared: [
                {
                    name: 'std',
                    package: `//@${NEWEST}/std`,
                    current: '//std',
                    sha: 'f00dfeed00000000000000000000000000000000',
                    short: 'f00dfeed',
                    versioned: '//std@f00dfeed00000000000000000000000000000000',
                    type: 'git',
                    location: 'https://example.com/std.git',
                    track: 'main',
                    pinned: 'f00dfeed00000000000000000000000000000000',
                },
            ],
            undeclared: [],
            subpackages: [],
        });

        const name = only(root, 'deps-name');
        assert.strictEqual(name.textContent, 'std');
        name.fire('click');
        only(root, 'deps-sha').fire('click');
        assert.deepStrictEqual(opened, ['//std', '//std@f00dfeed00000000000000000000000000000000']);
        // Nothing is changed at a revision.
        assert.strictEqual(root.find('deps-update').length, 0);
    });

    test("an object's folded views keep the object: what it depended on, not its package", () => {
        const { root, asked, reply } = pane(PART);
        reply('ops.rev.list', { ...HISTORY, revisions: [{ ...HISTORY.revisions[0], how: ['source'] }] });
        reply('ops.rev.status', OBJECT_CLEAN);

        title(root, 'deps').fire('click');
        assert.deepStrictEqual(asked[asked.length - 1].query, { method: 'ops.deps.list', at: NEWEST });
        title(root, 'usedBy').fire('click');
        assert.strictEqual(asked[asked.length - 1].query.whole, true);
    });

    test('Stage all stages, and the row that is left is selected and compared again', () => {
        const { root, view, written, reply, diffs } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CHANGED);

        only(root, 'revisions-stage').fire('click');
        assert.deepStrictEqual(written[0].query, { method: 'ops.rev.stage' });
        assert.strictEqual(only(root, 'revisions-stage').disabled, true);

        written[0].answer({
            data: {
                package: '//',
                object: null,
                staged: ['bracket.py', 'notes.md'],
                notes: [],
                status: { ...CHANGED, unstaged: [], untracked: [], files: [], partial: [], advice: null },
            },
        });

        assert.deepStrictEqual(view.offered, [STAGED, 'a06a1728', '9627b728']);
        assert.strictEqual(view.current, STAGED);
        assert.deepStrictEqual(diffs().pop(), { from: 'HEAD', to: STAGED });
        assert.ok(root.text().includes('Staged bracket.py, notes.md.'));
    });

    test('a new revision is drafted from what is staged, and sent with the index and the repository it was looked at in', () => {
        const { root, view, written, reply } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CHANGED);
        view.select(STAGED);
        // What the daemon would ask the user to agree to is said before.
        assert.ok(root.text().includes('Changed again since staged: :bracket'));

        only(root, 'revisions-new').fire('click');
        const message = only(root, 'revisions-message');
        assert.strictEqual(message.value, 'bracket: declaration, source');
        message.value = 'Longer bracket';
        message.fire('input');
        only(root, 'revisions-make').fire('click');

        assert.strictEqual(written.length, 1);
        assert.deepStrictEqual(written[0].query, {
            method: 'ops.rev.new',
            params: {
                message: 'Longer bracket',
                expectIndex: INDEX,
                includeOthers: undefined,
                yes: undefined,
                skipChecks: undefined,
            },
        });
        assert.strictEqual(written[0].directory, '/work/repo');
    });

    test('a refused revision says why, and is sent again once the user agrees', () => {
        const { root, view, written, reply } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CHANGED);
        view.select(STAGED);
        only(root, 'revisions-new').fire('click');
        only(root, 'revisions-make').fire('click');

        written[0].answer({
            error: 'Also staged, and would be in this revision: //sub',
            refusal: { code: 'others-staged', status: CHANGED },
        });
        assert.ok(root.text().includes('Also staged, and would be in this revision: //sub'));
        const include = only(root, 'revisions-include-others').children[0];
        include.checked = true;
        include.fire('change');
        only(root, 'revisions-make').fire('click');
        assert.strictEqual(written[1].query.params?.includeOthers, true);

        written[1].answer({
            error: 'Changes of // are not staged, and will not be in this revision',
            refusal: { code: 'warnings', status: CHANGED },
        });
        const yes = only(root, 'revisions-yes').children[0];
        yes.checked = true;
        yes.fire('change');
        only(root, 'revisions-make').fire('click');
        assert.strictEqual(written[2].query.params?.yes, true);
        assert.strictEqual(written[2].query.params?.includeOthers, true);

        written[2].answer({
            error: 'Checks failed on what is staged: lint: bad',
            refusal: {
                code: 'checks-failed',
                status: {
                    ...CHANGED,
                    checks: [
                        { name: 'lint', passed: false, summary: 'lint: bad' },
                        { name: 'qual test', object: '//:bracket', passed: true, summary: '//:bracket: passed' },
                    ],
                },
            },
        });
        assert.deepStrictEqual(
            only(root, 'revisions-checks').children.map((item) => item.className),
            ['failed', 'passed'],
        );
        const skip = only(root, 'revisions-skip-checks').children[0];
        skip.checked = true;
        skip.fire('change');
        only(root, 'revisions-make').fire('click');
        assert.strictEqual(written[3].query.params?.skipChecks, true);
    });

    test('a revision refused because the index moved reads the status again', () => {
        const { root, view, written, asked, reply } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CHANGED);
        view.select(STAGED);
        only(root, 'revisions-new').fire('click');
        only(root, 'revisions-make').fire('click');
        const before = asked.filter((each) => each.query.method === 'ops.rev.status').length;

        written[0].answer({
            error: 'What is staged changed since it was looked at: look again',
            refusal: { code: 'index-changed', status: CHANGED },
        });

        assert.strictEqual(asked.filter((each) => each.query.method === 'ops.rev.status').length, before + 1);
        // The form stays, for the next attempt.
        assert.strictEqual(root.find('revisions-form').length, 1);
    });

    test('a revision made is said, with who made it, and the list and the status are read again', () => {
        const { root, view, written, asked, reply } = pane();
        reply('ops.rev.list', HISTORY);
        reply('ops.rev.status', CHANGED);
        view.select(STAGED);
        only(root, 'revisions-new').fire('click');
        only(root, 'revisions-make').fire('click');
        const before = asked.length;

        written[0].answer({
            data: {
                package: '//',
                object: null,
                sha: 'c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00',
                short: 'c0ffee00',
                summary: 'bracket: declaration, source',
                checks: [{ name: 'lint', passed: true, summary: 'lint passed' }],
                author: { name: 'Ada Lovelace', email: 'ada@example.com' },
            },
        });

        assert.ok(root.text().includes('Made the revision c0ffee00'));
        assert.ok(root.text().includes('Ada Lovelace <ada@example.com>'));
        assert.deepStrictEqual(
            asked.slice(before).map((each) => each.query.method),
            ['ops.rev.list', 'ops.rev.status'],
        );
        assert.strictEqual(root.find('revisions-form').length, 0);
    });

    test('a first draft names each staged object and how, or the files where no object changed', () => {
        assert.strictEqual(draftMessage(CHANGED), 'bracket: declaration, source');
        assert.strictEqual(
            draftMessage({
                ...CLEAN,
                staged: [
                    { kind: 'part', name: 'a', object: '//:a', how: ['added'] },
                    { kind: 'part', name: 'b', object: '//:b', how: ['removed'] },
                ],
            }),
            'a: added; b: removed',
        );
        assert.strictEqual(
            draftMessage({ ...CLEAN, files: [{ path: 'README.md', sections: ['staged'] }] }),
            'Update README.md',
        );
    });

    test('a side missing, or both the same, is said over the comparison', () => {
        const same = renderComparison({ ...diff('a', 'b'), same: true, rows: [] }) as unknown as FakeElement;
        assert.ok(same.text().includes('No change between a and b'));
        const added = renderComparison({
            ...diff('a', 'b'),
            left: { label: 'a', missing: true },
        }) as unknown as FakeElement;
        assert.ok(added.text().includes('Not there at a'));
    });
});
