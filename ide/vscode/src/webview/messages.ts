//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The 'postMessage' contract between the Digital Thread panel (the extension
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
 * 'manufacturing', what making it takes; 'validation', whether it is what it
 * claims to be and does what it is supposed to; and 'operations', which has
 * nothing in it yet and is shown disabled. Each group is a strip of its own:
 * the object as '3d' (first, always), '2d' and 'draft'; 'fea', 'dynamic',
 * 'thermal' and 'cfd'; 'bvb' (Build vs Buy), 'build', 'supply' (labelled Buy),
 * 'bom' and 'assembly'; and 'test', what 'pc test' says of it check by check,
 * before 'simulation' and 'emulation' (Process Emulation), which has nothing in
 * it yet and is shown disabled.
 *
 * In front of the five, and only for an object that declares any:
 * 'requirements', a tab of its own with no strip under it.
 */
export type TabId =
    | 'requirements'
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
    | 'dynamic'
    | 'thermal'
    | 'cfd'
    | 'simulation'
    | 'emulation'
    | 'test';

/**
 * The tabs that run an analysis, each named after the analysis it runs: the
 * name 'pc cae <analysis>' takes and 'cae.analyze' is asked with, which the
 * host passes on as it is. Spelled out in 'TabId' as well, where
 * 'tests/partcad_ide_client/unit/test_protocol.py' reads every tab id from.
 */
export type AnalysisTabId = Extract<TabId, 'fea' | 'dynamic' | 'thermal' | 'cfd'>;

/** The Design tab's own tabs. */
export const DESIGN_TABS: TabId[] = ['3d', '2d', 'draft'];

/**
 * Every group of the panel's strip that holds tabs of its own, and those tabs in
 * the order they are shown.
 *
 * What a show's 'tab' may name ('pc ide view --design-2d' and its siblings), and
 * which group has to be opened for it. 'VIEWER_TABS' in
 * 'src/partcad_ide_client/protocol.py' is the other copy, and a test there holds
 * the two to each other.
 */
export const TAB_GROUPS: Partial<Record<TabId, TabId[]>> = {
    design: DESIGN_TABS,
    analysis: ['fea', 'dynamic', 'thermal', 'cfd'],
    manufacturing: ['bvb', 'build', 'supply', 'bom', 'assembly'],
    // Not 'emulation' (Process Emulation) yet: it holds nothing and is always
    // disabled, so a request for it could never be met.
    validation: ['test', 'simulation'],
};

/** The group a tab of 'TAB_GROUPS' is in, or undefined for anything else. */
export function groupOf(tab: string | null | undefined): TabId | undefined {
    for (const [group, tabs] of Object.entries(TAB_GROUPS)) {
        if (tabs?.includes(tab as TabId)) {
            return group as TabId;
        }
    }
    return undefined;
}

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

/**
 * The simulation plugins the Simulation tab offers, as '<package>:<name>': the two
 * registered at '//pub/feature/simulate', until there are more. The one a
 * simulation names in its 'simulation:' is the one selected; see 'simulation.ts'.
 */
export const SIMULATION_PLUGINS = ['//pub/feature/simulate/mujoco:mujoco', '//pub/feature/simulate/gazebo:gazebo'];

/**
 * The solvers each Analysis tab offers, as '<package>:<file type>': the ones
 * registered at '//pub/feature/cae' that implement that analysis, the user
 * configuration's default first ('caeFeaImplementation' and the rest). The one
 * a scenario runs with unasked -- its own 'implementation:', or that default --
 * is the one selected; see 'analysis.ts'. The Simulation tab's
 * 'SIMULATION_PLUGINS', for an analysis.
 */
export const CAE_IMPLEMENTATIONS: Record<AnalysisTabId, string[]> = {
    fea: [
        '//pub/feature/cae/calculix:fea',
        '//pub/feature/cae/code_aster:fea',
        '//pub/feature/cae/elmer:fea',
        '//pub/feature/cae/moose:fea',
    ],
    dynamic: [
        '//pub/feature/cae/elmer:dynamic',
        '//pub/feature/cae/code_aster:dynamic',
        '//pub/feature/cae/moose:dynamic',
    ],
    thermal: [
        '//pub/feature/cae/elmer:thermal',
        '//pub/feature/cae/code_aster:thermal',
        '//pub/feature/cae/moose:thermal',
    ],
    cfd: [
        '//pub/feature/cae/openfoam:cfd',
        '//pub/feature/cae/calculix:cfd',
        '//pub/feature/cae/code_saturne:cfd',
        '//pub/feature/cae/elmer:cfd',
        '//pub/feature/cae/moose:cfd',
    ],
};

/**
 * The tabs that run an analysis rather than ask a question about the object,
 * in the order the Analysis strip shows them: the structural ones first, static
 * then dynamic, then heat transfer, then flow.
 */
export const ANALYSIS_TABS = TAB_GROUPS.analysis as AnalysisTabId[];

/**
 * What each analysis is called where a person reads it: on its tab, and in its
 * pane - the implementation field's tooltip and accessible name, and the result
 * picture's alt text.
 *
 * Not derived from the id. The id is a command's word - 'pc cae dynamic' runs a
 * modal analysis, and "DYNAMIC" is not what anybody calls one - so it stays where
 * a person would type it ('pc cae <id> --implementation') and this is what is
 * shown. One table for the tab and the pane, so the two cannot come to disagree.
 */
export const ANALYSIS_LABELS: Record<AnalysisTabId, string> = {
    fea: 'FEA',
    dynamic: 'Dynamic FEA',
    thermal: 'Heat Transfer',
    cfd: 'CFD',
};

export function isAnalysisTab(tab: TabId): tab is AnalysisTabId {
    return (ANALYSIS_TABS as TabId[]).includes(tab);
}

/**
 * The tabs whose pane is a list of what the object declares, one of which is
 * selected and run: its simulations, and its scenarios of each analysis. What a
 * show's 'scenario' can select on; 'SCENARIO_TABS' in
 * 'src/partcad_ide_client/protocol.py' is the other copy.
 */
export const SCENARIO_TABS: TabId[] = [...ANALYSIS_TABS, 'simulation'];

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
    /**
     * What this node's shape reports about itself, where it reports anything.
     *
     * PartCAD's 'properties:' section, passed through untouched (see
     * 'KEY_PROPERTIES' in 'partcad/shape_envelope.py'): what it is made of, its
     * colour, its physics. The viewer reads 'color' - "#RRGGBB" or "#RRGGBBAA" -
     * and draws the node, and everything under it that states no colour of its
     * own, in it (see 'appearance.ts'); nothing else.
     */
    properties?: ShowProperties | null;
}

/** The part of a node's properties the viewer reads. */
export interface ShowProperties {
    /** "#RRGGBB", or "#RRGGBBAA" for a shape that is see-through. */
    color?: string | null;
    /** The name of the material it is made of. Not read by the viewer: a material states no colour. */
    material?: string | null;
    [property: string]: unknown;
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
    /**
     * The tab to open on, one of those in 'TAB_GROUPS', or null to stay on the
     * one that is open. What 'pc ide view --analysis-fea' asks for; a tab that
     * does not apply to this object is not opened.
     */
    tab?: TabId | null;
    /**
     * With a 'tab' that lists scenarios - the Simulation tab, and each analysis
     * tab - which of them to select, by the name the object declares it under:
     * what 'pc ide view --analysis-fea --scenario loaded' asks for. Null selects
     * the first, as opening the tab by hand does, and so does a name the object
     * does not declare. See 'SCENARIO_TABS'.
     */
    scenario?: string | null;
    /**
     * What the object was cut to before it was drawn - a box in millimetres in
     * the frame of its root, naming only the axes that cut ('section.ts') - or
     * null for the whole object. Absent from a 'partcad' that cannot cut, which
     * is how the view panel knows not to offer its section sliders. A cut is
     * asked for by asking the daemon to show the object again with one
     * ('ShowSectionMessage'), and this is how the panel learns what is on screen.
     */
    section?: ViewSection | null;
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

/** Host to renderer: what is on screen, for `pc ide state`; answered with a 'StateReplyMessage'. */
export interface StateRequestMessage {
    type: 'state';
    token: number;
}

/** Renderer to host: the panel's state, and the sub-tab on screen as a PNG. */
export interface StateReplyMessage {
    type: 'state';
    token: number;
    state: Record<string, unknown>;
    /** Base64, without a 'data:' prefix; absent with 'screenshotError' saying why. */
    screenshot?: string;
    screenshotError?: string;
}

/**
 * Host to renderer: the show asked for with 'ShowSectionMessage' has been asked
 * of the daemon and answered - the cut object is already on its way over the
 * viewer protocol by then - or could not be, and 'error' is why.
 */
export interface SectionShownMessage {
    type: 'sectionShown';
    token: number;
    error?: string;
}

export type HostMessage =
    | StateRequestMessage
    | SectionShownMessage
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
     * Only the analysis tabs send it, and only once the user has typed one and
     * run it: left out, the daemon uses the scenario's own 'implementation:',
     * and failing that the configured default ('caeFeaImplementation',
     * 'caeDynamicImplementation', 'caeThermalImplementation' or
     * 'caeCfdImplementation') - the same two the CLI's '--implementation'
     * overrides, in the same order. Neither side of the panel fills it in from
     * either of them, because a configured default sent as an override would
     * outrank the scenario's own.
     */
    implementation?: string;
    /** On a render tab: which file type to render to ('png', 'svg', ...). */
    format?: string;
    /**
     * On the Draft tab: the package whose 'render:' section implements that
     * file type, as 'pc render -e' names one. The 2D tab leaves it out and gets
     * PartCAD's own.
     *
     * On the Simulation tab: the simulation plugin to run it with instead of
     * the one it names, as '<package>:<name>' -- 'pc sim --plugin'. Left out,
     * it runs with its own.
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
    /**
     * On the Requirements tab: what is required alone (false, a read of the
     * declaration), or whether the model meets it as well (true, what
     * 'pc test -f requirements' checks). On the Test tab: the checks alone
     * (false, nothing run), or their verdicts as well (true, 'pc test').
     */
    verify?: boolean;
    /**
     * On the Simulation tab: the simulation to run, by the name the object's
     * 'simulate:' section declares it under -- 'pc sim -f'. Left out, the tab
     * is asking what the object declares rather than running anything.
     *
     * On an analysis tab: the scenario to run, by the name the part's section
     * of that analysis declares it under -- 'pc cae <analysis> -f'. What the
     * part declares is asked once for all four, under the group's own id
     * ('analysis'), so an analysis tab always names one.
     */
    scenario?: string;
    /**
     * On the 2D tab and the Simulation tab: where the picture is to be looked
     * at from, as the view panel says it -- 'viewport_origin' and
     * 'viewport_up', 'pc render --viewport-origin/--viewport-up'. Left out, it
     * is looked at from where the package's configuration says, or from the
     * default for the kind of object.
     */
    viewportOrigin?: [number, number, number];
    viewportUp?: [number, number, number];
    /**
     * On the 2D and Draft tabs: what to cut the object to before it is drawn,
     * as the view panel's section sliders say ('section.ts'). Left out for the
     * whole object.
     */
    section?: ViewSection;
}

/**
 * A cross-section as it travels: the axes that cut, each with the slab it keeps,
 * '[from, to]' in millimetres in the frame of the object's root. The same form
 * 'partcad/shape_section.py' normalizes to; 'Section' in 'section.ts' is this.
 */
export type ViewSection = Partial<Record<'x' | 'y' | 'z', [number, number]>>;

/** Where a picture was looked at from, under the names a 'render:' section uses. */
export interface ViewportData {
    // eslint-disable-next-line @typescript-eslint/naming-convention
    viewport_origin: [number, number, number];
    // eslint-disable-next-line @typescript-eslint/naming-convention
    viewport_up: [number, number, number];
}

/**
 * Renderer to host: show the object on screen again, cut to 'section' - or
 * whole, for null - which is how the 3D view's section sliders reach PartCAD.
 * The show comes back over the viewer protocol like any other, carrying the
 * section it was cut to; the host answers 'sectionShown' quoting 'token' once
 * the daemon has.
 */
export interface ShowSectionMessage {
    type: 'showSection';
    token: number;
    section: ViewSection | null;
}

/**
 * Renderer to host: show this object in the panel, as if it had been selected.
 *
 * What a Test tab's artifact opens with: an object the check left behind to be
 * looked at, such as the two parts an interference was found between and what
 * they share. Shown the way the explorer shows anything, through the daemon;
 * not remembered as the selection, since nothing declares it.
 */
export interface ShowObjectMessage {
    type: 'showObject';
    package: string;
    name: string;
    kind: string;
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

/**
 * A picture of a generated document, carried inline (see 'document.to_data').
 *
 * Its bytes and media type, which the extension asks for ('image_bytes'), or a
 * data URI in 'src' from a daemon that predates them.
 */
export interface DocumentImage {
    content?: Uint8Array | null;
    type?: string | null;
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
    /** The document written in the format asked for, for Save; its bytes stay with the host. */
    file?: { filename: string; extension: string };
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
 * What one scenario of 'pc cae <analysis>' produced - 'fea', 'dynamic',
 * 'thermal' or 'cfd' - as an entry of what 'cae.analyze' returns. The shape is
 * the same whichever ran.
 *
 * 'content' is the model file itself, as bytes, because the panel is a webview
 * with no file system in reach: a path it cannot open is a model it cannot
 * draw. (Bytes whatever the daemon sent: the host makes base64 bytes before
 * posting it -- see 'viewer/payloads.ts'.) 'extension' is what decides how it is drawn - a 3D field is
 * turned and zoomed, a 2D plot is panned and zoomed - and it is the
 * implementation's choice, not PartCAD's.
 *
 * 'error' is why the scenario produced nothing: a scenario that cannot be read,
 * a solver that could not run, no sandbox to run it in, an implementation that
 * does not resolve. Those are answers about the scenario and not failures of
 * the request, so they come back here, one scenario's alone, and the tab shows
 * the sentence where the model would have been.
 */
export interface CaeData {
    object: string;
    analysis: string;
    /** The scenario it is of, by the name the part declares it under. */
    scenario?: string;
    desc?: string | null;
    /** Declared in the form a section had before it had scenarios, and read as one named 'default'. */
    legacy?: boolean;
    /** The implementation that ran, or was to, as '<package>:<file type>'; null when nothing named one. */
    implementation?: string | null;
    /** Where the model was written on the machine running the daemon; null when nothing was. */
    filepath?: string | null;
    extension?: string | null;
    content?: Uint8Array | null;
    /** Empty when the analysis found nothing to report, which is a pass. */
    findings: CaeFinding[];
    /** Why this scenario produced nothing, or null when it ran. */
    error?: string | null;
}

/**
 * One scenario a part declares for one analysis, as 'cae.list' answers: an entry
 * of its 'fea:', 'dynamic:', 'thermal:' or 'cfd:' section, read rather than run.
 */
export interface CaeScenario {
    name: string;
    desc?: string | null;
    /** The implementation the scenario names itself, as '<package>:<file type>'; null for the configured one. */
    implementation?: string | null;
    /** The requirement features it demonstrates ('feature:'). */
    features?: string[];
    /** The section is in the form it had before it had scenarios, and this is it, named 'default'. */
    legacy?: boolean;
}

/**
 * What a part declares for every analysis, without running any of it.
 *
 * Configuration, so it costs what reading the part costs: it is asked for on
 * every show of a part, because which Analysis tabs apply depends on it. Every
 * analysis is answered, with an empty list for one the part declares nothing
 * for, and a section that cannot be read is answered under 'errors' with the
 * sentence that says why.
 */
export interface CaeListData {
    object: string;
    kind: string;
    analyses: Record<string, CaeScenario[]>;
    errors?: Record<string, string>;
    /**
     * The implementation each analysis runs under when neither the user nor the
     * scenario names one: 'cae.defaults', added to the answer by the host (the
     * user configuration's 'cae<Analysis>Implementation'). What the field over
     * the model is pre-filled with for a scenario that names none.
     */
    defaults?: Record<string, string>;
}

/**
 * The answer to a run of an analysis: what 'pc cae <analysis> -f <name>' prints
 * with '--json'. An entry per scenario run - the panel asks for one at a time -
 * shaped like 'simulate.run''s answer.
 */
export interface CaeRunData {
    object: string;
    analysis: string;
    analyses: CaeData[];
    /** Every finding of every scenario, each with its 'scenario'. */
    findings: CaeFinding[];
    total: number;
    failed: number;
    ok: boolean;
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
 * The file itself, as bytes, because the panel has no file system in reach -
 * and the daemon may be on another machine, where a path would name nothing
 * the user has. 'extension' is what decides how it is shown.
 */
export interface RenderData {
    object: string;
    format: string;
    filename: string;
    extension: string;
    content: Uint8Array;
    /** Where the picture was looked at from, when the implementation says; what the view panel shows. */
    viewport?: ViewportData | null;
    /** What it was cut to, as PartCAD read the section asked for, or null for the whole object. */
    section?: ViewSection | null;
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
    /** The SVG's bytes, already sized by the daemon. */
    thumbnail?: Uint8Array | null;
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

/**
 * One requirement of 'requirements.check', and what the model made of it.
 *
 * 'section' is 'ports', 'interfaces' or 'physics' for what 'pc test' measures;
 * 'simulate' for a 'simulate:' entry naming a feature nobody declared; and the
 * analysis ('fea', 'dynamic', 'thermal', 'cfd') for one of its scenarios that
 * does the same, with the scenario as 'name'. 'passed' is null until the model
 * has been asked.
 */
export interface RequirementCheck {
    section: string;
    name: string;
    requirement: string;
    passed: boolean | null;
    detail?: string | null;
}

/** One feature: its name, what it is, and the 'simulate:' entries and analysis scenarios that name it. */
export interface RequirementFeature {
    name: string;
    desc: string;
    simulations: string[];
    /**
     * The analysis scenarios that demonstrate it ('feature:' on an entry of a
     * part's 'fea:', 'dynamic:', 'thermal:' or 'cfd:'), in the order declared.
     * Absent from a daemon from before analyses had scenarios.
     */
    analyses?: { analysis: string; name: string }[];
}

/** The 'requirements' tab's data: 'partcad.requirements.Report.to_dict()'. */
export interface RequirementsData {
    object: string;
    kind: string;
    /** Whether the object declares any requirements at all: what decides whether the tab is offered. */
    defined: boolean;
    /** Whether the verdicts are in, or only what is required. */
    verified: boolean;
    features: RequirementFeature[];
    requirements: RequirementCheck[];
}

/** One simulation an object declares, as 'simulate.list' answers: its 'simulate:' entry. */
export interface SimulationScenario {
    name: string;
    desc?: string | null;
    /** The scene it is run in, as '<package>:<name>'. */
    scene?: string | null;
    /** The plugin that runs it, as '<package>:<name>'. */
    simulation?: string | null;
    /** The Python expression over 'before' and 'after' that decides the verdict. */
    validation?: string | null;
}

/**
 * What an object declares under 'simulate:', without running any of it.
 *
 * Configuration, so it costs what reading the object costs: it is asked for on
 * every show of a part or an assembly, because whether the Validation group
 * applies at all depends on it.
 */
export interface SimulationListData {
    object: string;
    kind: string;
    simulations: SimulationScenario[];
}

/** One picture of a run, as the bytes of the file the plugin wrote. */
export interface SimulationImage {
    filename: string;
    extension: string;
    content: Uint8Array;
}

/**
 * One run of one simulation, as 'simulate.run' reports it ('pc sim --json').
 *
 * 'passed' is the verdict of the 'validation:' expression: null when there is
 * none, or when the run never got far enough to have one -- which 'error' then
 * says. 'images' are the two pictures the plugin took of the scene, before
 * anything moved and when the run was over, from the scene's own viewpoint; a
 * plugin that takes none leaves them out, which is not a failure.
 */
export interface SimulationRun {
    object: string;
    simulation: string;
    scene?: string | null;
    plugin?: string | null;
    validation?: string | null;
    passed: boolean | null;
    error?: string | null;
    result?: Record<string, unknown>;
    images?: { before?: SimulationImage; after?: SimulationImage };
    /** Where the pictures were taken from; what the view panel shows beside them. */
    viewport?: ViewportData | null;
}

/** The answer to a run: what 'pc sim -f <name>' prints with '--json'. */
export interface SimulationRunData {
    simulations: SimulationRun[];
    total: number;
    failed: number;
    ok: boolean;
}

/** How a check came out: see 'partcad.test.report'. Null until it has been run. */
export type TestStatus = 'passed' | 'failed' | 'warned' | 'skipped' | 'not-applicable';

/** Something a check said on the way to its verdict. */
export interface TestFinding {
    level: 'error' | 'warning' | 'info';
    text: string;
}

/** An object a check left behind to be looked at, shown with 'ShowObjectMessage'. */
export interface TestArtifact {
    kind: string;
    package: string;
    name: string;
    title?: string;
    desc?: string;
}

/** One block of a check's documentation: the markup of 'partcad.test.catalog'. */
export type TestDocBlock =
    | { type: 'heading'; text: string }
    | { type: 'paragraph'; text: string }
    | { type: 'list'; items: string[] }
    | { type: 'code'; language: string; text: string };

/** What a check is, when it applies and what to do when it fails: 'partcad.test.catalog.describe()'. */
export interface TestDoc {
    title: string;
    applies: string;
    blocks: TestDocBlock[];
}

/** One check of 'test.report', and what it decided. */
export interface TestResult {
    name: string;
    status: TestStatus | null;
    findings: TestFinding[];
    artifacts: TestArtifact[];
    doc: TestDoc | null;
}

/** The 'test' tab's data: 'partcad.test.report.to_dict()'. */
export interface TestData {
    object: string;
    kind: string;
    /** Whether the checks were run, or only listed. */
    verified: boolean;
    tests: TestResult[];
}
