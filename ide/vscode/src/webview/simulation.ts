//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "Simulation" tab: what the object is supposed to do, and what it did.
//
// A list on the left and the selected simulation on the right, laid out and
// behaving like the Build tab's: the list is the object's 'simulate:' section,
// one row per simulation in the order it declares them, and the first is the
// one selected when the tab opens. Selecting one runs it - 'pc sim -f <name>' -
// the first time it is looked at for this object, and shows what came back:
//
//   * the verdict of its 'validation:' expression, as a symbol before its name
//     in the list, in green or red -- the one place it is said, so the list
//     reads as a summary of every run and the page as the detail of one;
//   * the two pictures the simulation plugin took of the scene, the one before
//     anything moved on the left and the one when the run was over on the
//     right, with an arrow between them. They are taken from where the scene is
//     looked at when it is rendered (its 'render: png:' viewpoint), and both
//     are framed alike, so what moved is seen to have moved;
//   * and, folded away under them, what the verdict is made of: the criteria
//     (the 'validation:' expression), and the 'before' and 'after' objects the
//     plugin reported, which are what that expression is evaluated over.
//
// The three folded views are a strip of titles along the bottom rather than
// three disclosure triangles one above the other: three of those open at once
// would push the pictures off the page. One is open at a time, the pictures
// make room for it, and which one is open is kept from one simulation to the
// next, so a reader comparing the 'after' of several runs can click down the
// list without reopening it.
//
// Over the page is the Draft tab's toolbar, doing for a simulation what that one
// does for a drawing: "Simulated by" picks the plugin -- the one the simulation
// names is selected, and another is 'pc sim --plugin' -- and choosing one runs
// it, the way choosing a drawing package draws again; "Simulate" runs it afresh.
//
// A run is minutes of daemon time the first time - the simulator is installed
// into a sandbox - and seconds after that, so each answer is kept for as long
// as the object is on screen, per simulation and per plugin: going back to one
// already run shows it rather than starting a simulator again. Nothing about
// running a simulation is implemented here: it is the CLI's own operation,
// asked for as data.
//

import { el, empty, placeholder } from './dom';
import {
    SIMULATION_PLUGINS,
    SimulationImage,
    SimulationListData,
    SimulationRun,
    SimulationRunData,
    SimulationScenario,
} from './messages';

export interface SimulationCallbacks {
    /**
     * Run this simulation, with this plugin or -- undefined -- the one it names
     * itself; the answer comes back through 'showRun' or 'showRunError', quoting
     * both back.
     */
    onRun: (scenario: string, plugin: string | undefined) => void;
}

/** One entry of the "Simulated by" list: the plugin, and whether it is the one the simulation names. */
interface PluginChoice {
    value: string;
    configured: boolean;
    title: string;
}

/**
 * The plugins a simulation can be run with, and which of them it names.
 *
 * The ones '//pub/feature/simulate' registers, always. The one the simulation
 * names in its 'simulation:' is usually one of them under a name of its own
 * package's ('sim-mujoco:mujoco', a dependency of that package), so it is
 * matched by what follows the ':' -- the simulation entry, which is the
 * plugin's own name for itself -- and that entry is the one marked as
 * configured. One that is neither is offered as itself, first.
 */
export function pluginChoices(configured: string | null | undefined): PluginChoice[] {
    const entry = (spec: string) => spec.slice(spec.lastIndexOf(':') + 1);
    const choices = SIMULATION_PLUGINS.map((value) => {
        const isConfigured = Boolean(configured) && entry(value) === entry(configured as string);
        return {
            value,
            configured: isConfigured,
            title: isConfigured ? `What this simulation names: ${configured}` : `Run it with ${value} instead`,
        };
    });
    if (configured && !choices.some((choice) => choice.configured)) {
        choices.unshift({ value: configured, configured: true, title: 'What this simulation names' });
    }
    return choices;
}

/** What is known about one simulation of the object on screen. */
type RunState =
    { state: 'running' } | { state: 'done'; run: SimulationRun | undefined } | { state: 'failed'; error: string };

/** The folded views under the pictures, in the order their titles are drawn. */
export type SimulationDetail = 'criteria' | 'before' | 'after';

const DETAILS: { id: SimulationDetail; label: string }[] = [
    { id: 'criteria', label: 'Criteria' },
    { id: 'before', label: 'Before' },
    { id: 'after', label: 'After' },
];

export class SimulationView {
    private readonly list = el('div', 'simulation-list');
    private readonly items = el('div', 'simulation-items');
    private readonly main = el('div', 'simulation-main');
    private scenarios: SimulationScenario[] = [];
    private selected: string | undefined;
    /** What is known of each run, by simulation and plugin (see 'key'). */
    private readonly runs = new Map<string, RunState>();
    /** The plugin each simulation is to be run with, by name; absent, the one it names. */
    private readonly plugins = new Map<string, string>();
    /** The folded view that is open, if any; kept across simulations and objects. */
    private detail: SimulationDetail | undefined;
    /** Where the folded views are drawn on the page on screen, to redraw them alone. */
    private details: HTMLElement | undefined;

    constructor(
        private readonly root: HTMLElement,
        private readonly callbacks: SimulationCallbacks,
    ) {
        root.classList.add('simulation');
        this.items.setAttribute('role', 'listbox');
        this.list.append(this.items);
        root.append(this.list, this.main);
    }

    /** The simulation selected, which is the one on screen. */
    public get current(): string | undefined {
        return this.selected;
    }

    /** The folded view that is open under the pictures, if any. */
    public get openDetail(): SimulationDetail | undefined {
        return this.detail;
    }

    /**
     * What the tab shows, for 'pc ide state': the simulations listed, which one
     * is selected, and how each run went so far -- 'running', 'passed',
     * 'failed', 'error', 'ran' (nothing to check it against), or null for one
     * not run yet.
     */
    public state(): {
        selected: string | null;
        simulations: { name: string; plugin: string; verdict: string | null }[];
    } {
        return {
            selected: this.selected ?? null,
            simulations: this.scenarios.map((scenario) => {
                const verdict = verdictOf(this.runState(scenario.name)).className.replace(/^simulation-/, '');
                return {
                    name: scenario.name,
                    plugin: this.choice(scenario.name).value,
                    verdict: verdict === 'unrun' ? null : verdict,
                };
            }),
        };
    }

    /** Whether this simulation has been asked for with the plugin it is set to, and its answer is kept or awaited. */
    public has(scenario: string): boolean {
        return this.runs.has(this.key(scenario, this.override(scenario)));
    }

    /** The plugin a simulation is set to run with: the one it names, unless another was chosen. */
    private choice(scenario: string): PluginChoice {
        const choices = pluginChoices(this.scenarios.find((entry) => entry.name === scenario)?.simulation);
        const chosen = this.plugins.get(scenario);
        return (
            choices.find((choice) => choice.value === chosen) ??
            choices.find((choice) => choice.configured) ??
            choices[0]
        );
    }

    /** What to ask the daemon to run a simulation with: undefined while that is the one it names. */
    private override(scenario: string): string | undefined {
        const choice = this.choice(scenario);
        return choice.configured ? undefined : choice.value;
    }

    private key(scenario: string, plugin: string | undefined): string {
        return `${scenario}\u0000${plugin ?? ''}`;
    }

    /** What is known of the run a simulation is set to, with the plugin it is set to. */
    private runState(scenario: string): RunState | undefined {
        return this.runs.get(this.key(scenario, this.override(scenario)));
    }

    /** Nothing to list: a different object, or one still being asked about. */
    public setBusy(text: string): void {
        this.scenarios = [];
        this.selected = undefined;
        this.runs.clear();
        this.plugins.clear();
        empty(this.items);
        this.list.hidden = true;
        this.showMain(placeholder(text));
    }

    public showError(message: string): void {
        this.setBusy('');
        this.showMain(el('p', 'error', message));
    }

    /**
     * What the object declares. The first simulation is selected, as a list
     * opened for the first time always is; the runs of the last object are
     * forgotten.
     */
    public setScenarios(data: SimulationListData): void {
        this.scenarios = data.simulations ?? [];
        this.runs.clear();
        this.plugins.clear();
        this.selected = this.scenarios[0]?.name;
        this.list.hidden = this.scenarios.length === 0;
        this.drawList();
        if (this.selected === undefined) {
            this.showMain(placeholder("This declares no simulations: it has no 'simulate:' section."));
            return;
        }
        this.showSelected();
    }

    /**
     * The tab came on screen, or a simulation was selected: run the selected
     * one, unless it has run or is running already.
     */
    public start(): void {
        if (this.selected !== undefined && !this.has(this.selected)) {
            this.run(this.selected);
        }
    }

    /** A run's answer: 'pc sim --json' for one simulation, run with 'plugin' (undefined: its own). */
    public showRun(scenario: string, data: SimulationRunData | undefined, plugin?: string): void {
        const run = data?.simulations?.find((entry) => entry.simulation === scenario) ?? data?.simulations?.[0];
        this.answered(scenario, plugin, { state: 'done', run });
    }

    /** A run that PartCAD could not even start: the request failed rather than the simulation. */
    public showRunError(scenario: string, error: string, plugin?: string): void {
        this.answered(scenario, plugin, { state: 'failed', error });
    }

    private answered(scenario: string, plugin: string | undefined, state: RunState): void {
        this.runs.set(this.key(scenario, plugin), state);
        this.drawList();
        if (scenario === this.selected) {
            this.showSelected();
        }
    }

    private run(scenario: string): void {
        const plugin = this.override(scenario);
        this.runs.set(this.key(scenario, plugin), { state: 'running' });
        this.drawList();
        if (scenario === this.selected) {
            this.showSelected();
        }
        this.callbacks.onRun(scenario, plugin);
    }

    private select(scenario: string): void {
        this.selected = scenario;
        this.drawList();
        this.showSelected();
        this.start();
    }

    private drawList(): void {
        empty(this.items);
        for (const scenario of this.scenarios) {
            const row = el('div', 'build-item simulation-item');
            row.setAttribute('role', 'option');
            row.tabIndex = 0;
            row.dataset.name = scenario.name;
            const selected = scenario.name === this.selected;
            row.classList.toggle('selected', selected);
            row.setAttribute('aria-selected', String(selected));
            // The verdict, before the name, in its colour: an empty slot of the
            // same width for one not run yet, so that the names stay in a column.
            const verdict = verdictOf(this.runState(scenario.name));
            const mark = el('span', `simulation-mark ${verdict.className}`, verdict.mark);
            mark.title = verdict.label;
            row.appendChild(mark);
            row.appendChild(el('span', 'build-title', scenario.name));
            row.title = scenario.desc ? `${scenario.name}: ${scenario.desc.trim()}` : scenario.name;
            row.addEventListener('click', () => this.select(scenario.name));
            row.addEventListener('keydown', (event: KeyboardEvent) => this.onKey(event, scenario.name));
            this.items.appendChild(row);
        }
    }

    /** Enter or Space selects; the arrow keys move through the list, as a listbox's do. */
    private onKey(event: KeyboardEvent, scenario: string): void {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            this.select(scenario);
            return;
        }
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
            return;
        }
        event.preventDefault();
        const index = this.scenarios.findIndex((entry) => entry.name === scenario);
        const next = this.scenarios[index + (event.key === 'ArrowDown' ? 1 : -1)];
        if (next !== undefined) {
            this.select(next.name);
            (this.items.querySelector(`[data-name="${CSS.escape(next.name)}"]`) as HTMLElement | null)?.focus();
        }
    }

    private showSelected(): void {
        const scenario = this.scenarios.find((entry) => entry.name === this.selected);
        if (scenario === undefined) {
            return;
        }
        const page = el('div', 'simulation-page');
        page.appendChild(this.toolbar(scenario));

        // What the run shows, between the toolbar and the folded views: it is
        // what gives up room when one of them is opened.
        const body = el('div', 'simulation-body');
        if (scenario.desc?.trim()) {
            body.appendChild(el('p', 'simulation-desc', scenario.desc.trim()));
        }
        const state = this.runState(scenario.name);
        if (state === undefined || state.state === 'running') {
            body.appendChild(
                placeholder(
                    'Running the simulation… The first run takes a while: PartCAD installs the simulator it needs.',
                ),
            );
        } else if (state.state === 'failed') {
            body.appendChild(el('p', 'error', state.error));
        } else if (state.run === undefined) {
            body.appendChild(el('p', 'error', 'PartCAD ran nothing for this simulation.'));
        } else {
            if (state.run.error) {
                body.appendChild(el('p', 'error', state.run.error));
            }
            body.appendChild(pictures(state.run));
        }
        page.appendChild(body);

        this.details = el('div', 'simulation-details');
        this.drawDetails(scenario);
        page.appendChild(this.details);
        this.showMain(page);
    }

    /**
     * The folded views: a strip of their titles, and under it the one that is
     * open. A title opens its view, and closes it again when it is the one
     * open; the open one says so with the same ▾ the Build list's open rows
     * have. Redrawn on its own, so that opening one does not reload the
     * pictures.
     */
    private drawDetails(scenario: SimulationScenario): void {
        const details = this.details;
        if (details === undefined) {
            return;
        }
        empty(details);
        const strip = el('div', 'tabs sub-tabs simulation-detail-tabs');
        strip.setAttribute('role', 'tablist');
        for (const detail of DETAILS) {
            const open = detail.id === this.detail;
            const title = el('button', `tab simulation-detail-tab${open ? ' current' : ''}`, detail.label);
            title.type = 'button';
            title.dataset.detail = detail.id;
            title.setAttribute('role', 'tab');
            title.setAttribute('aria-selected', String(open));
            title.setAttribute('aria-expanded', String(open));
            title.title = open ? `Fold ${detail.label} away` : `Show ${detail.label}`;
            if (open) {
                const chevron = el('span', 'simulation-detail-chevron', '▾');
                chevron.setAttribute('aria-hidden', 'true');
                title.appendChild(chevron);
            }
            title.addEventListener('click', () => {
                this.detail = open ? undefined : detail.id;
                this.drawDetails(scenario);
            });
            strip.appendChild(title);
        }
        details.appendChild(strip);
        if (this.detail !== undefined) {
            const view = el('div', 'simulation-detail');
            view.setAttribute('role', 'tabpanel');
            view.dataset.detail = this.detail;
            view.appendChild(this.detailContent(scenario, this.detail));
            details.appendChild(view);
        }
    }

    /** What one folded view holds, for the simulation on screen. */
    private detailContent(scenario: SimulationScenario, detail: SimulationDetail): HTMLElement {
        if (detail === 'criteria') {
            return scenario.validation
                ? el('pre', 'simulation-code', scenario.validation.trim())
                : placeholder(
                      "This simulation states no criteria: it has no 'validation:', so it runs and reports, and passes nothing.",
                  );
        }
        const state = this.runState(scenario.name);
        if (state === undefined || state.state === 'running') {
            return placeholder('Running the simulation…');
        }
        if (state.state === 'failed' || state.run === undefined || state.run.error) {
            return placeholder(`Nothing to show: the simulation did not run, so there is no '${detail}'.`);
        }
        const value = state.run.result?.[detail];
        if (value === undefined || value === null) {
            return placeholder(`The simulation plugin reported no '${detail}'.`);
        }
        return el('pre', 'simulation-code', prettyJson(value));
    }

    /**
     * The Draft tab's toolbar, for a simulation: which plugin runs it, and the
     * button that runs it afresh. Choosing a plugin runs the simulation with it
     * -- unless it already has, for this object -- the way choosing a drawing
     * package draws again.
     */
    private toolbar(scenario: SimulationScenario): HTMLElement {
        const toolbar = el('div', 'render-header simulation-toolbar');

        const plugins = el('select', 'render-select render-plugin simulation-plugin');
        plugins.setAttribute('aria-label', 'Simulated by');
        plugins.title = 'The simulation plugin that runs it';
        const current = this.choice(scenario.name).value;
        for (const choice of pluginChoices(scenario.simulation)) {
            const option = el('option', undefined, choice.value);
            option.value = choice.value;
            option.title = choice.title;
            option.selected = choice.value === current;
            plugins.appendChild(option);
        }
        plugins.value = current;
        plugins.addEventListener('change', () => {
            this.plugins.set(scenario.name, plugins.value);
            this.drawList();
            this.showSelected();
            this.start();
        });
        toolbar.appendChild(el('span', 'render-label', 'Simulated by'));
        toolbar.appendChild(plugins);

        const simulate = el('button', 'render-save simulation-run', 'Simulate');
        simulate.type = 'button';
        simulate.title = 'Run this simulation afresh, with the plugin chosen';
        simulate.disabled = this.runState(scenario.name)?.state === 'running';
        simulate.addEventListener('click', () => this.run(scenario.name));
        toolbar.appendChild(simulate);
        return toolbar;
    }

    private showMain(content: HTMLElement): void {
        empty(this.main);
        this.main.appendChild(content);
    }
}

/**
 * The two pictures, before on the left and after on the right, with an arrow
 * between them. A picture the plugin did not take is said to be missing in its
 * place, so the two never swap sides.
 */
function pictures(run: SimulationRun): HTMLElement {
    const row = el('div', 'simulation-pictures');
    const before = run.images?.before;
    const after = run.images?.after;
    if (before === undefined && after === undefined) {
        row.appendChild(
            placeholder(
                run.error
                    ? 'There are no pictures: the simulation did not run.'
                    : 'The simulation plugin took no pictures of the scene. A newer version of it may.',
            ),
        );
        return row;
    }
    row.appendChild(figure(before, 'Before'));
    const arrow = el('div', 'simulation-arrow', '→');
    arrow.setAttribute('aria-hidden', 'true');
    row.appendChild(arrow);
    row.appendChild(figure(after, 'After'));
    return row;
}

/** How long a line an array of plain values may be put on, at most. */
const INLINE_ARRAY_WIDTH = 100;

/**
 * A value as indented JSON, with every short array of plain values on one line.
 *
 * What a simulator reports is mostly vectors -- a position, a quaternion, a
 * gravity -- and JSON's own indentation puts each of their numbers on a line of
 * its own, so one body takes fifteen lines and a stack of two takes a page. An
 * array holding no object and no array is put back on one line while that line
 * stays short. Only the whitespace between values is touched: JSON writes a
 * newline inside a string as '\n', so there is no line break in one to remove.
 */
export function prettyJson(value: unknown): string {
    return JSON.stringify(value, null, 2).replace(/\[\n([^[\]{}]*?)\n\s*\]/g, (whole, inside: string) => {
        const line = `[${inside.trim().replace(/\n\s*/g, ' ')}]`;
        return line.length <= INLINE_ARRAY_WIDTH ? line : whole;
    });
}

function figure(image: SimulationImage | undefined, caption: string): HTMLElement {
    const figure = el('figure', 'simulation-figure');
    if (image === undefined) {
        figure.appendChild(placeholder('No picture.'));
    } else {
        const picture = el('img', 'simulation-image');
        picture.src = `data:${mimeType(image.extension)};base64,${image.content}`;
        picture.alt = `The scene ${caption.toLowerCase()} the simulation`;
        figure.appendChild(picture);
    }
    figure.appendChild(el('figcaption', undefined, caption));
    return figure;
}

function mimeType(extension: string): string {
    switch ((extension || '').toLowerCase()) {
        case 'jpg':
        case 'jpeg':
            return 'image/jpeg';
        case 'svg':
            return 'image/svg+xml';
        default:
            return 'image/png';
    }
}

/** How a run is marked in the list: the symbol, what it means, and the class that colours it. */
function verdictOf(state: RunState | undefined): { mark: string; label: string; className: string } {
    if (state === undefined) {
        return { mark: '', label: 'Not run yet', className: 'simulation-unrun' };
    }
    if (state.state === 'running') {
        return { mark: '…', label: 'Running', className: 'simulation-running' };
    }
    if (state.state === 'failed' || state.run === undefined || state.run.error) {
        return { mark: '!', label: 'Could not run', className: 'simulation-error' };
    }
    if (state.run.passed === true) {
        return { mark: '✓', label: 'Passed', className: 'simulation-passed' };
    }
    if (state.run.passed === false) {
        return { mark: '✗', label: 'Failed', className: 'simulation-failed' };
    }
    // Ran, and nothing said what it was supposed to do.
    return { mark: '•', label: 'Ran, with nothing to check it against', className: 'simulation-ran' };
}
