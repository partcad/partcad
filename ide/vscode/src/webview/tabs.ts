//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The panel's tab strip.
//
// Which tabs exist depends on what is being shown, and changes under the user:
// an assembly has a bill of materials and instructions, a part has neither, and
// nothing at all has only the 3D view. The strip is therefore rebuilt on every
// show, keeping the selected tab when it survives the change - switching from
// one assembly to another must not throw the reader back to the 3D view - and
// falling back to the first one when it does not.
//

import { el, empty } from './dom';
import { TabId } from './messages';

export interface TabSpec {
    id: TabId;
    label: string;
    pane: HTMLElement;
}

export class Tabs {
    private specs: TabSpec[] = [];
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

    /** The tab the panel is currently on. */
    public get current(): TabId | undefined {
        return this.selected;
    }

    /** Replace the strip, keeping the current tab if it is still one of them. */
    public setTabs(specs: TabSpec[]): void {
        this.specs = specs;
        for (const spec of specs) {
            this.known.add(spec.pane);
        }
        for (const pane of this.known) {
            pane.hidden = true;
        }
        const keep = specs.some((spec) => spec.id === this.selected) ? this.selected : specs[0]?.id;

        empty(this.bar);
        // One tab is not a choice; the strip would be a title bar for a view
        // there is no alternative to.
        this.bar.hidden = specs.length < 2;
        for (const spec of specs) {
            const button = el('button', 'tab', spec.label);
            button.setAttribute('role', 'tab');
            button.dataset.tab = spec.id;
            button.addEventListener('click', () => this.select(spec.id));
            this.bar.appendChild(button);
        }

        this.selected = undefined;
        if (keep !== undefined) {
            this.select(keep);
        }
    }

    /** Switch to a tab, if it is one of the ones on offer. */
    public select(id: TabId): void {
        if (!this.specs.some((spec) => spec.id === id)) {
            return;
        }
        const changed = this.selected !== id;
        this.selected = id;

        for (const spec of this.specs) {
            spec.pane.hidden = spec.id !== id;
        }
        for (const button of Array.from(this.bar.children) as HTMLElement[]) {
            const selected = button.dataset.tab === id;
            button.classList.toggle('current', selected);
            button.setAttribute('aria-selected', String(selected));
        }

        if (changed) {
            this.onSelect(id);
        }
    }
}
