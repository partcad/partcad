//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The control pane of the Design tabs: what the object is made of, as a tree with
// a checkbox on every item.
//
// One class for all three tabs, because all three are asking the same question
// of the same tree -- which of these do I want to see? -- and differ only in
// what the answer is used for. The 3D view switches things on the stage on and
// off. The 2D and Draft tabs cannot: the picture is made by PartCAD, on the
// other side of a JSON-RPC connection, so what the boxes produce there is a
// *filter* ('filter()') that is sent with the render, plus -- on the 2D tab --
// which of the port overlays to draw ('overlay()'). A second tree widget for
// that would be a second set of rules about what a row stands for.
//
// The three differ in two options and nothing else: Draft lists no ports or
// interfaces (a dimensioned drawing is of the solid), and the two render tabs
// fix the root's box ticked, since the object itself is what is being rendered
// and there is no picture without it.
//
// **The three share one answer.** What is ticked is a property of the object
// being looked at, not of the tab it is being looked at on, so switching from 3D
// to 2D to Draft shows the same selection and a box cleared on one is cleared on
// all of them ('Selection'). Draft lists no ports, which is precisely why the
// state lives outside the widgets: a port switched off on the 2D tab has to
// survive a visit to Draft, which has no row to hold it.
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
import { ShowNode, ShowPort } from './messages';
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
    /**
     * Whether this row belongs to something *inside* the object rather than to
     * the object itself. What '--with-internals' says of the port overlays: an
     * assembly is taken at its word by default and only the ports it
     * externalizes are drawn.
     */
    deep?: boolean;
    /**
     * On a port row: the name PartCAD reports that port under, which is what
     * names it in a request back ('pc render --port').
     *
     * The port's own name for a port of the object, and the path of links then
     * the port for one inside it, joined with ':' - which is 'shape_ports.qualify'
     * and is why the labels down the tree are the link names (see
     * 'ShowNode.label'): both sides compose the same string from the same parts.
     */
    port?: string;
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
function itemsOf(node: ShowNode, path: number[], options: TreeOptions, owner: readonly string[] = []): Item {
    const depth = path.length;
    const children: Item[] = (node.assembly ?? []).map((child, index) =>
        itemsOf(child, [...path, index], options, [...owner, nodeLabel(child)]),
    );

    const { loose, interfaces } = groupPorts(node);
    const ports = node.ports ?? [];
    // The object's own, and nothing deeper. See the note at the top of this file.
    // A pane whose boxes drive a render starts them clear instead: the picture a
    // tab shows when it is first opened is the object, and an overlay nobody
    // asked for is not it.
    const drawn = depth === 0 && options.portsDrawn !== false;
    const deep = depth > 0;

    if (options.ports === false) {
        // A dimensioned drawing is of the solid. Nothing is drawn at a port in
        // one, so a row for one would be a box with nothing behind it.
        return {
            id: nodeId(path),
            name: nodeLabel(node),
            kind: depth === 0 ? 'object' : 'node',
            checked: true,
            collapsed: false,
            children,
            deep,
        };
    }

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
            deep,
            children: loose.map((index) => ({
                id: portId(path, index),
                name: portLabel(ports[index]),
                kind: 'port',
                checked: true,
                collapsed: false,
                children: [],
                deep,
                port: reportedAs(owner, ports[index]),
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
            deep,
            children: interfaces.map((entry, index) => ({
                id: interfaceId(path, index),
                name: interfaceLabel(entry.interface),
                kind: 'interface',
                checked: true,
                collapsed: false,
                deep,
                // A port is listed under the interface it belongs to and nowhere
                // else: one triad, one box.
                children: entry.ports.map((port) => ({
                    id: portId(path, port),
                    name: portLabel(ports[port]),
                    kind: 'port',
                    checked: true,
                    collapsed: false,
                    children: [],
                    deep,
                    port: reportedAs(owner, ports[port]),
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
        deep,
    };
}

/**
 * The name PartCAD reports one port under: the path of links, then the port.
 *
 * 'shape_ports.qualify' on the other side, and it has to be the same string -
 * it is what '--port' and the 'ports' of a render request name. The owner path
 * is the labels of the nodes above this one, which are the link names, and the
 * object itself contributes none (its own ports are reported under their own
 * names).
 */
function reportedAs(owner: readonly string[], port: ShowPort | undefined): string {
    return [...owner, port?.name ?? ''].join(':');
}

/** How one pane's tree differs from the 3D view's. */
export interface TreeOptions {
    /**
     * List a row per port and per interface instance a node declares. Default:
     * true. False on the Draft tab, whose drawing is of the solid.
     */
    ports?: boolean;
    /**
     * Start those rows ticked where the 3D view would tick them -- the object's
     * own, and nothing deeper. Default: true. False where the boxes drive a
     * render: what such a tab shows when it is opened is the object itself.
     */
    portsDrawn?: boolean;
    /**
     * The root row is the object, and its box is fixed ticked. Default: false.
     * True on the two tabs that render it: there is no picture without it, so
     * offering to clear the box would offer nothing.
     */
    lockRoot?: boolean;
    /**
     * Where what is ticked is kept, when it is shared with the other tabs.
     * Without one the tree keeps its own, which is what a test does.
     */
    selection?: Selection;
}

/** What the ticked port and interface rows ask for; see 'Tree.overlay()'. */
export interface OverlayRequest {
    ports: boolean;
    interfaces: boolean;
    internals: boolean;
    /** The ports to draw, by the name PartCAD reports each under. */
    select: string[];
}

/** A filter as 'pc render --filter' takes one: link name to the mask inside it. */
export type LinkFilter = Record<string, unknown>;

/**
 * What is ticked, for the whole Design group rather than for one tab of it.
 *
 * The three tabs are three widgets over one object, and what somebody wants to
 * look at is a property of the object: switching from 3D to 2D must not change
 * the selection, and a box cleared on one tab is cleared on the others. So the
 * answer lives here and the widgets read and write it.
 *
 * It also has to outlive a widget that has no row for it. The Draft tab lists no
 * ports, so a port switched off on the 2D tab would be forgotten the moment
 * Draft rebuilt the state out of its own rows -- which is the reason this is a
 * store the trees consult rather than something each of them owns.
 *
 * Keyed the way 'Tree' identifies a row across two shows of one object (see
 * 'key'): a row nobody has touched is absent, and each tab then falls back to
 * its own default for it.
 */
export class Selection {
    private readonly ticked = new Map<string, boolean>();
    private readonly listeners: (() => void)[] = [];

    /** Whether this row was ticked, or undefined if nobody has said. */
    public get(rowKey: string): boolean | undefined {
        return this.ticked.get(rowKey);
    }

    /** Record a row, and tell every other widget showing it. */
    public set(rowKey: string, checked: boolean): void {
        this.ticked.set(rowKey, checked);
        this.listeners.forEach((listener) => listener());
    }

    /** A different object: nothing said about the old one applies. */
    public clear(): void {
        this.ticked.clear();
    }

    /**
     * Be told when something else changes it.
     *
     * The listener re-reads the store; it must not write to it, or two widgets
     * would answer each other forever.
     */
    public onChange(listener: () => void): void {
        this.listeners.push(listener);
    }
}

export class Tree {
    private root: Row | undefined;

    /**
     * @param host the element the rows are drawn into
     * @param onChange called after every change the user makes to a box
     * @param onHover called with the items to single out while the pointer is over
     *   a part or a sub-assembly, and with undefined when it leaves
     * @param options how this pane differs from the 3D view's; see 'TreeOptions'
     */
    constructor(
        private readonly host: HTMLElement,
        private readonly onChange: () => void,
        private readonly onHover: (items: Set<ItemId> | undefined) => void = () => undefined,
        private readonly options: TreeOptions = {},
    ) {
        // Another tab changed something: show it. Reading only, so this cannot
        // loop back into the store.
        options.selection?.onChange(() => this.adopt());
    }

    /** Take what the store says, without announcing anything of our own. */
    private adopt(): void {
        const selection = this.options.selection;
        if (this.root === undefined || selection === undefined) {
            return;
        }
        const walk = (row: Row) => {
            const checked = selection.get(key(row.item));
            if (checked !== undefined && checked !== row.checked && !row.box.disabled) {
                row.checked = checked;
                row.box.checked = checked;
            }
            row.children.forEach(walk);
        };
        walk(this.root);
        this.refresh();
    }

    /**
     * Draw a tree, taking whatever the shared selection already says.
     *
     * Nothing else is remembered here. What the user ticked is the store's (see
     * 'Selection'), which is what lets the same object shown again - an edit
     * saved, a re-render - keep the selection the way it keeps the camera, and
     * what lets the other two Design tabs show the same answer.
     */
    public setObject(object: ShowNode): void {
        empty(this.host);
        this.root = this.build(itemsOf(object, [], this.options), true);
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

    /**
     * The links to keep, as 'pc render --filter' takes them, or undefined when
     * every one of them is kept.
     *
     * Undefined rather than a mask of the whole object, for two reasons: there
     * is nothing to filter, and PartCAD would walk the tree to arrive at the
     * tree it already had. It is also what a part answers -- a part has no
     * links -- so a caller need not ask what it is looking at.
     *
     * An empty mask is *not* "keep everything": it is "keep nothing", which the
     * filter language has no spelling for (a link named with nothing under it
     * keeps everything inside it, and so does an empty mask). A caller that gets
     * one has had every part unticked and has nothing to render; see
     * 'filterIsEmpty'.
     */
    public filter(): LinkFilter | undefined {
        if (this.root === undefined) {
            return undefined;
        }
        const { mask, whole } = this.links(this.root.children);
        return whole ? undefined : mask;
    }

    /**
     * The links of one level that are kept, and whether that is all of them.
     *
     * A row's name *is* the name the filter uses: a node's label is what the
     * assembly holding it addresses it by, down to a child nothing named, which
     * is addressed by its position (see 'ShowNode.label'). So there is no row
     * here that cannot be named and no second rule for one.
     *
     * Only node rows take part. A port is not a link, and whether one is drawn
     * is the overlay's business, not the filter's.
     */
    private links(rows: Row[]): { mask: LinkFilter; whole: boolean } {
        const mask: LinkFilter = {};
        let whole = true;
        for (const row of rows) {
            if (row.item.kind !== 'node') {
                continue;
            }
            if (!row.checked) {
                whole = false;
                continue;
            }
            const inner = this.links(row.children);
            whole = whole && inner.whole;
            // An empty mask is how the filter language says "and everything
            // inside it", which is exactly what a subtree with every box ticked
            // means -- and it is shorter than naming all of them.
            mask[row.item.name] = inner.whole ? {} : inner.mask;
        }
        return { mask, whole };
    }

    /**
     * Which of the port overlays the ticked boxes ask for.
     *
     * The overlay PartCAD draws is three flags rather than a set of ports (see
     * 'partcad.render_overlay'), so this is what the rows resolve to: a ticked
     * port row asks for the coordinate frames, a ticked interface row for the
     * boundaries, and either of them below the object's own level asks for the
     * ports of what is *inside* an assembly -- which an assembly does not offer
     * by default, since it is taken at its word about which ports are its own.
     *
     * 'select' is the ports themselves, by the name PartCAD reports each under,
     * so the picture draws the ones the panel says and no others -- which is
     * what makes unticking one of a part's twelve ports mean something. Each of
     * the three flags still has to be sent: a selection says *which* ports, not
     * that any are drawn (see 'Overlay.of').
     *
     * Effective visibility, not the box: a port under an unticked assembly is
     * not drawn, and must not turn the overlay on for the rest of the picture.
     */
    public overlay(): OverlayRequest {
        const asked: OverlayRequest = { ports: false, interfaces: false, internals: false, select: [] };
        const walk = (row: Row) => {
            if (!row.checked) {
                return;
            }
            if (row.item.kind === 'port') {
                asked.ports = true;
                if (row.item.port !== undefined) {
                    asked.select.push(row.item.port);
                }
            } else if (row.item.kind === 'interface') {
                asked.interfaces = true;
            }
            if ((row.item.kind === 'port' || row.item.kind === 'interface') && row.item.deep === true) {
                asked.internals = true;
            }
            row.children.forEach(walk);
        };
        if (this.root !== undefined) {
            walk(this.root);
        }
        return asked;
    }

    private build(item: Item, root = false): Row {
        const box = el('input');
        box.type = 'checkbox';
        // The object itself, on a pane whose boxes drive a render: there is no
        // picture without it, so the box is ticked and fixed rather than offered.
        const locked = root && this.options.lockRoot === true;
        // What the user said, on whichever tab they said it, and otherwise this
        // pane's own default for the row.
        const said = this.options.selection?.get(key(item));
        const row: Row = {
            item,
            checked: locked ? true : (said ?? item.checked),
            box,
            children: item.children.map((child) => this.build(child)),
        };
        box.checked = row.checked;
        if (locked) {
            box.disabled = true;
            box.title = 'The object itself is always drawn';
        }
        box.addEventListener('change', () => {
            row.checked = box.checked;
            // Written before anything is drawn: the other tabs are told by the
            // store, and this pane's own marks are refreshed below.
            this.options.selection?.set(key(item), box.checked);
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
        let displayName = row.item.name;
        // Add triangle count if performance debugging is enabled
        if (typeof window !== 'undefined') {
            const triangleCounts = (window as any).pcNodeTriangleCounts as Map<string, number> | undefined;
            if (triangleCounts) {
                const count = triangleCounts.get(row.item.id);
                if (count !== undefined && count > 0) {
                    displayName = `${row.item.name} (${count.toLocaleString()} triangles)`;
                }
            }
        }
        const name = el('span', 'tree-name', displayName);
        // The names are long (a port is 'inner-TL-3mm-thru-opening-m3') and the
        // pane is narrow, so a row is cut off with an ellipsis; this is where the
        // whole of it can still be read.
        name.title = displayName;
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
 * Whether a filter keeps nothing at all, which is not something it can say.
 *
 * 'Tree.filter()' answers undefined for "everything" and a mask for "these"; the
 * one case left is a mask with nothing in it, which happens when every part has
 * been unticked. There is no picture of that, so the caller says so rather than
 * sending a mask PartCAD would read as "everything".
 */
export function filterIsEmpty(filter: LinkFilter | undefined): boolean {
    return filter !== undefined && Object.keys(filter).length === 0;
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
