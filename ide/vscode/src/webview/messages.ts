//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The 'postMessage' contract between the PartCAD Viewer panel (the extension
// host, 'src/viewer/PartcadViewer.ts') and the renderer that runs inside it.
//
// Geometry is only half of what the panel shows. The other tabs - the bill of
// materials, the assembly instructions, where to buy the parts - are answered by
// the PartCAD daemon, which only the extension host can reach: the webview's CSP
// forbids every network request, and the daemon is behind a JSON-RPC connection
// anyway. So the renderer asks ('fetchTab') and the host answers ('tabData').
//

/** The tabs the panel can show. '3d' is always the first one. */
export type TabId = '3d' | 'bom' | 'instructions' | 'supply' | 'fea' | 'cfd';

/** The two tabs that run an analysis rather than ask a question about the object. */
export const ANALYSIS_TABS: TabId[] = ['fea', 'cfd'];

export function isAnalysisTab(tab: TabId): boolean {
    return ANALYSIS_TABS.includes(tab);
}

/** A packed rigid placement: [[tx, ty, tz], [ax, ay, az], angleInDegrees]. */
export type Placement = [[number, number, number], [number, number, number], number];

/** One port a node declares: a coordinate frame, and what it is part of. */
export interface ShowPort {
    name?: string | null;
    /** Where it is, in the frame of the object that declares it. */
    location: Placement;
    /** The interface instance it belongs to, or absent when it belongs to none. */
    interface?: string | null;
    instance?: string | null;
    /** The sketch it is drawn with, as '<package>:<name>', where it has one. */
    sketch?: string | null;
}

/** One interface instance a node implements, and the ports it is made of. */
export interface ShowInterface {
    name?: string | null;
    instance?: string | null;
    ports?: string[];
}

/**
 * One node of the object being shown, as the host hands it over.
 *
 * Every subject is a tree of these and nothing else - a part or a sketch is one
 * node deep, an assembly is a node per thing it holds, an interface is a node per
 * port - so nothing in this renderer asks which kind it is looking at. PartCAD
 * builds the tree (it is the hierarchy it instantiates an assembly as, with glTF
 * at the nodes instead of BREP); 'src/viewer/protocol.ts' carries it, and
 * 'src/partcad_ide_client/protocol.py' is the normative description.
 *
 * Placements are not baked in: 'gltf' is this node's own geometry in its own
 * coordinate system and 'location' is where the node sits inside its parent, so
 * the locations are composed down the tree as it is drawn. A port's location is
 * in the same frame and moves with the node holding it.
 */
export interface ShowNode {
    name?: string | null;
    label?: string | null;
    location?: Placement | null;
    /**
     * Which entry of the root's 'geometry' table is this node's geometry.
     *
     * A reference rather than a copy, because one shape can be in the tree many
     * times over: an assembly places the same bolt a hundred times and a hundred
     * nodes then name one entry. What differs between them is 'location', which
     * was never part of the geometry.
     */
    gltfRef?: string;
    /**
     * This node's geometry outright, as base64 binary glTF.
     *
     * What 'gltfRef' resolves to, and what a node carries when nothing built a
     * table - a hand-written message, a test. A node has one or the other.
     */
    gltf?: string;
    /** How many bytes that is, for the loading readout. */
    size?: number;
    ports?: ShowPort[];
    interfaces?: ShowInterface[];
    /** What is inside this node, or absent for a leaf. */
    assembly?: ShowNode[];
    /**
     * On the root node: the sketches the ports anywhere in the tree are drawn
     * with, keyed by the reference those ports name in their own 'sketch'.
     *
     * A port is a coordinate frame, drawn as a triad, and most ports are also
     * drawn *with* something - the circle of a hole, the profile of a rail. One
     * entry per sketch however many ports point at it, so each is parsed once and
     * drawn as an instance of itself per port.
     */
    sketches?: Record<string, ShowNode>;
    /**
     * On the root node: every distinct piece of geometry in the tree, decompressed
     * by the host, keyed by a digest of the exact shape it was tessellated from.
     *
     * One entry however many nodes name it, so it is parsed and uploaded to the GPU
     * once and drawn as an instance of itself per node - the same arrangement the
     * port sketches above have always had, applied to the model itself. The
     * digests are opaque: nothing here computes or checks one, it only looks them
     * up.
     */
    geometry?: Record<string, ShowGeometry>;
    /**
     * What was learnt about this node's shape as it was built, where anything was.
     *
     * PartCAD's own metadata, passed through untouched (see 'KEY_METADATA' in
     * 'partcad/shape_envelope.py'). The viewer reads one section of it - the
     * per-element 'annotations', which it pins to the elements as callouts (see
     * 'callouts.ts') - and nothing else.
     */
    metadata?: ShowMetadata;
}

/** The part of a node's metadata the viewer reads. */
export interface ShowMetadata {
    /** What the source said about the shape's individual elements, one record each. */
    annotations?: ShowAnnotation[];
    [section: string]: unknown;
}

/**
 * One element's record.
 *
 * The producing wrapper's own vocabulary; 'points' and 'metadata' are the two
 * fields the viewer relies on, and 'layer' the one it uses as a heading.
 */
export interface ShowAnnotation {
    /** Where the element is, in the node's own frame, in millimetres. */
    points?: number[][];
    /** What was said about it, as key/value pairs. */
    metadata?: Record<string, unknown> | null;
    layer?: string | null;
    [field: string]: unknown;
}

/** One entry of that table: the geometry, and how many bytes it is. */
export interface ShowGeometry {
    gltf: string;
    size: number;
}

export interface ShowMessage {
    type: 'show';
    name: string | null;
    kind: string | null;
    /**
     * The package the object belongs to, or null when the 'partcad' that sent it
     * did not say. Every tab but the 3D one asks the daemon about
     * '<package>:<name>', so without it those tabs are not offered at all.
     */
    package: string | null;
    keepCamera: boolean;
    /** The object itself, as the root node of its tree, or null when it is empty. */
    object: ShowNode | null;
}

export interface ClearMessage {
    type: 'clear';
}

/**
 * The answer to one 'fetchTab'.
 *
 * 'token' is the 'fetchTab' this answers, echoed back untouched. A daemon round
 * trip outlives a change of selection easily - a bill of materials walks the
 * whole assembly tree, a supply quote goes out to the network - so an answer
 * that arrives after the panel moved on has to be dropped rather than painted
 * over what is now on screen. An analysis outlives one by a great deal more (a
 * solver runs for as long as it runs) and can be asked twice over for one
 * object, which is why the token counts requests and not objects.
 */
export interface TabDataMessage {
    type: 'tabData';
    tab: TabId;
    token: number;
    data?: unknown;
    error?: string;
    /**
     * Which implementation the host actually asked for, on an analysis tab.
     *
     * It comes back even when the analysis failed, and that is what it is for:
     * the field over the model is pre-filled with it, so a user whose configured
     * solver is not installed can see what was tried and type something else,
     * rather than being shown an error about a package and an empty box.
     */
    implementation?: string;
}

export type HostMessage = ShowMessage | ClearMessage | TabDataMessage;

/** Renderer to host: fill this tab in, quoting 'token' back in the answer. */
export interface FetchTabMessage {
    type: 'fetchTab';
    tab: TabId;
    token: number;
    /**
     * Who should run this analysis, as '<package>:<file type>'.
     *
     * Only the analysis tabs send it, and only once the user has typed one: left
     * out, the daemon uses the configured default ('caeFeaImplementation' /
     * 'caeCfdImplementation'), which is the same default the CLI's
     * '--implementation' overrides.
     */
    implementation?: string;
}

//
// What the daemon answers with, as the operations in
// 'partcad_service_json_rpc.core.operations' return it. The names are the
// Python ones, snake_case included: this is that payload, not a translation of
// it.
//

/** One line item of `pc bom`. */
export interface BomItem {
    name: string;
    kind?: string | null;
    count: number;
    desc?: string | null;
    vendor?: string | null;
    sku?: string | null;
    // eslint-disable-next-line @typescript-eslint/naming-convention
    count_per_sku?: number | null;
}

export interface BomData {
    assembly: string;
    items: BomItem[];
    total: number;
}

/** A picture of a generated document, carried inline (see 'document.to_data'). */
export interface DocumentImage {
    src?: string | null;
    alt?: string | null;
    caption?: string | null;
}

/**
 * One block of a generated document.
 *
 * The union of every shape 'partcad.document._block_to_data()' produces; each
 * block only carries the fields of its own 'type'.
 */
export interface DocumentBlock {
    type: string;
    text?: string;
    level?: number;
    url?: string | null;
    items?: [string, string][];
    columns?: string[];
    aligns?: string[];
    rows?: string[][];
    images?: DocumentImage[];
    height?: number;
}

export interface DocumentPage {
    title?: string | null;
    blocks: DocumentBlock[];
}

export interface DocumentData {
    title: string;
    subtitle?: string | null;
    footer?: string | null;
    pages: DocumentPage[];
}

export interface GuideData {
    assembly: string;
    document: DocumentData;
}

/** One supplier's answer for one line item. */
export interface SupplyOption {
    name: string;
    desc?: string | null;
    url?: string | null;
    currency?: string | null;
    price?: number | null;
    cartId?: string | null;
    expire?: number | null;
    etaMin?: number | null;
    etaMax?: number | null;
    qos?: string | null;
    /** Why this supplier gave no quote, when it gave none. */
    error?: string;
}

/** One thing to order: a part, or a sub-assembly that is sold assembled. */
export interface SupplyItem {
    name: string;
    kind?: string | null;
    desc?: string | null;
    count: number;
    vendor?: string | null;
    sku?: string | null;
    // eslint-disable-next-line @typescript-eslint/naming-convention
    count_per_sku?: number | null;
    /** Cheapest first, so the first entry is the one to order from. */
    suppliers: SupplyOption[];
}

export interface SupplyTotal {
    currency: string | null;
    price: number;
}

export interface SupplyData {
    object: string;
    items: SupplyItem[];
    /** Per currency: two suppliers quoting in different ones cannot be added up. */
    totals: SupplyTotal[];
}

/** One thing an analysis has to say about the part. */
export interface CaeFinding {
    message: string;
    /** 'error', 'warning' or 'info' where the implementation says; absent otherwise. */
    severity?: string | null;
    /** Where in the part it is, in whatever terms the implementation uses. */
    where?: string | null;
    /** An implementation may carry anything else it wants to show. */
    [key: string]: unknown;
}

/**
 * What one run of 'pc cae fea' / 'pc cae cfd' produced, as 'cae.analyze' returns
 * it.
 *
 * 'content' is the model file itself, base64-encoded, because the panel is a
 * webview with no file system in reach: a path it cannot open is a model it
 * cannot draw. 'extension' is what decides how it is drawn - a 3D field is
 * turned and zoomed, a 2D plot is panned and zoomed - and it is the
 * implementation's choice, not PartCAD's.
 */
export interface CaeData {
    object: string;
    analysis: string;
    /** The implementation that actually ran, as '<package>:<file type>'. */
    implementation: string;
    /** Where the model was written on the machine running the daemon. */
    filepath: string;
    extension: string;
    content?: string | null;
    /** Empty when the analysis found nothing to report, which is a pass. */
    findings: CaeFinding[];
}
