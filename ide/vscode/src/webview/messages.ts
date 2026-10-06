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

import type { SpaceMouseSettings } from './spacemouse';

/**
 * The tabs the panel can show.
 *
 * Two levels of them. The panel's own strip is five groups, always the same
 * five: 'design', the object itself; 'analysis', what analysing it says;
 * 'manufacturing', what making it takes; and 'validation' and 'operations',
 * which have nothing in them yet and are shown disabled. Each group is a strip of its own: the
 * object as '3d' (first, always), '2d' and 'draft'; 'fea' and 'cfd'; 'bvb'
 * (Build vs Buy), 'build', 'supply' (labelled Buy), 'bom' and 'assembly'.
 */
export type TabId =
    | 'design'
    | 'analysis'
    | 'manufacturing'
    | 'validation'
    | 'operations'
    | '3d'
    | '2d'
    | 'draft'
    | 'bvb'
    | 'build'
    | 'bom'
    | 'supply'
    | 'assembly'
    | 'fea'
    | 'cfd';

/** The Design tab's own tabs. */
export const DESIGN_TABS: TabId[] = ['3d', '2d', 'draft'];

/** The two tabs that show the object rendered to a file, and save it. */
export const RENDER_TABS: TabId[] = ['2d', 'draft'];

export function isRenderTab(tab: TabId): boolean {
    return RENDER_TABS.includes(tab);
}

/**
 * Where the Draft tab's drawings come from, until there is more than one.
 *
 * A package whose 'render:' section implements drawing file types, used the way
 * 'pc render -e' uses one: see 'examples/feature_render_custom'.
 */
export const DRAFT_PLUGINS = ['//pub/feature/render/draftwright'];

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
    /**
     * The object this node holds: '<package>:<object>'. An assembly that places
     * the same bolt a hundred times sends one name on a hundred nodes.
     */
    name?: string | null;
    /**
     * The link: what the node holding this one addresses it by, which is what
     * tells those hundred nodes apart.
     *
     * The 'name:' of the ASSY link that placed it, or - for a child nothing
     * named - its position in its parent, one-based ('link#2'). Never a
     * fallback to the object's own name, which is what makes it usable as a
     * name a request carries back: a 'connect:', a 'map:', 'pc filter' and the
     * mask this panel composes ('Tree.filter()') all name a link this way.
     * See 'Assembly.link_name' and 'partcad_utils.assy_filter'.
     */
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
    /** Configuration for the viewer, sent from the extension. */
    config?: {
        viewer?: {
            performanceDebug?: boolean;
        };
    };
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

/**
 * How the SpaceMouse is to behave in this panel, sent on boot and whenever it changes.
 *
 * 'settings' is the user's 'partcad.spaceMouse.*'. 'active' is whether the panel
 * is visible in the focused window: spacenavd tells every client about every
 * push, so a panel that is not where the user is must not act on it. 'spacenavd'
 * is whether the host is reading spacenavd, which then speaks for the device and
 * the Gamepad API is left alone. 'spacenavdDevice' is the device spacenavd
 * says it serves, which is what says which of its buttons is "Fit"; null when
 * it has not said. See 'spacemouse.ts'.
 */
export interface SpaceMouseStateMessage {
    type: 'spaceMouseState';
    settings: SpaceMouseSettings;
    active: boolean;
    spacenavd: boolean;
    spacenavdDevice: number | null;
}

/**
 * One event from spacenavd, forwarded as it came: six axis values in spacenavd's
 * own frame and scale, or a button. The conversion is the renderer's
 * ('fromSpacenav'), so that every convention about the device is in one file.
 */
export interface SpaceMouseEventMessage {
    type: 'spaceMouseEvent';
    motion?: number[];
    button?: number;
    pressed?: boolean;
}

/** Updated viewer configuration when settings change. */
export interface UpdateConfigMessage {
    type: 'updateConfig';
    config: {
        viewer: {
            performanceDebug: boolean;
        };
    };
}

/** The answer to one 'fetchFormats': the file types a package renders to. */
export interface FormatsMessage {
    type: 'formats';
    token: number;
    plugin: string;
    formats?: RenderFormat[];
    error?: string;
}

/** The answer to one 'fetchDetails': what the Build vs Buy table shows of each line beside its name. */
export interface DetailsMessage {
    type: 'details';
    token: number;
    items?: ItemDetails[];
    error?: string;
}

export type HostMessage =
    | ShowMessage
    | ClearMessage
    | TabDataMessage
    | FormatsMessage
    | DetailsMessage
    | SpaceMouseStateMessage
    | SpaceMouseEventMessage
    | UpdateConfigMessage;

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
    /** On a render tab: which file type to render to ('png', 'svg', ...). */
    format?: string;
    /**
     * On the Draft tab: the package whose 'render:' section implements that
     * file type, as 'pc render -e' names one. The 2D tab leaves it out and gets
     * PartCAD's own.
     */
    plugin?: string;
    /**
     * On a render tab: which links of the object to draw, as the mask
     * 'pc render --filter' takes - a mapping of link name to the mask that
     * applies inside it, where an empty mapping keeps everything below.
     *
     * Composed from the boxes ticked in the panel beside the drawing
     * ('Tree.filter()'), and left out when every one of them is ticked: there is
     * nothing to filter then, and sending a mask of the whole object would only
     * make PartCAD walk it to arrive at the same tree.
     */
    filter?: unknown;
    /**
     * On the 2D tab: whether the ports and the interfaces ticked in that panel
     * are drawn on top of the projection, which is 'pc render --with-ports' /
     * '--with-interfaces' / '--with-internals'. The Draft tab sends none: a
     * dimensioned drawing is of the solid, and its panel lists no ports.
     */
    withPorts?: boolean;
    withInterfaces?: boolean;
    withInternals?: boolean;
    /**
     * On the 2D tab: which of the object's ports to draw, by the name PartCAD
     * reports each under -- the port's own name for a port of the object, and
     * the path of links then the port for one inside it ('bolt:thread-m8').
     * What 'pc render --port' names on the command line.
     *
     * Left out when the panel ticked none, so that an overlay a file type asked
     * for itself is not narrowed to nothing.
     */
    ports?: string[];
    /**
     * On the Build and Assembly tabs: what the user chose to build and to buy
     * on the Build vs Buy tab. The renderer holds it and sends it with every
     * request rather than the host reading it back, so that what is asked is
     * exactly what is on screen.
     */
    choices?: Choices;
    /** On the Build and Assembly tabs: whether sub-assemblies are documented as well. */
    recursive?: boolean;
    /** On the Assembly tab: whether the steps that make the built parts are included. */
    buildParts?: boolean;
    /** On the Build tab: the plan alone (false, fast), or the pages it points into as well (true). */
    document?: boolean;
}

/** Renderer to host: the thumbnails and measurements of these objects, sized 'width' x 'height'. */
export interface FetchDetailsMessage {
    type: 'fetchDetails';
    token: number;
    objects: { name: string; kind: string }[];
    width: number;
    height: number;
}

/**
 * Renderer to host: the user changed what is built and what is bought.
 *
 * Kept by the host, on this machine, in the garage (see 'common/garage.ts'),
 * and never by the daemon: it is this user's decision about how they will get
 * hold of the thing, and the daemon may be somebody else's.
 */
export interface SaveChoicesMessage {
    type: 'saveChoices';
    object: string;
    choices: Choices;
}

/** Renderer to host: which file types a package renders to, for the Draft tab. */
export interface FetchFormatsMessage {
    type: 'fetchFormats';
    token: number;
    plugin: string;
}

/**
 * Renderer to host: save what a render tab is showing.
 *
 * Only the tab is named, never a file: the host keeps the file it rendered, and
 * asks the user where it should go.
 */
export interface SaveMessage {
    type: 'save';
    tab: TabId;
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
    pages?: Record<string, number>;
    plan?: PlanItem;
    /** The document written in the format asked for, for Save. */
    file?: { filename: string; extension: string; content?: string };
    /**
     * Whether the assembly is meant to be made ('manufacturable:', on it or its
     * package). The tab asks for the instructions regardless, and says so.
     */
    manufacturable?: boolean;
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

/** One file type a package renders to, as 'render.formats' lists it. */
export interface RenderFormat {
    name: string;
    desc?: string | null;
    extension?: string | null;
}

/**
 * One object rendered to one file, as 'render.inline' returns it.
 *
 * The file itself, base64-encoded, because the panel has no file system in
 * reach - and the daemon may be on another machine, where a path would name
 * nothing the user has. 'extension' is what decides how it is shown.
 */
export interface RenderData {
    object: string;
    format: string;
    filename: string;
    extension: string;
    content: string;
}

/** What the user chose for each line that can be both built and bought, by its full name. */
export type Choices = Record<string, 'build' | 'buy'>;

/**
 * One node of what an object is made of, as 'manufacturing.tree' answers.
 *
 * The object's own structure - an assembly's links in order, a part's stock -
 * with what each node declares about being built and being bought. No geometry:
 * it is asked on every show, because which Manufacturing tabs apply depends on it.
 */
export interface TreeNode {
    /** Unique within one tree: the path to this node. */
    id: string;
    /** '//package:name'; an embedded assembly is named after its parent and link. */
    name: string;
    kind: 'part' | 'assembly';
    /** The link's name inside the parent assembly. */
    link?: string | null;
    desc?: string | null;
    /** It declares a vendor and an SKU. */
    buy: boolean;
    /** It declares how it is made (a part) or has links to put together (an assembly). */
    build: boolean;
    vendor?: string | null;
    sku?: string | null;
    /** The material reference, as written. */
    material?: string | null;
    /**
     * The file the object is made from - its script, STEP or ASSY file - as an
     * absolute path on the daemon's machine, or absent when it has none of its
     * own. What the line's name opens in an editor.
     */
    source?: string | null;
    /** Nested in its parent's ASSY file: always built, and never a line of its own. */
    embedded?: boolean;
    /** A stock reference that resolves to nothing. */
    missing?: boolean;
    /**
     * Meant to be made where it is used: false when it, or its package, says
     * 'manufacturable: false' and nothing manufacturable it is used in
     * overrides that (see 'partcad.build_plan._manufacturable'). Absent from
     * a daemon too old to say, which reads as true.
     */
    manufacturable?: boolean;
    /**
     * What stops it from being built, worded as 'pc test -f manufacturability'
     * words it: incomplete instructions, no tolerance, an unpinned file, an
     * assembly that is not an ASSY file. 'build' is false whenever this is not
     * empty.
     */
    problems?: string[];
    /** What a made part is made from. */
    stock?: TreeNode;
    /** An assembly's links, in order. */
    children?: TreeNode[];
}

/** The 'bvb' tab's data: the tree, and what this user chose for it last time. */
export interface BvbData {
    object: string;
    kind: string;
    tree: TreeNode;
    choices: Choices;
}

/** One object's thumbnail and measurements, as 'manufacturing.details' answers. */
export interface ItemDetails {
    name: string;
    kind?: string;
    /** Base64 SVG, already sized by the daemon. */
    thumbnail?: string | null;
    /** The bounding box's size, in millimetres. */
    size?: [number, number, number] | null;
    volume?: number | null;
    /** In grams. */
    mass?: number | null;
    error?: string;
}

/**
 * One item of a build plan, as 'manufacturing.plan' answers.
 *
 * The order the thing is made in: the Build tab's list, and the order of the
 * pages of the assembly instructions - the same plan, worked out once, by the
 * daemon, so that the two cannot disagree.
 */
export interface PlanItem {
    id: string;
    type: 'part' | 'assembly' | 'link' | 'manufacture';
    name: string;
    title: string;
    kind?: 'part' | 'assembly';
    link?: string;
    count: number;
    step?: number;
    children?: PlanItem[];
}

/** The 'build' tab's data: the plan, and, once asked for, the pages it points into. */
export interface PlanData {
    object: string;
    kind: string;
    plan: PlanItem;
    document?: DocumentData;
    /** Plan item id -> index into 'document.pages'. */
    pages?: Record<string, number>;
}
