//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "Build" tab: the order the object is made in, one step at a time.
//
// A list on the left and the selected step on the right. The list is the build
// plan the daemon works out from what the user chose on the Build vs Buy tab
// ('manufacturing.plan'), and the step is a page of the instruction book that
// plan is also written out as - so the list here and the pages of what the
// Assembly tab saves are one plan in one order, and cannot disagree about either.
//
//   * For a part, the list is flat: the stock that is built, deepest first, and
//     the part itself last - so the reader starts from the first thing they
//     have to make and ends at the thing they are browsing.
//   * For an assembly, it is a tree: the assembly, then its links in order, each
//     part that is built preceded by a step that makes it (and those by the
//     steps that make their stock). With "Recursively" on, a sub-assembly that is
//     built gets an item of its own before the link that adds it, holding its
//     own tree. A part or a sub-assembly built in several places is made once,
//     with how many written beside it, at the lowest level that holds all of
//     them.
//
// The plan is asked for first and alone, because it is cheap and the list is
// what the user came for; the pages take every illustration of the book to be
// drawn, and arrive afterwards.
//

import { renderPage } from './document';
import { el, empty, placeholder } from './dom';
import { PlanData, PlanItem } from './messages';

export interface BuildCallbacks {
    /** "Recursively" was switched: the plan has to be asked for again. */
    onRecursive: () => void;
}

export class BuildView {
    private readonly list = el('div', 'build-list');
    private readonly tree = el('div', 'build-tree');
    private readonly recursiveControl = el('label', 'control-label build-recursive');
    private readonly recursiveBox = el('input');
    private readonly main = el('div', 'build-main');
    private data: PlanData | undefined;
    private selected: string | undefined;
    private documentError: string | undefined;

    constructor(
        private readonly root: HTMLElement,
        callbacks: BuildCallbacks,
    ) {
        root.classList.add('build');
        this.tree.setAttribute('role', 'tree');
        this.recursiveBox.type = 'checkbox';
        this.recursiveBox.addEventListener('change', () => callbacks.onRecursive());
        this.recursiveControl.append(this.recursiveBox, ' Recursively');
        this.recursiveControl.title =
            'Include how to put together the sub-assemblies that are built, each before the link that adds it';
        this.list.append(this.tree, this.recursiveControl);
        root.append(this.list, this.main);
    }

    /** Whether the sub-assemblies' own steps are asked for too. */
    public get recursive(): boolean {
        return this.recursiveBox.checked;
    }

    public setBusy(text: string): void {
        this.data = undefined;
        this.documentError = undefined;
        empty(this.tree);
        this.recursiveControl.hidden = true;
        this.showMain(placeholder(text));
    }

    public showError(message: string): void {
        this.data = undefined;
        empty(this.tree);
        this.recursiveControl.hidden = true;
        this.showMain(el('p', 'error', message));
    }

    /** The plan has arrived: list it, and select where to start. */
    public showPlan(data: PlanData): void {
        this.data = data;
        this.documentError = undefined;
        // Only an assembly has sub-assemblies to recurse into.
        this.recursiveControl.hidden = data.plan.type !== 'assembly';
        const items = data.plan.type === 'part' ? (data.plan.children ?? []) : [data.plan];
        if (items.length === 0) {
            empty(this.tree);
            this.showMain(placeholder('This is bought rather than built, so there is nothing to build.'));
            return;
        }
        // The same item again if the plan still has it - "Recursively" moves
        // the items around, and should not move the reader - and the first one
        // otherwise: the assembly's intro, or the first part to make.
        const ids = new Set<string>();
        collect(items, ids);
        if (this.selected === undefined || !ids.has(this.selected)) {
            this.selected = items[0].id;
        }
        this.drawTree(items);
        this.showSelected();
    }

    /** The pages have arrived: show the selected one. */
    public showDocument(data: PlanData): void {
        if (this.data === undefined) {
            return;
        }
        this.data = { ...this.data, document: data.document, pages: data.pages };
        this.showSelected();
    }

    /** The pages could not be had; the list stays, since it is still right. */
    public showDocumentError(message: string): void {
        this.documentError = message;
        this.showSelected();
    }

    /** Forget the selection: a different object is on screen. */
    public forget(): void {
        this.selected = undefined;
    }

    private drawTree(items: PlanItem[]): void {
        empty(this.tree);
        for (const item of items) {
            this.tree.appendChild(this.drawItem(item, 0));
        }
    }

    private drawItem(item: PlanItem, depth: number): HTMLElement {
        const node = el('div', 'build-node');
        const row = el('div', `build-item build-${item.type}`);
        row.setAttribute('role', 'treeitem');
        row.tabIndex = 0;
        row.dataset.id = item.id;
        row.style.paddingLeft = `${0.4 + depth * 1.1}rem`;
        const children = item.children ?? [];
        const twisty = el('span', 'twisty', children.length > 0 ? '▾' : '');
        row.appendChild(twisty);
        row.appendChild(el('span', 'build-title', item.title));
        row.title = describe(item);
        row.classList.toggle('selected', item.id === this.selected);
        row.setAttribute('aria-selected', String(item.id === this.selected));
        node.appendChild(row);

        if (children.length > 0) {
            const group = el('div', 'build-children');
            group.setAttribute('role', 'group');
            for (const child of children) {
                group.appendChild(this.drawItem(child, depth + 1));
            }
            node.appendChild(group);
            row.setAttribute('aria-expanded', 'true');
            twisty.addEventListener('click', (event) => {
                event.stopPropagation();
                group.hidden = !group.hidden;
                twisty.textContent = group.hidden ? '▸' : '▾';
                row.setAttribute('aria-expanded', String(!group.hidden));
            });
        }

        const select = () => {
            this.selected = item.id;
            for (const other of Array.from(this.tree.querySelectorAll('.build-item')) as HTMLElement[]) {
                const on = other.dataset.id === item.id;
                other.classList.toggle('selected', on);
                other.setAttribute('aria-selected', String(on));
            }
            this.showSelected();
        };
        row.addEventListener('click', select);
        row.addEventListener('keydown', (event: KeyboardEvent) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                select();
            }
        });
        return node;
    }

    private showSelected(): void {
        const data = this.data;
        if (data === undefined || this.selected === undefined) {
            return;
        }
        if (this.documentError !== undefined) {
            this.showMain(el('p', 'error', this.documentError));
            return;
        }
        if (data.document === undefined || data.pages === undefined) {
            this.showMain(
                placeholder('Preparing the instructions… The first time takes a while: every step is drawn.'),
            );
            return;
        }
        const index = data.pages[this.selected];
        const page = index === undefined ? undefined : data.document.pages[index];
        if (page === undefined) {
            this.showMain(placeholder('There is no page for this step.'));
            return;
        }
        const pages = el('div', 'document-pages');
        const rendered = renderPage(page, data.document.footer);
        rendered.classList.add('current');
        pages.appendChild(rendered);
        const wrapper = el('div', 'document');
        wrapper.appendChild(pages);
        this.showMain(wrapper);
    }

    private showMain(content: HTMLElement): void {
        empty(this.main);
        this.main.appendChild(content);
    }
}

function collect(items: PlanItem[], ids: Set<string>): void {
    for (const item of items) {
        ids.add(item.id);
        collect(item.children ?? [], ids);
    }
}

/** The tooltip of an item: what selecting it shows. */
function describe(item: PlanItem): string {
    switch (item.type) {
        case 'manufacture':
            return `Make ${item.name}${item.count > 1 ? `, ${item.count} of them` : ''}`;
        case 'assembly':
            return `Put together ${item.name}${item.count > 1 ? `, ${item.count} of them` : ''}`;
        case 'link':
            return item.step ? `Step ${item.step}: add ${item.name}` : `Start with ${item.name}`;
        default:
            return item.name;
    }
}
