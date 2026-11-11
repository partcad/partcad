//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The CAM tab's control pane: what a part's machine makes, and the settings it
// makes it with.
//
// The tab is the 3D view, of what the part's machine makes - its print, its cut,
// its molding - rather than of the part, with this pane down its left where the
// 3D view has its tree. The pane says what the part is and how it is made, then
// lists every setting its machine takes, as fields, and a Save button under them.
//
// None of what a setting is, or which settings a machine takes, is decided here:
// the daemon reads both off the configuration schema ('partcad.cam_view.settings',
// asked as 'cam.settings'), and this file draws a field per row it is sent. A
// field changed is a setting *tried*: the view asks PartCAD to make the part again
// with it, without writing anything ('showSection' with 'cam' in 'viewer.ts'),
// so that a print's infill made sparser shows in a section at once. Save writes
// what was tried into the part's 'partcad.yaml' ('cam.save'), and with it the part's
// materialized file where it has one.
//
// A field holds what the part states, as it is written ('20%', '0.2 mm'), and is
// empty where it states nothing, with what is taken then as its placeholder. So
// what is sent is what was typed - PartCAD reads it as it reads the file - and a
// field emptied is a setting taken out, back to what is taken where the part
// states none.
//
// No three.js here, so that the extension host's tests can load it.
//

import { el, empty, placeholder } from './dom';
import { CamControl, CamSavedData, CamSettings, CamSettingsData, CamStats } from './messages';

/** What each machine is called where the pane says what a part is made on. */
const MACHINE_NAMES: Record<string, string> = {
    fff: 'a filament printer',
    mold: 'a mold',
    cnc: 'a CNC router',
    laser: 'a laser cutter',
    drill: 'a drill',
    cut: 'a saw',
};

/** A setting's key as a label: 'layerHeight' as 'Layer height', 'safe_z' as 'Safe z'. */
export function labelOf(key: string): string {
    const words = key
        .replace(/_/g, ' ')
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .toLowerCase()
        .trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

/** What a setting's field starts out holding: what the part states, as written, or nothing. */
export function stated(control: CamControl): string {
    return control.value === null || control.value === undefined ? '' : String(control.value);
}

/**
 * The same settings tried: the same keys, each with the same value. A key set to null takes a setting out, so it is
 * not the same as a key left out -- that one is what the part states.
 */
export function sameSettings(a: CamSettings, b: CamSettings): boolean {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    return [...keys].every((key) => key in a && key in b && a[key] === b[key]);
}

/**
 * What the fields say that the part does not: each setting whose field differs
 * from what the part states, as typed, and null for one emptied - taken out.
 * Nothing for a field left as it was.
 */
export function editsOf(controls: CamControl[], entered: Record<string, string>): CamSettings {
    const edits: CamSettings = {};
    for (const control of controls) {
        const now = (entered[control.key] ?? stated(control)).trim();
        const was = stated(control).trim();
        if (now === was) {
            continue;
        }
        edits[control.key] = now === '' ? null : now;
    }
    return edits;
}

/** How a part is made, as one sentence: by what, on what, from what. */
export function makingOf(data: CamSettingsData): string {
    const machine = data.machine ?? '';
    const on = MACHINE_NAMES[machine] ? `${MACHINE_NAMES[machine]} ('${machine}')` : `'${machine}'`;
    const declared = data.declared === false ? ', its usual settings, since the part names none' : '';
    if (data.method === 'additive') {
        return `Printed on ${on}${declared}, after its design ${data.design ? `'${data.design}'` : '(none named)'}.`;
    }
    if (data.method === 'forming') {
        return `Molded in ${on}${declared}, from its cavity ${data.design ? `'${data.design}'` : '(none named)'}.`;
    }
    if (data.method === 'subtractive') {
        const along = data.instructions ? `, along '${data.instructions}'` : ', along its own outline';
        return `Cut on ${on}${declared} from its stock ${data.design ? `'${data.design}'` : '(none named)'}${along}.`;
    }
    return `Made by '${data.method ?? 'nothing'}'.`;
}

/** Where the part's geometry is kept, as one sentence. */
export function keptOf(data: CamSettingsData): string {
    const kept = data.materialized;
    if (kept === null || kept === undefined) {
        return 'It has a geometry of its own; what is drawn here is what its machine makes of it.';
    }
    if (kept.exists) {
        return `Its geometry is kept in ${kept.path} ('pc cam --materialize'); Save writes it again with the settings saved.`;
    }
    return `Its geometry is made on demand: nothing is materialized yet ('pc cam --materialize' writes ${kept.path}).`;
}

/** A number for a person: a few significant places, no trailing zeros. */
function formatted(value: number): string {
    const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 1 ? 2 : 3;
    const text = value.toFixed(digits);
    return digits === 0 ? text : text.replace(/\.?0+$/, '');
}

/** What a product came to, a line each: the layers, how much is deposited of the design, the filament. */
export function statsLines(stats: CamStats | null | undefined): string[] {
    if (!stats) {
        return [];
    }
    const lines: string[] = [];
    const number = (key: string) => (typeof stats[key] === 'number' ? (stats[key] as number) : undefined);
    const layers = number('layers');
    if (layers !== undefined) {
        lines.push(`Layers: ${layers}`);
    }
    const volume = number('volume');
    const solid = number('solid_volume');
    if (volume !== undefined) {
        const share = solid ? ` of the design's ${formatted(solid)} mm³ (${Math.round((100 * volume) / solid)}%)` : '';
        lines.push(`Deposited: ${formatted(volume)} mm³${share}`);
    }
    const filament = number('filament_length');
    if (filament !== undefined) {
        lines.push(`Filament: ${formatted(filament / 1000)} m`);
    }
    const length = number('cut_length');
    if (length !== undefined && filament === undefined) {
        lines.push(`Route: ${formatted(length / 1000)} m`);
    }
    return lines;
}

export interface CamCallbacks {
    /** The fields changed: the settings tried, which the view makes the part again with. */
    onChange: (settings: CamSettings) => void;
    /** Save: write what the fields say into the part's declaration. */
    onSave: (settings: CamSettings) => void;
}

/** The CAM tab's control pane. */
export class CamView {
    private data: CamSettingsData | undefined;
    private readonly fields = new Map<string, HTMLInputElement | HTMLSelectElement>();
    private readonly entered: Record<string, string> = {};
    private readonly save = el('button', 'cam-save', 'Save');
    private readonly revert = el('button', 'cam-revert', 'Revert');
    private readonly note = el('p', 'cam-note');
    private readonly stats = el('div', 'cam-stats');
    private saving = false;

    constructor(
        private readonly host: HTMLElement,
        private readonly callbacks: CamCallbacks,
    ) {
        this.host.classList.add('cam-controls');
        this.save.type = 'button';
        this.save.title = "Write these settings into the part's partcad.yaml";
        this.save.addEventListener('click', () => {
            if (!this.save.disabled) {
                this.callbacks.onSave(this.edits());
            }
        });
        this.revert.type = 'button';
        this.revert.title = 'Back to the settings the part states';
        this.revert.addEventListener('click', () => this.discard());
        this.setBusy('Select a part a machine makes to see how it is made.');
    }

    /** The object the pane is about, as '<package>:<name>', once it knows one. */
    public get object(): string | undefined {
        return this.data?.object;
    }

    /** What the fields say that the part does not (see 'editsOf'). */
    public edits(): CamSettings {
        return editsOf(this.data?.controls ?? [], this.entered);
    }

    /** Say 'text' in place of everything: nothing known yet, or nothing to know. */
    public setBusy(text: string): void {
        this.data = undefined;
        this.fields.clear();
        empty(this.host);
        this.host.appendChild(placeholder(text));
    }

    public showError(text: string): void {
        this.data = undefined;
        this.fields.clear();
        empty(this.host);
        this.host.appendChild(el('p', 'error', text));
    }

    /**
     * Draw what the daemon said of the part. 'keep' keeps what was typed into the
     * fields - the same part again, the settings re-read after something else
     * changed - and is otherwise forgotten with what the part states.
     */
    public show(data: CamSettingsData, keep = false): void {
        if (keep && this.data !== undefined && JSON.stringify(data) === JSON.stringify(this.data)) {
            // The same answer again - asked with every show of the part - and
            // somebody may be typing into a field: nothing is drawn again.
            return;
        }
        if (!keep || data.object !== this.data?.object) {
            for (const key of Object.keys(this.entered)) {
                delete this.entered[key];
            }
        }
        this.data = data;
        this.fields.clear();
        empty(this.host);
        if (data.refused) {
            this.host.appendChild(placeholder(data.refused));
            return;
        }
        const head = el('div', 'cam-head');
        head.appendChild(el('h3', 'cam-title', 'What the machine makes'));
        if (data.description) {
            head.appendChild(el('p', 'cam-description', data.description));
        }
        head.appendChild(el('p', 'cam-making', makingOf(data)));
        head.appendChild(el('p', 'cam-kept', keptOf(data)));
        if (data.error) {
            head.appendChild(el('p', 'error', data.error));
        }
        this.host.appendChild(head);

        const form = el('div', 'cam-settings');
        form.appendChild(el('h4', 'cam-subtitle', `Settings of the '${data.machine ?? ''}'`));
        for (const control of data.controls ?? []) {
            form.appendChild(this.row(control));
        }
        this.host.appendChild(form);

        const buttons = el('div', 'cam-buttons');
        buttons.append(this.save, this.revert);
        this.host.append(buttons, this.note, this.stats);
        this.note.hidden = true;
        this.refresh();
    }

    /** What the product on screen came to, or nothing known. */
    public setStats(stats: CamStats | null | undefined): void {
        empty(this.stats);
        const lines = statsLines(stats);
        if (lines.length === 0) {
            return;
        }
        this.stats.appendChild(el('h4', 'cam-subtitle', 'What it comes to'));
        for (const line of lines) {
            this.stats.appendChild(el('div', 'cam-stat', line));
        }
    }

    /** A line under the buttons: what Save did, or why it could not; nothing for undefined. */
    public setNote(text: string | undefined, error = false): void {
        this.note.textContent = text ?? '';
        this.note.hidden = !text;
        this.note.classList.toggle('error', error);
    }

    /**
     * Whether Save is under way: nothing can be saved twice at once, and no field changed meanwhile, since the fields
     * start again from what the part states once the Save is done.
     */
    public setSaving(saving: boolean): void {
        this.saving = saving;
        this.refresh();
    }

    /**
     * Save is done: say where it went. The settings are asked for again by the caller, and the fields follow them --
     * so they stay as they are, and cannot be changed, until the caller has shown those and ends the Save
     * ('setSaving'): an edit typed in between would be lost to them.
     */
    public saved(data: CamSavedData | null | undefined): void {
        if (!data) {
            this.setNote('Saved.');
            return;
        }
        this.setNote(
            data.materialized
                ? `Saved into ${data.config}, and written again into ${data.materialized}.`
                : `Saved into ${data.config}.`,
        );
    }

    /** Every field back to what the part states, and the part made again with that. */
    private discard(): void {
        const had = Object.keys(this.edits()).length > 0;
        for (const key of Object.keys(this.entered)) {
            delete this.entered[key];
        }
        for (const control of this.data?.controls ?? []) {
            const field = this.fields.get(control.key);
            if (field !== undefined) {
                field.value = stated(control);
            }
        }
        this.refresh();
        if (had) {
            this.callbacks.onChange(this.edits());
        }
    }

    private row(control: CamControl): HTMLElement {
        const row = el('label', 'cam-row');
        const name = el('span', 'cam-label', labelOf(control.key));
        const what = control.description ? `${control.key}: ${control.description}` : control.key;
        row.title = what;
        const fallback =
            control.default === null || control.default === undefined ? 'not stated' : String(control.default);
        let field: HTMLInputElement | HTMLSelectElement;
        if (control.choices !== undefined) {
            const select = el('select', 'cam-field');
            const none = el('option', undefined, `${fallback} (not stated)`);
            none.value = '';
            select.appendChild(none);
            for (const choice of control.choices) {
                const option = el('option', undefined, choice);
                option.value = choice;
                select.appendChild(option);
            }
            const current = stated(control);
            if (current !== '' && !control.choices.includes(current)) {
                // Written some other way than the choices are ('-z'): kept as it is.
                const option = el('option', undefined, current);
                option.value = current;
                select.appendChild(option);
            }
            select.addEventListener('change', () => this.changed(control.key, select.value));
            field = select;
        } else {
            const input = el('input', 'cam-field');
            if (control.type === 'count') {
                input.type = 'number';
                input.step = '1';
                if (control.minimum !== undefined) {
                    input.min = String(control.minimum);
                }
            } else {
                input.type = 'text';
                input.spellcheck = false;
            }
            input.placeholder = fallback;
            input.addEventListener('input', () => this.changed(control.key, input.value));
            field = input;
        }
        field.value = this.entered[control.key] ?? stated(control);
        field.setAttribute('aria-label', labelOf(control.key));
        this.fields.set(control.key, field);
        row.append(name, field);
        return row;
    }

    private changed(key: string, value: string): void {
        this.entered[key] = value;
        this.refresh();
        this.callbacks.onChange(this.edits());
    }

    /** Save and Revert, enabled only while there is something to save or take back. */
    private refresh(): void {
        const pending = Object.keys(this.edits()).length > 0;
        this.save.disabled = this.saving || !pending;
        this.revert.disabled = this.saving || !pending;
        for (const control of this.data?.controls ?? []) {
            const field = this.fields.get(control.key);
            field?.classList.toggle('edited', control.key in this.edits());
            if (field !== undefined) {
                field.disabled = this.saving;
            }
        }
    }
}
