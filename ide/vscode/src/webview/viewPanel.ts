//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The view panel: how the object on a tab is looked at, down the right of every
// tab that shows one - 3D, 2D and Draft, each analysis, and Simulation.
//
// Top to bottom:
//
//   * the orientation gizmo ('gizmo.ts'), which turns the view;
//   * a button per axis view - X, -X, Y, -Y, Z, -Z - each looking along that
//     axis from that end, as 'pc render --view' names them (see 'viewpoint.ts');
//   * a section slider per axis, X, Y and Z, each two-ended: its ends start at
//     the two faces of the object's bounding box, and moving one inwards cuts
//     that much off from that side. PartCAD does the cutting (see 'section.ts');
//   * where the view is looked at from, as the three vectors a 'render:' section
//     says it with - Origin, Up and, where the view has one to move, Target -
//     each a field that can be typed into, copied out of and pasted into;
//   * Animate and Opacity, which used to be at the bottom of the 3D view's tree.
//
// One widget for every tab, and the tabs differ in what each part of it can do
// there: a picture PartCAD renders has a viewpoint but nothing to animate, an
// analysis's result is the solver's mesh and not something PartCAD can cut, and
// so on. So a part that does not apply on a tab is not taken away - the panel
// keeps its shape from tab to tab - it is disabled, and says why ('Capability').
//
// The panel holds no opinion about what a change means. It reports what was
// asked for ('ViewPanelCallbacks'), and whoever owns the tab decides: the 3D view
// moves its camera, the 2D tab renders again. Sliders and fields report once a
// change is settled - a slider let go, a field left or Entered - because on most
// tabs a change is a round trip to the daemon; the gizmo reports as it is
// dragged, saying when the drag is over, so that a camera can follow it.
//
// Everything is built node by node through 'dom.ts', as every pane is.
//

import { el } from './dom';
import { Gizmo } from './gizmo';
import {
    Bounds,
    Range,
    SECTION_AXES,
    Section,
    SectionAxis,
    formatLength,
    rangeOf,
    sameSection,
    sectionOf,
} from './section';
import { SidePanel } from './sidePanel';
import {
    AXIS_DIRECTIONS,
    AXIS_VIEWS,
    AxisView,
    DEFAULT_VIEWPOINT,
    Pole,
    Viewpoint,
    Z_POLE,
    axisView,
    formatVector,
    orbit,
    parseVector,
    problemWith,
} from './viewpoint';

/** Whether a part of the panel works on a tab: true, or the sentence saying why it does not. */
export type Capability = true | string;

export interface ViewCapabilities {
    /** The gizmo, the axis buttons and the viewpoint fields. */
    viewpoint: Capability;
    /** The section sliders. */
    section: Capability;
    animate: Capability;
    opacity: Capability;
}

export interface ViewPanelCallbacks {
    /** The view was turned, an axis chosen or a field changed; 'final' once it is to be kept. */
    onViewpoint: (viewpoint: Viewpoint, final: boolean) => void;
    /** "Reset": back to the view the tab starts out with. */
    onResetView: () => void;
    /** The section was changed - a slider let go - or reset (null). */
    onSection: (section: Section | null) => void;
    onAnimate?: (animate: boolean) => void;
    /** From 0 to 1. */
    onOpacity?: (opacity: number) => void;
}

export interface ViewPanelOptions {
    /** Whether the view has a point it looks at that can be moved: the 3D views do, a rendered picture does not. */
    target: boolean;
    /** Whether the model starts out turning on its own, which the Animate box then says. */
    animate?: boolean;
    /**
     * Ids for the Animate box and the Opacity slider, for the one panel that is
     * driven from outside the webview (the 3D tab's, by the screenshot script).
     */
    ids?: { animate?: string; opacity?: string; opacityValue?: string };
}

/** The ends of one section slider, and what they say. */
interface SliderRow {
    low: HTMLInputElement;
    high: HTMLInputElement;
    readout: HTMLElement;
    track: HTMLElement;
}

/** How many steps a section slider has from one face of the object to the other. */
const SLIDER_STEPS = 1000;

export class ViewPanel {
    public readonly side: SidePanel;
    private readonly gizmo: Gizmo;
    private readonly axisButtons = new Map<AxisView, HTMLButtonElement>();
    private readonly sliders = new Map<SectionAxis, SliderRow>();
    private readonly sectionReset = el('button', 'view-reset', 'Reset');
    private readonly sectionNote = el('div', 'view-note');
    private readonly viewReset = el('button', 'view-reset', 'Reset');
    private readonly viewNote = el('div', 'view-note');
    private readonly fields: { origin: HTMLInputElement; up: HTMLInputElement; target: HTMLInputElement };
    private readonly targetRow: HTMLElement;
    private readonly animate: HTMLInputElement;
    private readonly opacity: HTMLInputElement;
    private readonly opacityValue: HTMLElement;
    private readonly groups: Record<'viewpoint' | 'section' | 'display', HTMLElement>;
    private readonly animateRow: HTMLElement;
    private readonly opacityRow: HTMLElement;

    private capabilities: ViewCapabilities = { viewpoint: true, section: true, animate: true, opacity: true };
    /**
     * What each field was last given, so that one somebody is typing into is
     * left alone and one they have finished with - Entered, with the cursor
     * still in it - goes on following the view.
     */
    private readonly written: Record<'origin' | 'up' | 'target', string> = { origin: '', up: '', target: '' };
    /**
     * What the line under the viewpoint and the one under the sliders say while
     * their part of the panel works: kept apart from why it does not work, which
     * replaces them while it does not and gives them back once it does.
     */
    private readonly notes: Record<'view' | 'section', { text?: string; error: boolean }> = {
        view: { error: false },
        section: { error: false },
    };
    private viewpoint: Viewpoint | undefined;
    private pole: Pole = Z_POLE;
    private bounds: Bounds | undefined;
    private section: Section | null = null;
    /** What the section sliders are showing while one is being moved, before it is let go. */
    private ranges: Partial<Record<SectionAxis, Range>> = {};

    constructor(
        private readonly callbacks: ViewPanelCallbacks,
        private readonly options: ViewPanelOptions,
    ) {
        this.side = new SidePanel('right', 'the view panel');
        const body = this.side.body;
        body.classList.add('view-panel');

        // The gizmo, at the top in the middle.
        this.gizmo = new Gizmo({
            onOrbit: (azimuth, polar, final) => this.turn(azimuth, polar, final),
            onPick: (axis) => this.pick(axis),
        });
        const gizmoRow = el('div', 'view-gizmo-row');
        gizmoRow.appendChild(this.gizmo.element);

        // A button per axis view, in the order the gizmo's axes are named.
        const buttons = el('div', 'view-axes');
        buttons.setAttribute('role', 'group');
        buttons.setAttribute('aria-label', 'Look along an axis');
        for (const axis of AXIS_VIEWS) {
            const button = el('button', `view-axis view-axis-${axis.replace('-', 'minus-')}`, axis.toUpperCase());
            button.type = 'button';
            const from = axis.startsWith('-') ? `-${axis.slice(1).toUpperCase()}` : `+${axis.toUpperCase()}`;
            button.title = `Look from ${from}: the ${AXIS_DIRECTIONS[axis].view} view`;
            button.addEventListener('click', () => this.pick(axis));
            buttons.appendChild(button);
            this.axisButtons.set(axis, button);
        }

        // The section: a two-ended slider per axis.
        const section = el('div', 'view-group view-section');
        section.appendChild(this.heading('Section', this.sectionReset));
        this.sectionReset.type = 'button';
        this.sectionReset.title = 'Keep the whole object';
        this.sectionReset.addEventListener('click', () => this.resetSection());
        for (const axis of SECTION_AXES) {
            section.appendChild(this.slider(axis));
        }
        section.appendChild(this.sectionNote);

        // Where the view is looked at from.
        const view = el('div', 'view-group view-viewpoint');
        view.appendChild(this.heading('Viewpoint', this.viewReset));
        this.viewReset.type = 'button';
        this.viewReset.addEventListener('click', () => this.callbacks.onResetView());
        const origin = this.field(
            'Origin',
            'viewport_origin: where the view is looked at from, as seen from the target',
        );
        const up = this.field('Up', 'viewport_up: which way is up in the picture');
        const target = this.field('Target', 'The point the view looks at, in the frame of the object');
        this.fields = { origin: origin.input, up: up.input, target: target.input };
        this.targetRow = target.row;
        this.targetRow.hidden = !options.target;
        view.append(origin.row, up.row, target.row, this.viewNote);

        // How the model is drawn: Animate and Opacity.
        const display = el('div', 'view-group view-display');
        this.animateRow = el('label', 'control-label');
        this.animate = el('input');
        this.animate.type = 'checkbox';
        // Ticked where the view starts out turning - the 3D view's - and not
        // where nothing turns, so that a disabled box does not say it is on.
        this.animate.checked = options.animate === true;
        if (options.ids?.animate) {
            this.animate.id = options.ids.animate;
        }
        this.animate.addEventListener('change', () => this.callbacks.onAnimate?.(this.animate.checked));
        this.animateRow.append(this.animate, el('span', undefined, 'Animate'));

        this.opacityRow = el('label', 'control-label');
        this.opacity = el('input', 'opacity-slider');
        this.opacity.type = 'range';
        this.opacity.min = '0';
        this.opacity.max = '100';
        this.opacity.value = '100';
        if (options.ids?.opacity) {
            this.opacity.id = options.ids.opacity;
        }
        this.opacityValue = el('span', 'control-value', '100%');
        if (options.ids?.opacityValue) {
            this.opacityValue.id = options.ids.opacityValue;
        }
        this.opacity.addEventListener('input', () => {
            const value = parseInt(this.opacity.value, 10);
            this.opacityValue.textContent = `${value}%`;
            this.callbacks.onOpacity?.(value / 100);
        });
        this.opacityRow.append(el('span', undefined, 'Opacity'), this.opacity, this.opacityValue);
        display.append(this.animateRow, this.opacityRow);

        this.groups = { viewpoint: view, section, display };
        body.append(gizmoRow, buttons, section, view, display);

        this.setViewpoint(undefined);
        this.setBounds(undefined);
    }

    /** The panel, to be put at the right-hand end of a pane. */
    public get element(): HTMLElement {
        return this.side.element;
    }

    /** What each part of the panel can do on this tab; what it cannot do says why. */
    public setCapabilities(capabilities: ViewCapabilities): void {
        this.capabilities = capabilities;
        this.apply();
    }

    /** The pole the gizmo turns the view about: Z, unless the model is drawn in a frame of its own. */
    public setPole(pole: Pole): void {
        this.pole = pole;
    }

    /**
     * Show where the view is looked at from, or that it is not known yet.
     *
     * A field somebody is typing into is left alone: the view moving under them -
     * the 3D view turning on its own - must not take back what they typed.
     */
    public setViewpoint(viewpoint: Viewpoint | undefined, note?: string): void {
        this.viewpoint = viewpoint;
        this.gizmo.set(viewpoint ?? DEFAULT_VIEWPOINT);
        this.gizmo.element.classList.toggle('unknown', viewpoint === undefined);
        for (const key of ['origin', 'up', 'target'] as const) {
            const field = this.fields[key];
            if (isFocused(field) && field.value !== this.written[key]) {
                continue;
            }
            field.value = viewpoint !== undefined ? formatVector(viewpoint[key]) : '';
            this.written[key] = field.value;
            field.classList.remove('invalid');
        }
        this.notes.view = { text: note, error: false };
        this.drawNotes();
    }

    /** The view the panel shows, if it knows one. */
    public get current(): Viewpoint | undefined {
        return this.viewpoint;
    }

    /** How big the object is, which is what the section sliders span; undefined when it is not known. */
    public setBounds(bounds: Bounds | undefined): void {
        this.bounds = bounds;
        this.ranges = {};
        this.apply();
    }

    /** What the object is cut to, as the tab holds it; null for the whole of it. */
    public setSection(section: Section | null): void {
        this.section = section;
        this.ranges = {};
        this.drawSliders();
    }

    /** A line under the section sliders - "Cutting…", or why the last cut failed - or nothing. */
    public setSectionNote(note: string | undefined, error = false): void {
        this.notes.section = { text: note, error };
        this.drawNotes();
    }

    public setAnimate(animate: boolean): void {
        this.animate.checked = animate;
    }

    public get animating(): boolean {
        return this.animate.checked;
    }

    /** What the Opacity slider says, from 0 to 1. */
    public get opacityFraction(): number {
        return parseInt(this.opacity.value, 10) / 100;
    }

    private heading(text: string, button: HTMLElement): HTMLElement {
        const heading = el('div', 'view-heading');
        heading.append(el('span', 'view-title', text), button);
        return heading;
    }

    private field(label: string, title: string): { row: HTMLElement; input: HTMLInputElement } {
        const row = el('label', 'view-field');
        const input = el('input', 'view-vector');
        input.type = 'text';
        input.spellcheck = false;
        input.title = `${title}. Three numbers, x, y, z, in millimetres`;
        input.setAttribute('aria-label', label);
        input.addEventListener('change', () => this.typed());
        input.addEventListener('keydown', (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                // Put back what the view is, and let go of the field.
                this.setViewpoint(this.viewpoint);
                input.blur();
            }
        });
        row.append(el('span', 'view-field-label', label), input);
        return { row, input };
    }

    private slider(axis: SectionAxis): HTMLElement {
        const row = el('div', 'view-slider');
        const track = el('div', 'range-pair');
        const low = el('input', 'range-low');
        const high = el('input', 'range-high');
        for (const [input, end] of [
            [low, 'from'],
            [high, 'to'],
        ] as const) {
            input.type = 'range';
            input.min = '0';
            input.max = String(SLIDER_STEPS);
            input.step = '1';
            input.setAttribute('aria-label', `${axis.toUpperCase()} ${end}`);
            input.addEventListener('input', () => this.sliding(axis, input === low));
            input.addEventListener('change', () => this.slid());
        }
        low.value = '0';
        high.value = String(SLIDER_STEPS);
        track.append(low, high);
        const readout = el('span', 'view-slider-value');
        row.append(el('span', 'view-slider-label', axis.toUpperCase()), track, readout);
        this.sliders.set(axis, { low, high, readout, track });
        return row;
    }

    /** One end of a slider moved: held behind the other end, and shown, but not reported until let go. */
    private sliding(axis: SectionAxis, lowEnd: boolean): void {
        const row = this.sliders.get(axis);
        const bounds = this.bounds;
        if (row === undefined || bounds === undefined) {
            return;
        }
        let low = parseInt(row.low.value, 10);
        let high = parseInt(row.high.value, 10);
        if (low >= high) {
            // The two ends cannot pass each other: a section keeps something.
            if (lowEnd) {
                low = Math.max(0, high - 1);
                row.low.value = String(low);
            } else {
                high = Math.min(SLIDER_STEPS, low + 1);
                row.high.value = String(high);
            }
        }
        this.ranges[axis] = [this.toLength(axis, low, bounds), this.toLength(axis, high, bounds)];
        this.drawSlider(axis);
    }

    /** A slider was let go: the section the sliders now say, reported if it is a new one. */
    private slid(): void {
        const bounds = this.bounds;
        if (bounds === undefined) {
            return;
        }
        const ranges: Partial<Record<SectionAxis, Range>> = {};
        for (const axis of SECTION_AXES) {
            ranges[axis] = this.ranges[axis] ?? rangeOf(this.section, axis, bounds);
        }
        const section = sectionOf(ranges, bounds);
        this.ranges = {};
        if (sameSection(section, this.section)) {
            this.drawSliders();
            return;
        }
        this.section = section;
        this.drawSliders();
        this.callbacks.onSection(section);
    }

    private resetSection(): void {
        this.ranges = {};
        if (this.section === null) {
            return;
        }
        this.section = null;
        this.drawSliders();
        this.callbacks.onSection(null);
    }

    private toLength(axis: SectionAxis, step: number, bounds: Bounds): number {
        const index = SECTION_AXES.indexOf(axis);
        const span = bounds.max[index] - bounds.min[index];
        if (step <= 0) {
            return bounds.min[index];
        }
        if (step >= SLIDER_STEPS) {
            return bounds.max[index];
        }
        return bounds.min[index] + (span * step) / SLIDER_STEPS;
    }

    private toStep(axis: SectionAxis, length: number, bounds: Bounds): number {
        const index = SECTION_AXES.indexOf(axis);
        const span = bounds.max[index] - bounds.min[index];
        if (span <= 0) {
            return 0;
        }
        return Math.round(((length - bounds.min[index]) / span) * SLIDER_STEPS);
    }

    private drawSliders(): void {
        for (const axis of SECTION_AXES) {
            this.drawSlider(axis);
        }
        this.sectionReset.disabled = this.capabilities.section !== true || this.section === null;
    }

    /** One slider as the section says - or as it is being moved - with its ends in millimetres beside it. */
    private drawSlider(axis: SectionAxis): void {
        const row = this.sliders.get(axis);
        if (row === undefined) {
            return;
        }
        const bounds = this.bounds;
        if (bounds === undefined) {
            row.low.value = '0';
            row.high.value = String(SLIDER_STEPS);
            row.readout.textContent = '';
            row.track.style.setProperty('--low', '0%');
            row.track.style.setProperty('--high', '100%');
            return;
        }
        const [low, high] = this.ranges[axis] ?? rangeOf(this.section, axis, bounds);
        const lowStep = this.toStep(axis, low, bounds);
        const highStep = this.toStep(axis, high, bounds);
        if (this.ranges[axis] === undefined) {
            row.low.value = String(lowStep);
            row.high.value = String(highStep);
        }
        row.readout.textContent = `${formatLength(low)} – ${formatLength(high)}`;
        row.readout.title = `Kept from ${formatLength(low)} to ${formatLength(high)} mm along ${axis.toUpperCase()}`;
        row.track.style.setProperty('--low', `${(lowStep / SLIDER_STEPS) * 100}%`);
        row.track.style.setProperty('--high', `${(highStep / SLIDER_STEPS) * 100}%`);
        row.track.classList.toggle('cut', this.section?.[axis] !== undefined);
    }

    /** The gizmo was dragged. */
    private turn(azimuth: number, polar: number, final: boolean): void {
        if (this.capabilities.viewpoint !== true) {
            return;
        }
        const from = this.viewpoint ?? DEFAULT_VIEWPOINT;
        const turned = azimuth === 0 && polar === 0 ? from : orbit(from, azimuth, polar, this.pole);
        this.setViewpoint(turned);
        this.callbacks.onViewpoint(turned, final);
    }

    /** A ball of the gizmo, or a button under it. */
    private pick(axis: AxisView): void {
        if (this.capabilities.viewpoint !== true) {
            return;
        }
        const chosen = axisView(axis, this.viewpoint);
        this.setViewpoint(chosen);
        this.callbacks.onViewpoint(chosen, true);
    }

    /** A field was changed: the viewpoint the three now say, if they say one. */
    private typed(): void {
        if (this.capabilities.viewpoint !== true) {
            return;
        }
        const read = {
            origin: parseVector(this.fields.origin.value),
            up: parseVector(this.fields.up.value),
            target: this.options.target ? parseVector(this.fields.target.value) : [0, 0, 0],
        };
        let problem: string | undefined;
        for (const key of ['origin', 'up', 'target'] as const) {
            const bad = read[key] === undefined;
            this.fields[key].classList.toggle('invalid', bad);
            if (bad && problem === undefined) {
                problem = `${key === 'origin' ? 'Origin' : key === 'up' ? 'Up' : 'Target'} is three numbers: x, y, z`;
            }
        }
        if (problem === undefined) {
            const viewpoint = { origin: read.origin!, up: read.up!, target: read.target! } as Viewpoint;
            problem = problemWith(viewpoint);
            if (problem === undefined) {
                this.viewpoint = viewpoint;
                for (const key of ['origin', 'up', 'target'] as const) {
                    this.written[key] = this.fields[key].value;
                }
                this.gizmo.set(viewpoint);
                this.notes.view = { error: false };
                this.drawNotes();
                this.callbacks.onViewpoint(viewpoint, true);
                return;
            }
            this.fields.up.classList.add('invalid');
        }
        this.notes.view = { text: problem, error: true };
        this.drawNotes();
    }

    /** Draw what each part can do. */
    private apply(): void {
        const { viewpoint, section, animate, opacity } = this.capabilities;

        const viewing = viewpoint === true;
        this.gizmo.setEnabled(viewing, viewing ? undefined : viewpoint);
        for (const button of this.axisButtons.values()) {
            button.disabled = !viewing;
        }
        for (const field of Object.values(this.fields)) {
            field.disabled = !viewing;
        }
        this.viewReset.disabled = !viewing;
        this.viewReset.title = viewing ? 'Back to the view this tab starts out with' : '';
        this.groups.viewpoint.classList.toggle('disabled', !viewing);

        const cutting = section === true && this.bounds !== undefined;
        for (const row of this.sliders.values()) {
            row.low.disabled = !cutting;
            row.high.disabled = !cutting;
        }
        this.groups.section.classList.toggle('disabled', !cutting);
        this.drawNotes();
        this.drawSliders();

        this.animate.disabled = animate !== true;
        this.animateRow.title = animate === true ? 'Turn the model on its own' : animate;
        this.animateRow.classList.toggle('disabled', animate !== true);
        this.opacity.disabled = opacity !== true;
        this.opacityRow.title = opacity === true ? 'How see-through the model is drawn' : opacity;
        this.opacityRow.classList.toggle('disabled', opacity !== true);
        this.groups.display.classList.toggle('disabled', animate !== true && opacity !== true);
    }

    /** The two lines: why a part does not work where it does not, and what it has to say where it does. */
    private drawNotes(): void {
        const { viewpoint, section } = this.capabilities;
        if (viewpoint !== true) {
            this.say(this.viewNote, viewpoint);
        } else {
            this.say(this.viewNote, this.notes.view.text, this.notes.view.error);
        }
        if (section !== true) {
            this.say(this.sectionNote, section);
        } else if (this.bounds === undefined) {
            this.say(this.sectionNote, 'PartCAD did not say how big this is, so there is nothing to slide across');
        } else {
            this.say(this.sectionNote, this.notes.section.text, this.notes.section.error);
        }
    }

    private say(note: HTMLElement, text: string | undefined, error = false): void {
        note.textContent = text ?? '';
        note.hidden = !text;
        note.classList.toggle('error', error);
    }
}

/** Whether somebody is typing into 'input' right now. */
function isFocused(input: HTMLElement): boolean {
    return typeof document !== 'undefined' && document.activeElement === input;
}
