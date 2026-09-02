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
export type TabId = '3d' | 'bom' | 'instructions' | 'cam' | 'supply';

/** A displayable object: the glTF, decompressed by the host, as base64. */
export interface ShowObject {
    name: string;
    label: string | null;
    gltf: string;
    size: number;
}

/** A bare coordinate frame (a PartCAD interface port), as a packed location. */
export interface ShowMarker {
    name?: string | null;
    location: [[number, number, number], [number, number, number], number];
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
    objects: ShowObject[];
    markers: ShowMarker[];
}

export interface ClearMessage {
    type: 'clear';
}

/**
 * Which further tabs this object turns out to have.
 *
 * Sent after the 'show' it belongs to rather than inside it. Whether an object
 * has a CAM view is a question for the daemon - does its package declare a
 * 'cam:' file type, and can that implementation draw what it writes - and the
 * geometry must not wait on the answer. The renderer adds the tab when this
 * arrives for the generation it is still on, keeping whichever tab the reader
 * is looking at.
 */
export interface TabsMessage {
    type: 'tabs';
    token: number;
    /** The file type the CAM visualization is written as, or null for none. */
    cam: string | null;
}

/**
 * The answer to one 'fetchTab'.
 *
 * 'token' is the generation of the object the request was made for. A daemon
 * round trip outlives a change of selection easily - a bill of materials walks
 * the whole assembly tree, a supply quote goes out to the network - so an answer
 * that arrives after the panel moved on has to be dropped rather than painted
 * over what is now on screen.
 */
export interface TabDataMessage {
    type: 'tabData';
    tab: TabId;
    token: number;
    data?: unknown;
    error?: string;
}

export type HostMessage = ShowMessage | ClearMessage | TabDataMessage | TabsMessage;

/** Renderer to host: fill this tab in for the object of generation 'token'. */
export interface FetchTabMessage {
    type: 'fetchTab';
    tab: TabId;
    token: number;
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

/**
 * The CAM view of an object: what its manufacturing instructions look like.
 *
 * Not the part. A 'cam:' plugin that can draw what it is about to do writes a 3D
 * model of it - the beads an FDM printer lays, the volume a mill takes away - in
 * whatever format it finds natural, and PartCAD converts that to glTF before it
 * gets here. See 'partcad.actions.cam.visual_model_async'.
 */
export interface CamData {
    object: string;
    /** Binary glTF, base64 encoded. */
    gltf: string;
    size: number;
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
