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
 * The answer to one 'fetchTab'.
 *
 * 'token' is the generation of the object the request was made for. A daemon
 * round trip outlives a change of selection easily - a bill of materials walks
 * the whole assembly tree, a supply quote goes out to the network - so an answer
 * that arrives after the panel moved on has to be dropped rather than painted
 * over what is now on screen. An analysis outlives one by a great deal more: a
 * solver runs for as long as it runs.
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

/** Renderer to host: fill this tab in for the object of generation 'token'. */
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
