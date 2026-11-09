//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the 3D view shows of an object when an item or one of its CMF sets is
// chosen in the CMF tab (docs/design/cmf.md, section 9).
//
// The CMF tab lists what an object is made of, item by item, each with its sets
// - a colour, a material and a finish, and the faces and solids in them. Its
// "Show in 3D" on an item, or on one of an item's sets, opens the 3D view on the
// same object with that singled out: what was chosen is drawn as it always is,
// and everything else faint and plain - see-through, in its colour, with no
// finish - so that the faces of one set read as those faces, in place, and the
// rest says where they are. A chip over the view says what is shown and takes it
// away again.
//
// Faint rather than flickered, as a row of the tree is when pointed at: a set is
// chosen to be looked at, turned and compared, which a flicker that comes and
// goes with the pointer does not let anybody do - and the faces of a set are
// often a few among many, which blinking leaves as hard to find as before.
//
// How a set's faces are found: PartCAD writes the faces of a payload whose CMF
// section addresses faces or solids one by one as a mesh per set, each saying
// in its 'extras' which sets it is in ('wrapper_gltf._face_sets'), as the
// colour, material, finish and origin the CMF tab's summary says of each. A
// mesh that says nothing is a part in one set - every face of it is in
// whichever set of its item is chosen. An item is found by name: the nodes the
// item is (a part placed three times is three nodes), and everything under one
// that is an item itself (an assembly bought whole).
//
// Only 'messages.ts' types are imported, so the extension host's tests can
// import this file (see 'viewerChoice.test.ts').
//

import type { CmfSet } from './messages';

/** The key of a mesh's 'userData' (its glTF 'extras') that says which CMF sets its faces are in. */
export const SETS_EXTRAS = 'partcadSets';

/** What a CMF set is known by where it is chosen: its references, and where it came from. */
export interface SetIdentity {
    readonly color?: string;
    readonly material?: string;
    readonly finish?: string;
    readonly origin?: string;
}

const IDENTITY_KEYS = ['color', 'material', 'finish', 'origin'] as const;

/** What the 3D view singles out: an item of the CMF tab, or one of its sets. */
export interface CmfChoice {
    /** '//package:name', as the CMF tab names the item and the tree names its nodes. */
    readonly item: string;
    /** One of its sets, or every face of it. */
    readonly set?: SetIdentity;
    /** What the chip over the view says is shown. */
    readonly label: string;
}

/** A set of the CMF tab as it is chosen. */
export function identityOf(set: CmfSet | SetIdentity): SetIdentity {
    const identity: Record<string, string> = {};
    for (const key of IDENTITY_KEYS) {
        const value = (set as Record<string, unknown>)[key];
        if (typeof value === 'string' && value !== '') {
            identity[key] = value;
        }
    }
    return identity;
}

/** Whether two sets are the same one: the same references and the same origin, nothing more and nothing less. */
export function sameSet(a: SetIdentity, b: SetIdentity): boolean {
    return IDENTITY_KEYS.every((key) => (a[key] ?? undefined) === (b[key] ?? undefined));
}

/**
 * The sets a mesh says its faces are in, or undefined where it says nothing.
 * Anything that is not a list of sets says nothing.
 */
export function setsOf(userData: Record<string, unknown> | undefined): SetIdentity[] | undefined {
    const value = userData?.[SETS_EXTRAS];
    if (!Array.isArray(value)) {
        return undefined;
    }
    return value.filter((entry) => typeof entry === 'object' && entry !== null).map((entry) => identityOf(entry));
}

/**
 * Whether a mesh is part of what 'choice' shows.
 *
 * 'names' are the name of the node the mesh is the geometry of and the names of
 * every node above it, so that an item that is an assembly takes everything in
 * it. 'sets' is what the mesh says of its faces ('setsOf'): a mesh that says
 * nothing is in every set of its item.
 */
export function chosen(choice: CmfChoice, names: readonly string[], sets: readonly SetIdentity[] | undefined): boolean {
    if (!names.includes(choice.item)) {
        return false;
    }
    if (choice.set === undefined || sets === undefined) {
        return true;
    }
    const wanted = choice.set;
    return sets.some((set) => sameSet(set, wanted));
}

/** What a set is called on the chip: its colour, material and finish by name, or what it leaves unsaid. */
export function setLabel(set: SetIdentity, name: (reference: string) => string): string {
    const said = (['color', 'material', 'finish'] as const)
        .map((key) => set[key])
        .filter((value): value is string => value !== undefined)
        .map(name);
    return said.length > 0 ? said.join(' · ') : 'the faces nothing is said of';
}
