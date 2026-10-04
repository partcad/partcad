//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The 2D and Draft tabs: the object rendered to a file, shown, and saved.
//
// Both are one pane of the same shape - what the object is made of down the left,
// what to render to along the top, the file under it, and a Save button - because
// both are the same operation, 'pc render' of one object to one file type. What
// differs is who implements the file type: the 2D tab asks PartCAD's own
// renderers for a picture (PNG, JPEG, SVG), and the Draft tab names a package
// that draws, the way 'pc render -e' names one, and offers whatever that package
// declares.
//
// The pane down the left is the one the 3D view has, built by the same 'Tree' and
// styled by the same rules, because it is answering the same question. What it
// cannot do here is switch something off on a stage: the picture is made by
// PartCAD and arrives as a file. So the boxes compose a *filter* instead, sent
// with the render, and - on the 2D tab, whose rows include the ports and the
// interfaces - which overlays to draw on top of the projection. This file owns
// the element the tree is drawn into and nothing else about it: who fills it in
// and what a change does are 'viewer.ts'.
//
// The file is shown the way the browser shows it: a picture through an <img>,
// which pans and zooms ('image.ts'), and which cannot run any script an SVG
// carries. A file type the browser cannot show - a PDF, a DXF - is still a file
// the user asked for, so it can be saved all the same; the pane says so rather
// than pretending there was nothing.
//
// The pane never holds a path. The host rendered the file, keeps it, and asks
// the user where to save it; all this side says is "save what this tab shows".
//

import { el, empty, placeholder } from './dom';
import { IMAGE_TYPES, ImageView } from './image';
import { RenderData } from './messages';

/** One entry of a drop-down: what is sent, and what the user reads. */
export interface Choice {
    value: string;
    label: string;
    title?: string;
}

export interface RenderViewOptions {
    /** A fixed list of file types, for a pane that knows them up front. */
    formats?: Choice[];
    /** The packages to draw with, for a pane that offers a choice of them. */
    plugins?: string[];
    /** The file type, or the package, was changed: render again. */
    onChange: () => void;
    /** The package was changed, and its file types are not known yet. */
    onPlugin?: (plugin: string) => void;
    onSave: () => void;
}

export class RenderView {
    private readonly formats = el('select', 'render-select');
    private readonly plugins: HTMLSelectElement | undefined;
    private readonly save = el('button', 'render-save', 'Save…');
    private readonly body = el('div', 'render-body');
    private readonly controls = el('div', 'controls');
    /**
     * Where the control pane's tree is drawn. Owned here because the pane is
     * part of this one's layout; filled in by 'viewer.ts', which is what knows
     * the object and what a change to a box should do.
     */
    public readonly treeHost = el('div', 'tree');
    private image: ImageView | undefined;

    constructor(pane: HTMLElement, options: RenderViewOptions) {
        pane.classList.add('render');
        this.treeHost.setAttribute('role', 'tree');
        this.controls.appendChild(this.treeHost);
        // Hidden until there is an object to list, the way the 3D view's is:
        // with nothing shown it would be an empty list beside an empty picture.
        this.controls.hidden = true;
        pane.appendChild(this.controls);

        const main = el('div', 'render-main');
        const header = el('div', 'render-header');

        if (options.plugins !== undefined) {
            const plugins = el('select', 'render-select render-plugin');
            fill(
                plugins,
                options.plugins.map((plugin) => ({ value: plugin, label: plugin })),
            );
            plugins.title = 'The package that makes the drawing';
            plugins.setAttribute('aria-label', 'Drawn by');
            plugins.addEventListener('change', () => options.onPlugin?.(plugins.value));
            header.appendChild(el('span', 'render-label', 'Drawn by'));
            header.appendChild(plugins);
            this.plugins = plugins;
        }

        this.formats.setAttribute('aria-label', 'Format');
        this.formats.addEventListener('change', () => options.onChange());
        header.appendChild(el('span', 'render-label', 'Format'));
        header.appendChild(this.formats);
        if (options.formats !== undefined) {
            this.setFormats(options.formats);
        }

        this.save.title = 'Save this file somewhere of your choosing';
        this.save.disabled = true;
        this.save.addEventListener('click', () => options.onSave());
        header.appendChild(this.save);

        main.appendChild(header);
        main.appendChild(this.body);
        pane.appendChild(main);
    }

    /** Show or hide the control pane: there is nothing to list without an object. */
    public offerControls(shown: boolean): void {
        this.controls.hidden = !shown;
    }

    /** The file type chosen, or undefined while there is none to choose from. */
    public get format(): string | undefined {
        return this.formats.value || undefined;
    }

    /** The package chosen to draw with, on a pane that offers one. */
    public get plugin(): string | undefined {
        return this.plugins?.value || undefined;
    }

    /**
     * Offer these file types, keeping the one chosen if it is still among them.
     *
     * Otherwise the first of 'preferred' that is, and otherwise the first: a
     * drawing package lists its types in whatever order it likes, and the one
     * the pane can show is the better one to start on.
     */
    public setFormats(choices: Choice[], preferred: string[] = []): void {
        const current = this.formats.value;
        fill(this.formats, choices);
        const values = choices.map((choice) => choice.value);
        const pick = values.includes(current) ? current : preferred.find((value) => values.includes(value));
        if (pick !== undefined) {
            this.formats.value = pick;
        }
        this.formats.disabled = choices.length === 0;
    }

    /** While a render is on its way, which can be a while. */
    public setBusy(text: string): void {
        this.clear();
        this.body.appendChild(placeholder(text));
    }

    public showError(message: string): void {
        this.clear();
        this.body.appendChild(el('p', 'error', message));
    }

    public show(data: RenderData): void {
        this.clear();
        this.save.disabled = false;
        const type = IMAGE_TYPES[data.extension];
        if (type !== undefined) {
            this.image = new ImageView(this.body);
            this.image.show(`data:${type};base64,${data.content}`, `${data.object} as ${data.format}`);
            return;
        }
        this.body.appendChild(
            placeholder(
                `A .${data.extension} file can't be shown here. Save it, and open it in a program that reads ` +
                    `${data.extension.toUpperCase()} files.`,
            ),
        );
    }

    /** Take the file away, and the Save button with it. */
    private clear(): void {
        this.image?.dispose();
        this.image = undefined;
        empty(this.body);
        this.save.disabled = true;
    }
}

function fill(select: HTMLSelectElement, choices: Choice[]): void {
    empty(select);
    for (const choice of choices) {
        const option = el('option', undefined, choice.label);
        option.value = choice.value;
        if (choice.title) {
            option.title = choice.title;
        }
        select.appendChild(option);
    }
}
