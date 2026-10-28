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
// one selected when the tab opens (the list itself is 'scenarioList.ts', which
// the Analysis tabs list their scenarios with too). Selecting one runs it - 'pc
// sim -f <name>' - the first time it is looked at for this object, and shows
// what came back:
//
//   * the verdict of its 'validation:' expression, as a symbol before its name
//     in the list, in green or red -- the one place it is said, so the list
//     reads as a summary of every run and the page as the detail of one;
//   * the video of the run the simulation plugin recorded, in a player with the
//     usual controls -- play, pause and replay, a step back and forward, a
//     position to drag, the speed, full screen -- whose still, until it is
//     played, is the two pictures the plugin took of the scene: the one before
//     anything moved on the left and the one when the run was over on the
//     right, with an arrow between them. The player is 'videoPlayer.ts', handed
//     in as 'SimulationCallbacks.player'. A run with no video -- a plugin that
//     predates them, a machine set to record none -- shows the two pictures as
//     they are, side by side with the arrow between. All of it is taken from
//     where the scene is looked at when it is rendered (its 'render: png:'
//     viewpoint), and framed alike, so what moved is seen to have moved;
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
// does for a drawing: "Simulated by" names the plugin -- filled in with the one
// the simulation names, offering the ones '//pub/feature/simulate' registers,
// and taking any other name typed into it ('packagePicker.ts', which the Draft
// and the Analysis tabs name their packages in too); another than its own is
// 'pc sim --plugin' -- and choosing one runs it, the way choosing a drawing
// package draws again; "Simulate" runs it afresh.
//
// A run is minutes of daemon time the first time - the simulator is installed
// into a sandbox - and seconds after that, so each answer is kept for as long
// as the object is on screen, per simulation and per plugin: going back to one
// already run shows it rather than starting a simulator again. Nothing about
// running a simulation is implemented here: it is the CLI's own operation,
// asked for as data.
//

import { ObjectUrls } from './blobs';
import { el, empty, placeholder } from './dom';
import {
    SIMULATION_PLUGINS,
    SimulationImage,
    SimulationListData,
    SimulationRun,
    SimulationRunData,
    SimulationScenario,
} from './messages';
import { PackageChoice, PackagePicker, quickChoices, unaskedChoice } from './packagePicker';
import { ScenarioList, Verdict, firstSelected } from './scenarioList';
import { Viewpoint, formatVector } from './viewpoint';

export interface SimulationCallbacks {
    /**
     * Run this simulation, with this plugin or -- undefined -- the one it names
     * itself, and taking its pictures from this viewpoint or -- undefined --
     * from where its scene is rendered from; the answer comes back through
     * 'showRun' or 'showRunError', quoting all three back.
     */
    onRun: (scenario: string, plugin: string | undefined, viewpoint: Viewpoint | undefined) => void;
    /**
     * The simulation on screen changed, or its run did: where its pictures were
     * taken from, as the run said, or undefined when there is no run to say.
     * What the view panel shows.
     */
    onShown?: (viewpoint: Viewpoint | undefined) => void;
    /**
     * A player for the video of a run, with the run's pictures as its still
     * ('videoPlayer.ts'). Absent, a run is shown as its two pictures, which is
     * what a run with no video is shown as anyway.
     */
    player?: (recording: SimulationImage, still: SimulationStill) => SimulationPlayer;
}

/** The pictures a run's player shows as its still: before and after, either of which the plugin may not have taken. */
export interface SimulationStill {
    before?: SimulationImage;
    after?: SimulationImage;
}

/** A player on the page: what it is drawn as, and how to stop it when the page is drawn again. */
export interface SimulationPlayer {
    readonly element: HTMLElement;
    dispose(): void;
}

/**
 * The plugins a simulation can be run with, and which of them it names.
 *
 * The ones '//pub/feature/simulate' registers, always. The one the simulation
 * names in its 'simulation:' is usually one of them under a name of its own
 * package's ('sim-mujoco:mujoco', a dependency of that package), so it is
 * matched by what follows the ':' -- the simulation entry, which is the
 * plugin's own name for itself -- and that entry is the one marked as
 * configured. A name rooted at '//' says which package it is, so it has to be
 * that one exactly: '//acme/sim:mujoco' is somebody else's MuJoCo, and taking
 * it for the registered one would show one plugin while running another. One
 * that is neither is offered as itself, first.
 */
export function pluginChoices(configured: string | null | undefined): PackageChoice[] {
    const entry = (spec: string) => spec.slice(spec.lastIndexOf(':') + 1);
    return quickChoices(
        SIMULATION_PLUGINS,
        configured || undefined,
        (value, named) => (named.startsWith('//') ? value === named : entry(value) === entry(named)),
        `What this simulation names: ${configured}`,
        'named by the simulation',
    );
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
    private readonly list = new ScenarioList('simulation', (name) => this.select(name));
    private readonly main = el('div', 'simulation-main');
    /**
     * The toolbar, made once and kept: an answer arriving redraws the page under
     * it, and must not take the field away from somebody typing a plugin's name.
     */
    private readonly toolbar = el('div', 'render-header simulation-toolbar');
    private readonly picker = new PackagePicker({
        label: 'Simulated by',
        title: 'The simulation plugin that runs it',
        className: 'simulation-plugin',
        onCommit: (plugin) => this.choose(plugin),
    });
    private readonly simulate = el('button', 'render-save simulation-run', 'Simulate');
    /** What the toolbar is over: the page of the simulation selected, or why there is none. */
    private readonly content = el('div', 'simulation-content');
    private scenarios: SimulationScenario[] = [];
    private selected: string | undefined;
    /**
     * The simulation a show asked for ('pc ide view --validation-simulation
     * --scenario <name>'), to select instead of the first once the list is
     * known; see 'request'.
     */
    private requested: string | undefined;
    /** What is known of each run, by simulation and plugin (see 'key'). */
    private readonly runs = new Map<string, RunState>();
    /** The pictures of those runs, which go with them. */
    private readonly urls = new ObjectUrls();
    /** The plugin each simulation is to be run with, by name, as chosen or typed; absent, the one it names. */
    private readonly plugins = new Map<string, string>();
    /** The folded view that is open, if any; kept across simulations and objects. */
    private detail: SimulationDetail | undefined;
    /**
     * Where the pictures are taken from, as the view panel set it, for every
     * simulation of the object; undefined is from where the scene is rendered
     * from. Part of what a run is (see 'key'), as the plugin is.
     */
    private viewpoint: Viewpoint | undefined;
    /** Where the folded views are drawn on the page on screen, to redraw them alone. */
    private details: HTMLElement | undefined;
    /** The player on the page on screen, if it plays a video; stopped when the page is drawn again. */
    private player: SimulationPlayer | undefined;

    constructor(
        private readonly root: HTMLElement,
        private readonly callbacks: SimulationCallbacks,
    ) {
        root.classList.add('simulation');
        this.toolbar.appendChild(el('span', 'render-label', 'Simulated by'));
        this.toolbar.appendChild(this.picker.element);
        this.simulate.type = 'button';
        this.simulate.title = 'Run this simulation afresh, with the plugin named';
        // Pressed without leaving the field, so that a name typed and not yet
        // entered is the one it runs with, once.
        this.simulate.addEventListener('mousedown', (event?: { preventDefault?: () => void }) =>
            event?.preventDefault?.(),
        );
        this.simulate.addEventListener('click', () => this.afresh());
        this.toolbar.appendChild(this.simulate);
        this.toolbar.hidden = true;
        this.main.append(this.toolbar, this.content);
        root.append(this.list.element, this.main);
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
                const verdict = verdictOf(this.runState(scenario.name)).state;
                return {
                    name: scenario.name,
                    plugin: this.pluginOf(scenario.name),
                    verdict: verdict === 'unrun' ? null : verdict,
                };
            }),
        };
    }

    /** Whether this simulation has been asked for with the plugin it is set to, and its answer is kept or awaited. */
    public has(scenario: string): boolean {
        return this.runs.has(this.key(scenario, this.override(scenario), this.viewpoint));
    }

    /**
     * Take the pictures from 'viewpoint' - undefined: from where the scene is
     * rendered from - and run the simulation on screen so, unless it has been.
     * Choosing where to look from runs it, the way choosing a plugin does: the
     * pictures are taken by the run.
     */
    public setViewpoint(viewpoint: Viewpoint | undefined): void {
        this.viewpoint = viewpoint;
        if (this.selected === undefined) {
            return;
        }
        this.drawList();
        this.showSelected();
        this.start();
    }

    /** The quick choices of a simulation's "Simulated by". */
    private choices(scenario: string): PackageChoice[] {
        return pluginChoices(this.scenarios.find((entry) => entry.name === scenario)?.simulation);
    }

    /** The plugin a simulation is set to run with: the one it names, unless another was chosen or typed. */
    private pluginOf(scenario: string): string {
        return this.plugins.get(scenario) ?? unaskedChoice(this.choices(scenario))?.value ?? '';
    }

    /** What to ask the daemon to run a simulation with: undefined while that is the one it names. */
    private override(scenario: string): string | undefined {
        const unasked = unaskedChoice(this.choices(scenario));
        const plugin = this.pluginOf(scenario);
        return unasked?.configured && plugin === unasked.value ? undefined : plugin || undefined;
    }

    /** A plugin was chosen or typed into "Simulated by": run the simulation on screen with it, unless it has. */
    private choose(plugin: string): void {
        if (this.selected === undefined) {
            return;
        }
        this.plugins.set(this.selected, plugin);
        this.drawList();
        this.showSelected();
        this.start();
    }

    /** "Simulate": the simulation on screen, afresh, with what "Simulated by" says. */
    private afresh(): void {
        if (this.selected === undefined) {
            return;
        }
        const typed = this.picker.value;
        if (typed !== '') {
            this.plugins.set(this.selected, typed);
        }
        this.run(this.selected);
    }

    private key(scenario: string, plugin: string | undefined, viewpoint: Viewpoint | undefined): string {
        const from = viewpoint === undefined ? '' : `${formatVector(viewpoint.origin)}/${formatVector(viewpoint.up)}`;
        return `${scenario}\u0000${plugin ?? ''}\u0000${from}`;
    }

    /** What is known of the run a simulation is set to, with the plugin and the viewpoint it is set to. */
    private runState(scenario: string): RunState | undefined {
        return this.runs.get(this.key(scenario, this.override(scenario), this.viewpoint));
    }

    /**
     * Select this simulation rather than the first when the list next arrives,
     * or - undefined - the first, as opening the tab by hand does.
     *
     * What a show asks for ('pc ide view --validation-simulation --scenario
     * <name>'), said before the list is asked for and kept until it arrives:
     * every show says, so a request this object could not honour does not
     * linger for the next one. A name the object does not declare selects the
     * first.
     */
    public request(scenario: string | undefined): void {
        this.requested = scenario;
    }

    /** Nothing to list: a different object, or one still being asked about. */
    public setBusy(text: string): void {
        this.scenarios = [];
        this.selected = undefined;
        this.runs.clear();
        this.urls.revoke();
        this.plugins.clear();
        this.list.draw([], undefined);
        this.list.element.hidden = true;
        this.toolbar.hidden = true;
        this.showMain(placeholder(text));
    }

    public showError(message: string): void {
        this.setBusy('');
        this.requested = undefined;
        this.showMain(el('p', 'error', message));
    }

    /**
     * What the object declares. The first simulation is selected, as a list
     * opened for the first time always is - or the one a show asked for (see
     * 'request'); the runs of the last object are forgotten.
     */
    public setScenarios(data: SimulationListData): void {
        this.scenarios = data.simulations ?? [];
        this.runs.clear();
        this.urls.revoke();
        this.plugins.clear();
        this.selected = firstSelected(
            this.scenarios.map((scenario) => scenario.name),
            this.requested,
        );
        this.requested = undefined;
        this.list.element.hidden = this.scenarios.length === 0;
        this.drawList();
        if (this.selected === undefined) {
            this.toolbar.hidden = true;
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

    /**
     * A run's answer: 'pc sim --json' for one simulation, run with 'plugin'
     * (undefined: its own) and its pictures taken from 'viewpoint' (undefined:
     * the scene's).
     */
    public showRun(
        scenario: string,
        data: SimulationRunData | undefined,
        plugin?: string,
        viewpoint?: Viewpoint,
    ): void {
        const run = data?.simulations?.find((entry) => entry.simulation === scenario) ?? data?.simulations?.[0];
        this.answered(scenario, plugin, viewpoint, { state: 'done', run });
    }

    /** A run that PartCAD could not even start: the request failed rather than the simulation. */
    public showRunError(scenario: string, error: string, plugin?: string, viewpoint?: Viewpoint): void {
        this.answered(scenario, plugin, viewpoint, { state: 'failed', error });
    }

    private answered(
        scenario: string,
        plugin: string | undefined,
        viewpoint: Viewpoint | undefined,
        state: RunState,
    ): void {
        this.runs.set(this.key(scenario, plugin, viewpoint), state);
        this.drawList();
        if (scenario === this.selected) {
            this.showSelected();
        }
    }

    private run(scenario: string): void {
        const plugin = this.override(scenario);
        this.runs.set(this.key(scenario, plugin, this.viewpoint), { state: 'running' });
        this.drawList();
        if (scenario === this.selected) {
            this.showSelected();
        }
        this.callbacks.onRun(scenario, plugin, this.viewpoint);
    }

    private select(scenario: string): void {
        this.selected = scenario;
        this.drawList();
        this.showSelected();
        this.start();
    }

    private drawList(): void {
        this.list.draw(
            this.scenarios.map((scenario) => ({
                name: scenario.name,
                desc: scenario.desc,
                verdict: verdictOf(this.runState(scenario.name)),
            })),
            this.selected,
        );
    }

    private showSelected(): void {
        const scenario = this.scenarios.find((entry) => entry.name === this.selected);
        if (scenario === undefined) {
            return;
        }
        const page = el('div', 'simulation-page');
        this.drawToolbar(scenario);

        // What the run shows, between the toolbar and the folded views: it is
        // what gives up room when one of them is opened.
        const body = el('div', 'simulation-body');
        let player: SimulationPlayer | undefined;
        if (scenario.desc?.trim()) {
            body.appendChild(el('p', 'simulation-desc', scenario.desc.trim()));
        }
        const state = this.runState(scenario.name);
        // Where the pictures were taken from, for the view panel: what the run
        // said, or - before it has said - what it was asked for.
        const viewport = state?.state === 'done' ? state.run?.viewport : undefined;
        this.callbacks.onShown?.(
            viewport
                ? { origin: [...viewport.viewport_origin], up: [...viewport.viewport_up], target: [0, 0, 0] }
                : this.viewpoint,
        );
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
            const recording = state.run.recording;
            if (recording?.content && this.callbacks.player !== undefined) {
                player = this.callbacks.player(recording, state.run.images ?? {});
                body.appendChild(player.element);
            } else {
                body.appendChild(pictures(state.run, this.urls));
            }
        }
        page.appendChild(body);

        this.details = el('div', 'simulation-details');
        this.drawDetails(scenario);
        page.appendChild(this.details);
        this.showMain(page);
        this.player = player;
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
    private drawToolbar(scenario: SimulationScenario): void {
        this.toolbar.hidden = false;
        this.picker.set(this.pluginOf(scenario.name), this.choices(scenario.name));
        const running = this.runState(scenario.name)?.state === 'running';
        this.simulate.disabled = running;
        this.picker.disabled = false;
    }

    /** Put this on the page in place of whatever was there, a player included. */
    private showMain(content: HTMLElement): void {
        this.stopPlayer();
        empty(this.content);
        this.content.appendChild(content);
    }

    /** Stop the player on screen, if there is one: its video, its file, and its full screen. */
    private stopPlayer(): void {
        this.player?.dispose();
        this.player = undefined;
    }
}

/**
 * The two pictures, before on the left and after on the right, with an arrow
 * between them. A picture the plugin did not take is said to be missing in its
 * place, so the two never swap sides.
 */
function pictures(run: SimulationRun, urls: ObjectUrls): HTMLElement {
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
    row.appendChild(figure(before, 'Before', urls));
    const arrow = el('div', 'simulation-arrow', '→');
    arrow.setAttribute('aria-hidden', 'true');
    row.appendChild(arrow);
    row.appendChild(figure(after, 'After', urls));
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

function figure(image: SimulationImage | undefined, caption: string, urls: ObjectUrls): HTMLElement {
    const figure = el('figure', 'simulation-figure');
    if (image === undefined) {
        figure.appendChild(placeholder('No picture.'));
    } else {
        const picture = el('img', 'simulation-image');
        picture.src = urls.of(image.content, mimeType(image.extension));
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

/** How a run is marked in the list: the symbol, and what it means. */
function verdictOf(state: RunState | undefined): Verdict {
    if (state === undefined) {
        return { state: 'unrun', mark: '', label: 'Not run yet' };
    }
    if (state.state === 'running') {
        return { state: 'running', mark: '…', label: 'Running' };
    }
    if (state.state === 'failed' || state.run === undefined || state.run.error) {
        return { state: 'error', mark: '!', label: 'Could not run' };
    }
    if (state.run.passed === true) {
        return { state: 'passed', mark: '✓', label: 'Passed' };
    }
    if (state.run.passed === false) {
        return { state: 'failed', mark: '✗', label: 'Failed' };
    }
    // Ran, and nothing said what it was supposed to do.
    return { state: 'ran', mark: '•', label: 'Ran, with nothing to check it against' };
}
