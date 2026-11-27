//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Operations group's Dependencies, Used By and Impact tabs: what each asks
// the daemon, what it draws of the answer, and what each of its buttons sends -
// a dependency declared, removed or updated, the workspace loaded, a change
// measured or tested. And the host's half: what an Operations question is asked
// about ('<package>@<state>', the package or the object), who a new revision is
// made as, and which errors are a revision refused rather than a failure.
//
// The panes run in the webview and this suite in the extension host, which has
// no DOM, so it is given the handful of things 'dom.ts' and the panes ask of an
// element (as 'viewerRevisions.test.ts' is).
//

import * as assert from 'assert';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

import { OPS_COMMANDS, gitIdentity, opsArgs, refusalOf } from '../../viewer/operations';
import { DependenciesView, removed, updated } from '../../webview/dependencies';
import { ImpactView, describeMeasured, describeTested, rangeStates } from '../../webview/impact';
import {
    ImpactData,
    OpsQuery,
    OpsReadMethod,
    OpsWriteMethod,
    PackageDepsData,
    STAGED,
    UsedByData,
    WORKTREE,
} from '../../webview/messages';
import { OpsAnswer, OpsCallbacks, OpsSubject, OpsWritten } from '../../webview/operations';
import { UsedByView, behind, renderUsedBy } from '../../webview/usedBy';

/** The element last given the focus. */
let focused: FakeElement | undefined;

class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public disabled = false;
    public checked = false;
    public value = '';
    public placeholder = '';
    public spellcheck = false;
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

    public focus(): void {
        focused = this;
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

const PACKAGE: OpsSubject = { package: '//', name: '//', kind: 'package' };
const PART: OpsSubject = { package: '//', name: 'bracket', kind: 'part' };
const PIN = 'f00dfeed00000000000000000000000000000000';

const DEPS: PackageDepsData = {
    package: '//',
    object: null,
    kind: 'package',
    declared: [
        {
            name: 'std',
            package: '//std',
            current: '//std',
            sha: PIN,
            short: 'f00dfeed',
            versioned: `//std@${PIN}`,
            type: 'git',
            location: 'https://example.com/std.git',
            track: 'main',
            pinned: PIN,
        },
        {
            name: 'local',
            package: '//local',
            current: '//local',
            sha: null,
            short: null,
            versioned: null,
            type: null,
            location: '../local',
            track: null,
            pinned: null,
        },
    ],
    undeclared: [{ package: '//pub/std/metric', users: [{ name: 'frame', object: '//:frame', count: 2 }] }],
    subpackages: [{ name: 'sub', package: '//sub' }],
};

interface Asked {
    query: OpsQuery<OpsReadMethod>;
    answer: OpsAnswer;
}

interface Written {
    query: OpsQuery<OpsWriteMethod>;
    answer: OpsWritten;
}

function callbacks() {
    const asked: Asked[] = [];
    const written: Written[] = [];
    const opened: string[] = [];
    const shown: string[] = [];
    const ops: OpsCallbacks = {
        ask: (query, answer) => asked.push({ query, answer }),
        write: (query, answer) => written.push({ query, answer }),
        openPackage: (name) => opened.push(name),
        showObject: (object) => shown.push(`${object.package}:${object.name}`),
        copy: () => undefined,
    };
    return { ops, asked, written, opened, shown };
}

function only(root: FakeElement, className: string): FakeElement {
    const found = root.find(className);
    assert.strictEqual(found.length, 1, `expected one '${className}', found ${found.length}`);
    return found[0];
}

function rowOf(root: FakeElement, name: string): FakeElement {
    const found = root.find('deps-dependency').find((row) => row.dataset.name === name);
    assert.ok(found, `no dependency '${name}'`);
    return found;
}

suite('Digital Thread Operations: Dependencies, Used By and Impact', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tag: string) => new FakeElement(tag),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test("a package's dependencies are listed with what each declaration says, and where each is", () => {
        const root = new FakeElement('div');
        const { ops, asked, opened } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        assert.deepStrictEqual(asked[0].query, { method: 'ops.deps.list' });

        asked[0].answer(DEPS);

        const std = rowOf(root, 'std');
        assert.ok(std.text().includes('https://example.com/std.git'));
        assert.ok(std.text().includes('main'));
        assert.ok(std.find('deps-pinned')[0].textContent === 'f00dfeed');
        std.find('deps-name')[0].fire('click');
        std.find('deps-sha')[0].fire('click');
        assert.deepStrictEqual(opened, ['//std', `//std@${PIN}`]);
        // One in no repository says so where its commit would be.
        assert.ok(rowOf(root, 'local').text().includes('not in a repository'));
        // What its objects use without declaring it is listed; the sub-packages
        // are folded away until asked for.
        assert.ok(only(root, 'deps-undeclared').text().includes('//pub/std/metric'));
        assert.strictEqual(root.find('deps-subpackages').length, 0);
        root.find('ops-section-title')
            .find((title) => title.dataset.section === 'subpackages')
            ?.fire('click');
        assert.strictEqual(root.find('deps-subpackages').length, 1);
    });

    test('Update moves one pin, and is offered only to a dependency that tracks a branch', () => {
        const root = new FakeElement('div');
        const { ops, asked, written } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        asked[0].answer(DEPS);

        assert.strictEqual(rowOf(root, 'local').find('deps-update')[0].disabled, true);
        rowOf(root, 'std').find('deps-update')[0].fire('click');

        assert.deepStrictEqual(written[0].query, {
            method: 'ops.deps.update',
            whole: true,
            params: { names: ['std'] },
        });
        written[0].answer({ data: { pinned: 1, current: 0, failed: 0, count: 1, package: '//' } });
        // What the package declares now is asked again.
        assert.deepStrictEqual(asked[1].query, { method: 'ops.deps.list' });
        assert.ok(root.text().includes('Updated std: pinned 1 to the tip of its branch.'));
    });

    test('Remove asks to be confirmed, then takes the dependency out and says what still uses it', () => {
        const root = new FakeElement('div');
        const { ops, asked, written } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        asked[0].answer(DEPS);

        rowOf(root, 'std').find('deps-remove')[0].fire('click');
        assert.strictEqual(written.length, 0);
        rowOf(root, 'std').find('deps-confirm')[0].fire('click');

        assert.deepStrictEqual(written[0].query, { method: 'ops.deps.remove', whole: true, params: { name: 'std' } });
        written[0].answer({ data: { package: '//', name: 'std', removed: true, users: ['//:frame'] } });
        assert.ok(root.text().includes('Still used by //:frame'));
    });

    test('Add dependency declares one from the form, and Declare fills it in from a package used but not declared', () => {
        const root = new FakeElement('div');
        const { ops, asked, written } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        asked[0].answer(DEPS);

        only(root, 'deps-declare').fire('click');
        const field = (key: string) => {
            const found = root.find('requirements-input').find((input) => input.dataset.field === key);
            assert.ok(found, `no field '${key}'`);
            return found;
        };
        assert.strictEqual(field('name').value, 'metric');

        // A name alone is not enough.
        only(root, 'deps-add-confirm').fire('click');
        assert.strictEqual(written.length, 0);
        assert.ok(root.text().includes('needs a name and a location'));

        field('location').value = 'https://example.com/metric.git';
        field('location').fire('input');
        field('track').value = 'main';
        field('track').fire('input');
        only(root, 'deps-add-confirm').fire('click');
        assert.deepStrictEqual(written[0].query, {
            method: 'ops.deps.add',
            whole: true,
            params: { name: 'metric', location: 'https://example.com/metric.git', track: 'main' },
        });
        written[0].answer({ data: { package: '//', name: 'metric', added: true } });
        assert.strictEqual(root.find('deps-form').length, 0);
        assert.strictEqual(asked.length, 2);
    });

    test('a draft of Add dependency outlives Update all, and Declare waits for a change in flight', () => {
        const root = new FakeElement('div');
        const { ops, asked, written } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        asked[0].answer(DEPS);
        only(root, 'deps-add').fire('click');
        const location = root.find('requirements-input').find((input) => input.dataset.field === 'location');
        assert.ok(location);
        location.value = '../metric';
        location.fire('input');

        only(root, 'deps-update-all').fire('click');
        assert.strictEqual(only(root, 'deps-declare').disabled, true);
        written[0].answer({ data: { pinned: 1, current: 0, failed: 0 } });
        asked[asked.length - 1].answer(DEPS);

        const kept = root.find('requirements-input').find((input) => input.dataset.field === 'location');
        assert.strictEqual(kept?.value, '../metric');
        assert.strictEqual(only(root, 'deps-declare').disabled, false);
    });

    test('a change that failed reads the declaration again, which it may have changed, and keeps saying why', () => {
        const root = new FakeElement('div');
        const { ops, asked, written } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        asked[0].answer(DEPS);

        only(root, 'deps-update-all').fire('click');
        written[0].answer({ error: 'Could not fetch //std' });

        assert.deepStrictEqual(asked[1].query, { method: 'ops.deps.list' });
        asked[1].answer(DEPS);
        assert.ok(root.text().includes('Could not fetch //std'));
        assert.strictEqual(root.find('deps-declared').length, 1);
    });

    test('a change in flight is waited for by the tab started over, and only it ends the wait', () => {
        const root = new FakeElement('div');
        const { ops, asked, written } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        asked[0].answer(DEPS);
        only(root, 'deps-update-all').fire('click');

        // Saved meanwhile: started over on the same package, which waits for it.
        view.setBusy('Select this tab to see what this package depends on.');
        view.start({ ...PACKAGE });
        asked[1].answer(DEPS);
        assert.strictEqual(only(root, 'deps-update-all').disabled, true);
        only(root, 'deps-update-all').fire('click');
        assert.strictEqual(written.length, 1);
        written[0].answer({ data: { pinned: 1, current: 0, failed: 0 } });
        asked[asked.length - 1].answer(DEPS);
        assert.strictEqual(only(root, 'deps-update-all').disabled, false);

        // One sent for another package meanwhile is not ended by the first's answer.
        only(root, 'deps-update-all').fire('click');
        const other: OpsSubject = { package: '//other', name: '//other', kind: 'package' };
        view.setBusy('');
        view.start(other);
        asked[asked.length - 1].answer(DEPS);
        only(root, 'deps-update-all').fire('click');
        assert.strictEqual(written.length, 3);
        written[1].answer({ data: { pinned: 1, current: 0, failed: 0 } });
        assert.strictEqual(only(root, 'deps-update-all').disabled, true);
        written[2].answer({ data: { pinned: 0, current: 1, failed: 0 } });
        asked[asked.length - 1].answer(DEPS);
        assert.strictEqual(only(root, 'deps-update-all').disabled, false);
    });

    test("a change still in flight for a package is waited for on going back to it, after another package's", () => {
        const root = new FakeElement('div');
        const { ops, asked, written } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        const other: OpsSubject = { package: '//other', name: '//other', kind: 'package' };
        view.start(PACKAGE);
        asked[0].answer(DEPS);
        only(root, 'deps-update-all').fire('click');

        // On to another package, and a change of its own sent there.
        view.setBusy('');
        view.start(other);
        asked[asked.length - 1].answer(DEPS);
        only(root, 'deps-update-all').fire('click');
        assert.strictEqual(written.length, 2);

        // Back to the first, whose change is still out: it waits, and sends no second.
        view.setBusy('');
        view.start({ ...PACKAGE });
        asked[asked.length - 1].answer(DEPS);
        assert.strictEqual(only(root, 'deps-update-all').disabled, true);
        only(root, 'deps-update-all').fire('click');
        assert.strictEqual(written.length, 2);

        // The other's answer does not end the wait - drawn again, it still waits; its own does.
        written[1].answer({ data: { pinned: 0, current: 1, failed: 0 } });
        root.find('ops-section-title')
            .find((title) => title.dataset.section === 'subpackages')
            ?.fire('click');
        assert.strictEqual(only(root, 'deps-update-all').disabled, true);
        written[0].answer({ data: { pinned: 1, current: 0, failed: 0 } });
        asked[asked.length - 1].answer(DEPS);
        assert.strictEqual(only(root, 'deps-update-all').disabled, false);
    });

    test('a change made when the package is shown again is said on the tab started over, and not on another', () => {
        const root = new FakeElement('div');
        const { ops, asked, written } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        asked[0].answer(DEPS);
        rowOf(root, 'std').find('deps-update')[0].fire('click');

        // Saved meanwhile: the same package shown again, and the tab started over.
        view.setBusy('Select this tab to see what this package depends on.');
        view.start({ ...PACKAGE });
        asked[1].answer(DEPS);
        written[0].answer({ data: { pinned: 1, current: 0, failed: 0 } });
        asked[asked.length - 1].answer(DEPS);
        assert.ok(root.text().includes('Updated std: pinned 1 to the tip of its branch.'));

        rowOf(root, 'std').find('deps-update')[0].fire('click');
        view.setBusy('');
        view.start({ ...PACKAGE, package: '//other', name: '//other' });
        const before = asked.length;
        written[1].answer({ data: { pinned: 1, current: 0, failed: 0 } });
        assert.strictEqual(asked.length, before);
        assert.ok(!root.text().includes('Updated std'));
    });

    test("an object's dependencies are the objects it names, how, and the commit each comes from", () => {
        const root = new FakeElement('div');
        const { ops, asked, opened, shown } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PART);

        asked[0].answer({
            package: '//',
            object: '//:bracket',
            kind: 'part',
            dependencies: [
                {
                    object: '//std:bolt',
                    package: '//std',
                    name: 'bolt',
                    kind: 'part',
                    how: ['source (alias)'],
                    count: 1,
                    revision: PIN,
                    short: 'f00dfeed',
                },
            ],
        });

        assert.ok(only(root, 'deps-objects').text().includes('source (alias)'));
        root.find('ops-open')[0].fire('click');
        assert.deepStrictEqual(shown, ['//std:bolt']);
        only(root, 'deps-sha').fire('click');
        assert.deepStrictEqual(opened, [`//std@${PIN}`]);
        // Nothing to change on an object: no toolbar, no form.
        assert.strictEqual(root.find('deps-add').length, 0);
    });

    test('an object of a package named at a revision opens that package as it is named, with no second revision', () => {
        const root = new FakeElement('div');
        const { ops, asked, opened } = callbacks();
        const view = new DependenciesView(root as unknown as HTMLElement, ops);
        view.start(PART);

        asked[0].answer({
            package: '//',
            object: '//:bracket',
            kind: 'part',
            dependencies: [
                {
                    object: `//std@${PIN}:bolt`,
                    package: `//std@${PIN}`,
                    name: 'bolt',
                    kind: 'part',
                    how: ['source'],
                    count: 1,
                    revision: PIN,
                    short: 'f00dfeed',
                },
            ],
        });

        only(root, 'deps-sha').fire('click');
        assert.deepStrictEqual(opened, [`//std@${PIN}`]);
    });

    test('what uses a package is two sections: the packages that pin it, and how far behind; and the objects', () => {
        const root = new FakeElement('div');
        const { ops, asked } = callbacks();
        const view = new UsedByView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        assert.deepStrictEqual(asked[0].query, { method: 'ops.used_by', params: undefined });

        asked[0].answer({
            package: '//',
            object: null,
            kind: 'package',
            packages: [{ package: '//app', name: 'lib', type: 'git', pinned: PIN, short: 'f00dfeed', behind: 3 }],
            objects: [
                { object: '//app:frame', package: '//app', name: 'frame', kind: 'assembly', count: 2, how: ['placed'] },
            ],
        } as UsedByData);

        assert.ok(only(root, 'usedby-packages').text().includes('3 revisions behind'));
        assert.ok(only(root, 'usedby-table').text().includes('placed'));
        assert.ok(root.find('usedby-count').some((cell) => cell.textContent === '2'));
        assert.ok(root.text().includes('Of what PartCAD has loaded'));
    });

    test('Load workspace asks again, loading every package first', () => {
        const root = new FakeElement('div');
        const { ops, asked } = callbacks();
        const view = new UsedByView(root as unknown as HTMLElement, ops);
        view.start(PART);
        asked[0].answer({ objects: [] });
        assert.ok(root.text().includes('Nothing PartCAD has loaded uses this part'));

        only(root, 'ops-load').fire('click');

        assert.deepStrictEqual(asked[1].query, { method: 'ops.used_by', params: { load: true } });
        asked[1].answer({ objects: [] });
        assert.strictEqual(root.find('ops-load').length, 0);
    });

    test('a workspace that could not be loaded leaves what was found, and Load workspace to try again', () => {
        const root = new FakeElement('div');
        const { ops, asked } = callbacks();
        const view = new UsedByView(root as unknown as HTMLElement, ops);
        view.start(PART);
        asked[0].answer({
            objects: [
                { object: '//:frame', package: '//', name: 'frame', kind: 'assembly', count: 1, how: ['placed'] },
            ],
        });

        only(root, 'ops-load').fire('click');
        assert.ok(root.text().includes('Loading every package of the workspace'));
        asked[1].answer(undefined, 'Could not fetch //pub');

        assert.ok(only(root, 'usedby-table').text().includes('//:frame'));
        assert.ok(root.text().includes('Could not fetch //pub'));
        assert.ok(root.text().includes('Of what PartCAD has loaded'));
        only(root, 'ops-load').fire('click');
        assert.deepStrictEqual(asked[2].query, { method: 'ops.used_by', params: { load: true } });
    });

    test('a section folded from the keyboard keeps the focus on its title', () => {
        const root = new FakeElement('div');
        const { ops, asked } = callbacks();
        const view = new UsedByView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        asked[0].answer({ packages: [], objects: [] } as unknown as UsedByData);
        const heading = () =>
            root.find('ops-section-title').find((title) => title.dataset.section === 'packages') as FakeElement;

        const before = heading();
        before.fire('click');

        assert.notStrictEqual(heading(), before);
        assert.strictEqual(focused, heading());
        assert.strictEqual(heading().attributes['aria-expanded'], 'false');
    });

    test('Used By opens the object a row names, and says how far behind a pin is', () => {
        const host = new FakeElement('div');
        const { ops, shown } = callbacks();

        renderUsedBy(
            host as unknown as HTMLElement,
            { objects: [{ object: '//sub2:pair', package: '//sub2', name: 'pair', kind: 'assembly', count: 2 }] },
            ops,
            'this part',
        );
        host.find('ops-open')[0].fire('click');

        assert.deepStrictEqual(shown, ['//sub2:pair']);
        const pin = { package: '//a', name: 'b', type: 'git', pinned: PIN, short: 'f00dfeed' };
        assert.strictEqual(behind({ ...pin, behind: 0 }), 'up to date');
        assert.strictEqual(behind({ ...pin, behind: 1 }), '1 revision behind');
        assert.strictEqual(behind({ ...pin, behind: null }), 'not known');
    });

    test('Impact asks about what is not committed first, and the selector names the other changes', () => {
        const root = new FakeElement('div');
        const { ops, asked } = callbacks();
        const view = new ImpactView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        const params = () => asked[asked.length - 1].query.params;
        assert.deepStrictEqual(asked[0].query.method, 'ops.impact');
        assert.deepStrictEqual(params(), {
            from: 'HEAD',
            to: WORKTREE,
            load: undefined,
            measure: undefined,
            test: undefined,
        });

        const select = only(root, 'impact-range-select');
        select.value = 'staged';
        select.fire('change');
        assert.strictEqual(params()?.to, STAGED);
        view.choose('unstaged');
        assert.deepStrictEqual([params()?.from, params()?.to], [STAGED, WORKTREE]);

        // Since a revision waits for one to be typed.
        const before = asked.length;
        view.choose('since');
        assert.strictEqual(asked.length, before);
        const revision = only(root, 'impact-revision');
        revision.value = 'v1.2';
        revision.fire('change');
        assert.deepStrictEqual([params()?.from, params()?.to], ['v1.2', WORKTREE]);
    });

    test('Measure and Test ask again with what costs more, and keep asking it for the same change', () => {
        const root = new FakeElement('div');
        const { ops, asked } = callbacks();
        const view = new ImpactView(root as unknown as HTMLElement, ops);
        view.start(PART);
        const params = () => asked[asked.length - 1].query.params;

        only(root, 'impact-measure').fire('click');
        assert.strictEqual(params()?.measure, true);
        only(root, 'impact-test').fire('click');
        assert.deepStrictEqual([params()?.measure, params()?.test], [true, true]);
        // Another change is measured and tested afresh, if asked.
        view.choose('staged');
        assert.deepStrictEqual([params()?.measure, params()?.test], [undefined, undefined]);
    });

    test('another revision typed is another change: measured and tested afresh, if asked', () => {
        const root = new FakeElement('div');
        const { ops, asked } = callbacks();
        const view = new ImpactView(root as unknown as HTMLElement, ops);
        view.start(PART);
        const params = () => asked[asked.length - 1].query.params;
        view.choose('since');
        const revision = only(root, 'impact-revision');
        revision.value = 'v1.2';
        revision.fire('change');
        only(root, 'impact-measure').fire('click');
        only(root, 'impact-test').fire('click');
        assert.deepStrictEqual([params()?.from, params()?.measure, params()?.test], ['v1.2', true, true]);

        revision.value = 'v2.0';
        revision.fire('change');

        assert.deepStrictEqual([params()?.from, params()?.measure, params()?.test], ['v2.0', undefined, undefined]);
        only(root, 'impact-measure').fire('click');
        assert.deepStrictEqual([params()?.from, params()?.measure, params()?.test], ['v2.0', true, undefined]);
    });

    test('a workspace that could not be loaded leaves what was found, and Load workspace to try again, on Impact too', () => {
        const root = new FakeElement('div');
        const { ops, asked } = callbacks();
        const view = new ImpactView(root as unknown as HTMLElement, ops);
        view.start(PACKAGE);
        asked[0].answer({
            package: '//',
            object: null,
            from: 'HEAD',
            to: WORKTREE,
            changed: [],
            affects: [],
            // eslint-disable-next-line @typescript-eslint/naming-convention
            affected_by: [],
            pins: [],
            pinned: [],
            summary: { changed: 2 },
        } as ImpactData);

        only(root, 'ops-load').fire('click');
        assert.strictEqual(asked[1].query.params?.load, true);
        assert.ok(root.text().includes('loading the workspace'));
        asked[1].answer(undefined, 'Could not fetch //pub');

        assert.ok(only(root, 'impact-summary').text().includes('2 changed'));
        assert.ok(root.text().includes('Could not fetch //pub'));
        assert.ok(root.text().includes('Of what PartCAD has loaded'));
        only(root, 'ops-load').fire('click');
        assert.strictEqual(asked[2].query.params?.load, true);
        // A change chosen afterwards is not asked with a load that failed.
        asked[2].answer(undefined, 'Could not fetch //pub');
        view.choose('staged');
        assert.strictEqual(asked[3].query.params?.load, undefined);
    });

    test('an answer for a change no longer chosen is not drawn over the field asking for a revision', () => {
        const root = new FakeElement('div');
        const { ops, asked } = callbacks();
        const view = new ImpactView(root as unknown as HTMLElement, ops);
        view.start(PART);

        view.choose('since');
        asked[0].answer({
            package: '//',
            object: '//:bracket',
            from: 'HEAD',
            to: WORKTREE,
            changed: [],
            affects: [],
            // eslint-disable-next-line @typescript-eslint/naming-convention
            affected_by: [],
            pins: [],
            pinned: [],
            summary: {},
        } as ImpactData);

        assert.strictEqual(root.find('impact-summary').length, 0);
        assert.ok(root.text().includes('Type the revision'));
    });

    test('Impact draws the counts by severity, what is reached and how, and the pins', () => {
        const root = new FakeElement('div');
        const { ops, asked, shown } = callbacks();
        const view = new ImpactView(root as unknown as HTMLElement, ops);
        view.start(PART);

        const data: ImpactData = {
            package: '//',
            object: '//:bracket',
            kind: 'part',
            from: 'HEAD',
            to: WORKTREE,
            changed: [{ kind: 'part', name: 'bracket', object: '//:bracket', how: ['source'] }],
            affects: [
                {
                    kind: 'part',
                    name: 'bracket',
                    package: '//',
                    object: '//:bracket',
                    how: ['source'],
                    reached: 'changed',
                    via: [],
                    users: ['//:frame'],
                    findings: [
                        {
                            severity: 'changed',
                            analyzer: 'geometry',
                            summary: 'shape changed',
                            measured: { volume: { difference: 12.5, percent: 3.125, unit: 'mm^3' }, passed: null },
                        },
                    ],
                },
                {
                    kind: 'assembly',
                    name: 'frame',
                    package: '//',
                    object: '//:frame',
                    how: [],
                    reached: 'via',
                    via: ['//:bracket'],
                    users: [],
                    findings: [
                        { severity: 'verify', analyzer: 'requirements', summary: 'its tests need running again' },
                    ],
                },
            ],
            // eslint-disable-next-line @typescript-eslint/naming-convention
            affected_by: [
                { kind: 'sketch', name: 'outline', object: '//:outline', how: ['declaration'], path: ['//:outline'] },
            ],
            pins: [{ name: 'std', how: 'pin moved', from: PIN, to: 'c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00' }],
            pinned: [{ package: '//app', name: 'lib', type: 'git', pinned: PIN, short: 'f00dfeed', behind: 2 }],
            summary: { breaking: 0, changed: 1, verify: 1, info: 0 },
        };
        asked[0].answer(data);

        const summary = only(root, 'impact-summary');
        assert.ok(summary.text().includes('1 changed'));
        assert.ok(summary.text().includes('1 to verify'));
        const affects = only(root, 'impact-affects');
        assert.ok(affects.text().includes('via //:bracket'));
        assert.ok(affects.text().includes('measured: volume +12.5 mm^3 (+3.1%)'));
        assert.ok(only(root, 'impact-affected-by').text().includes('//:outline'));
        assert.ok(only(root, 'impact-pins').text().includes('c0ffee00'));
        assert.ok(only(root, 'usedby-packages').text().includes('2 revisions behind'));
        affects.find('ops-open')[1].fire('click');
        assert.deepStrictEqual(shown, ['//:frame']);
    });

    test('what measuring and testing found is said in words', () => {
        assert.strictEqual(describeMeasured({ error: 'not there at HEAD' }), 'not measured: not there at HEAD');
        assert.strictEqual(
            describeMeasured({ mass: { difference: -0.5, percent: -10, unit: 'kg' } }),
            'measured: mass -0.5 kg (-10%)',
        );
        assert.strictEqual(describeTested({ passed: true, failed: [] }), 'tested: passed');
        assert.strictEqual(describeTested({ passed: false, failed: ['volume'] }), 'tested: failed volume');
        assert.strictEqual(describeTested({ skipped: 'not tested' }), 'not tested');
        assert.deepStrictEqual(rangeStates('since', '  '), undefined);
    });

    test('a change says what it did in a sentence', () => {
        assert.strictEqual(updated({ pinned: 0, current: 2, failed: 0 }), '2 were there already.');
        assert.strictEqual(updated({}, 'std'), 'std: nothing to update.');
        assert.strictEqual(removed({ users: [] }, 'std'), 'Removed std.');
    });
});

suite('What the host puts to the daemon for the Operations tabs', () => {
    test('asks about the object on screen, its package, or the package at a state', () => {
        const part = { package: '//p', name: 'bracket', kind: 'part' };

        assert.deepStrictEqual(opsArgs(part, { method: 'ops.rev.list', params: { after: 'abc' } }), {
            after: 'abc',
            dependency: undefined,
            pkg: '//p',
            name: 'bracket',
            kind: 'part',
        });
        // At a revision, still about the object: what it depended on then.
        assert.deepStrictEqual(opsArgs(part, { method: 'ops.deps.list', at: 'abc' }), {
            dependency: undefined,
            pkg: '//p@abc',
            name: 'bracket',
            kind: 'part',
        });
        // About the package, which names no object.
        assert.strictEqual(opsArgs(part, { method: 'ops.used_by', whole: true }).kind, 'package');
        assert.strictEqual(
            opsArgs({ package: '//p', name: '//p', kind: 'package' }, { method: 'ops.rev.status' }).kind,
            'package',
        );
        // A dependency's name is not the subject's.
        const added = opsArgs(
            { package: '//p', name: '//p', kind: 'package' },
            { method: 'ops.deps.add', params: { name: 'std', location: '../std' } },
        );
        assert.deepStrictEqual([added.name, added.dependency, added.location], ['//p', 'std', '../std']);
    });

    test('a change is told apart from a question, and every method has a command', () => {
        assert.deepStrictEqual(
            Object.entries(OPS_COMMANDS)
                .filter(([, entry]) => entry.writes)
                .map(([method]) => method)
                .sort(),
            ['ops.deps.add', 'ops.deps.remove', 'ops.deps.update', 'ops.rev.new', 'ops.rev.stage'],
        );
        assert.strictEqual(Object.keys(OPS_COMMANDS).length, 11);
    });

    test('a revision the daemon would not make is a refusal, with its reason; any other error is not', () => {
        assert.deepStrictEqual(
            refusalOf({ code: -32002, message: 'no', data: { code: 'warnings', status: { a: 1 } } }),
            {
                code: 'warnings',
                status: { a: 1 },
            },
        );
        assert.strictEqual(refusalOf({ code: -32002, message: 'no' }), undefined);
        assert.strictEqual(refusalOf(new Error('no')), undefined);
        assert.strictEqual(refusalOf(undefined), undefined);
    });

    test("a revision is made as the user git names in the package's repository, on this machine", async () => {
        const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-identity-'));
        try {
            execFileSync('git', ['init', '-q'], { cwd: directory });
            execFileSync('git', ['config', 'user.name', 'Ada Lovelace'], { cwd: directory });
            execFileSync('git', ['config', 'user.email', 'ada@example.com'], { cwd: directory });
            assert.deepStrictEqual(await gitIdentity(directory), { name: 'Ada Lovelace', email: 'ada@example.com' });
            // A repository that is not on this machine is asked about where the workspace is.
            assert.deepStrictEqual(await gitIdentity('/no/such/repository', directory), {
                name: 'Ada Lovelace',
                email: 'ada@example.com',
            });
            // No git at all names nobody, rather than failing.
            assert.deepStrictEqual(await gitIdentity(directory, undefined, path.join(directory, 'no-such-git')), {});
        } finally {
            fs.rmSync(directory, { recursive: true, force: true });
        }
    });
});
