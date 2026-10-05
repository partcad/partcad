//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The panel's tab strip.
//
// Which tabs apply depends on what is being shown, and changes under the user:
// an assembly has a bill of materials and instructions, a part has neither, and
// nothing at all has only the 3D view. The strip is therefore rebuilt on every
// show, keeping the selected tab when it survives the change - switching from
// one assembly to another must not throw the reader back to the 3D view - and
// falling back to the first one it can open when it does not.
//
// A tab can be left out, or shown and disabled. The panel's strips are fixed
// sets - 3D, 2D and Draft; FEA beside CFD; the five Manufacturing ones - that
// show every one of their tabs always and disable what does not apply, so that the layout does not shift
// from one object to the next and a missing tab reads as "not for this" rather
// than as "not there". The tab the user last opened is remembered through a
// spell of being disabled: back on an object it applies to, it is the one
// shown again.
//
// What the user clicked and what is on screen are kept apart for that reason.
// A strip falls back to another tab when the one clicked does not apply, and
// falling back is not the user changing their mind: the Manufacturing strip
// disables Build and Buy for the moment it takes to learn what is built and
// what is bought, and a reader who was on Buy has to land on Buy again when
// that answer arrives rather than on whatever the strip fell back to.
//

import { el, empty } from './dom';
import { TabId } from './messages';

export interface TabSpec {
    id: TabId;
    label: string;
    pane: HTMLElement;
    /** Shown, but not for this object: it cannot be opened. */
    disabled?: boolean;
    /** Why, when it is disabled: the tab's tooltip. */
    hint?: string;
    /**
     * Opened by a click and never chosen for the user.
     *
     * For a tab that applies but has nothing worth opening on: Build vs Buy of a
     * part that has no stock is a table of one line, and the tab after it is the
     * one somebody opening the strip came for.
     */
    secondary?: boolean;
}

export class Tabs {
    private specs: TabSpec[] = [];
    /** The tab the user last clicked, whether or not it can be opened now. */
    private preferred: TabId | undefined;
    /** The tab on screen. */
    private selected: TabId | undefined;
    /**
     * Every pane this strip has ever been given.
     *
     * A pane dropped from the strip has to be hidden as it goes: the panes are
     * stacked on top of each other, so a Bill of Materials left visible when the
     * next show is a part - which has no such tab - would cover the 3D view with
     * the previous assembly's parts list.
     */
    private readonly known = new Set<HTMLElement>();

    constructor(
        private readonly bar: HTMLElement,
        private readonly onSelect: (id: TabId) => void,
    ) {
        this.bar.setAttribute('role', 'tablist');
    }

    /** The tab the panel is currently on, or undefined when none of them can be opened. */
    public get current(): TabId | undefined {
        return this.enabled(this.selected) ? this.selected : undefined;
    }

    /** Whether any tab of the strip can be opened: what a tab over this strip is enabled by. */
    public static anyEnabled(specs: TabSpec[]): boolean {
        return specs.some((spec) => !spec.disabled);
    }

    /**
     * Replace the strip, keeping the tab last clicked if it can still be opened.
     *
     * Otherwise the first one that can and is not 'secondary' - which is also
     * what a strip opened for the first time shows - and failing that the first
     * one that can. The tab shown is always announced ('onSelect'), because a
     * rebuild is a new object and whatever is on screen has to be asked for
     * again.
     *
     * 'keepCurrent' is a rebuild for the same object - the user changed
     * something the strip depends on - and keeps the tab on screen while it can
     * be opened, 'secondary' or not: a strip must not walk away from the tab the
     * user is working in.
     */
    public setTabs(specs: TabSpec[], options: { keepCurrent?: boolean } = {}): void {
        this.specs = specs;
        for (const spec of specs) {
            this.known.add(spec.pane);
        }
        for (const pane of this.known) {
            pane.hidden = true;
        }
        const keep = options.keepCurrent && this.enabled(this.selected) ? this.selected : this.choose();

        empty(this.bar);
        // One tab is not a choice; the strip would be a title bar for a view
        // there is no alternative to.
        this.bar.hidden = specs.length < 2;
        for (const spec of specs) {
            const button = el('button', 'tab', spec.label);
            button.setAttribute('role', 'tab');
            button.dataset.tab = spec.id;
            // Marked rather than made 'disabled': a disabled button takes no
            // pointer events, so a browser may show no tooltip over it - and the
            // tooltip is the one thing such a tab is there to say. A click on it
            // is refused by 'click()' instead.
            const disabled = spec.disabled === true;
            button.classList.toggle('disabled', disabled);
            button.setAttribute('aria-disabled', String(disabled));
            if (disabled && spec.hint) {
                button.title = spec.hint;
            }
            button.addEventListener('click', () => this.click(spec.id));
            this.bar.appendChild(button);
        }

        if (keep !== undefined) {
            this.selected = undefined;
            this.select(keep);
        } else {
            // Nothing here applies. What was open last is kept in mind for the
            // next object that it does apply to.
            this.markSelected(undefined);
        }
    }

    /** The user asked for a tab: remembered, and opened if it can be. */
    public click(id: TabId): void {
        if (!this.enabled(id)) {
            return;
        }
        this.preferred = id;
        this.select(id);
    }

    /** Switch to a tab, if it is one of the ones on offer and can be opened. */
    public select(id: TabId): void {
        if (!this.enabled(id)) {
            return;
        }
        const changed = this.selected !== id;
        this.selected = id;
        this.markSelected(id);

        if (changed) {
            this.onSelect(id);
        }
    }

    /** What a rebuilt strip opens on; see 'setTabs'. */
    private choose(): TabId | undefined {
        const open = this.specs.filter((spec) => !spec.disabled);
        const usable = (id: TabId | undefined) => open.find((spec) => spec.id === id && !spec.secondary)?.id;
        return (
            usable(this.preferred) ??
            usable(this.selected) ??
            open.find((spec) => !spec.secondary)?.id ??
            open.find((spec) => spec.id === this.preferred)?.id ??
            open[0]?.id
        );
    }

    private enabled(id: TabId | undefined): boolean {
        return id !== undefined && this.specs.some((spec) => spec.id === id && !spec.disabled);
    }

    /** Show the pane of 'id' and nothing else, and say so on the buttons. */
    private markSelected(id: TabId | undefined): void {
        for (const spec of this.specs) {
            spec.pane.hidden = spec.id !== id;
        }
        for (const button of Array.from(this.bar.children) as HTMLElement[]) {
            const selected = button.dataset.tab === id;
            button.classList.toggle('current', selected);
            button.setAttribute('aria-selected', String(selected));
        }
    }
}
