//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A panel along one side of a pane, folded away and brought back by the button
// on its edge.
//
// The button is the one an editor hides and shows its side bars with - a window
// with a strip down one side, the strip filled while the panel is out - so it
// reads as what it is without a word on it, and it stays where the panel's edge
// is, folded or not: a strip the width of the button down that side of the pane,
// which is where the panel comes out of. Nothing is laid over the pane to hold
// it, so it never covers a picture's own controls.
//
// Folded or not is one answer per side for the whole panel, not one per tab:
// somebody who brought the view panel out on the 3D tab and turned to the 2D
// one is still looking for it there. Every panel of a side follows the one that
// was clicked, and whoever owns what is beside them hears of it ('onToggle'),
// because a canvas whose pane just got narrower has to be told.
//
// The right side starts folded: the view panel is for whoever wants it, and the
// picture is what a pane is for.
//

import { el } from './dom';

export type Side = 'left' | 'right';

/** Whether each side's panels are out, for the whole of the Digital Thread. */
const expanded: Record<Side, boolean> = { left: true, right: false };

const panels = new Set<SidePanel>();
const listeners = new Set<(side: Side, expanded: boolean) => void>();

/** Whether the panels along 'side' are out. */
export function isExpanded(side: Side): boolean {
    return expanded[side];
}

/** Bring the panels along 'side' out, or fold them away, on every tab at once. */
export function setExpanded(side: Side, value: boolean): void {
    if (expanded[side] === value) {
        return;
    }
    expanded[side] = value;
    panels.forEach((panel) => panel.sync());
    listeners.forEach((listener) => listener(side, value));
}

/** Be told when a side is brought out or folded away: what is beside it has changed size. */
export function onToggle(listener: (side: Side, expanded: boolean) => void): void {
    listeners.add(listener);
}

const SVG = 'http://www.w3.org/2000/svg';

/**
 * The editor's side bar icon, drawn rather than loaded: a window, and the strip
 * down 'side' of it, filled while the panel is out (see '.side-panel-icon-fill').
 */
function icon(side: Side): Element {
    const make = (tag: string, attributes: Record<string, string>) => {
        const node = document.createElementNS(SVG, tag);
        for (const [name, value] of Object.entries(attributes)) {
            node.setAttribute(name, value);
        }
        return node;
    };
    const strip = side === 'right' ? { x: '10', line: '10.5' } : { x: '2', line: '5.5' };
    const svg = make('svg', {
        class: 'side-panel-icon',
        viewBox: '0 0 16 16',
        width: '16',
        height: '16',
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'aria-hidden': 'true',
    });
    svg.appendChild(
        make('rect', { x: '1.5', y: '2.5', width: '13', height: '11', rx: '1', class: 'side-panel-icon-frame' }),
    );
    svg.appendChild(make('rect', { x: strip.x, y: '3', width: '4', height: '10', class: 'side-panel-icon-fill' }));
    svg.appendChild(
        make('line', { x1: strip.line, y1: '3', x2: strip.line, y2: '13', class: 'side-panel-icon-frame' }),
    );
    return svg;
}

export class SidePanel {
    /** The panel: the button and what it folds, to be put at the 'side' end of a pane. */
    public readonly element: HTMLElement;
    /** What it folds away: the owner fills it. */
    public readonly body: HTMLElement;
    private readonly toggle: HTMLButtonElement;

    /** 'name' is what the button shows and hides, as a person would say it: "the view panel". */
    constructor(
        public readonly side: Side,
        private readonly name: string,
    ) {
        this.element = el('aside', `side-panel side-panel-${side}`);
        this.toggle = el('button', 'side-panel-toggle');
        this.toggle.type = 'button';
        this.toggle.appendChild(icon(side) as unknown as HTMLElement);
        this.toggle.addEventListener('click', () => setExpanded(side, !isExpanded(side)));
        this.body = el('div', 'side-panel-body');
        this.element.append(this.toggle, this.body);
        panels.add(this);
        this.sync();
    }

    public get expanded(): boolean {
        return isExpanded(this.side);
    }

    /** Draw the side's state: out or folded, said by the button to whoever cannot see it. */
    public sync(): void {
        const out = isExpanded(this.side);
        this.element.classList.toggle('expanded', out);
        this.body.hidden = !out;
        this.toggle.setAttribute('aria-expanded', out ? 'true' : 'false');
        this.toggle.title = out ? `Hide ${this.name}` : `Show ${this.name}`;
        this.toggle.setAttribute('aria-label', this.toggle.title);
    }
}
