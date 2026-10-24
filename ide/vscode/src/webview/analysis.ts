//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The Analysis tabs - FEA, Dynamic FEA, Heat Transfer and CFD - as what a part
// declares for each: its scenarios, the one selected, and what each of them
// came back with.
//
// A part's 'fea:' section, like its 'dynamic:', 'thermal:' and 'cfd:', is a map
// of named scenarios, the way 'simulate:' is a map of named simulations: one
// set of boundary conditions each - fixed here, loaded there - and the
// requirement feature it demonstrates. So each tab is laid out and behaves like
// the Simulation tab ('simulation.ts'), with the same list ('scenarioList.ts'):
// one row per scenario on the left, in the order the section declares them, and
// the first selected when the tab opens. Selecting one runs it - 'pc cae
// <analysis> -f <name>' - the first time it is looked at for this object, and
// the right of the pane shows what came back: the model the solver wrote and
// what it found ('cae.ts'), or, where the scenario produced nothing, the
// sentence that says why, in the model's place. Before each name is how its run
// went: a green ✓ when it ran and found nothing, a red ✗ when it found
// something, a red ! when it could not run, … while it runs, and an empty slot
// before it has.
//
// Over the model is the Simulation tab's toolbar - which is the Draft tab's -
// doing for a scenario what that one does for a simulation: "Analysed by" picks
// the solver, and "Analyse" runs it afresh. The solver the scenario runs with
// when nobody says otherwise is selected - its own 'implementation:', or failing
// that the configured default, the order 'pc cae' resolves them in - and the
// others registered at '//pub/feature/cae' for the analysis are offered beside
// it; choosing one runs the scenario with it ('pc cae <analysis>
// --implementation'), the way choosing another plugin runs a simulation with
// it. Under the toolbar is what the scenario says it is ('desc:'), as under
// the Simulation tab's.
//
// A run is minutes of daemon time the first time - the solver is installed into
// a sandbox - so each answer is kept for as long as the object is on screen, per
// scenario and per implementation, as the Simulation tab keeps its answers per
// simulation and plugin: going back to one already run shows it rather than
// starting a solver again.
//
// This file draws none of a result itself and knows nothing of three.js: what an
// answer looks like is the 'CaeResultView' it is handed, which 'cae.ts'
// implements. That split is what lets the extension host's test suite, which has
// no WebGL, exercise everything here.
//

import { el, empty } from './dom';
import {
    ANALYSIS_LABELS,
    ANALYSIS_TABS,
    AnalysisTabId,
    CAE_IMPLEMENTATIONS,
    CaeData,
    CaeListData,
    CaeRunData,
    CaeScenario,
} from './messages';
import { ScenarioList, Verdict, firstSelected } from './scenarioList';
import { TabSpec } from './tabs';

/**
 * The bands the selected scenario's answer is drawn in: the model and the
 * findings. 'cae.ts' is the one that draws them; a test hands in one of its own.
 */
export interface CaeResultView {
    /** A sentence where the model would be: something is on its way, or there is nothing to show. */
    setBusy(text: string): void;
    /** Why there is no model, where the model would be. */
    showError(message: string): void;
    /** A scenario's model, and what it found. */
    render(data: CaeData): void;
    /** The pane came on screen: a canvas that had no size while hidden has one again. */
    resize(): void;
}

export interface AnalysisCallbacks {
    /**
     * Run this scenario, with this implementation or -- undefined -- the one
     * the scenario names, and failing that the configured default; the answer
     * comes back through 'showRun' or 'showRunError', quoting both back.
     */
    onRun: (scenario: string, implementation: string | undefined) => void;
    /** An answer arrived and could not be drawn: the pane says so, and this is for the log. */
    onFailure?: (message: string) => void;
}

/** What is known about one scenario's run, with one implementation. */
type RunState =
    { state: 'running' } | { state: 'done'; entry: CaeData | undefined } | { state: 'failed'; error: string };

/** What the panel knows about what the part on screen declares: the answer, 'failed', or undefined while it is asked. */
export type CaeListState = CaeListData | 'failed' | undefined;

/** Whether the object a show is about is one that is analysed: a part, of a package the daemon can be asked about. */
export function isAnalysed(message: { package?: string | null; kind?: string | null } | undefined): boolean {
    return Boolean(message?.package) && message?.kind === 'part';
}

/**
 * The Analysis strip for an object: FEA, Dynamic FEA, Heat Transfer and CFD,
 * all four always shown, in the order and under the names 'ANALYSIS_TABS' and
 * 'ANALYSIS_LABELS' give them, each enabled while the part declares at least one
 * scenario for it.
 *
 * What a part declares is asked of the daemon on every show ('cae.list', a
 * read of its configuration, nothing run), so until it has answered every tab
 * is disabled and says it is asking, and if it could not answer every tab says
 * that. A section that is there and cannot be read is the exception the other
 * way: its tab is enabled, with nothing to list, because the sentence saying
 * what is wrong with it is what the tab is then for.
 *
 * Only a part is analysed. An assembly is a set of parts that each have
 * boundary conditions of their own, and a load on the whole of one says nothing
 * about which member carries it - so 'pc cae' takes a part, and so does this.
 */
export function analysisTabSpecs(
    message: { package?: string | null; kind?: string | null } | undefined,
    list: CaeListState,
    panes: Record<AnalysisTabId, HTMLElement>,
): TabSpec[] {
    const analysed = isAnalysed(message);
    const state = message === undefined ? undefined : list;
    const known = state !== undefined && state !== 'failed' ? state : undefined;
    return ANALYSIS_TABS.map((id) => {
        const label = ANALYSIS_LABELS[id];
        const declared = known?.analyses?.[id]?.length ?? 0;
        const unreadable = Boolean(known?.errors?.[id]);
        let hint: string;
        if (!message?.package) {
            hint = 'PartCAD did not say which package this belongs to';
        } else if (!analysed) {
            hint = 'Only a part is analysed';
        } else if (state === undefined) {
            hint = `Asking PartCAD what this declares under ${id}:…`;
        } else if (state === 'failed') {
            hint = 'PartCAD could not say what this analyses';
        } else {
            hint = `This part declares no ${label} scenarios: it has no '${id}:' section`;
        }
        return {
            id,
            label,
            pane: panes[id],
            disabled: !analysed || known === undefined || (declared === 0 && !unreadable),
            hint,
        };
    });
}

/** What the Analysis group's own tab says when none of its tabs applies. */
export function analysisGroupHint(
    message: { package?: string | null; kind?: string | null } | undefined,
    list: CaeListState,
): string {
    if (isAnalysed(message) && list === undefined) {
        return 'Asking PartCAD what this part analyses…';
    }
    if (isAnalysed(message) && list === 'failed') {
        return 'PartCAD could not say what this analyses';
    }
    return 'No engineering analysis configurations are defined for this object';
}

/** One entry of the "Analysed by" list: the solver, and whether it is the one the scenario runs with unasked. */
export interface ImplementationChoice {
    /** As '<package>:<file type>'; empty for the configured default when nobody could say what it is. */
    value: string;
    label: string;
    configured: boolean;
    title: string;
}

/**
 * The solvers a scenario can be run with, and which of them it runs with when
 * nobody says otherwise: 'pluginChoices' ('simulation.ts'), for an analysis.
 *
 * The ones '//pub/feature/cae' registers for the analysis, always. The one the
 * scenario runs with unasked is its own 'implementation:', or failing that the
 * configured default ('cae.defaults'), and that is the one marked. A name
 * rooted at '//' says which package it is, so it has to be that one exactly; a
 * relative one ('calculix:fea', the package the part's own package imported
 * under that name) is matched by its last package name, since every one of
 * them calls its file type after the analysis and that alone names nothing.
 * One that is neither is offered as itself, first - a package's own solver,
 * ':fea'. When there is nothing to mark at all, the first entry is the
 * configured default, unnamed, so that what is selected is still what runs.
 */
export function implementationChoices(
    analysis: AnalysisTabId,
    own: string | null | undefined,
    configured: string | null | undefined,
): ImplementationChoice[] {
    const unasked = own || configured || undefined;
    const spelt = (spec: string) => (spec.includes(':') ? spec : `${spec}:${analysis}`);
    const matches = (value: string, named: string) =>
        named.startsWith('//') ? value === spelt(named) : value.endsWith(`/${spelt(named)}`);
    const why = own ? `What this scenario names: ${own}` : `The configured default: ${configured}`;
    const choices = CAE_IMPLEMENTATIONS[analysis].map((value) => {
        const isUnasked = unasked !== undefined && matches(value, unasked);
        return {
            value,
            label: value,
            configured: isUnasked,
            title: isUnasked ? why : `Run it with ${value} instead`,
        };
    });
    if (unasked === undefined) {
        choices.unshift({
            value: '',
            label: 'the configured default',
            configured: true,
            title: `Whatever 'cae${analysis.charAt(0).toUpperCase()}${analysis.slice(1)}Implementation' names`,
        });
    } else if (!choices.some((choice) => choice.configured)) {
        choices.unshift({ value: unasked, label: unasked, configured: true, title: why });
    }
    return choices;
}

/**
 * One analysis tab: the list of the part's scenarios for that analysis down the
 * left, and on the right the selected one under the Simulation tab's toolbar,
 * in the bands its answer is drawn in.
 *
 * It owns its pane for the life of the panel, as every analysis did before it
 * had scenarios: the bands hold a 3D view, and a GPU context is not something
 * to make again on every show. Fetching is the shell's job ('viewer.ts'), the
 * same as for every other tab.
 */
export class AnalysisView {
    /** What the analysis is called on its tab, which is what the pane calls it too. */
    private readonly label: string;
    private readonly list = new ScenarioList('cae', (name) => this.select(name));
    /** The Simulation tab's toolbar, drawn again for whichever scenario is selected. */
    private readonly toolbar = el('div', 'render-header cae-toolbar');
    /** What the selected scenario says it is, under the toolbar. */
    private readonly desc = el('p', 'simulation-desc cae-desc');
    private readonly result: CaeResultView;
    /** What the part declares for this analysis, in the order it declares it. */
    private scenarios: CaeScenario[] = [];
    /** What the analysis runs under when neither the user nor the scenario says. */
    private configured: string | undefined;
    private selected: string | undefined;
    /** The scenario a show asked for, to select instead of the first once the list is known; see 'request'. */
    private requested: string | undefined;
    /** What is known of each run, by scenario and implementation (see 'key'). */
    private readonly runs = new Map<string, RunState>();
    /** The implementation each scenario is to be run with, by name; absent, the one it runs with unasked. */
    private readonly chosen = new Map<string, string>();

    constructor(
        root: HTMLElement,
        private readonly analysis: AnalysisTabId,
        private readonly callbacks: AnalysisCallbacks,
        result: (host: HTMLElement) => CaeResultView,
    ) {
        this.label = ANALYSIS_LABELS[analysis];
        root.classList.add('cae');

        const body = el('div', 'cae-body');
        const main = el('div', 'cae-main');
        main.appendChild(this.toolbar);
        main.appendChild(this.desc);
        main.appendChild(body);
        root.append(this.list.element, main);
        this.result = result(body);

        this.setBusy('Waiting for PartCAD…');
    }

    /** The scenario selected, which is the one on screen. */
    public get current(): string | undefined {
        return this.selected;
    }

    /**
     * What the tab shows, for 'pc ide state': the scenarios listed, which one is
     * selected, which implementation each is set to run with, and how each run
     * went so far -- 'running', 'passed' (found nothing), 'failed' (found
     * something), 'error' (could not run), or null for one not run yet.
     */
    public state(): {
        selected: string | null;
        scenarios: { name: string; implementation: string | null; verdict: string | null }[];
    } {
        return {
            selected: this.selected ?? null,
            scenarios: this.scenarios.map((scenario) => {
                const verdict = verdictOf(this.runState(scenario.name)).state;
                return {
                    name: scenario.name,
                    implementation: this.choice(scenario.name).value || null,
                    verdict: verdict === 'unrun' ? null : verdict,
                };
            }),
        };
    }

    /** Whether this scenario has been asked for with the implementation it is set to, and its answer is kept or awaited. */
    public has(scenario: string): boolean {
        return this.runs.has(this.key(scenario, this.override(scenario)));
    }

    /** The implementation a scenario is set to run with: the one it runs with unasked, unless another was chosen. */
    private choice(scenario: string): ImplementationChoice {
        const choices = implementationChoices(
            this.analysis,
            this.scenarios.find((entry) => entry.name === scenario)?.implementation,
            this.configured,
        );
        const chosen = this.chosen.get(scenario);
        return (
            choices.find((choice) => choice.value === chosen) ??
            choices.find((choice) => choice.configured) ??
            choices[0]
        );
    }

    /** What to ask the daemon to run a scenario with: undefined while that is the one it runs with unasked. */
    private override(scenario: string): string | undefined {
        const choice = this.choice(scenario);
        return choice.configured ? undefined : choice.value;
    }

    /**
     * Select this scenario rather than the first when the list next arrives,
     * or - undefined - the first, as opening the tab by hand does.
     *
     * What a show asks for ('pc ide view --analysis-fea --scenario <name>'),
     * said before the list is asked for and kept until it arrives: every show
     * says, so a request this object could not honour does not linger for the
     * next one. A name the part does not declare selects the first.
     */
    public request(scenario: string | undefined): void {
        this.requested = scenario;
    }

    /** Nothing to list: a different object, or one still being asked about. */
    public setBusy(text: string): void {
        this.scenarios = [];
        this.selected = undefined;
        this.runs.clear();
        this.chosen.clear();
        this.list.draw([], undefined);
        this.list.element.hidden = true;
        this.hideToolbar();
        this.result.setBusy(text);
    }

    /** What the part declares could not be had: the tab says why, in the model's place. */
    public showError(message: string): void {
        this.setBusy('');
        this.requested = undefined;
        this.result.showError(message);
    }

    /**
     * What the part declares, for every analysis: this tab lists its own. The
     * first scenario is selected, as a list opened for the first time always is
     * - or the one a show asked for (see 'request'); the runs of the last object
     * are forgotten.
     */
    public setScenarios(data: CaeListData): void {
        const error = data.errors?.[this.analysis];
        this.configured = data.defaults?.[this.analysis] || undefined;
        this.scenarios = error ? [] : (data.analyses?.[this.analysis] ?? []);
        this.runs.clear();
        this.chosen.clear();
        this.selected = firstSelected(
            this.scenarios.map((scenario) => scenario.name),
            this.requested,
        );
        this.requested = undefined;
        this.list.element.hidden = this.scenarios.length === 0;
        this.drawList();
        if (error) {
            // Enabled all the same, so that this can be read: the section is
            // there, and what is wrong with it is the answer.
            this.hideToolbar();
            this.result.showError(error);
            return;
        }
        if (this.selected === undefined) {
            this.hideToolbar();
            this.result.setBusy(
                `This part declares no ${this.label} scenarios: it has no '${this.analysis}:' section.`,
            );
            return;
        }
        this.showSelected();
    }

    /**
     * The tab came on screen, or a scenario was selected: run the selected one,
     * unless it has run or is running already.
     */
    public start(): void {
        if (this.selected !== undefined && !this.has(this.selected)) {
            this.run(this.selected);
        }
    }

    /**
     * A run's answer: 'pc cae <analysis> -f <name> --json' for one scenario, run
     * with 'implementation' (undefined: its own). A daemon from before analyses
     * had scenarios answers with the one model at the top level, which is read
     * as the entry it would now be.
     */
    public showRun(scenario: string, data: CaeRunData | CaeData | undefined, implementation?: string): void {
        const entries =
            data === undefined || data === null
                ? []
                : Array.isArray((data as CaeRunData).analyses)
                  ? (data as CaeRunData).analyses
                  : [data as CaeData];
        const entry = entries.find((candidate) => candidate.scenario === scenario) ?? entries[0];
        this.answered(scenario, implementation, { state: 'done', entry });
    }

    /** A run PartCAD could not even start: the request failed rather than the scenario. */
    public showRunError(scenario: string, error: string, implementation?: string): void {
        this.answered(scenario, implementation, { state: 'failed', error });
    }

    public resize(): void {
        this.result.resize();
    }

    private key(scenario: string, implementation: string | undefined): string {
        return `${scenario}\u0000${implementation ?? ''}`;
    }

    /** What is known of the run a scenario is set to, with the implementation it is set to. */
    private runState(scenario: string): RunState | undefined {
        return this.runs.get(this.key(scenario, this.override(scenario)));
    }

    private run(scenario: string): void {
        const implementation = this.override(scenario);
        this.runs.set(this.key(scenario, implementation), { state: 'running' });
        this.drawList();
        if (scenario === this.selected) {
            this.showSelected();
        }
        this.callbacks.onRun(scenario, implementation);
    }

    private answered(scenario: string, implementation: string | undefined, state: RunState): void {
        this.runs.set(this.key(scenario, implementation), state);
        this.drawList();
        if (scenario === this.selected) {
            this.showSelected();
        }
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

    private hideToolbar(): void {
        empty(this.toolbar);
        this.toolbar.hidden = true;
        this.desc.hidden = true;
    }

    /**
     * The Simulation tab's toolbar, for a scenario: which solver runs it, and
     * the button that runs it afresh. Choosing a solver runs the scenario with
     * it -- unless it already has, for this object -- the way choosing a
     * plugin runs a simulation with it.
     */
    private drawToolbar(scenario: CaeScenario): void {
        empty(this.toolbar);
        this.toolbar.hidden = false;

        const solvers = el('select', 'render-select render-plugin cae-implementation');
        solvers.setAttribute('aria-label', 'Analysed by');
        // The label where a person reads it, the id where they would type it:
        // 'pc cae thermal' is the command, "Heat Transfer" is what it does.
        solvers.title = `The implementation that runs this ${this.label} scenario: 'pc cae ${this.analysis} --implementation'`;
        const current = this.choice(scenario.name).value;
        for (const choice of implementationChoices(this.analysis, scenario.implementation, this.configured)) {
            const option = el('option', undefined, choice.label);
            option.value = choice.value;
            option.title = choice.title;
            option.selected = choice.value === current;
            solvers.appendChild(option);
        }
        solvers.value = current;
        solvers.addEventListener('change', () => {
            this.chosen.set(scenario.name, solvers.value);
            this.drawList();
            this.showSelected();
            this.start();
        });
        this.toolbar.appendChild(el('span', 'render-label', 'Analysed by'));
        this.toolbar.appendChild(solvers);

        const analyse = el('button', 'render-save cae-run', 'Analyse');
        analyse.type = 'button';
        analyse.title = 'Run this scenario afresh, with the implementation chosen';
        analyse.disabled = this.runState(scenario.name)?.state === 'running';
        analyse.addEventListener('click', () => this.run(scenario.name));
        this.toolbar.appendChild(analyse);

        const desc = scenario.desc?.trim() ?? '';
        this.desc.textContent = desc;
        this.desc.hidden = desc === '';
    }

    private showSelected(): void {
        const scenario = this.scenarios.find((entry) => entry.name === this.selected);
        if (scenario === undefined) {
            return;
        }
        this.drawToolbar(scenario);
        const state = this.runState(scenario.name);
        if (state === undefined) {
            this.result.setBusy('Select this tab to run the analysis.');
        } else if (state.state === 'running') {
            this.result.setBusy('Running the analysis…');
        } else if (state.state === 'failed') {
            this.result.showError(state.error);
        } else if (state.entry === undefined) {
            this.result.showError('PartCAD ran nothing for this scenario.');
        } else if (state.entry.error) {
            // The scenario's own answer, and the one the tab is for: which
            // implementation was asked, what it said, and which machine it did
            // not work on.
            this.result.showError(state.entry.error);
        } else {
            try {
                this.result.render(state.entry);
            } catch (e: unknown) {
                this.result.showError(`Failed to display this: ${e}`);
                this.callbacks.onFailure?.(`failed to render the '${this.analysis}' tab: ${e}`);
            }
        }
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
    if (state.state === 'failed' || state.entry === undefined || state.entry.error) {
        return { state: 'error', mark: '!', label: 'Could not run' };
    }
    const found = state.entry.findings?.length ?? 0;
    if (found > 0) {
        // A finding is what the analysis was asked about, so a run with one is a
        // run whose answer is "no" - what 'pc test' fails a part on.
        return { state: 'failed', mark: '✗', label: `Found ${found === 1 ? 'one thing' : `${found} things`}` };
    }
    return { state: 'passed', mark: '✓', label: 'Ran, and found nothing' };
}
