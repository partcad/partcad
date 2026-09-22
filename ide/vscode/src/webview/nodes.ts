//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The vocabulary the 3D view's two halves share about one object's tree.
//
// The renderer ('scene.ts') walks the tree to build what is on the stage; the
// control pane ('tree.ts') walks it to build the rows that switch those things
// on and off. They have to agree on what the things *are* - which is what this
// file is: a name for every drawable in the tree, derived from where it sits, so
// that two independent walks of one tree name the same things the same way and
// neither has to hand the other a data structure.
//
// A path rather than a counter, because it is derived rather than handed out: a
// walk that arrives at the same node by the same route gets the same name without
// having to have been the one that made it up.
//

import { ShowInterface, ShowNode, ShowPort } from './messages';

/** What one row of the pane and its drawables are called. */
export type ItemId = string;

/** The id of the node reached by this path from the root. */
export function nodeId(path: readonly number[]): ItemId {
    return `n${path.join('.')}`;
}

/** The id of one of a node's ports. */
export function portId(path: readonly number[], port: number): ItemId {
    return `${nodeId(path)}:p${port}`;
}

/** The id of a node's 'ports' group row, which draws nothing of its own. */
export function portsGroupId(path: readonly number[]): ItemId {
    return `${nodeId(path)}:ports`;
}

/** The id of a node's 'interfaces' group row, or of one instance under it. */
export function interfacesGroupId(path: readonly number[]): ItemId {
    return `${nodeId(path)}:interfaces`;
}

export function interfaceId(path: readonly number[], index: number): ItemId {
    return `${nodeId(path)}:i${index}`;
}

/** What a node is called in the pane: what it is called where it sits. */
export function nodeLabel(node: ShowNode): string {
    return node.label || node.name || '';
}

/**
 * How a node's ports are divided between its rows.
 *
 * A port is drawn once - it is one coordinate frame - so exactly one row may own
 * it, and which row that is follows from the port itself: one that belongs to an
 * interface instance is listed under that instance, and one that belongs to none
 * is listed under 'ports'. Two rows over one triad, disagreeing about whether it
 * is drawn, is what this rules out.
 *
 * The interfaces are taken in the order PartCAD listed them, and a port an
 * interface names but the node does not carry is skipped rather than invented.
 */
export interface PortGrouping {
    /** Ports belonging to no interface, as indices into 'node.ports'. */
    loose: number[];
    /** One entry per interface instance, in order, with the ports it is made of. */
    interfaces: { interface: ShowInterface; ports: number[] }[];
}

export function groupPorts(node: ShowNode): PortGrouping {
    const ports = node.ports ?? [];
    const byName = new Map<string, number>();
    ports.forEach((port, index) => {
        if (port.name && !byName.has(port.name)) {
            byName.set(port.name, index);
        }
    });

    const claimed = new Set<number>();
    const interfaces = (node.interfaces ?? []).map((entry) => {
        const members: number[] = [];
        for (const name of entry.ports ?? []) {
            const index = byName.get(name);
            if (index !== undefined && !claimed.has(index)) {
                claimed.add(index);
                members.push(index);
            }
        }
        return { interface: entry, ports: members };
    });

    const loose = ports.map((_port, index) => index).filter((index) => !claimed.has(index));
    return { loose, interfaces };
}

/** What an interface instance is called in the pane. */
export function interfaceLabel(entry: ShowInterface): string {
    // The short name, which is what a user writes in a 'connect:' for an
    // interface of the package being worked in - the same choice 'pc render
    // --with-interfaces' makes for what it draws beside a port.
    const name = (entry.name ?? '').split(':').pop() || (entry.name ?? '');
    return entry.instance ? `${name} (${entry.instance})` : name;
}

/** What a port is called in the pane. */
export function portLabel(port: ShowPort): string {
    return port.name || '';
}

/**
 * The colour a port is drawn in: the blue of the Z axis of its own triad.
 *
 * 'AxesHelper' colours that axis (0, 0, 1) in the working space, and '0x0000ff' is
 * what that value converts from - so a boundary drawn in it reads as part of the
 * same annotation rather than as a second thing that happens to be blue. The
 * material has to be unlit and untone-mapped for the two to actually match, which
 * is where 'scene.ts' uses this; 'viewerPorts.test.ts' holds the value to the axis.
 */
export const PORT_COLOR = 0x0000ff;

/**
 * How opaque a port's boundary is drawn.
 *
 * Half: the boundary is the shape of an opening and is drawn across it, so a solid
 * one hides the hole it is there to point at - and the part behind it, which is
 * what tells you the port is on the far face rather than the near one.
 */
export const PORT_OPACITY = 0.5;

/** How many times a second an item flickers while the pointer is over its row. */
export const FLICKER_HZ = 7;

/**
 * Whether something flickering is showing at this moment.
 *
 * Driven by the clock rather than by a frame count, so the rate is the rate
 * whatever the renderer manages: seven flickers a second means seven on and seven
 * off, so the state turns over every half period.
 */
export function flickerOn(elapsedMs: number): boolean {
    return Math.floor((elapsedMs * FLICKER_HZ * 2) / 1000) % 2 === 0;
}

/** Every node of the tree, with the path that names it, parents before children. */
export function walk(root: ShowNode, visit: (node: ShowNode, path: number[]) => void): void {
    const descend = (node: ShowNode, path: number[]) => {
        visit(node, path);
        (node.assembly ?? []).forEach((child, index) => descend(child, [...path, index]));
    };
    descend(root, []);
}

/** How many bytes of glTF the whole tree carries, for the loading readout. */
export function totalSize(root: ShowNode): number {
    let total = 0;
    walk(root, (node) => {
        total += node.size ?? 0;
    });
    return total;
}
