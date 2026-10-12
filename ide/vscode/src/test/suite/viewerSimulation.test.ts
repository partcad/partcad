//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Validation group's Simulation tab: which simulation is on screen, when one
// is run, and which side of the arrow each picture is on.
//
// The pane runs in the webview and this suite in the extension host, which has
// no DOM, so it is given the handful of things 'dom.ts' and the pane ask of an
// element. The pictures are not decoded here; what is pinned is that the first
// simulation is the one selected, that each is run once for an object however
// often it is looked at, and that "before" is always on the left.
//

import * as assert from 'assert';

import { SimulationListData, SimulationRunData } from '../../webview/messages';
import { SimulationView, pluginChoices, prettyJson } from '../../webview/simulation';

class FakeElement {
    public readonly children: FakeElement[] = [];
    public className = '';
    public textContent = '';
    public title = '';
    public hidden = false;
    public disabled = false;
    public tabIndex = -1;
    public type = '';
    public src = '';
    public alt = '';
    public value = '';
    public selected = false;
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
    public fire(name: string): void {
        (this.listeners[name] ?? []).forEach((handler) => handler());
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

    public text(): string {
        return this.textContent + this.children.map((child) => child.text()).join('');
    }
}

const LIST: SimulationListData = {
    object: '//examples/feature_simulate:unstable',
    kind: 'assembly',
    simulations: [
        { name: 'falls', desc: 'The top block topples off', simulation: 'sim-mujoco:mujoco', validation: 'True' },
        { name: 'falls_in_gazebo', desc: 'The same, in Gazebo', simulation: 'sim-gazebo:gazebo' },
    ],
};

const BEFORE = { time: 0, bodies: { top: { pos: [18, 0, 30] } } };
const AFTER = { time: 10, bodies: { top: { pos: [29.7, 0, 9.8] } } };

function ran(name: string, passed: boolean | null, images = true, error?: string): SimulationRunData {
    return {
        total: 1,
        failed: passed === false || error ? 1 : 0,
        ok: passed !== false && !error,
        simulations: [
            {
                object: LIST.object,
                simulation: name,
                passed,
                error: error ?? null,
                result: error ? {} : { before: BEFORE, after: AFTER },
                images: images
                    ? {
                          before: { filename: 'snapshot-before.png', extension: 'png', content: 'QkVGT1JF' },
                          after: { filename: 'snapshot-after.png', extension: 'png', content: 'QUZURVI=' },
                      }
                    : undefined,
            },
        ],
    };
}

function pane(): { root: FakeElement; view: SimulationView; runs: string[]; plugins: (string | undefined)[] } {
    const root = new FakeElement('div');
    const runs: string[] = [];
    const plugins: (string | undefined)[] = [];
    const view = new SimulationView(root as unknown as HTMLElement, {
        onRun: (scenario, plugin) => {
            runs.push(scenario);
            plugins.push(plugin);
        },
    });
    return { root, view, runs, plugins };
}

const MUJOCO = '//pub/feature/simulate/mujoco:mujoco';
const GAZEBO = '//pub/feature/simulate/gazebo:gazebo';

/** The "Simulated by" drop-down of the page on screen. */
function pluginSelect(root: FakeElement): FakeElement {
    return root.find('simulation-plugin')[0];
}

/** Choose another plugin, the way the user would. */
function choose(root: FakeElement, plugin: string): void {
    const select = pluginSelect(root);
    select.value = plugin;
    select.fire('change');
}

function rows(root: FakeElement): FakeElement[] {
    return root.find('simulation-item');
}

/** The symbol before a simulation's name in the list. */
function mark(row: FakeElement): FakeElement {
    return row.find('simulation-mark')[0];
}

/** The titles of the folded views under the pictures, by what they show. */
function detailTitle(root: FakeElement, detail: string): FakeElement {
    const title = root.find('simulation-detail-tab').find((tab) => tab.dataset.detail === detail);
    assert.ok(title, `no '${detail}' title`);
    return title;
}

suite('Digital Thread Simulation tab', () => {
    suiteSetup(() => {
        (globalThis as unknown as { document: unknown }).document = {
            createElement: (tag: string) => new FakeElement(tag),
        };
    });

    suiteTeardown(() => {
        delete (globalThis as unknown as { document?: unknown }).document;
    });

    test('lists the simulations in the order they are declared, the first one selected', () => {
        const { root, view } = pane();

        view.setScenarios(LIST);

        const listed = rows(root);
        assert.deepStrictEqual(
            listed.map((row) => row.dataset.name),
            ['falls', 'falls_in_gazebo'],
        );
        assert.ok(listed[0].className.includes('selected'));
        assert.ok(!listed[1].className.includes('selected'));
        assert.strictEqual(view.current, 'falls');
        // Laid out and drawn like the Build tab's list.
        assert.ok(listed.every((row) => row.className.split(' ').includes('build-item')));
    });

    test('runs the selected simulation when the tab is opened, and once for the object', () => {
        const { root, view, runs } = pane();
        view.setScenarios(LIST);

        view.start();
        view.start();
        assert.deepStrictEqual(runs, ['falls']);

        // Another one, then back: the first is not run again.
        rows(root)[1].fire('click');
        view.showRun('falls', ran('falls', true));
        rows(root)[0].fire('click');
        assert.deepStrictEqual(runs, ['falls', 'falls_in_gazebo']);
    });

    test('shows the scene before on the left and after on the right, with an arrow between', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);
        view.start();

        view.showRun('falls', ran('falls', true));

        const [row] = root.find('simulation-pictures');
        assert.deepStrictEqual(
            row.children.map((child) => child.className),
            ['simulation-figure', 'simulation-arrow', 'simulation-figure'],
        );
        const [before, after] = root.find('simulation-image');
        assert.strictEqual(before.src, 'data:image/png;base64,QkVGT1JF');
        assert.strictEqual(after.src, 'data:image/png;base64,QUZURVI=');
        assert.deepStrictEqual(
            row.children.filter((child) => child.tagName === 'figure').map((figure) => figure.children[1].textContent),
            ['Before', 'After'],
        );
        // The verdict is said once, before the name in the list, in its colour.
        assert.strictEqual(mark(rows(root)[0]).textContent, '✓');
        assert.ok(mark(rows(root)[0]).className.includes('simulation-passed'));
        assert.strictEqual(mark(rows(root)[0]).title, 'Passed');
    });

    test('the page repeats neither the name nor the verdict, which the list says', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);
        view.start();
        view.showRun('falls', ran('falls', true));

        const [page] = root.find('simulation-page');
        assert.strictEqual(page.find('simulation-mark').length, 0);
        assert.ok(!page.find('simulation-toolbar')[0].text().includes('falls'));
        assert.match(page.find('simulation-desc')[0].textContent, /topples off/);
    });

    test('a simulation not run yet has an empty slot, so the names stay in a column', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);

        assert.strictEqual(mark(rows(root)[1]).textContent, '');
        assert.ok(mark(rows(root)[1]).className.includes('simulation-unrun'));
    });

    test('the plugin it names is the one selected, among both, and is run as itself', () => {
        const { root, view, plugins } = pane();
        view.setScenarios(LIST);
        view.start();

        const select = pluginSelect(root);
        assert.deepStrictEqual(
            select.children.map((option) => option.value),
            [MUJOCO, GAZEBO],
        );
        // 'sim-mujoco:mujoco' is MuJoCo under its package's own name for it.
        assert.strictEqual(select.value, MUJOCO);
        // So nothing is overridden: the simulation runs with what it names.
        assert.deepStrictEqual(plugins, [undefined]);
        assert.match(root.find('simulation-toolbar')[0].text(), /Simulated by/);
        assert.strictEqual(root.find('simulation-run')[0].textContent, 'Simulate');
    });

    test('choosing another plugin runs it with that one, and each keeps its own answer', () => {
        const { root, view, runs, plugins } = pane();
        view.setScenarios(LIST);
        view.start();
        view.showRun('falls', ran('falls', true));

        choose(root, GAZEBO);
        assert.deepStrictEqual(plugins, [undefined, GAZEBO]);
        assert.strictEqual(mark(rows(root)[0]).textContent, '…');
        view.showRun('falls', ran('falls', false), GAZEBO);
        assert.strictEqual(mark(rows(root)[0]).textContent, '✗');

        // Back to MuJoCo: its answer is still there, and nothing runs again.
        choose(root, MUJOCO);
        assert.strictEqual(runs.length, 2);
        assert.strictEqual(mark(rows(root)[0]).textContent, '✓');
        assert.deepStrictEqual(view.state().simulations[0], { name: 'falls', plugin: MUJOCO, verdict: 'passed' });
    });

    test('a plugin that is neither of the two is offered as itself, first', () => {
        const choices = pluginChoices('//acme/sim:bullet');
        assert.deepStrictEqual(
            choices.map((choice) => [choice.value, choice.configured]),
            [
                ['//acme/sim:bullet', true],
                [MUJOCO, false],
                [GAZEBO, false],
            ],
        );
        assert.ok(pluginChoices('sim-gazebo:gazebo').find((choice) => choice.value === GAZEBO)?.configured);
    });

    test('criteria, before and after are folded away until their title is clicked', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);
        view.start();
        view.showRun('falls', ran('falls', true));

        assert.deepStrictEqual(
            root.find('simulation-detail-tab').map((tab) => tab.dataset.detail),
            ['criteria', 'before', 'after'],
        );
        assert.strictEqual(root.find('simulation-detail').length, 0);

        detailTitle(root, 'before').fire('click');
        const [open] = root.find('simulation-detail');
        assert.strictEqual(open.dataset.detail, 'before');
        // The object the plugin reported, indented to be read.
        assert.strictEqual(open.find('simulation-code')[0].textContent, prettyJson(BEFORE));
        // The open one says so, and is the one a click folds away again.
        assert.strictEqual(detailTitle(root, 'before').find('simulation-detail-chevron').length, 1);
        assert.strictEqual(detailTitle(root, 'after').find('simulation-detail-chevron').length, 0);
        detailTitle(root, 'before').fire('click');
        assert.strictEqual(root.find('simulation-detail').length, 0);
    });

    test('a vector is written on one line, and what is nested in it is not', () => {
        const text = prettyJson({ pos: [18, 0, 30], quat: [1, 0, 0, 0], samples: [{ t: 0 }], note: 'a [b]\nc' });

        assert.ok(text.includes('"pos": [18, 0, 30]'));
        assert.ok(text.includes('"quat": [1, 0, 0, 0]'));
        // An array of objects stays indented, and a string is left alone.
        assert.ok(text.includes('"samples": [\n'));
        assert.ok(text.includes('"note": "a [b]\\nc"'));
        // Still the same value.
        assert.deepStrictEqual(JSON.parse(text), {
            pos: [18, 0, 30],
            quat: [1, 0, 0, 0],
            samples: [{ t: 0 }],
            note: 'a [b]\nc',
        });
    });

    test('a long array of plain values keeps a line each', () => {
        const long = Array.from({ length: 40 }, (_, i) => i * 1000.5);
        assert.deepStrictEqual(prettyJson(long).split('\n').length, 42);
    });

    test('the criteria are the validation expression, and the open view is kept across simulations', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);
        view.start();
        detailTitle(root, 'criteria').fire('click');

        assert.strictEqual(root.find('simulation-detail')[0].find('simulation-code')[0].textContent, 'True');

        // The second declares no validation: still the criteria view, saying so.
        rows(root)[1].fire('click');
        assert.strictEqual(view.openDetail, 'criteria');
        assert.match(root.find('simulation-detail')[0].text(), /states no criteria/);
    });

    test('before and after wait for the run, and say so when there was none', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);
        view.start();
        detailTitle(root, 'after').fire('click');
        assert.match(root.find('simulation-detail')[0].text(), /Running/);

        view.showRun('falls', ran('falls', null, false, 'No Gazebo found'));
        assert.match(root.find('simulation-detail')[0].text(), /did not run/);
    });

    test('says why there is no verdict when the simulation could not run', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);
        view.start();

        view.showRun('falls', ran('falls', null, false, 'No Gazebo found'));

        assert.match(root.find('error')[0].textContent, /No Gazebo found/);
        assert.match(root.find('simulation-pictures')[0].text(), /did not run/);
        assert.strictEqual(mark(rows(root)[0]).textContent, '!');
        assert.ok(mark(rows(root)[0]).className.includes('simulation-error'));
    });

    test('a plugin that took no pictures is said to have taken none, not to have failed', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);
        view.start();

        view.showRun('falls', ran('falls', false, false));

        assert.strictEqual(root.find('simulation-image').length, 0);
        assert.match(root.find('simulation-pictures')[0].text(), /took no pictures/);
        assert.strictEqual(mark(rows(root)[0]).textContent, '✗');
        assert.ok(mark(rows(root)[0]).className.includes('simulation-failed'));
    });

    test('a request that failed is shown on the simulation it was for', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);
        view.start();

        view.showRunError('falls', 'PartCAD is not connected.');

        assert.match(root.find('error')[0].textContent, /not connected/);
    });

    test('says which simulation is on screen and how each went, for pc ide state', () => {
        const { view } = pane();
        view.setScenarios(LIST);
        view.start();
        view.showRun('falls', ran('falls', false));

        assert.deepStrictEqual(view.state(), {
            selected: 'falls',
            simulations: [
                { name: 'falls', plugin: MUJOCO, verdict: 'failed' },
                { name: 'falls_in_gazebo', plugin: GAZEBO, verdict: null },
            ],
        });
    });

    test('"Simulate" runs the simulation on screen again', () => {
        const { root, view, runs } = pane();
        view.setScenarios(LIST);
        view.start();
        view.showRun('falls', ran('falls', true));

        root.find('simulation-run')[0].fire('click');

        assert.deepStrictEqual(runs, ['falls', 'falls']);
        assert.match(root.text(), /Running the simulation/);
    });

    test('an object with nothing to simulate says so, and a new object forgets the last one', () => {
        const { root, view, runs } = pane();
        view.setScenarios(LIST);
        view.start();
        view.showRun('falls', ran('falls', true));

        view.setScenarios({ object: '//p:block', kind: 'part', simulations: [] });
        view.start();

        assert.match(root.text(), /declares no simulations/);
        assert.strictEqual(runs.length, 1);
        assert.strictEqual(view.has('falls'), false);
    });
});
