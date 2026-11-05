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
// A shape can also say it face by face. A part whose CMF colours its faces one
// by one - a two-colour moulding, a STEP file with a painted face - arrives as
// a glTF of a mesh per colour, each primitive with a material of its own
// (PartCAD's 'wrapper_gltf._colored'; see docs/design/cmf.md, section 9). Such
// a primitive is drawn in its own colour, whatever the node and the nodes above
// it say: what the part states of a face is more specific than anything stated
// of the part or of an assembly it is placed in, which is the one precedence
// rule of CMF. Only the colour is taken from the file - the material it is drawn
// with is still this viewer's, so it is lit, faded by the Opacity slider and
// flickered exactly as everything else is - and a primitive that brings no
// material keeps the node's colour, which is every primitive of every part that
// does not colour its faces.
//
// A shape may also say it is one-sided: 'properties: oneSided: true', which is
// what a wall reports (see 'src/partcad/part_factory_wall.py'). It is then drawn
// from the front of its faces only - the side their normals point to - and from
// behind it is not there at all, which is how a room seen from outside is seen
// into through its near walls. Inherited the way a colour is, and independently
// of it: a wall that states no colour is still one-sided, and a scene that
// colours its walls does not make them two-sided.
//
// A colour may be drawn with an image - a texture its declaration names (see
// 'docs/source/config_cmf.rst') - and a primitive whose faces are in one arrives
// with that image as its material's base colour texture, laid on by PartCAD
// ('wrapper_gltf._with_textures'; the same box mapping a shaded 'pc render'
// draws with). Such a primitive brings its image as well as its colour: the
// viewer's own material draws it with the image ('map'), white under it, and
// 'color' is then what it is drawn as wherever an image cannot be - the colour
// its declaration says, or the image's mean, which the file carries in the
// material's 'extras' as 'partcadColor'. A wallpapered wall is one-sided and
// drawn with an image, and is both.
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
    /**
     * Drawn from the front of its faces only, and see-through from behind: what a
     * shape stating 'oneSided: true' is drawn as. Absent for every other shape,
     * which is drawn from both sides as it always was.
     */
    readonly oneSided?: true;
    /**
     * The image the faces are drawn with, where their colour is drawn with one;
     * 'color' is then what they are drawn as where an image cannot be.
     */
    readonly map?: THREE.Texture;
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

/** What colour this node itself says it is, or undefined if it says nothing usable. */
export function statedAppearance(node: ShowNode): Appearance | undefined {
    return parseColor(node.properties?.color);
}

/**
 * Whether this node itself says it is one-sided, or undefined if it says nothing.
 *
 * A boolean or nothing: anything else a node's 'oneSided' holds is not a statement
 * about how it is drawn, and it is drawn as if it had stated nothing.
 */
export function statedOneSided(node: ShowNode): boolean | undefined {
    const value = node.properties?.oneSided;
    return typeof value === 'boolean' ? value : undefined;
}

/**
 * What a node is drawn as: what it states, else what the node holding it is drawn
 * as - which, at the root, is the default.
 *
 * The tree is walked from the root down, each node handing its own answer to its
 * children as 'inherited', so a colour stated by an assembly reaches every part in
 * it that does not state one of its own, however deep. Whether it is one-sided is
 * inherited the same way and on its own: the colour of one node and the sides of
 * another make the appearance of a node under both.
 */
export function appearanceOf(node: ShowNode, inherited: Appearance = DEFAULT_APPEARANCE): Appearance {
    const stated = statedAppearance(node);
    const oneSided = statedOneSided(node) ?? inherited.oneSided === true;
    const color = stated ?? inherited;
    if (oneSided === (color.oneSided === true)) {
        return color;
    }
    return oneSided
        ? { color: color.color, opacity: color.opacity, oneSided: true }
        : { color: color.color, opacity: color.opacity };
}

/**
 * Where a primitive's own colour is kept once its file's material is gone: the
 * key of its 'userData' (see 'ownAppearance').
 */
export const OWN_APPEARANCE = 'partcadOwnAppearance';

/**
 * The colour a glTF primitive brings with it, or undefined when it brings none.
 *
 * 'fromFile' is whether 'material' is one the file declares - three gives a
 * primitive with no material a default one of its own, white, which is not a
 * colour anybody stated and must not be drawn as one. Read as sRGB, which is
 * what an 'Appearance' is: three keeps a glTF's linear factors in its linear
 * working space and gives them back converted, so a face stated '#C91A09' comes
 * out '#C91A09' again. Its opacity counts only when the file says it is blended;
 * an opaque material's alpha means nothing.
 */
export function ownAppearance(
    material: THREE.Material | THREE.Material[] | null | undefined,
    fromFile: boolean,
): Appearance | undefined {
    if (!fromFile || !material || Array.isArray(material)) {
        return undefined;
    }
    const color = (material as THREE.Material & { color?: THREE.Color }).color;
    if (color?.isColor !== true) {
        return undefined;
    }
    const opacity = material.transparent ? material.opacity : 1;
    const map = (material as THREE.Material & { map?: THREE.Texture | null }).map;
    if (map?.isTexture === true) {
        // Drawn with an image: white under it in the file, and drawn as the
        // colour the file says wherever an image cannot be.
        const flat = parseColor(material.userData?.partcadColor);
        return { color: flat?.color ?? color.getHex(THREE.SRGBColorSpace), opacity, map };
    }
    return { color: color.getHex(THREE.SRGBColorSpace), opacity };
}

/**
 * What a primitive is drawn as: its own colour where it brought one, else the colour of the node holding it.
 *
 * Its own colour - and the image it is drawn with, where it brought one - is only
 * how it looks: whether it is one-sided is still its node's, so a wall whose CMF
 * colours one face differently is a wall all the same.
 */
export function primitiveAppearance(own: Appearance | undefined, node: Appearance): Appearance {
    if (own === undefined) {
        return node;
    }
    // Spread rather than rebuilt: the image it is drawn with, if any, is its own too.
    return node.oneSided ? { ...own, oneSided: true } : own;
}

/**
 * One string per distinct appearance, for a pane to keep one material per colour.
 *
 * "daa520ff" for the default. A part stating "#DAA520" is therefore the same key as
 * a part stating nothing, and is drawn with the same material - the two look the
 * same, so they should cost the same. A one-sided shape is drawn with a material of
 * its own, which culls the backs of faces, so its key says so: "daa520ff/front".
 */
export function appearanceKey(appearance: Appearance): string {
    const alpha = Math.round(Math.min(1, Math.max(0, appearance.opacity)) * 255);
    const key = appearance.color.toString(16).padStart(6, '0') + alpha.toString(16).padStart(2, '0');
    // One material per image too: two images drawn as one colour are two looks.
    const looked = appearance.map === undefined ? key : `${key}:${appearance.map.uuid}`;
    return appearance.oneSided ? looked + '/front' : looked;
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
