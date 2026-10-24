//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The list down the left of a tab that runs what an object declares: the
// Simulation tab's simulations, and each Analysis tab's scenarios.
//
// Both are the same thing - a name per entry of a section, in the order the
// section declares them, one of them selected, and before each name a mark
// saying how its last run went - so both are this one widget, laid out and
// drawn like the Build tab's list ('build-item'), and driven from the keyboard
// as a listbox is. What differs is what a run is and what decides its verdict,
// which stay with each pane: this only draws the verdict it is handed, under
// the pane's own class names ('simulation-mark', 'cae-mark', ...), so that each
// pane's rows are still told apart by what they are of.
//

import { el, empty } from './dom';

/**
 * How a run went, as far as the list says: not run yet, running, or one of how
 * it came out. 'ran' is a run with nothing to check it against - a simulation
 * with no 'validation:' - which an analysis never is: an analysis that found
 * nothing has passed.
 */
export type VerdictState = 'unrun' | 'running' | 'passed' | 'failed' | 'error' | 'ran';

/** A verdict as a row shows it: the symbol before the name, and what it means, for its tooltip. */
export interface Verdict {
    state: VerdictState;
    mark: string;
    label: string;
}

/** One row: what the section declares it under, what it says it is, and how its last run went. */
export interface ScenarioRow {
    name: string;
    desc?: string | null;
    verdict: Verdict;
}

export class ScenarioList {
    /** The column the list is drawn in, which the pane puts down its left. */
    public readonly element: HTMLElement;
    private readonly items: HTMLElement;
    private rows: ScenarioRow[] = [];

    /**
     * 'prefix' is the pane's own: the column is '<prefix>-list', a row
     * 'build-item <prefix>-item', its mark '<prefix>-mark <prefix>-<state>'.
     * 'onSelect' is a click on a row, or Enter, Space or an arrow key on one.
     */
    constructor(
        private readonly prefix: string,
        private readonly onSelect: (name: string) => void,
    ) {
        this.element = el('div', `${prefix}-list`);
        this.items = el('div', `${prefix}-items`);
        this.items.setAttribute('role', 'listbox');
        this.element.append(this.items);
    }

    /** Draw the rows again, with 'selected' marked as the one on screen. */
    public draw(rows: ScenarioRow[], selected: string | undefined): void {
        this.rows = rows;
        empty(this.items);
        for (const entry of rows) {
            const row = el('div', `build-item ${this.prefix}-item`);
            row.setAttribute('role', 'option');
            row.tabIndex = 0;
            row.dataset.name = entry.name;
            const isSelected = entry.name === selected;
            row.classList.toggle('selected', isSelected);
            row.setAttribute('aria-selected', String(isSelected));
            // The verdict, before the name, in its colour: an empty slot of the
            // same width for one not run yet, so that the names stay in a column.
            const mark = el('span', `${this.prefix}-mark ${this.prefix}-${entry.verdict.state}`, entry.verdict.mark);
            mark.title = entry.verdict.label;
            row.appendChild(mark);
            row.appendChild(el('span', 'build-title', entry.name));
            row.title = entry.desc?.trim() ? `${entry.name}: ${entry.desc.trim()}` : entry.name;
            row.addEventListener('click', () => this.onSelect(entry.name));
            row.addEventListener('keydown', (event: KeyboardEvent) => this.onKey(event, entry.name));
            this.items.appendChild(row);
        }
    }

    /** Enter or Space selects; the arrow keys move through the list, as a listbox's do. */
    private onKey(event: KeyboardEvent, name: string): void {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            this.onSelect(name);
            return;
        }
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
            return;
        }
        event.preventDefault();
        const index = this.rows.findIndex((entry) => entry.name === name);
        const next = this.rows[index + (event.key === 'ArrowDown' ? 1 : -1)];
        if (next !== undefined) {
            // Selecting draws the list again, so the row to focus is looked up
            // afterwards rather than kept from before.
            this.onSelect(next.name);
            (this.items.querySelector(`[data-name="${CSS.escape(next.name)}"]`) as HTMLElement | null)?.focus();
        }
    }
}

/**
 * Which entry a list opens on: the one asked for from outside the panel, when
 * the section declares it, and otherwise the first - which is what opening the
 * tab by hand selects.
 */
export function firstSelected(names: string[], requested: string | undefined): string | undefined {
    return requested !== undefined && names.includes(requested) ? requested : names[0];
}
