//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What colour a shape is drawn in, in every 3D pane of the Digital Thread.
//
// A shape may say. Its 'properties' carry a 'color' - "#RRGGBB", or "#RRGGBBAA"
// for one that is see-through - stated by whatever built it: a URDF link's
// material, a colour read out of the file a part was imported from, or the
// package itself (see 'docs/source/config_parts.rst'). A node that states none
// takes the colour of the nearest node above it that does, so that a part placed
// in an assembly that states a colour is drawn in it until it says otherwise.
//
// A shape that nothing above it colours is the common case, and it is drawn in
// goldenrod: the colour OCCT draws a shape nobody coloured in
// ('Quantity_NOC_GOLDENROD'), which is what anybody who has looked at a solid in
// an OpenCASCADE viewer has seen an uncoloured one as. The 2D projections
// '//builtin/render' writes draw it in the same colour, and that is not something
// kept by hand: 'DEFAULT_COLOR' below is the twin of the one in
// 'src/partcad/wrappers/appearance.py' - a webview cannot import Python - and a
// test on the Python side reads this file and fails when the two differ.
//
// Only three's core is imported here, never an addon, so the extension host's
// tests can import this module the way they import 'nodes.ts' (see
// 'viewerAppearance.test.ts').
//

import * as THREE from 'three';

import type { ShowNode } from './messages';

/** A colour as the 3D panes draw a shape in it. */
export interface Appearance {
    /**
     * The colour, as 0xRRGGBB in sRGB - what a hex colour means to CSS, to a
     * colour picker and to three alike. three converts it into its linear working
     * space itself, wherever it is given one.
     */
    readonly color: number;
    /** How opaque, from 1 for solid down to 0: the "AA" of "#RRGGBBAA", over 255. */
    readonly opacity: number;
}

/**
 * The colour of a shape that states none: goldenrod, #DAA520.
 *
 * The twin of 'DEFAULT_COLOR' in 'src/partcad/wrappers/appearance.py', and spelled
 * exactly like this because a Python test finds it by that spelling. Change both.
 */
export const DEFAULT_COLOR = 0xdaa520;

/** What a shape that states nothing, under nothing that does, is drawn as. */
export const DEFAULT_APPEARANCE: Appearance = { color: DEFAULT_COLOR, opacity: 1 };

/**
 * The colour of a line drawn across a shape of the default colour: darkgoldenrod.
 *
 * A line that bounds no face - the bend lines across the blank of a sheet metal
 * part - lies on the shape it belongs to, and drawn in the shape's own colour it
 * would disappear into it. The deeper shade of the same colour reads against the
 * faces and still reads as belonging to them. See 'edgeColor' for every other
 * colour.
 */
export const DEFAULT_EDGE_COLOR = 0xb8860b;

/** "#RRGGBB" or "#RRGGBBAA", the '#' optional, in either case. */
const COLOR_PATTERN = /^#?([0-9a-f]{6})([0-9a-f]{2})?$/i;

/**
 * A colour as PartCAD states one, or undefined if this is not one.
 *
 * Strict about the form, because a colour that is not one is not a guess away
 * from one: "red" is what a part's free-form 'color' *parameter* may say, and the
 * property it is not is "#RRGGBB". A shape stating something else is drawn as if
 * it stated nothing, in whatever colour it would otherwise be drawn in.
 */
export function parseColor(text: unknown): Appearance | undefined {
    if (typeof text !== 'string') {
        return undefined;
    }
    const match = COLOR_PATTERN.exec(text.trim());
    if (match === null) {
        return undefined;
    }
    return {
        color: parseInt(match[1], 16),
        opacity: match[2] === undefined ? 1 : parseInt(match[2], 16) / 255,
    };
}

/** What this node itself says it looks like, or undefined if it says nothing usable. */
export function statedAppearance(node: ShowNode): Appearance | undefined {
    return parseColor(node.properties?.color);
}

/**
 * What a node is drawn as: what it states, else what the node holding it is drawn
 * as - which, at the root, is the default.
 *
 * The tree is walked from the root down, each node handing its own answer to its
 * children as 'inherited', so a colour stated by an assembly reaches every part in
 * it that does not state one of its own, however deep.
 */
export function appearanceOf(node: ShowNode, inherited: Appearance = DEFAULT_APPEARANCE): Appearance {
    return statedAppearance(node) ?? inherited;
}

/**
 * One string per distinct appearance, for a pane to keep one material per colour.
 *
 * "daa520ff" for the default. A part stating "#DAA520" is therefore the same key as
 * a part stating nothing, and is drawn with the same material - the two look the
 * same, so they should cost the same.
 */
export function appearanceKey(appearance: Appearance): string {
    const alpha = Math.round(Math.min(1, Math.max(0, appearance.opacity)) * 255);
    return appearance.color.toString(16).padStart(6, '0') + alpha.toString(16).padStart(2, '0');
}

/**
 * The colour a line across a shape of this colour is drawn in.
 *
 * The default colour has a name for its deeper shade, and gets it. Any other is
 * darkened by a quarter of its lightness - which is about what darkgoldenrod is to
 * goldenrod - unless it is already dark, where a darker line would be no line at
 * all, and it is lightened instead. Worked in sRGB, the space a person compares
 * two colours in, rather than in three's linear one.
 */
export function edgeColor(color: number): number {
    if (color === DEFAULT_COLOR) {
        return DEFAULT_EDGE_COLOR;
    }
    const hsl = { h: 0, s: 0, l: 0 };
    new THREE.Color().setHex(color, THREE.SRGBColorSpace).getHSL(hsl, THREE.SRGBColorSpace);
    const lightness = hsl.l > 0.3 ? hsl.l * 0.75 : hsl.l + 0.3;
    return new THREE.Color().setHSL(hsl.h, hsl.s, lightness, THREE.SRGBColorSpace).getHex(THREE.SRGBColorSpace);
}
