//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A PartCAD generated document, drawn into the panel.
//
// The document is the very one 'pc render -t html|pdf' writes for an assembly:
// a title page, the bill of materials, a page for every step of putting the
// thing together, and a page of links. It is built once, in Python, as the
// renderer-independent model in 'partcad/document.py' ('assembly.guide' hands it
// over through 'document.to_data()'), so what the instructions say here and what
// the printed book says cannot drift apart - this file only writes it down.
//
// Laid out the way 'document.render_html()' lays the same model out: one page at
// a time, with arrows on either side to flip through it, because a page of an
// instruction book is a step and a reader follows them one at a time.
//

import { el, empty, link } from './dom';
import { DocumentBlock, DocumentData, DocumentImage, DocumentPage } from './messages';

/** A rendered document, with the paging its reader flips through. */
export class DocumentView {
    private readonly pages: HTMLElement[] = [];
    private readonly titles: string[] = [];
    private readonly previous = el('button', 'nav', '‹');
    private readonly next = el('button', 'nav', '›');
    private readonly counter = el('div', 'counter');
    /** The scrolling half; the arrows below it stay put. */
    private readonly body = el('div', 'document-pages');
    private current = 0;

    constructor(root: HTMLElement, data: DocumentData) {
        empty(root);

        const body = this.body;
        for (const page of data.pages) {
            const rendered = renderPage(page, data.footer);
            this.pages.push(rendered);
            this.titles.push(page.title ?? '');
            body.appendChild(rendered);
        }

        this.previous.title = 'Previous page';
        this.next.title = 'Next page';
        this.previous.addEventListener('click', () => this.show(this.current - 1));
        this.next.addEventListener('click', () => this.show(this.current + 1));

        const bar = el('div', 'document-bar');
        bar.append(this.previous, this.counter, this.next);

        root.classList.add('document');
        root.append(body, bar);
        this.show(0);
    }

    /** Flip to a page, clamped to the ones that exist. */
    public show(index: number): void {
        if (this.pages.length === 0) {
            return;
        }
        this.current = Math.min(Math.max(index, 0), this.pages.length - 1);
        this.pages.forEach((page, i) => page.classList.toggle('current', i === this.current));
        this.previous.disabled = this.current === 0;
        this.next.disabled = this.current === this.pages.length - 1;
        const title = this.titles[this.current];
        this.counter.textContent = `${this.current + 1} / ${this.pages.length}` + (title ? ` — ${title}` : '');
        this.body.scrollTop = 0;
    }

    /** Whether an arrow key was one this document could use. */
    public handleKey(key: string): boolean {
        switch (key) {
            case 'ArrowLeft':
            case 'PageUp':
                this.show(this.current - 1);
                return true;
            case 'ArrowRight':
            case 'PageDown':
                this.show(this.current + 1);
                return true;
            case 'Home':
                this.show(0);
                return true;
            case 'End':
                this.show(this.pages.length - 1);
                return true;
            default:
                return false;
        }
    }
}

function renderPage(page: DocumentPage, footer: string | null | undefined): HTMLElement {
    const section = el('section', 'page');
    for (const block of page.blocks) {
        const node = renderBlock(block);
        if (node !== undefined) {
            section.appendChild(node);
        }
    }
    if (footer) {
        // The footer belongs to the page, not to the document: every page of the
        // printed book carries it, and a page here is a page there.
        section.appendChild(renderFooter(footer));
    }
    return section;
}

function renderBlock(block: DocumentBlock): HTMLElement | undefined {
    switch (block.type) {
        case 'heading':
            return renderHeading(block);
        case 'paragraph':
            return renderParagraph(block.text ?? '');
        case 'properties':
            return renderProperties(block.items ?? []);
        case 'images':
            return renderImages(block.images ?? [], block.height);
        case 'table':
            return renderTable(block);
        case 'links':
            return renderLinks(block.items ?? []);
        default:
            // A block type this renderer does not know: a newer 'partcad' against
            // an older extension. Skipping it leaves the rest of the page
            // readable, which is better than refusing the whole document.
            return undefined;
    }
}

function renderHeading(block: DocumentBlock): HTMLElement {
    const level = Math.min(Math.max(block.level ?? 1, 1), 6);
    const heading = document.createElement(`h${level}`);
    heading.appendChild(link(block.text ?? '', block.url));
    return heading;
}

function renderParagraph(text: string): HTMLElement {
    // The model carries newlines inside a paragraph, and the HTML document turns
    // each into a break; 'white-space: pre-line' in the stylesheet does the same
    // without building the markup by hand.
    return el('p', undefined, text);
}

function renderProperties(items: [string, string][]): HTMLElement {
    const list = el('dl', 'properties');
    for (const [label, value] of items) {
        list.append(el('dt', undefined, String(label)), el('dd', undefined, String(value)));
    }
    return list;
}

function renderImages(images: DocumentImage[], height: number | undefined): HTMLElement {
    const row = el('div', 'images');
    // The same share of the page the paginated formats give the row, so a step's
    // exploded view is as prominent here as it is on paper.
    row.style.flexBasis = `${Math.round((height ?? 0.4) * 100)}%`;
    for (const image of images) {
        if (!image.src) {
            continue;
        }
        const figure = el('figure');
        const picture = el('img');
        // A data URI, embedded by the daemon: the illustrations of an instruction
        // book live in a temporary directory that is gone before this runs, and
        // the panel's CSP forbids fetching anything anyway.
        picture.src = image.src;
        picture.alt = image.alt ?? '';
        figure.appendChild(picture);
        if (image.caption) {
            figure.appendChild(el('figcaption', undefined, image.caption));
        }
        row.appendChild(figure);
    }
    return row;
}

function renderTable(block: DocumentBlock): HTMLElement {
    const columns = block.columns ?? [];
    const aligns = block.aligns ?? columns.map(() => 'left');
    const table = el('table');

    const head = el('tr');
    columns.forEach((column, index) => {
        const cell = el('th', undefined, String(column));
        cell.style.textAlign = aligns[index] ?? 'left';
        head.appendChild(cell);
    });
    table.appendChild(el('thead')).appendChild(head);

    const body = el('tbody');
    for (const row of block.rows ?? []) {
        const line = el('tr');
        row.forEach((value, index) => {
            const cell = el('td', undefined, value === null || value === undefined ? '' : String(value));
            cell.style.textAlign = aligns[index] ?? 'left';
            line.appendChild(cell);
        });
        body.appendChild(line);
    }
    table.appendChild(body);
    return table;
}

function renderLinks(items: [string, string][]): HTMLElement {
    const list = el('ul', 'links');
    for (const [text, url] of items) {
        list.appendChild(el('li')).appendChild(link(String(text), url));
    }
    return list;
}

/**
 * The document's footer, whose one markdown link is the only markup the model
 * carries. 'render_html()' translates it the same way, for the same reason: it
 * is written once, in the model, and spelled out by each format.
 */
function renderFooter(text: string): HTMLElement {
    const footer = el('div', 'footer');
    const pattern = /\[([^\]]*)\]\(([^)]*)\)/g;
    let position = 0;
    for (let match = pattern.exec(text); match !== null; match = pattern.exec(text)) {
        footer.appendChild(document.createTextNode(text.slice(position, match.index)));
        footer.appendChild(link(match[1], match[2]));
        position = match.index + match[0].length;
    }
    footer.appendChild(document.createTextNode(text.slice(position)));
    return footer;
}
