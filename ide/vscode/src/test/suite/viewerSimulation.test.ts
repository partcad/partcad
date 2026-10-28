//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Validation group's Simulation tab: which simulation is on screen, when one
// is run, which side of the arrow each picture is on, and that a run with a
// video is played -- the pictures its still -- by the player the panel hands in.
//
// The pane runs in the webview and this suite in the extension host, which has
// no DOM, so it is given the handful of things 'dom.ts' and the pane ask of an
// element. The pictures are not decoded here; what is pinned is that the first
// simulation is the one selected, that each is run once for an object however
// often it is looked at, and that "before" is always on the left -- named by a
// Blob URL of the bytes the host posted, which Node resolves as a browser would.
//

import * as assert from 'assert';
import { resolveObjectURL } from 'buffer';

import { SimulationImage, SimulationListData, SimulationRunData, groupOf } from '../../webview/messages';
import { SimulationPlayer, SimulationStill, SimulationView, pluginChoices, prettyJson } from '../../webview/simulation';

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

function bytes(text: string): Uint8Array {
    return new TextEncoder().encode(text);
}

/** What a Blob URL the pane made names: its media type and its bytes, as text. */
async function blobAt(url: string): Promise<{ type: string; text: string }> {
    const blob = resolveObjectURL(url);
    assert.ok(blob, `${url} names nothing`);
    return { type: blob.type, text: await blob.text() };
}

const RECORDING: SimulationImage = { filename: 'video.webm', extension: 'webm', content: bytes('WEBM') };

function filmed(name: string, passed: boolean | null): SimulationRunData {
    const data = ran(name, passed);
    data.simulations[0].video = '/daemon/state/simulate/abc/video.webm';
    data.simulations[0].recording = RECORDING;
    return data;
}

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
                          before: { filename: 'snapshot-before.png', extension: 'png', content: bytes('BEFORE') },
                          after: { filename: 'snapshot-after.png', extension: 'png', content: bytes('AFTER') },
                      }
                    : undefined,
            },
        ],
    };
}

/** A player the way the panel hands one in, which says what it was asked to play and whether it was stopped. */
interface FakePlayer {
    recording: SimulationImage;
    still: SimulationStill;
    element: FakeElement;
    disposed: boolean;
}

function pane(withPlayer = false): {
    root: FakeElement;
    view: SimulationView;
    runs: string[];
    plugins: (string | undefined)[];
    players: FakePlayer[];
} {
    const root = new FakeElement('div');
    const runs: string[] = [];
    const plugins: (string | undefined)[] = [];
    const players: FakePlayer[] = [];
    const view = new SimulationView(root as unknown as HTMLElement, {
        onRun: (scenario, plugin) => {
            runs.push(scenario);
            plugins.push(plugin);
        },
        player: withPlayer
            ? (recording, still): SimulationPlayer => {
                  const element = new FakeElement('div');
                  element.className = 'fake-player';
                  const player: FakePlayer = { recording, still, element, disposed: false };
                  players.push(player);
                  return {
                      element: element as unknown as HTMLElement,
                      dispose: () => {
                          player.disposed = true;
                      },
                  };
              }
            : undefined,
    });
    return { root, view, runs, plugins, players };
}

const MUJOCO = '//pub/feature/simulate/mujoco:mujoco';
const GAZEBO = '//pub/feature/simulate/gazebo:gazebo';

/** The "Simulated by" field of the page on screen: a combo box ('packagePicker.ts'). */
function pluginSelect(root: FakeElement): FakeElement {
    return root.find('simulation-plugin')[0];
}

/** The quick choices "Simulated by" offers, in order. */
function offered(root: FakeElement): string[] {
    return root.find('package-picker-option').map((option) => option.find('package-picker-value')[0].textContent);
}

/** Name another plugin, the way the user would: typed into the field, and the field left. */
function choose(root: FakeElement, plugin: string): void {
    const field = pluginSelect(root);
    field.value = plugin;
    field.fire('blur');
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

    test('a viewpoint chosen in the view panel runs it again, its pictures taken from there', () => {
        const root = new FakeElement('div');
        const asked: { scenario: string; viewpoint: unknown }[] = [];
        const shownFrom: unknown[] = [];
        const view = new SimulationView(root as unknown as HTMLElement, {
            onRun: (scenario, _plugin, viewpoint) => asked.push({ scenario, viewpoint }),
            onShown: (viewpoint) => shownFrom.push(viewpoint),
        });
        view.setScenarios(LIST);
        view.start();
        // Where the scene says it is looked at from, which the run says.
        const answer = ran('falls', true);
        // eslint-disable-next-line @typescript-eslint/naming-convention
        answer.simulations[0].viewport = { viewport_origin: [100, -100, 100], viewport_up: [0, 0, 1] };
        view.showRun('falls', answer);
        assert.deepStrictEqual(shownFrom[shownFrom.length - 1], {
            origin: [100, -100, 100],
            up: [0, 0, 1],
            target: [0, 0, 0],
        });

        const top = { origin: [0, 0, 100] as [number, number, number], up: [0, 1, 0] as [number, number, number] };
        view.setViewpoint({ ...top, target: [0, 0, 0] });
        assert.deepStrictEqual(
            asked.map((run) => run.scenario),
            ['falls', 'falls'],
        );
        assert.deepStrictEqual(asked[1].viewpoint, { ...top, target: [0, 0, 0] });
        // Running: nothing is known of where this one's pictures were taken but what was asked.
        assert.deepStrictEqual(shownFrom[shownFrom.length - 1], { ...top, target: [0, 0, 0] });
        // And going back to where the scene says shows the run already answered,
        // without running it again.
        view.setViewpoint(undefined);
        assert.strictEqual(asked.length, 2);
        assert.strictEqual(root.find('simulation-pictures').length, 1);
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

    test('shows the scene before on the left and after on the right, with an arrow between', async () => {
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
        assert.deepStrictEqual(await blobAt(before.src), { type: 'image/png', text: 'BEFORE' });
        assert.deepStrictEqual(await blobAt(after.src), { type: 'image/png', text: 'AFTER' });
        assert.deepStrictEqual(
            row.children.filter((child) => child.tagName === 'figure').map((figure) => figure.children[1].textContent),
            ['Before', 'After'],
        );
        // The verdict is said once, before the name in the list, in its colour.
        assert.strictEqual(mark(rows(root)[0]).textContent, '✓');
        assert.ok(mark(rows(root)[0]).className.includes('simulation-passed'));
        assert.strictEqual(mark(rows(root)[0]).title, 'Passed');
    });

    test('a run with a video is played, its pictures the still, instead of being shown side by side', () => {
        const { root, view, players } = pane(true);
        view.setScenarios(LIST);
        view.start();

        view.showRun('falls', filmed('falls', true));

        assert.strictEqual(players.length, 1);
        const [player] = players;
        assert.deepStrictEqual(player.recording, RECORDING);
        assert.deepStrictEqual(player.still.before?.content, bytes('BEFORE'));
        assert.deepStrictEqual(player.still.after?.content, bytes('AFTER'));
        assert.strictEqual(root.find('fake-player').length, 1);
        assert.strictEqual(root.find('simulation-pictures').length, 0);
        // The verdict is still the list's to say.
        assert.strictEqual(mark(rows(root)[0]).textContent, '✓');
        // Opening a folded view does not start the video again.
        detailTitle(root, 'after').fire('click');
        assert.strictEqual(players.length, 1);
        assert.strictEqual(player.disposed, false);
    });

    test('a player is stopped when the page it is on is drawn again, or put away', () => {
        const { root, view, players } = pane(true);
        view.setScenarios(LIST);
        view.start();
        view.showRun('falls', filmed('falls', true));

        // Another simulation selected: the first one's video stops.
        rows(root)[1].fire('click');
        assert.strictEqual(players[0].disposed, true);
        view.showRun('falls_in_gazebo', filmed('falls_in_gazebo', null));
        assert.strictEqual(players.length, 2);

        // Run afresh: the old answer's player goes with it.
        root.find('simulation-run')[0].fire('click');
        assert.strictEqual(players[1].disposed, true);

        // And a new object puts every player away.
        view.showRun('falls_in_gazebo', filmed('falls_in_gazebo', null));
        view.setBusy('Loading…');
        assert.strictEqual(players[2].disposed, true);
    });

    test('a run with no video, or a panel with no player, shows the pictures side by side', () => {
        const withPlayer = pane(true);
        withPlayer.view.setScenarios(LIST);
        withPlayer.view.start();
        withPlayer.view.showRun('falls', ran('falls', true));
        assert.strictEqual(withPlayer.players.length, 0);
        assert.strictEqual(withPlayer.root.find('simulation-pictures').length, 1);

        const withoutPlayer = pane();
        withoutPlayer.view.setScenarios(LIST);
        withoutPlayer.view.start();
        withoutPlayer.view.showRun('falls', filmed('falls', true));
        assert.strictEqual(withoutPlayer.root.find('simulation-pictures').length, 1);
    });

    test('the page repeats neither the name nor the verdict, which the list says', () => {
        const { root, view } = pane();
        view.setScenarios(LIST);
        view.start();
        view.showRun('falls', ran('falls', true));

        const [page] = root.find('simulation-page');
        assert.strictEqual(page.find('simulation-mark').length, 0);
        // The toolbar is over the page, and kept while the page is drawn again.
        assert.ok(!root.find('simulation-toolbar')[0].text().includes('falls'));
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
        assert.deepStrictEqual(offered(root), [MUJOCO, GAZEBO]);
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

    test('any plugin may be named, not only the ones offered', () => {
        const { root, view, plugins } = pane();
        view.setScenarios(LIST);
        view.start();

        choose(root, '//acme/sim:bullet');
        assert.deepStrictEqual(plugins, [undefined, '//acme/sim:bullet']);
        assert.strictEqual(pluginSelect(root).value, '//acme/sim:bullet');
        assert.strictEqual(view.state().simulations[0].plugin, '//acme/sim:bullet');
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

    test("a rooted name is that package's plugin, not the registered one of the same name", () => {
        assert.deepStrictEqual(
            pluginChoices('//acme/sim:mujoco').map((choice) => [choice.value, choice.configured]),
            [
                ['//acme/sim:mujoco', true],
                [MUJOCO, false],
                [GAZEBO, false],
            ],
        );
        assert.deepStrictEqual(
            pluginChoices(MUJOCO).map((choice) => [choice.value, choice.configured]),
            [
                [MUJOCO, true],
                [GAZEBO, false],
            ],
        );
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

    test("a simulation a show asked for is selected instead of the first ('pc ide view --scenario')", () => {
        const { view, runs } = pane();

        view.request('falls_in_gazebo');
        view.setScenarios(LIST);
        assert.strictEqual(view.current, 'falls_in_gazebo');
        view.start();
        assert.deepStrictEqual(runs, ['falls_in_gazebo']);

        // Asked for once: the next object's list opens on its first again.
        view.setScenarios(LIST);
        assert.strictEqual(view.current, 'falls');

        // And one the object does not declare selects the first, as no request does.
        view.request('flies');
        view.setScenarios(LIST);
        assert.strictEqual(view.current, 'falls');
    });

    test("'pc ide view --validation-simulation' opens the Validation group on Simulation", () => {
        assert.strictEqual(groupOf('simulation'), 'validation');
        // Process Emulation holds nothing, so nothing can ask for it.
        assert.strictEqual(groupOf('emulation'), undefined);
    });
});
