//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The field every tab that runs somebody else's package names that package in:
// the Draft tab's "Drawn by", the Simulation tab's "Simulated by", and each
// Analysis tab's "Analysed by".
//
// It is a combo box - an editable one: a text field with a list of quick
// choices under it. The field is always filled in, with the package that runs
// when nobody chooses one (what the object names, or the configured default);
// the list offers the packages PartCAD knows of for the job, that one marked;
// and the field takes any other name too, because a package of the user's own,
// or one nobody has registered yet, is as good a package as any of those. What
// is in the field is what 'pc render -e', 'pc sim --plugin' and 'pc cae -i'
// would be given.
//
// Not a <select>, which cannot take a name it does not list, and not an <input>
// with a <datalist>, which Chromium filters by what the field already says -
// and the field always says something, so the list would only ever offer what
// is already chosen - and draws in the operating system's colours rather than
// the editor's. So the list is drawn here, as the WAI-ARIA combo box pattern
// has it: opened by its arrow, by Down, or by typing (which narrows it to what
// matches), and closed by choosing, by Escape or by leaving the field.
//
// A name is *committed* - handed to whoever owns the field - when one is chosen
// from the list, when Enter is pressed, and when the field is left with a new
// name in it. Leaving it empty puts back the one there was. What the owner
// does with it is its own: the Draft tab asks the package what it draws, a
// simulation or an analysis runs with it.
//
// One list of quick choices, made one way ('quickChoices'), so that the three
// tabs cannot come to disagree about what is offered and what is marked.
//

import { el, empty } from './dom';

/** One quick choice: the package, and whether it is the one used when nobody chooses. */
export interface PackageChoice {
    value: string;
    /** Whether it is what runs unasked: what the object names, or the configured default. */
    configured: boolean;
    /** What it is, when pointed at. */
    title: string;
    /** Said beside the one used unasked, in the list: why it is that one. */
    note?: string;
}

/**
 * The quick choices: every package PartCAD knows of for the job, in the order
 * given, with the one used unasked marked - and that one first, as itself,
 * when it is none of them.
 *
 * 'matches' says whether a known package is the one 'unasked' names, which is
 * the owner's to say: a simulation plugin is told apart by its entry's name, an
 * analysis by its package's, since every solver calls its file type after the
 * analysis.
 */
export function quickChoices(
    known: string[],
    unasked: string | undefined,
    matches: (value: string, unasked: string) => boolean,
    why: string,
    note?: string,
): PackageChoice[] {
    const choices: PackageChoice[] = known.map((value) => {
        const isUnasked = unasked !== undefined && matches(value, unasked);
        return {
            value,
            configured: isUnasked,
            title: isUnasked ? why : `Use ${value} instead`,
            ...(isUnasked && note ? { note } : {}),
        };
    });
    if (unasked !== undefined && unasked !== '' && !choices.some((choice) => choice.configured)) {
        choices.unshift({ value: unasked, configured: true, title: why, ...(note ? { note } : {}) });
    }
    return choices;
}

/** The choice used unasked, or the first when none is marked. */
export function unaskedChoice(choices: PackageChoice[]): PackageChoice | undefined {
    return choices.find((choice) => choice.configured) ?? choices[0];
}

export interface PackagePickerOptions {
    /** What the field is called where it is read, and for a screen reader: "Simulated by". */
    label: string;
    /** What it is, when pointed at. */
    title: string;
    /** A class of the owner's own on the field, which is what its tests and its styles find it by. */
    className?: string;
    /** A name was committed: chosen, entered, or left in the field. */
    onCommit: (value: string) => void;
}

/** Ids for the list and its options, unique in the panel. */
let pickers = 0;

/** The keyboard and mouse events the field acts on, as far as it reads them. */
interface KeyLike {
    key?: string;
    altKey?: boolean;
    preventDefault?: () => void;
}

export class PackagePicker {
    /** The field, its arrow and its list: what the owner puts in its toolbar. */
    public readonly element: HTMLElement;
    private readonly input: HTMLInputElement;
    private readonly toggle: HTMLButtonElement;
    private readonly list: HTMLElement;
    private readonly id: string;
    private choices: PackageChoice[] = [];
    /** What was last committed, or set: what the field goes back to. */
    private committed = '';
    /** Whether the field has the focus: what it says then is what is being typed, and is left alone. */
    private focused = false;
    /** The options on show, and which of them Up and Down have reached. */
    private shown: PackageChoice[] = [];
    private active = -1;

    constructor(private readonly options: PackagePickerOptions) {
        pickers += 1;
        this.id = `package-picker-${pickers}`;
        this.element = el('span', 'package-picker');

        this.input = el('input', `render-select render-plugin package-picker-input ${options.className ?? ''}`.trim());
        this.input.type = 'text';
        this.input.spellcheck = false;
        this.input.title = `${options.title}. Choose one, or type the name of any other, as '<package>:<name>'`;
        this.input.setAttribute('aria-label', options.label);
        this.input.setAttribute('role', 'combobox');
        this.input.setAttribute('aria-autocomplete', 'list');
        this.input.setAttribute('aria-expanded', 'false');
        this.input.setAttribute('aria-controls', `${this.id}-list`);
        this.input.addEventListener('focus', () => {
            this.focused = true;
        });
        this.input.addEventListener('blur', () => this.left());
        this.input.addEventListener('input', () => this.open(true));
        this.input.addEventListener('keydown', (event?: KeyLike) => this.onKey(event));

        this.toggle = el('button', 'package-picker-toggle', '▾');
        this.toggle.type = 'button';
        this.toggle.tabIndex = -1;
        this.toggle.title = 'Show the choices';
        this.toggle.setAttribute('aria-label', `${options.label}: show the choices`);
        // Pressed without taking the focus from the field, so that opening the
        // list is not leaving the field.
        this.toggle.addEventListener('mousedown', (event?: KeyLike) => event?.preventDefault?.());
        this.toggle.addEventListener('click', () => {
            if (this.isOpen) {
                this.close();
            } else {
                this.open(false);
                this.input.focus?.();
            }
        });

        this.list = el('div', 'package-picker-list');
        this.list.id = `${this.id}-list`;
        this.list.setAttribute('role', 'listbox');
        this.list.hidden = true;

        this.element.appendChild(this.input);
        this.element.appendChild(this.toggle);
        this.element.appendChild(this.list);
    }

    /** What the field says now, which may be a name being typed. */
    public get value(): string {
        return this.input.value.trim();
    }

    /** The name last committed or set: the one in use. */
    public get current(): string {
        return this.committed;
    }

    public set disabled(disabled: boolean) {
        this.input.disabled = disabled;
        this.toggle.disabled = disabled;
    }

    /**
     * Fill the field with 'value', and offer 'choices'.
     *
     * What the user is typing is left alone: an answer arriving while somebody
     * is in the middle of a package name must not put the old one back under
     * their fingers. Otherwise the field says 'value', always.
     */
    public set(value: string, choices: PackageChoice[]): void {
        const typing = this.focused && this.input.value !== this.committed;
        this.committed = value;
        this.choices = choices;
        if (!typing && this.input.value !== value) {
            this.input.value = value;
        }
        if (this.isOpen) {
            this.open(typing);
        } else {
            this.draw(this.choices);
        }
    }

    /** Take what the field says as the name, as Enter does, and hand it to the owner if it is a new one. */
    public commit(): void {
        this.close();
        const value = this.value;
        if (value === '') {
            // Emptied: the name it had is the name it has.
            this.input.value = this.committed;
            return;
        }
        if (value !== this.input.value) {
            this.input.value = value;
        }
        if (value === this.committed) {
            return;
        }
        this.committed = value;
        this.options.onCommit(value);
    }

    private get isOpen(): boolean {
        return !this.list.hidden;
    }

    /** Show the list: every choice, or - 'narrow' - the ones matching what is typed. */
    private open(narrow: boolean): void {
        const typed = this.value.toLowerCase();
        const choices =
            narrow && typed !== ''
                ? this.choices.filter((choice) => choice.value.toLowerCase().includes(typed))
                : this.choices;
        this.draw(choices);
        this.list.hidden = choices.length === 0;
        this.input.setAttribute('aria-expanded', String(!this.list.hidden));
    }

    private close(): void {
        this.list.hidden = true;
        this.active = -1;
        this.input.setAttribute('aria-expanded', 'false');
        this.input.setAttribute('aria-activedescendant', '');
    }

    /** The field was left: close the list, and commit what it says. */
    private left(): void {
        this.focused = false;
        this.commit();
    }

    private draw(choices: PackageChoice[]): void {
        this.shown = choices;
        this.active = -1;
        empty(this.list);
        choices.forEach((choice, index) => {
            const option = el(
                'div',
                `package-picker-option${choice.configured ? ' configured' : ''}${choice.value === this.committed ? ' current' : ''}`,
            );
            option.id = `${this.id}-option-${index}`;
            option.setAttribute('role', 'option');
            option.setAttribute('aria-selected', String(choice.value === this.committed));
            option.title = choice.title;
            option.appendChild(el('span', 'package-picker-value', choice.value));
            if (choice.note) {
                option.appendChild(el('span', 'package-picker-note', choice.note));
            }
            // On the press rather than the click, and without taking the focus:
            // a click is a press and a release, and the field is left in
            // between - which would commit what it said before the choice.
            option.addEventListener('mousedown', (event?: KeyLike) => {
                event?.preventDefault?.();
                this.choose(choice.value);
            });
            this.list.appendChild(option);
        });
    }

    private choose(value: string): void {
        this.input.value = value;
        this.commit();
    }

    /** Down and Up move through the list (Down opens it), Enter takes, Escape closes or puts back. */
    private onKey(event: KeyLike | undefined): void {
        const key = event?.key;
        if (key === 'ArrowDown' || key === 'ArrowUp') {
            event?.preventDefault?.();
            if (!this.isOpen) {
                this.open(false);
                return;
            }
            if (this.shown.length === 0 || event?.altKey) {
                return;
            }
            const step = key === 'ArrowDown' ? 1 : -1;
            this.highlight((this.active + step + this.shown.length) % this.shown.length);
            return;
        }
        if (key === 'Enter') {
            event?.preventDefault?.();
            if (this.isOpen && this.active >= 0) {
                this.choose(this.shown[this.active].value);
            } else {
                this.commit();
            }
            return;
        }
        if (key === 'Escape') {
            if (this.isOpen) {
                event?.preventDefault?.();
                this.close();
            } else {
                this.input.value = this.committed;
            }
        }
    }

    private highlight(index: number): void {
        this.active = index;
        Array.from(this.list.children).forEach((option, at) => {
            option.classList.toggle('active', at === index);
        });
        this.input.setAttribute('aria-activedescendant', index >= 0 ? `${this.id}-option-${index}` : '');
    }
}
