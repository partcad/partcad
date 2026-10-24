//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Analysis tabs - FEA, Dynamic FEA, Heat Transfer and CFD - as lists of the
// scenarios a part declares: which tabs are offered, which scenario is on
// screen, when one is run, which solver the toolbar over the model offers and
// selects, and what each row's mark says of its run.
//
// The pane runs in the webview and this suite in the extension host, which has
// no DOM and no WebGL, so it is given the handful of things 'dom.ts' and the
// pane ask of an element, and a stand-in for the bands the model and findings
// are drawn in ('cae.ts', which needs three.js). What is pinned is that the
// tabs apply where the part declares something, that the first scenario - or
// the one a show asked for - is selected, that each is run once for an object
// however often it is looked at, per implementation, and that the toolbar is
// the Simulation tab's: the solver a scenario runs with unasked is selected,
// and choosing another runs it with that one.
//

import * as assert from 'assert';

import {
    AnalysisView,
    CaeResultView,
    analysisGroupHint,
    analysisTabSpecs,
    implementationChoices,
} from '../../webview/analysis';
import {
    ANALYSIS_TABS,
    AnalysisTabId,
    CaeData,
    CaeListData,
    CaeRunData,
    SCENARIO_TABS,
    groupOf,
} from '../../webview/messages';

class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public disabled = false;
    public tabIndex = -1;
    public type = '';
    public value = '';
    public placeholder = '';
    public spellcheck = true;
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

    /** Raise an event the way the user would. */
    public fire(name: string, event?: unknown): void {
        (this.listeners[name] ?? []).forEach((handler) => handler(event));
    }

    /** Everything under this element with this class, in the order it is drawn. */
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
}

/** What the bands under the toolbar were last told to show. */
class FakeResult implements CaeResultView {
    public last: { kind: 'busy' | 'error' | 'render'; text?: string; data?: CaeData } | undefined;
    public renders = 0;

    public setBusy(text: string): void {
        this.last = { kind: 'busy', text };
    }

    public showError(message: string): void {
        this.last = { kind: 'error', text: message };
    }

    public render(data: CaeData): void {
        this.renders += 1;
        this.last = { kind: 'render', data };
    }

    public resize(): void {}
}

const BRACKET = '//examples/feature_cae:bracket';
const CALCULIX = '//pub/feature/cae/calculix:fea';
const ELMER = '//pub/feature/cae/elmer:fea';

/** What 'cae.list' answers for a part with two FEA scenarios and a heat transfer one, plus the host's defaults. */
function listed(overrides: Partial<CaeListData> = {}): CaeListData {
    return {
        object: BRACKET,
        kind: 'part',
        analyses: {
            fea: [
                { name: 'loaded', desc: 'A full shelf on it', implementation: null, features: ['carries-a-shelf'] },
                { name: 'dropped', desc: null, implementation: ELMER, features: [] },
            ],
            dynamic: [],
            thermal: [{ name: 'sunlit', implementation: null, features: [] }],
            cfd: [],
        },
        errors: {},
        defaults: { fea: CALCULIX },
        ...overrides,
    };
}

/** One scenario's answer, as 'cae.analyze' with 'scenario' gives it. */
function ran(scenario: string, findings = 0, error: string | null = null, implementation = CALCULIX): CaeRunData {
    const entry: CaeData = {
        object: BRACKET,
        analysis: 'fea',
        scenario,
        implementation,
        filepath: error ? null : `/tmp/bracket.fea.${scenario}.png`,
        extension: error ? null : 'png',
        content: error ? null : 'UE5H',
        findings: Array.from({ length: findings }, (_, i) => ({ message: `finding ${i}`, severity: 'warning' })),
        error,
    };
    return {
        object: BRACKET,
        analysis: 'fea',
        analyses: [entry],
        findings: entry.findings,
        total: 1,
        failed: error ? 1 : 0,
        ok: !error && findings === 0,
    };
}

function pane(analysis: AnalysisTabId = 'fea'): {
    root: FakeElement;
    view: AnalysisView;
    result: FakeResult;
    runs: [string, string | undefined][];
} {
    const root = new FakeElement('div');
    const result = new FakeResult();
    const runs: [string, string | undefined][] = [];
    const view = new AnalysisView(
        root as unknown as HTMLElement,
        analysis,
        { onRun: (scenario, implementation) => runs.push([scenario, implementation]) },
        () => result,
    );
    return { root, view, result, runs };
}

function rows(root: FakeElement): FakeElement[] {
    return root.find('cae-item');
}

/** The symbol before a scenario's name in the list. */
function mark(row: FakeElement): FakeElement {
    return row.find('cae-mark')[0];
}

/** The "Analysed by" list over the model. */
function solvers(root: FakeElement): FakeElement {
    return root.find('cae-implementation')[0];
}

/** Choose a solver in "Analysed by", the way the user would. */
function choose(root: FakeElement, implementation: string): void {
    const select = solvers(root);
    select.value = implementation;
    select.fire('change');
}

function analyseButton(root: FakeElement): FakeElement {
    return root.find('cae-run')[0];
}

function panes(): Record<AnalysisTabId, HTMLElement> {
    return Object.fromEntries(
        ANALYSIS_TABS.map((id) => [id, new FakeElement('div') as unknown as HTMLElement]),
    ) as Record<AnalysisTabId, HTMLElement>;
}

const PART = { package: '//examples/feature_cae', kind: 'part' };

suite('Digital Thread Analysis tabs', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tag: string) => new FakeElement(tag),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('a tab is enabled only where the part declares a scenario for it', () => {
        const specs = analysisTabSpecs(PART, listed(), panes());

        assert.deepStrictEqual(
            specs.map((spec) => [spec.id, spec.label, spec.disabled]),
            [
                ['fea', 'FEA', false],
                ['dynamic', 'Dynamic FEA', true],
                ['thermal', 'Heat Transfer', false],
                ['cfd', 'CFD', true],
            ],
        );
        // What a disabled one says when hovered: why it does not apply.
        assert.strictEqual(
            specs.find((spec) => spec.id === 'cfd')?.hint,
            "This part declares no CFD scenarios: it has no 'cfd:' section",
        );
    });

    test('while PartCAD is asked, and when it cannot say, every tab is disabled and says so', () => {
        const pending = analysisTabSpecs(PART, undefined, panes());
        assert.ok(pending.every((spec) => spec.disabled));
        assert.strictEqual(pending[0].hint, 'Asking PartCAD what this declares under fea:…');
        assert.strictEqual(analysisGroupHint(PART, undefined), 'Asking PartCAD what this part analyses…');

        const failed = analysisTabSpecs(PART, 'failed', panes());
        assert.ok(failed.every((spec) => spec.disabled));
        assert.ok(failed.every((spec) => spec.hint === 'PartCAD could not say what this analyses'));
    });

    test('a section that cannot be read is a tab of its own, to read why', () => {
        const specs = analysisTabSpecs(
            PART,
            listed({
                analyses: { fea: [], dynamic: [], thermal: [], cfd: [] },
                errors: { thermal: "//examples/feature_cae:bracket: 'thermal:' has no 'heat:'" },
            }),
            panes(),
        );
        assert.deepStrictEqual(
            specs.filter((spec) => !spec.disabled).map((spec) => spec.id),
            ['thermal'],
        );
    });

    test('only a part of a known package is analysed', () => {
        const assembly = analysisTabSpecs({ package: '//p', kind: 'assembly' }, listed(), panes());
        assert.ok(assembly.every((spec) => spec.disabled));
        assert.strictEqual(assembly[0].hint, 'Only a part is analysed');

        const loose = analysisTabSpecs({ package: null, kind: 'part' }, listed(), panes());
        assert.ok(loose.every((spec) => spec.disabled));
        assert.strictEqual(analysisGroupHint({ package: null, kind: 'part' }, undefined).startsWith('No '), true);
    });

    test('lists the scenarios in the order they are declared, the first one selected', () => {
        const { root, view } = pane();

        view.setScenarios(listed());

        const listedRows = rows(root);
        assert.deepStrictEqual(
            listedRows.map((row) => row.dataset.name),
            ['loaded', 'dropped'],
        );
        assert.ok(listedRows[0].className.includes('selected'));
        assert.ok(!listedRows[1].className.includes('selected'));
        assert.strictEqual(view.current, 'loaded');
        // Laid out and drawn like the Build and Simulation tabs' lists.
        assert.ok(listedRows.every((row) => row.className.split(' ').includes('build-item')));
        // What a scenario is about is its row's tooltip.
        assert.strictEqual(listedRows[0].title, 'loaded: A full shelf on it');
        assert.strictEqual(listedRows[1].title, 'dropped');
    });

    test('each tab lists its own analysis', () => {
        const { root, view } = pane('thermal');
        view.setScenarios(listed());
        assert.deepStrictEqual(
            rows(root).map((row) => row.dataset.name),
            ['sunlit'],
        );
    });

    test('runs the selected scenario when the tab is opened, and once for the object', () => {
        const { root, view, runs } = pane();
        view.setScenarios(listed());

        view.start();
        view.start();
        assert.deepStrictEqual(runs, [['loaded', undefined]]);

        // Another one, then back: the first is not run again.
        rows(root)[1].fire('click');
        view.showRun('loaded', ran('loaded'));
        rows(root)[0].fire('click');
        assert.deepStrictEqual(runs, [
            ['loaded', undefined],
            ['dropped', undefined],
        ]);
    });

    test('says how each run went before its name: found nothing, found something, could not run', () => {
        const { root, view, result } = pane();
        view.setScenarios(listed());
        view.start();

        // Before any answer, the one asked for is running and the other is a blank slot.
        assert.strictEqual(mark(rows(root)[0]).textContent, '…');
        assert.ok(mark(rows(root)[0]).className.includes('cae-running'));
        assert.strictEqual(mark(rows(root)[1]).textContent, '');
        assert.ok(mark(rows(root)[1]).className.includes('cae-unrun'));
        assert.strictEqual(result.last?.text, 'Running the analysis…');

        view.showRun('loaded', ran('loaded'));
        assert.strictEqual(mark(rows(root)[0]).textContent, '✓');
        assert.ok(mark(rows(root)[0]).className.includes('cae-passed'));
        assert.strictEqual(result.last?.kind, 'render');
        assert.strictEqual(result.last?.data?.scenario, 'loaded');

        rows(root)[1].fire('click');
        view.showRun('dropped', ran('dropped', 2), ELMER);
        // Not with the implementation it named itself: that is an answer for an override nobody made.
        assert.strictEqual(mark(rows(root)[1]).textContent, '…');
        view.showRun('dropped', ran('dropped', 2));
        assert.strictEqual(mark(rows(root)[1]).textContent, '✗');
        assert.ok(mark(rows(root)[1]).className.includes('cae-failed'));
        assert.strictEqual(mark(rows(root)[1]).title, 'Found 2 things');
    });

    test("a scenario that could not run says why where the model would be, and is marked '!'", () => {
        const { root, view, result } = pane();
        view.setScenarios(listed());
        view.start();

        const why = '//examples/feature_cae:bracket: FEA loaded: CalculiX is not installed here';
        view.showRun('loaded', ran('loaded', 0, why));

        assert.deepStrictEqual(result.last, { kind: 'error', text: why });
        assert.strictEqual(mark(rows(root)[0]).textContent, '!');
        assert.ok(mark(rows(root)[0]).className.includes('cae-error'));

        // And a request that failed outright is said on the scenario it was for.
        rows(root)[1].fire('click');
        view.showRunError('dropped', 'PartCAD is not connected.');
        assert.deepStrictEqual(result.last, { kind: 'error', text: 'PartCAD is not connected.' });
    });

    test("the toolbar is the Simulation tab's: the solver the scenario runs with unasked, and Analyse", () => {
        const { root, view } = pane();
        view.setScenarios(listed());

        // 'loaded' names none: what the user configuration runs FEA with is
        // selected, among every FEA solver '//pub/feature/cae' registers.
        assert.strictEqual(root.find('render-label')[0].textContent, 'Analysed by');
        assert.deepStrictEqual(
            solvers(root).children.map((option) => option.value),
            [CALCULIX, '//pub/feature/cae/code_aster:fea', ELMER, '//pub/feature/cae/moose:fea'],
        );
        assert.strictEqual(solvers(root).value, CALCULIX);
        assert.strictEqual(analyseButton(root).textContent, 'Analyse');
        // What the scenario says it is, under the toolbar, as a simulation's is.
        assert.strictEqual(root.find('cae-desc')[0].textContent, 'A full shelf on it');

        // 'dropped' names Elmer, and says nothing of itself.
        rows(root)[1].fire('click');
        assert.strictEqual(solvers(root).value, ELMER);
        assert.strictEqual(root.find('cae-desc')[0].hidden, true);
    });

    test('choosing another solver runs the scenario with it, and its answer is kept beside the first', () => {
        const { root, view, runs } = pane();
        view.setScenarios(listed());
        view.start();
        view.showRun('loaded', ran('loaded'));
        assert.strictEqual(mark(rows(root)[0]).textContent, '✓');

        choose(root, ELMER);
        assert.deepStrictEqual(runs, [
            ['loaded', undefined],
            ['loaded', ELMER],
        ]);
        view.showRun('loaded', ran('loaded', 1, null, ELMER), ELMER);
        assert.strictEqual(mark(rows(root)[0]).textContent, '✗');
        assert.strictEqual(view.state().scenarios[0].implementation, ELMER);

        // Back to the one it runs with unasked: that answer is still here, and
        // nothing is run again.
        choose(root, CALCULIX);
        assert.strictEqual(runs.length, 2);
        assert.strictEqual(mark(rows(root)[0]).textContent, '✓');

        // Analyse runs it afresh, with whatever is chosen - and the one it runs
        // with unasked is no override.
        analyseButton(root).fire('click');
        assert.deepStrictEqual(runs[2], ['loaded', undefined]);
        assert.strictEqual(analyseButton(root).disabled, true);
    });

    test('an answer is the one of the solver it was asked with', () => {
        const { root, view, result, runs } = pane();
        view.setScenarios(listed());
        view.start();

        // Another chosen before the first run is back: two solvers in flight
        // over one scenario.
        choose(root, ELMER);
        assert.deepStrictEqual(runs, [
            ['loaded', undefined],
            ['loaded', ELMER],
        ]);

        // The first to finish is not the one chosen last, and is not shown as its answer.
        view.showRun('loaded', ran('loaded'));
        assert.strictEqual(mark(rows(root)[0]).textContent, '…');
        assert.strictEqual(result.last?.kind, 'busy');
        view.showRun('loaded', ran('loaded', 3, null, ELMER), ELMER);
        assert.strictEqual(mark(rows(root)[0]).textContent, '✗');
        assert.strictEqual(mark(rows(root)[0]).title, 'Found 3 things');
    });

    test('the solvers a scenario is offered, and which of them it runs with unasked', () => {
        const marked = (choices: { value: string; configured: boolean }[]) =>
            choices.filter((choice) => choice.configured).map((choice) => choice.value);

        // Its own, rooted: that one exactly.
        assert.deepStrictEqual(marked(implementationChoices('fea', ELMER, CALCULIX)), [ELMER]);
        // Its own, relative to its package: matched by the package it names.
        assert.deepStrictEqual(marked(implementationChoices('fea', 'moose:fea', CALCULIX)), [
            '//pub/feature/cae/moose:fea',
        ]);
        // A package alone means the analysis's file type in it.
        assert.deepStrictEqual(marked(implementationChoices('cfd', 'openfoam', null)), [
            '//pub/feature/cae/openfoam:cfd',
        ]);
        // None of its own: the configured default.
        assert.deepStrictEqual(marked(implementationChoices('thermal', null, '//pub/feature/cae/elmer:thermal')), [
            '//pub/feature/cae/elmer:thermal',
        ]);
        // Somebody else's, or the package's own: offered as itself, first.
        const own = implementationChoices('fea', ':fea', CALCULIX);
        assert.deepStrictEqual([own[0].value, own[0].configured], [':fea', true]);
        assert.deepStrictEqual(marked(implementationChoices('fea', '//acme/cae/calculix:fea', null)), [
            '//acme/cae/calculix:fea',
        ]);
        // Nothing known at all: the configured default, unnamed, is what runs.
        const unknown = implementationChoices('dynamic', null, null);
        assert.deepStrictEqual([unknown[0].value, unknown[0].configured], ['', true]);
        assert.strictEqual(unknown.length, 4);
    });

    test('a scenario a show asked for is selected instead of the first, and only once', () => {
        const { view, runs } = pane();

        view.request('dropped');
        view.setScenarios(listed());
        assert.strictEqual(view.current, 'dropped');
        view.start();
        assert.deepStrictEqual(runs, [['dropped', undefined]]);

        // The next list, with nothing asked, opens on the first again.
        view.setScenarios(listed());
        assert.strictEqual(view.current, 'loaded');

        // A name the part does not declare selects the first, as no request does.
        view.request('misspelt');
        view.setScenarios(listed());
        assert.strictEqual(view.current, 'loaded');
    });

    test('a section that cannot be read is said in the tab, with nothing listed', () => {
        const { root, view, result, runs } = pane('thermal');
        const why = "//examples/feature_cae:bracket: 'thermal:' cannot be read: 'heat' is not a number";
        view.setScenarios(listed({ errors: { thermal: why } }));
        view.start();

        assert.deepStrictEqual(result.last, { kind: 'error', text: why });
        assert.strictEqual(rows(root).length, 0);
        assert.deepStrictEqual(runs, []);
    });

    test('a part that declares nothing for the analysis says so, and runs nothing', () => {
        const { view, result, runs } = pane('cfd');
        view.setScenarios(listed());
        view.start();

        assert.strictEqual(result.last?.text, "This part declares no CFD scenarios: it has no 'cfd:' section.");
        assert.deepStrictEqual(runs, []);
    });

    test('says which scenario is on screen and how each went, for pc ide state', () => {
        const { view } = pane();
        view.setScenarios(listed());
        view.start();
        view.showRun('loaded', ran('loaded', 1));

        assert.deepStrictEqual(view.state(), {
            selected: 'loaded',
            scenarios: [
                { name: 'loaded', implementation: CALCULIX, verdict: 'failed' },
                { name: 'dropped', implementation: ELMER, verdict: null },
            ],
        });
    });

    test('another list forgets the runs and the solvers chosen, as the Simulation tab does', () => {
        const { root, view, runs } = pane();
        view.setScenarios(listed());
        view.start();
        view.showRun('loaded', ran('loaded'));
        choose(root, ELMER);

        // The part shown again - an edit saved - or another one: its answers
        // are asked afresh, with the solver each runs with unasked.
        view.setBusy('Asking PartCAD what this declares under fea:…');
        view.setScenarios(listed({ object: '//examples/feature_cae:plate' }));
        assert.strictEqual(view.has('loaded'), false);
        assert.strictEqual(solvers(root).value, CALCULIX);
        view.start();
        assert.deepStrictEqual(runs[runs.length - 1], ['loaded', undefined]);
    });

    test('a daemon from before scenarios answers with the model at the top level, which is still drawn', () => {
        const { view, result } = pane();
        view.setScenarios(listed());
        view.start();

        const legacy: CaeData = {
            object: BRACKET,
            analysis: 'fea',
            implementation: CALCULIX,
            filepath: '/tmp/bracket.fea.png',
            extension: 'png',
            content: 'UE5H',
            findings: [],
        };
        view.showRun('loaded', legacy);
        assert.strictEqual(result.last?.kind, 'render');
        assert.strictEqual(result.last?.data?.filepath, '/tmp/bracket.fea.png');
    });

    test('a scenario is selected on the tabs that list them, as pc ide view --scenario says', () => {
        // What a show's 'scenario' can name a scenario on, and the group each
        // tab is opened in.
        assert.deepStrictEqual(SCENARIO_TABS, ['fea', 'dynamic', 'thermal', 'cfd', 'simulation']);
        for (const tab of ANALYSIS_TABS) {
            assert.strictEqual(groupOf(tab), 'analysis');
        }
    });
});
