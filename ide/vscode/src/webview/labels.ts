//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The callout boxes at the bottom of the 3D and 2D tabs' control pane: which of
// five things are written on the object as callouts.
//
// * "Component names" and "Component prices" put one callout on every component -
//   every part, wherever the object places it - with a row for each of the two
//   that is ticked: its name over its price.
// * "Materials" puts one on every cluster of a material, naming it: the faces of
//   one material, of one part or of several, that touch or are closer than the
//   user's 'materialClusterDistance' (ten millimetres unless it says otherwise).
//   One per cluster rather than one per face or per part, so that a frame of
//   twelve steel tubes says "steel" once.
// * "Port names" and "Interface names" write the names of the ports and of the
//   interface instances that are drawn. On by default, because a port drawn with
//   no name is a frame nobody can find in an ASSY file, and the 2D tab's picture
//   always wrote them.
//
// None of the five puts anything on a thing the tree above does not draw: a
// callout belongs to what it is pinned to, so the box that hides a part hides its
// callout and a port that is not drawn has no name written beside it - and a
// cluster of a material is called out while the tree draws any part of it. The
// boxes say *what* is written; the tree says *on what*.
//
// The answer is one for the two tabs, for the reason the tree's is ('Selection'):
// how somebody wants the object annotated is the same question on both, and a box
// cleared on one is cleared on the other. Unlike the tree's, it is kept from one
// object to the next - it says nothing about any one object - the way the
// Metadata box is.
//
// What a box does differs between the tabs exactly as the tree's boxes do. The 3D
// view writes the callouts itself ('scene.ts'); the 2D tab's picture is made by
// PartCAD, so the boxes are sent with the render as the 'pc render' options they
// are ('renderOptions'). The two write a component's name by one rule
// ('componentName' in 'callouts.ts', and its Python twin in 'render_svg.py').
//
// Free of three.js, so that it can be tested outside a browser.
//

import { el } from './dom';

/** The five boxes, as what they say. */
export interface LabelChoices {
    componentNames: boolean;
    componentPrices: boolean;
    materials: boolean;
    portNames: boolean;
    interfaceNames: boolean;
}

export type LabelKey = keyof LabelChoices;

/** What the boxes start out as: the names of what is drawn, and nothing about the components. */
export const LABEL_DEFAULTS: Readonly<LabelChoices> = {
    componentNames: false,
    componentPrices: false,
    materials: false,
    portNames: true,
    interfaceNames: true,
};

/** The boxes, in the order they are listed, with what each one is called and what it does. */
export const LABEL_BOXES: readonly { key: LabelKey; label: string; title: string }[] = [
    {
        key: 'componentNames',
        label: 'Component names',
        title: 'A callout on every component that is drawn, with its name (pc render --with-component-names)',
    },
    {
        key: 'componentPrices',
        label: 'Component prices',
        title:
            'A callout on every component that is drawn, with its share of what the object costs to buy - the ' +
            'cheapest quote of each thing to order, as the Buy tab finds it (pc render --with-component-prices)',
    },
    {
        key: 'materials',
        label: 'Materials',
        title:
            'A callout on every cluster of a material that is drawn, naming it: the faces of one material that ' +
            'touch or are closer than materialClusterDistance in the user configuration, 10 mm unless it says ' +
            'otherwise (pc render --with-materials)',
    },
    {
        key: 'portNames',
        label: 'Port names',
        title: 'The name of every port that is drawn (pc render --without-port-names to leave them off)',
    },
    {
        key: 'interfaceNames',
        label: 'Interface names',
        title: 'The name of every interface that is drawn (pc render --without-interface-names to leave them off)',
    },
];

/**
 * What the boxes say, for both tabs.
 *
 * A store the widgets consult rather than something each of them owns, for the
 * reason 'Selection' is one: the two tabs show one answer.
 */
export class Labels {
    private choices: LabelChoices = { ...LABEL_DEFAULTS };
    private readonly listeners: ((key: LabelKey) => void)[] = [];

    /** A copy of what the boxes say. */
    public get current(): LabelChoices {
        return { ...this.choices };
    }

    public get(key: LabelKey): boolean {
        return this.choices[key];
    }

    /** Record one box, and tell everybody showing it - unless it said that already. */
    public set(key: LabelKey, value: boolean): void {
        if (this.choices[key] === value) {
            return;
        }
        this.choices[key] = value;
        this.listeners.forEach((listener) => listener(key));
    }

    /**
     * Be told when a box changes, and which.
     *
     * The listener re-reads the store; it must not write to it, or two widgets
     * would answer each other forever.
     */
    public onChange(listener: (key: LabelKey) => void): void {
        this.listeners.push(listener);
    }
}

/**
 * The five boxes, drawn into one tab's control pane under its tree.
 *
 * Every tab's boxes read and write the one 'Labels', so ticking one on the 3D
 * view ticks it on the 2D tab as well; and a line under them says what the
 * prices and the materials are doing, on the tab that asks for them itself
 * ('setNote'), one line for each.
 */
export class LabelBoxes {
    private readonly boxes = new Map<LabelKey, HTMLInputElement>();
    private readonly note: HTMLElement;
    private readonly notes = new Map<LabelKey, string>();

    constructor(host: HTMLElement, labels: Labels) {
        host.classList.add('viewer-controls', 'label-controls');
        host.setAttribute('role', 'group');
        host.setAttribute('aria-label', 'Callouts');
        for (const { key, label, title } of LABEL_BOXES) {
            const row = el('label', 'control-label');
            row.title = title;
            const box = el('input');
            box.type = 'checkbox';
            box.checked = labels.get(key);
            box.addEventListener('change', () => labels.set(key, box.checked));
            row.append(box, document.createTextNode(` ${label}`));
            host.appendChild(row);
            this.boxes.set(key, box);
        }
        this.note = el('div', 'label-note');
        this.note.hidden = true;
        host.appendChild(this.note);
        // Another tab changed one: show it. Reading only, so this cannot loop
        // back into the store.
        labels.onChange((key) => {
            const box = this.boxes.get(key);
            if (box !== undefined) {
                box.checked = labels.get(key);
            }
        });
    }

    /**
     * Say what one box's answer is doing - being asked for, or why there is none
     * - or nothing. A line per box, in the order the boxes are listed, so that
     * the prices and the materials, asked at once, do not write over each other.
     */
    public setNote(text: string | undefined, key: LabelKey = 'componentPrices'): void {
        if (text === undefined) {
            this.notes.delete(key);
        } else {
            this.notes.set(key, text);
        }
        const lines = LABEL_BOXES.map((box) => this.notes.get(box.key)).filter((line) => line !== undefined);
        this.note.textContent = lines.join('\n');
        this.note.hidden = lines.length === 0;
    }
}

/**
 * The boxes as a render request carries them: the 'pc render' options they are.
 *
 * The two components' boxes and the materials' are sent when ticked and the two
 * names' boxes when cleared, which is when each says something a render does
 * not do anyway - so a picture asked for with the boxes as they start is asked
 * for in exactly the words it always was, and a daemon from before them is
 * asked nothing it does not know.
 */
export function renderOptions(choices: LabelChoices): {
    withComponentNames?: boolean;
    withComponentPrices?: boolean;
    withMaterials?: boolean;
    withPortNames?: boolean;
    withInterfaceNames?: boolean;
} {
    return {
        ...(choices.componentNames ? { withComponentNames: true } : {}),
        ...(choices.componentPrices ? { withComponentPrices: true } : {}),
        ...(choices.materials ? { withMaterials: true } : {}),
        ...(choices.portNames ? {} : { withPortNames: false }),
        ...(choices.interfaceNames ? {} : { withInterfaceNames: false }),
    };
}
