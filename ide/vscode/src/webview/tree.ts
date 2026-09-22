//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The 3D view's control pane: what is on screen, as a tree with a checkbox on
// every item.
//
// The object is a tree of nodes and this is the tree read out as rows: a row per
// node, and under each, a row per port and per interface instance it declares.
// There is no per-kind case in any of it - a part is a tree one node deep, an
// assembly is a node per thing it holds, an interface is a node per port - so
// nothing here asks what it is looking at, and a depth of one is not a shape this
// file knows about.
//
// A box switches its item and everything under it off, and does that without
// touching what is under it: unchecking an assembly node hides the ports inside
// it and checking it again brings back exactly the ones that were on. So an item
// is drawn when its own box is ticked and every box above it is too, and a ticked
// box whose subtree is not entirely on is shown indeterminate - which is the only
// way a collapsed row can say that something below it is hidden.
//
// What starts out ticked follows from depth and nothing else. The object's own
// ports are drawn, because those are the few it says are its own; the ports of
// everything inside it are not, because an assembly of forty parts has a frame at
// every hole of every one of them and all of that at once is not a view of
// anything.
//
// Nothing here is escaped on its way in: an item's name is a part's name or a
// port's, out of a package's configuration, so every row is built node by node
// through 'dom.ts' rather than as markup.
//

import { el, empty } from './dom';
import { ShowNode } from './messages';
import {
    ItemId,
    groupPorts,
    interfaceId,
    interfaceLabel,
    interfacesGroupId,
    nodeId,
    nodeLabel,
    portId,
    portLabel,
    portsGroupId,
} from './nodes';

/**
 * One item of the pane: a row, and what it stands for.
 *
 * 'id' is what the renderer knows the same thing by (see 'nodes.ts'), so an item
 * with nothing on the stage - a group row - simply matches nothing there.
 */
interface Item {
    id: ItemId;
    name: string;
    kind: string;
    checked: boolean;
    /** Whether the row starts folded up. See 'itemsOf'. */
    collapsed: boolean;
    children: Item[];
}

/**
 * The kinds of row that stand for something with geometry of its own or under it:
 * the object, and the nodes inside it. What a hover flickers.
 */
const GEOMETRY_KINDS = new Set(['object', 'node']);

/** One row: the item, whether its own box is ticked, and the rows under it. */
interface Row {
    item: Item;
    checked: boolean;
    box: HTMLInputElement;
    children: Row[];
}

/** What the pane lists for one node: itself, what is inside it, what it declares. */
function itemsOf(node: ShowNode, path: number[]): Item {
    const depth = path.length;
    const children: Item[] = (node.assembly ?? []).map((child, index) => itemsOf(child, [...path, index]));

    const { loose, interfaces } = groupPorts(node);
    const ports = node.ports ?? [];
    // The object's own, and nothing deeper. See the note at the top of this file.
    const drawn = depth === 0;

    if (loose.length > 0) {
        children.push({
            id: portsGroupId(path),
            name: 'ports',
            kind: 'ports',
            checked: drawn,
            // Folded up to begin with. What a reader of the pane is looking at is
            // the object and what it is made of; the ports of a part run to a dozen
            // rows and of an assembly to hundreds, and unfolded they bury the
            // hierarchy they are attached to.
            collapsed: true,
            children: loose.map((index) => ({
                id: portId(path, index),
                name: portLabel(ports[index]),
                kind: 'port',
                checked: true,
                collapsed: false,
                children: [],
            })),
        });
    }

    if (interfaces.length > 0) {
        children.push({
            id: interfacesGroupId(path),
            name: 'interfaces',
            kind: 'interfaces',
            checked: drawn,
            collapsed: true,
            children: interfaces.map((entry, index) => ({
                id: interfaceId(path, index),
                name: interfaceLabel(entry.interface),
                kind: 'interface',
                checked: true,
                collapsed: false,
                // A port is listed under the interface it belongs to and nowhere
                // else: one triad, one box.
                children: entry.ports.map((port) => ({
                    id: portId(path, port),
                    name: portLabel(ports[port]),
                    kind: 'port',
                    checked: true,
                    collapsed: false,
                    children: [],
                })),
            })),
        });
    }

    return {
        id: nodeId(path),
        name: nodeLabel(node),
        kind: depth === 0 ? 'object' : 'node',
        checked: true,
        // The hierarchy itself is what the pane is for, so it is open.
        collapsed: false,
        children,
    };
}

export class Tree {
    private root: Row | undefined;

    /**
     * @param host the element the rows are drawn into
     * @param onChange called after every change the user makes to a box
     * @param onHover called with the items to single out while the pointer is over
     *   a part or a sub-assembly, and with undefined when it leaves
     */
    constructor(
        private readonly host: HTMLElement,
        private readonly onChange: () => void,
        private readonly onHover: (items: Set<ItemId> | undefined) => void = () => undefined,
    ) {}

    /**
     * Draw a tree, optionally keeping what the user had switched off.
     *
     * 'remembered' is for the same object shown again - an edit saved, a
     * re-render - where throwing the selection away would be as unwelcome as
     * throwing the camera away, which is why the show says whether the camera is
     * to be kept. An item is matched by its id *and* its name: the ids are a
     * counter over a walk of the object, so they are stable while the object is,
     * and the name is what notices when it is not.
     */
    public setObject(object: ShowNode, remembered?: Map<string, boolean>): void {
        empty(this.host);
        this.root = this.build(itemsOf(object, []), remembered);
        this.host.appendChild(this.render(this.root));
        this.refresh();
    }

    /** Nothing to list: the panel is empty. */
    public clear(): void {
        empty(this.host);
        this.root = undefined;
    }

    /** The items to draw: every one whose own box and every box above it is ticked. */
    public visible(): Set<ItemId> {
        const visible = new Set<ItemId>();
        const walk = (row: Row) => {
            if (!row.checked) {
                return;
            }
            visible.add(row.item.id);
            row.children.forEach(walk);
        };
        if (this.root !== undefined) {
            walk(this.root);
        }
        return visible;
    }

    /** What the user has switched off, to be handed back to a later 'setTree'. */
    public state(): Map<string, boolean> {
        const state = new Map<string, boolean>();
        const walk = (row: Row) => {
            state.set(key(row.item), row.checked);
            row.children.forEach(walk);
        };
        if (this.root !== undefined) {
            walk(this.root);
        }
        return state;
    }

    private build(item: Item, remembered: Map<string, boolean> | undefined): Row {
        const box = el('input');
        box.type = 'checkbox';
        const row: Row = {
            item,
            checked: remembered?.get(key(item)) ?? item.checked,
            box,
            children: item.children.map((child) => this.build(child, remembered)),
        };
        box.checked = row.checked;
        box.addEventListener('change', () => {
            row.checked = box.checked;
            this.refresh();
            this.onChange();
        });
        return row;
    }

    private render(row: Row): HTMLElement {
        const item = el('div', `tree-item tree-${row.item.kind}`);
        item.setAttribute('role', 'treeitem');

        const line = el('div', 'tree-line');
        // Pointing at a part or a sub-assembly in the pane says which of the things
        // on screen it is. Only those: a port is already told apart by the triad and
        // the boundary drawn at it.
        if (GEOMETRY_KINDS.has(row.item.kind)) {
            line.addEventListener('mouseenter', () => this.onHover(geometryOf(row.item)));
            line.addEventListener('mouseleave', () => this.onHover(undefined));
        }
        const label = el('label', 'tree-label');
        const name = el('span', 'tree-name', row.item.name);
        // The names are long (a port is 'inner-TL-3mm-thru-opening-m3') and the
        // pane is narrow, so a row is cut off with an ellipsis; this is where the
        // whole of it can still be read.
        name.title = row.item.name;
        label.append(row.box, name);

        if (row.children.length === 0) {
            // Where a twisty would be, so that the labels of the rows at one
            // depth line up whether or not they have children.
            line.appendChild(el('span', 'tree-twisty tree-twisty-empty'));
            line.appendChild(label);
            item.appendChild(line);
            return item;
        }

        const children = el('div', 'tree-children');
        children.setAttribute('role', 'group');
        row.children.forEach((child) => children.appendChild(this.render(child)));

        const twisty = el('button', 'tree-twisty');
        const fold = (collapsed: boolean) => {
            children.hidden = collapsed;
            twisty.textContent = collapsed ? '▸' : '▾';
            twisty.title = collapsed ? 'Expand' : 'Collapse';
            twisty.setAttribute('aria-expanded', String(!collapsed));
        };
        fold(row.item.collapsed);
        twisty.addEventListener('click', () => fold(!children.hidden));

        line.append(twisty, label);
        item.append(line, children);
        return item;
    }

    /** Put the indeterminate mark on every ticked box that is hiding something. */
    private refresh(): void {
        const walk = (row: Row): boolean => {
            // Reduced over every child, not short-circuited: each of them has its
            // own mark to set, so all of them have to be walked.
            const whole = row.children.map(walk).every((all) => all) && row.checked;
            row.box.indeterminate = row.checked && !whole;
            return whole;
        };
        if (this.root !== undefined) {
            walk(this.root);
        }
    }
}

/**
 * Every item under this one that stands for geometry, including itself.
 *
 * A sub-assembly has no geometry of its own - what is drawn is the parts inside it -
 * so singling one out means singling out its subtree. The ports and interfaces in
 * that subtree are left out: what is being pointed at is the shape.
 */
function geometryOf(item: Item): Set<ItemId> {
    const found = new Set<ItemId>();
    const walk = (current: Item) => {
        if (!GEOMETRY_KINDS.has(current.kind)) {
            return;
        }
        found.add(current.id);
        current.children.forEach(walk);
    };
    walk(item);
    return found;
}

/**
 * How an item is recognised across two shows of one object.
 *
 * The id alone would match an item that happens to sit at the same place in the
 * tree; the name alone would match the wrong one of two nodes called the same
 * thing. Together they are as good as this can be: a node of an assembly is
 * identified by where it sits in the assembly, and that is exactly what an edit
 * may have changed.
 */
function key(item: Item): string {
    return `${item.id}\u0000${item.name}`;
}
