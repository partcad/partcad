//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "Assembly" tab: the assembly instructions as a document to keep.
//
// The Build tab is for following the steps one at a time; this one is for the
// book that is printed or sent - the same plan written out in full, in the
// format chosen at the top, and saved where the user says. It is laid out the
// way the 2D and Draft tabs are, for the same reason: what to produce along the
// top, the result under it, and Save beside it.
//
// "Recursive" and "Build parts" are 'pc instructions -r' and '-b': whether the
// sub-assemblies that are built are documented inside this book, and whether the
// steps that make the parts that are built are. The pages come in the order of
// the Build tab's list with the same two choices made.
//
// What is shown is the document model ('document.ts'), not the file: a PDF is
// not something a webview can show, and the HTML would need a frame the panel's
// CSP does not allow. Both are written by the daemon from the one model it sends
// beside the file, so what is on screen is what Save writes.
//

import { DocumentView } from './document';
import { el, empty, placeholder } from './dom';
import { GuideData } from './messages';

export interface AssemblyCallbacks {
    /** The format or one of the boxes changed: ask for the document again. */
    onChange: () => void;
    onSave: () => void;
}

export class AssemblyView {
    private readonly formats = el('select', 'render-select');
    private readonly recursiveBox = el('input');
    private readonly buildPartsBox = el('input');
    private readonly save = el('button', 'render-save', 'Save…');
    private readonly body = el('div', 'assembly-body');
    private document: DocumentView | undefined;

    constructor(pane: HTMLElement, callbacks: AssemblyCallbacks) {
        pane.classList.add('render', 'assembly');
        const header = el('div', 'render-header');

        for (const [value, label] of [
            ['pdf', 'PDF'],
            ['html', 'HTML'],
        ]) {
            const option = el('option', undefined, label);
            option.value = value;
            this.formats.appendChild(option);
        }
        this.formats.setAttribute('aria-label', 'Format');
        this.formats.addEventListener('change', () => callbacks.onChange());
        header.appendChild(el('span', 'render-label', 'Format'));
        header.appendChild(this.formats);

        header.appendChild(
            checkbox(
                this.recursiveBox,
                'Recursive',
                'Include the steps of the sub-assemblies that are built, each before the step that adds it',
                callbacks.onChange,
            ),
        );
        header.appendChild(
            checkbox(
                this.buildPartsBox,
                'Build parts',
                'Include how to make the parts that are built, each before the step that adds it',
                callbacks.onChange,
            ),
        );

        this.save.title = 'Save this document somewhere of your choosing';
        this.save.disabled = true;
        this.save.addEventListener('click', () => callbacks.onSave());
        header.appendChild(this.save);

        pane.append(header, this.body);
    }

    public get format(): string {
        return this.formats.value || 'pdf';
    }

    public get recursive(): boolean {
        return this.recursiveBox.checked;
    }

    public get buildParts(): boolean {
        return this.buildPartsBox.checked;
    }

    public setBusy(text: string): void {
        this.clear();
        this.body.appendChild(placeholder(text));
    }

    public showError(message: string): void {
        this.clear();
        this.body.appendChild(el('p', 'error', message));
    }

    public show(data: GuideData): void {
        this.clear();
        this.document = new DocumentView(this.body, data.document);
        // Only a file the host kept can be saved; a daemon too old to write one
        // still has its document shown.
        this.save.disabled = data.file === undefined;
    }

    /** The arrow keys flip the pages, as they do in any document viewer. */
    public handleKey(key: string): boolean {
        return this.document?.handleKey(key) ?? false;
    }

    private clear(): void {
        this.document = undefined;
        empty(this.body);
        this.body.className = 'assembly-body';
        this.save.disabled = true;
    }
}

function checkbox(box: HTMLInputElement, label: string, title: string, onChange: () => void): HTMLElement {
    const wrapper = el('label', 'control-label');
    box.type = 'checkbox';
    box.addEventListener('change', () => onChange());
    wrapper.append(box, ` ${label}`);
    wrapper.title = title;
    return wrapper;
}
