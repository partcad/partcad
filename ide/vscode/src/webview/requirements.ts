//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "Requirements" tab.
//
// What an object was required to be, and how far the model is it. Two halves,
// because a requirement is one of two kinds of thing:
//
//   - what PartCAD can measure - the ports, the interfaces, the physical
//     properties, how closely the volume, the displacement and the mass
//     match another object's, and the yes-or-no 'has_' requirements - listed
//     with a mark beside each: green where 'pc req test' finds the model meets
//     it, red where it does not;
//   - the features, which are prose, in a table: what each is, and what it is
//     validated by - the 'qual: sim:' entries that name it, the analysis
//     scenarios that name it (an entry of a part's 'fea:', 'dynamic:',
//     'thermal:' or 'cfd:'), and an LLM reading the evidence through the
//     '/pc:validate' skill.
//
// And every one of them can be changed here: added (the strip of kinds over the
// lists), edited and removed (the buttons on its row). That is 'pc req add' and
// 'pc req remove' - the same daemon methods, 'requirements.add' and
// 'requirements.remove' - so the tab cannot write what the command line would
// refuse, and a refusal is said here in the daemon's words. A form's fields are
// sent as typed ('text'), and the daemon reads each as the same text in
// 'partcad.yaml' is read: '5' is the number, '>5' the comparison, and no YAML
// quoting is needed in a field. An object whose requirements are not its own to
// change - an alias, a template - says why instead of offering the buttons.
//
// None of the verdicts is worked out here. The daemon's 'requirements.check'
// answers with what 'partcad.requirements' decided, which is the code 'pc req
// test' runs; this file only draws the answer, and turns a form into a request.
//

import { el, empty, placeholder } from './dom';
import {
    ANALYSIS_LABELS,
    AnalysisTabId,
    RequirementAddress,
    RequirementCheck,
    RequirementEdit,
    RequirementFeature,
    RequirementKind,
    RequirementsData,
} from './messages';

/**
 * What the "LLM" banner says when pointed at.
 *
 * Cursor's spelling of the skill rather than Claude Code's ('/pc:validate'),
 * because it is the one both editors' users can read as a name: the IDE does not
 * know which agent is open beside it.
 */
export const LLM_HINT = 'Validate using /pc-validate';

/** The sections PartCAD measures, in the order they are listed, and their headings. */
export const SECTIONS: [string, string][] = [
    ['ports', 'Ports'],
    ['interfaces', 'Interfaces'],
    ['physics', 'Physics'],
    ['match', 'Matches'],
    // The yes-or-no requirements: has_color, ..., has_private_dependencies.
    ['has', 'Specified'],
];

/** Where a check of any other section - a requirement that could not be read, a dangling 'feature:' - is listed. */
export const PROBLEMS = 'Problems';

/** The kinds of requirement, in the order the strip offers them, and what each is called there. */
export const KINDS: [RequirementKind, string][] = [
    ['feature', 'Feature'],
    ['port', 'Port'],
    ['interface', 'Interface'],
    ['physics', 'Physics'],
    ['match', 'Match'],
    ['has', 'Specified'],
];

/** The yes-or-no requirements, for a daemon that does not list them. */
export const HAS_NAMES = ['color', 'material', 'finish', 'weight', 'dependencies', 'private_dependencies'];

export type Mark = 'pass' | 'fail' | 'pending';

/**
 * What a check's mark is.
 *
 * 'pending' while the verdicts are not in - a requirement nobody has measured
 * yet is neither met nor unmet, and drawing it red or green would say it is.
 */
export function markOf(check: RequirementCheck): Mark {
    if (check.passed === true) {
        return 'pass';
    }
    if (check.passed === false) {
        return 'fail';
    }
    return 'pending';
}

/** The checks, by the heading they are listed under: the measured sections first, then everything else. */
export function groupChecks(checks: RequirementCheck[]): { heading: string; checks: RequirementCheck[] }[] {
    const groups: { heading: string; checks: RequirementCheck[] }[] = [];
    for (const [section, heading] of SECTIONS) {
        const inSection = checks.filter((check) => check.section === section);
        if (inSection.length > 0) {
            groups.push({ heading, checks: inSection });
        }
    }
    const known = new Set(SECTIONS.map(([section]) => section));
    const others = checks.filter((check) => !known.has(check.section));
    if (others.length > 0) {
        groups.push({ heading: PROBLEMS, checks: others });
    }
    return groups;
}

export interface Banner {
    label: string;
    title: string;
    kind: 'simulation' | 'analysis' | 'llm';
}

/**
 * What a feature is validated by: each simulation that names it, then each
 * analysis scenario that does, then the LLM.
 *
 * An analysis scenario is labelled with the analysis as well as its name -
 * "FEA: loaded" - because scenarios are named within an analysis, and a part's
 * FEA and its Heat Transfer can both have one called 'loaded'. The label is the
 * one the analysis's tab has ('ANALYSIS_LABELS'), and the tooltip is the command
 * that runs it.
 *
 * The LLM banner is on every feature, the ones a simulation or an analysis
 * stands behind included: each demonstrates the claim it was written for, and
 * whether that is the whole of the feature is a judgement it cannot make.
 */
export function bannersOf(feature: RequirementFeature): Banner[] {
    const banners: Banner[] = (feature.simulations ?? []).map((name) => ({
        label: name,
        title: `Demonstrated by the simulation '${name}' (pc qual test --simulation)`,
        kind: 'simulation',
    }));
    for (const { analysis, name } of feature.analyses ?? []) {
        // An analysis this extension does not know yet - from a newer PartCAD -
        // is still a banner, under the id it was sent with.
        const label = ANALYSIS_LABELS[analysis as AnalysisTabId] ?? analysis;
        banners.push({
            label: `${label}: ${name}`,
            title: `Demonstrated by the ${label} scenario '${name}' (pc cae ${analysis} -f ${name})`,
            kind: 'analysis',
        });
    }
    banners.push({ label: 'LLM', title: LLM_HINT, kind: 'llm' });
    return banners;
}

/** One line saying how it stands, over the lists. */
export function summary(data: RequirementsData, checking: boolean): string {
    const measured = data.requirements;
    if (measured.length === 0) {
        return data.features.length > 0
            ? 'Nothing here is for PartCAD to measure: every feature is validated by a simulation or an analysis, or by reading the evidence.'
            : 'No requirements are declared.';
    }
    if (!data.verified) {
        return checking ? 'Checking the model against what is required…' : 'Not checked yet.';
    }
    const failed = measured.filter((check) => check.passed === false).length;
    if (failed === 0) {
        return measured.length === 1 ? 'The requirement is met.' : `All ${measured.length} requirements are met.`;
    }
    return `${measured.length - failed} of ${measured.length} requirements are met.`;
}

// --- editing -------------------------------------------------------------------

/** Whether the requirements can be changed here: the daemon says null when they can, and why not otherwise. */
export function canEdit(data: RequirementsData): boolean {
    return data.editable === null;
}

/** One field of a form: what it is called, and how it is typed in. */
export interface FieldSpec {
    key: string;
    label: string;
    kind: 'text' | 'textarea' | 'select';
    options?: string[];
    placeholder?: string;
    /** Named by the row being edited, so not to be changed by editing it. */
    fixed?: boolean;
}

const AXES = ['x', 'y', 'z'];

/** The fields of a location: one per axis of the position and of the direction, and the angle. */
function locationFields(): FieldSpec[] {
    return [
        ...AXES.map((axis) => ({
            key: `position.${axis}`,
            label: `Position ${axis.toUpperCase()}`,
            kind: 'text' as const,
            placeholder: 'mm, e.g. 0 or >=5',
        })),
        ...AXES.map((axis) => ({
            key: `direction.${axis}`,
            label: `Faces ${axis.toUpperCase()}`,
            kind: 'text' as const,
            placeholder: 'e.g. 0, 0, -1 is facing down',
        })),
        { key: 'angle', label: 'Angle', kind: 'text', placeholder: 'degrees about that direction' },
    ];
}

/** What a physical property requirement may name, as the select offers it: a member of a mapping as 'inertia.ixx'. */
export function physicsChoices(data: RequirementsData): string[] {
    const choices: string[] = [];
    for (const [field, kind] of Object.entries(data.physics_fields ?? {})) {
        if (Array.isArray(kind)) {
            choices.push(...kind.map((member) => `${field}.${member}`));
        } else {
            choices.push(field);
        }
    }
    return choices;
}

/** Whether a physical property is a vector, and so has a value per axis. */
export function isVector(data: RequirementsData, field: string): boolean {
    return (data.physics_fields ?? {})[field] === 'vector';
}

/** The fields of the form for one kind of requirement; 'editing' fixes the ones that name it. */
export function formFields(kind: RequirementKind, data: RequirementsData, editing: boolean): FieldSpec[] {
    const named = (label: string, placeholderText?: string): FieldSpec => ({
        key: 'name',
        label,
        kind: 'text',
        placeholder: placeholderText,
        fixed: editing,
    });
    switch (kind) {
        case 'feature':
            return [
                named('Name', 'e.g. mount'),
                { key: 'desc', label: 'Description', kind: 'textarea', placeholder: 'What it has to have or do' },
            ];
        case 'port':
            return [named('Port'), ...locationFields(), { key: 'sketch', label: 'Boundary sketch', kind: 'text' }];
        case 'interface':
            return [
                named('Interface', 'e.g. //pub/std/metric/m3:m3-hole'),
                {
                    key: 'instance',
                    label: 'Instance',
                    kind: 'text',
                    placeholder: 'empty: any instance',
                    fixed: editing,
                },
                ...locationFields(),
            ];
        case 'physics': {
            const choices = physicsChoices(data);
            return [
                choices.length > 0
                    ? { key: 'name', label: 'Property', kind: 'select', options: choices, fixed: editing }
                    : named('Property', 'e.g. mass'),
                { key: 'value', label: 'Value', kind: 'text', placeholder: 'e.g. >0,<=0.05' },
                ...AXES.map((axis) => ({
                    key: `vector.${axis}`,
                    label: `Vector ${axis.toUpperCase()}`,
                    kind: 'text' as const,
                    placeholder: 'for a vector property',
                })),
            ];
        }
        case 'match':
            return [
                named('Object', 'e.g. :bracket-v1'),
                { key: 'volume', label: 'Volume', kind: 'text', placeholder: 'percent, e.g. 5' },
                { key: 'displacement', label: 'Displacement', kind: 'text', placeholder: 'percent' },
                { key: 'mass', label: 'Mass', kind: 'text', placeholder: 'percent' },
            ];
        case 'has':
            return [
                {
                    key: 'name',
                    label: 'Has',
                    kind: 'select',
                    options: data.has_names ?? HAS_NAMES,
                    fixed: editing,
                },
                { key: 'required', label: 'Required', kind: 'select', options: ['true', 'false'] },
            ];
    }
}

function text(value: unknown): string {
    if (value === null || value === undefined) {
        return '';
    }
    return String(value);
}

function record(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {};
}

/** A location requirement as the section holds it - a mapping, or '[position, direction, angle]' - as fields. */
function locationValues(raw: unknown): Record<string, string> {
    const location = Array.isArray(raw)
        ? { position: raw[0], direction: raw[1], angle: raw[2] }
        : (record(raw) as { position?: unknown; direction?: unknown; angle?: unknown });
    const values: Record<string, string> = { angle: text(location.angle) };
    for (const key of ['position', 'direction'] as const) {
        const vector = Array.isArray(location[key]) ? (location[key] as unknown[]) : [];
        AXES.forEach((axis, index) => (values[`${key}.${axis}`] = text(vector[index])));
    }
    return values;
}

/** The entry of the object's own section a row is about, as written there; undefined when it holds none. */
export function writtenAt(data: RequirementsData, address: RequirementAddress): unknown {
    const section = record(data.section);
    switch (address.requirement) {
        case 'feature':
            return record(section.features)[address.name];
        case 'port':
            return record(section.ports)[address.name];
        case 'interface': {
            const interfaces = record(section.interfaces);
            if (!(address.name in interfaces)) {
                return undefined;
            }
            const entry = interfaces[address.name];
            if (address.instance === undefined || address.instance === null) {
                return entry;
            }
            return record(entry)[address.instance] ?? null;
        }
        case 'physics': {
            const [field, member] = address.name.split('.', 2);
            const value = record(section.physics)[field];
            return member === undefined ? value : record(value)[member];
        }
        case 'match':
            return record(section.match)[address.name];
        case 'has': {
            const key = address.name.startsWith('has_') ? address.name : `has_${address.name}`;
            return section[key] ?? (key === 'has_weight' ? section.has_mass : undefined);
        }
    }
}

/** What a form is filled with to edit the requirement a row is about. */
export function prefill(data: RequirementsData, address: RequirementAddress): Record<string, string> {
    const raw = writtenAt(data, address);
    switch (address.requirement) {
        case 'feature':
            return { name: address.name, desc: text(raw) };
        case 'port': {
            const port = record(raw);
            return { name: address.name, ...locationValues(raw), sketch: text(port.sketch) };
        }
        case 'interface':
            return {
                name: address.name,
                instance: text(address.instance),
                ...(address.instance === undefined || address.instance === null
                    ? Array.isArray(raw) && raw.length === 3 && !raw.every((item) => typeof item === 'string')
                        ? locationValues(raw)
                        : {}
                    : locationValues(raw)),
            };
        case 'physics': {
            const values: Record<string, string> = { name: address.name };
            if (Array.isArray(raw)) {
                AXES.forEach((axis, index) => (values[`vector.${axis}`] = text(raw[index])));
            } else {
                values.value = text(raw);
            }
            return values;
        }
        case 'match': {
            const limits = record(raw);
            return {
                name: address.name,
                volume: text(limits.volume),
                displacement: text(limits.displacement),
                mass: text(limits.mass ?? limits.weight),
            };
        }
        case 'has':
            return { name: address.name.replace(/^has_/, ''), required: raw === false ? 'false' : 'true' };
    }
}

/** A location from its fields, as the daemon reads one; null when no field says anything. */
function locationOf(values: Record<string, string>): Record<string, unknown> | null {
    const location: Record<string, unknown> = {};
    for (const key of ['position', 'direction']) {
        const vector = AXES.map((axis) => (values[`${key}.${axis}`] ?? '').trim());
        if (vector.some((item) => item !== '')) {
            location[key] = vector;
        }
    }
    if ((values.angle ?? '').trim() !== '') {
        location.angle = values.angle.trim();
    }
    return Object.keys(location).length > 0 ? location : null;
}

/**
 * The request a form makes, or what is missing from it, in words.
 *
 * 'editing' is the row the form edits, and makes the request a replacement of
 * it; without one the form adds, and the daemon refuses what is there already.
 */
export function editFrom(
    kind: RequirementKind,
    values: Record<string, string>,
    data: RequirementsData,
    editing?: RequirementAddress,
): RequirementEdit | string {
    const name = (values.name ?? '').trim();
    if (name === '') {
        return 'Say which: the name is empty.';
    }
    const edit: RequirementEdit = { op: 'add', requirement: kind, name, text: true, replace: editing !== undefined };
    switch (kind) {
        case 'feature': {
            const desc = (values.desc ?? '').trim();
            if (desc === '') {
                return 'Say what the feature is: the description is empty.';
            }
            // Prose, not a value: sent as it is.
            return { ...edit, value: desc, text: false };
        }
        case 'port': {
            const location = locationOf(values);
            const sketch = (values.sketch ?? '').trim();
            const port = sketch === '' ? location : { ...(location ?? {}), sketch };
            return { ...edit, value: port };
        }
        case 'interface': {
            const instance = editing !== undefined ? editing.instance : (values.instance ?? '').trim() || undefined;
            const location = locationOf(values);
            if (instance === undefined || instance === null) {
                return { ...edit, value: location };
            }
            return { ...edit, value: location, instances: [instance] };
        }
        case 'physics': {
            if (isVector(data, name)) {
                const vector = AXES.map((axis) => (values[`vector.${axis}`] ?? '').trim());
                if (vector.every((item) => item === '')) {
                    return `Say what '${name}' is required to be: a value for at least one axis.`;
                }
                return { ...edit, value: vector };
            }
            const value = (values.value ?? '').trim();
            if (value === '') {
                return `Say what '${name}' is required to be: the value is empty.`;
            }
            return { ...edit, value };
        }
        case 'match': {
            const limits: Record<string, string> = {};
            for (const amount of ['volume', 'displacement', 'mass']) {
                const given = (values[amount] ?? '').trim();
                if (given !== '') {
                    limits[amount] = given;
                }
            }
            if (Object.keys(limits).length === 0) {
                return 'Say how closely: a percentage of its volume, its displacement or its mass.';
            }
            return { ...edit, value: limits };
        }
        case 'has':
            return { ...edit, value: values.required !== 'false', text: false };
    }
}

/** The request that removes the requirement a row is about; a feature, with what names it when asked to. */
export function removalOf(address: RequirementAddress, withReferences = false): RequirementEdit {
    const edit: RequirementEdit = { op: 'remove', requirement: address.requirement, name: address.name };
    if (address.instance !== undefined && address.instance !== null) {
        edit.instances = [address.instance];
    }
    if (address.amount !== undefined && address.amount !== null) {
        edit.amounts = [address.amount];
    }
    if (withReferences) {
        edit.with_references = true;
    }
    return edit;
}

/** The address of a feature's row. */
export function featureAddress(feature: RequirementFeature): RequirementAddress {
    return { requirement: 'feature', name: feature.name };
}

/** What names a feature, in words: what removing it would take out of as well. */
export function namedBy(feature: RequirementFeature): string[] {
    return [
        ...(feature.simulations ?? []).map((name) => `the simulation '${name}'`),
        ...(feature.analyses ?? []).map(({ analysis, name }) => `the ${analysis} scenario '${name}'`),
    ];
}

const MARK_TEXT: Record<Mark, string> = { pass: '✓', fail: '✗', pending: '…' };
const MARK_TITLE: Record<Mark, string> = {
    pass: 'Met (pc req test)',
    fail: 'Not met (pc req test)',
    pending: 'Not checked yet',
};

/** What the view asks of the panel: a change to a requirement, sent on to the daemon. */
export interface RequirementsCallbacks {
    onEdit(edit: RequirementEdit): void;
}

/** The form open over the lists: a kind to add, or the row being edited. */
interface OpenForm {
    kind: RequirementKind;
    editing?: RequirementAddress;
    values: Record<string, string>;
}

export class RequirementsView {
    private data: RequirementsData | undefined;
    private checking = false;
    private form: OpenForm | undefined;
    /** The feature whose removal is waiting to be confirmed, because something names it. */
    private confirming: RequirementFeature | undefined;
    private note: { text: string; error: boolean } | undefined;
    /** A change has been sent, and its answer is not in: nothing else may be sent meanwhile. */
    private saving = false;

    constructor(
        private readonly root: HTMLElement,
        private readonly callbacks?: RequirementsCallbacks,
    ) {}

    public setBusy(text: string): void {
        this.reset();
        this.root.appendChild(placeholder(text));
    }

    public showError(text: string): void {
        this.reset();
        this.root.appendChild(el('p', 'error', text));
    }

    /** Draw what is required, and the verdicts where they are in; 'checking' says they are on the way. */
    public show(data: RequirementsData, checking: boolean): void {
        if (this.data !== undefined && this.data.object !== data.object) {
            // Another object: what was being typed was about the last one.
            this.form = undefined;
            this.confirming = undefined;
            this.note = undefined;
            this.saving = false;
        }
        this.data = data;
        this.checking = checking;
        this.render();
    }

    /** Whether a form is open or a change is on its way: what a show of the same object must not throw away. */
    public get busy(): boolean {
        return this.form !== undefined || this.saving;
    }

    /** The change sent has been made: close the form, and say what was changed. */
    public edited(changed: string | null | undefined): void {
        this.saving = false;
        this.form = undefined;
        this.confirming = undefined;
        this.note = { text: changed ? `Changed: ${changed}.` : 'Changed.', error: false };
        this.render();
    }

    /** The change sent was refused: keep the form as it was typed, and say why. */
    public editFailed(error: string): void {
        this.saving = false;
        this.note = { text: error, error: true };
        this.render();
    }

    private reset(): void {
        empty(this.root);
        this.root.className = 'pane';
    }

    private send(edit: RequirementEdit): void {
        if (this.saving || this.callbacks === undefined) {
            return;
        }
        this.saving = true;
        this.note = { text: 'Saving…', error: false };
        this.render();
        this.callbacks.onEdit(edit);
    }

    private open(kind: RequirementKind, editing?: RequirementAddress): void {
        if (this.data === undefined) {
            return;
        }
        this.confirming = undefined;
        this.note = undefined;
        this.form = { kind, editing, values: editing !== undefined ? prefill(this.data, editing) : {} };
        this.render();
    }

    private render(): void {
        const data = this.data;
        if (data === undefined) {
            return;
        }
        this.reset();
        this.root.classList.add('sheet', 'requirements');
        this.root.appendChild(el('p', 'subtitle', summary(data, this.checking)));

        const editable = canEdit(data) && this.callbacks !== undefined;
        if (editable) {
            this.root.appendChild(this.kindStrip());
        } else if (typeof data.editable === 'string' && data.editable) {
            this.root.appendChild(el('p', 'requirements-note', `To be changed by hand: ${data.editable}.`));
        }
        if (this.note !== undefined) {
            this.root.appendChild(el('p', `requirements-note${this.note.error ? ' error' : ''}`, this.note.text));
        }
        if (this.confirming !== undefined) {
            this.root.appendChild(this.confirmation(this.confirming));
        }
        if (this.form !== undefined && editable) {
            this.root.appendChild(this.formOf(this.form, data));
        }

        for (const group of groupChecks(data.requirements)) {
            this.root.appendChild(el('h2', undefined, group.heading));
            this.root.appendChild(this.checkTable(group.checks, editable));
        }

        if (data.features.length > 0) {
            this.root.appendChild(el('h2', undefined, 'Features'));
            this.root.appendChild(this.featureTable(data.features, editable));
        }
    }

    private button(label: string, className: string, title: string, onClick: () => void): HTMLButtonElement {
        const button = el('button', className, label);
        button.type = 'button';
        button.title = title;
        button.disabled = this.saving;
        button.addEventListener('click', () => {
            if (!button.disabled) {
                onClick();
            }
        });
        return button;
    }

    private kindStrip(): HTMLElement {
        const strip = el('div', 'requirements-add');
        strip.appendChild(el('span', 'requirements-add-label', 'Add:'));
        for (const [kind, label] of KINDS) {
            strip.appendChild(
                this.button(label, 'requirements-button', `Add a requirement of this kind (pc req add ${kind})`, () =>
                    this.open(kind),
                ),
            );
        }
        return strip;
    }

    private formOf(form: OpenForm, data: RequirementsData): HTMLElement {
        const box = el('div', 'requirements-form');
        const label = KINDS.find(([kind]) => kind === form.kind)?.[1] ?? form.kind;
        box.appendChild(el('h3', undefined, form.editing !== undefined ? `Edit ${label}` : `Add ${label}`));
        const grid = el('div', 'requirements-fields');
        for (const field of formFields(form.kind, data, form.editing !== undefined)) {
            const row = el('label', 'requirements-field');
            row.appendChild(el('span', 'requirements-field-label', field.label));
            row.appendChild(this.input(field, form));
            grid.appendChild(row);
        }
        box.appendChild(grid);
        const buttons = el('div', 'requirements-buttons');
        buttons.appendChild(
            this.button('Save', 'requirements-button', "Write it into the object's partcad.yaml", () => {
                const edit = editFrom(form.kind, form.values, data, form.editing);
                if (typeof edit === 'string') {
                    this.note = { text: edit, error: true };
                    this.render();
                    return;
                }
                this.send(edit);
            }),
        );
        buttons.appendChild(
            this.button('Cancel', 'requirements-button secondary', 'Change nothing', () => {
                this.form = undefined;
                this.note = undefined;
                this.render();
            }),
        );
        box.appendChild(buttons);
        return box;
    }

    private input(field: FieldSpec, form: OpenForm): HTMLElement {
        const value = form.values[field.key] ?? '';
        let input: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
        if (field.kind === 'select') {
            const select = el('select', 'requirements-input');
            const options = [...(field.options ?? [])];
            if (value !== '' && !options.includes(value)) {
                options.push(value);
            }
            for (const option of options) {
                const node = el('option', undefined, option);
                node.value = option;
                select.appendChild(node);
            }
            select.value = value !== '' ? value : (options[0] ?? '');
            form.values[field.key] = select.value;
            input = select;
        } else if (field.kind === 'textarea') {
            input = el('textarea', 'requirements-input');
            input.value = value;
        } else {
            const text = el('input', 'requirements-input');
            text.type = 'text';
            text.spellcheck = false;
            text.value = value;
            input = text;
        }
        if (field.placeholder !== undefined && field.kind !== 'select') {
            (input as HTMLInputElement | HTMLTextAreaElement).placeholder = field.placeholder;
        }
        input.disabled = field.fixed === true || this.saving;
        input.setAttribute('aria-label', field.label);
        const changed = () => (form.values[field.key] = input.value);
        input.addEventListener('input', changed);
        input.addEventListener('change', changed);
        return input;
    }

    private confirmation(feature: RequirementFeature): HTMLElement {
        const box = el('div', 'requirements-form');
        box.appendChild(
            el(
                'p',
                undefined,
                `The feature '${feature.name}' is named by ${namedBy(feature).join(', ')}. ` +
                    'Removing it takes it out of those as well.',
            ),
        );
        const buttons = el('div', 'requirements-buttons');
        buttons.appendChild(
            this.button('Remove both', 'requirements-button', 'pc req remove feature --with-references', () =>
                this.send(removalOf(featureAddress(feature), true)),
            ),
        );
        buttons.appendChild(
            this.button('Cancel', 'requirements-button secondary', 'Change nothing', () => {
                this.confirming = undefined;
                this.render();
            }),
        );
        box.appendChild(buttons);
        return box;
    }

    private actions(address: RequirementAddress | null | undefined, onRemove?: () => void): HTMLElement {
        const cell = el('td', 'actions');
        if (address === undefined || address === null) {
            return cell;
        }
        if (this.data !== undefined && writtenAt(this.data, address) !== undefined) {
            // A match is edited whole - every amount of it in one form - and
            // removed an amount at a time, as its rows list it.
            const edited: RequirementAddress =
                address.requirement === 'match' ? { requirement: 'match', name: address.name } : address;
            cell.appendChild(
                this.button('Edit', 'requirements-button small', 'Change this requirement', () =>
                    this.open(edited.requirement, edited),
                ),
            );
        }
        cell.appendChild(
            this.button(
                'Remove',
                'requirements-button small secondary',
                'Take this requirement out (pc req remove)',
                onRemove ?? (() => this.send(removalOf(address))),
            ),
        );
        return cell;
    }

    private checkTable(checks: RequirementCheck[], editable: boolean): HTMLElement {
        const table = el('table', 'grid requirement-checks');
        const head = el('tr');
        for (const column of ['', 'Name', 'Required', 'Found', ...(editable ? [''] : [])]) {
            head.appendChild(el('th', undefined, column));
        }
        table.appendChild(el('thead')).appendChild(head);

        const body = el('tbody');
        for (const check of checks) {
            const mark = markOf(check);
            const row = el('tr', `requirement ${mark}`);
            const cell = el('td', `mark ${mark}`, MARK_TEXT[mark]);
            cell.title = MARK_TITLE[mark];
            cell.setAttribute('aria-label', MARK_TITLE[mark]);
            row.appendChild(cell);
            row.appendChild(el('td', 'name', check.name));
            row.appendChild(el('td', undefined, check.requirement));
            row.appendChild(el('td', 'detail', check.detail ?? ''));
            if (editable) {
                row.appendChild(this.actions(check.address));
            }
            body.appendChild(row);
        }
        table.appendChild(body);
        return table;
    }

    private featureTable(features: RequirementFeature[], editable: boolean): HTMLElement {
        const table = el('table', 'grid requirement-features');
        const head = el('tr');
        for (const column of ['Feature', 'Description', 'Validated by', ...(editable ? [''] : [])]) {
            head.appendChild(el('th', undefined, column));
        }
        table.appendChild(el('thead')).appendChild(head);

        const body = el('tbody');
        for (const feature of features) {
            const row = el('tr');
            row.appendChild(el('td', 'name', feature.name));
            row.appendChild(el('td', 'description', feature.desc));
            const validators = el('td', 'validators');
            for (const banner of bannersOf(feature)) {
                const node = el('span', `banner ${banner.kind}`, banner.label);
                node.title = banner.title;
                validators.appendChild(node);
            }
            row.appendChild(validators);
            if (editable) {
                const named = namedBy(feature).length > 0;
                row.appendChild(
                    this.actions(
                        featureAddress(feature),
                        named
                            ? () => {
                                  this.form = undefined;
                                  this.confirming = feature;
                                  this.render();
                              }
                            : undefined,
                    ),
                );
            }
            body.appendChild(row);
        }
        table.appendChild(body);
        return table;
    }
}
