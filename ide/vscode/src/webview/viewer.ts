//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The PartCAD Viewer panel, inside the webview.
//
// Geometry is only the first of what the panel has to say about what is on
// screen. An assembly also has a bill of materials and a set of assembly
// instructions, and anything that can be bought has suppliers and prices, so the
// panel is a strip of tabs over one object rather than a canvas:
//
//     Design           |  Analysis   |  Manufacturing                                                    |  Validation  |  Operations
//       3D | 2D | Draft     FEA | CFD    Build vs Buy | Build | Bill of Materials | Buy | Assembly
//
// Three groups, each a strip of its own. Design is the object itself: turned in
// 3D, rendered to a picture, drawn as a dimensioned drawing. Analysis is what
// engineering analysis says about it, and Manufacturing what making it takes -
// which of its parts are made and which are ordered, how to make them, what it
// is made of, where to buy it, how it goes together. Validation and Operations
// hold nothing yet, and are always disabled.
//
// Every group always shows all of its tabs and disables the ones that do not
// apply, and a group none of whose tabs apply is itself disabled; see 'Tabs'
// for which tab each strip then opens on. Design and its 3D view are always the
// first and always enabled, because that is what "show this part" means - and
// what an empty panel, before anything has been selected, opens on.
//
// This file is the shell: it owns the tab strips and the panes, routes what the
// extension host posts in, and asks for the contents of a tab the first time it
// is looked at. Each pane draws itself ('scene.ts', 'render.ts', 'bom.ts',
// 'bvb.ts', 'build.ts', 'assembly.ts', 'supply.ts'); none of them talks to the
// host directly.
//
// The Manufacturing strip is the one whose shape depends on an answer. Whether
// anything is built (the Build tab) and whether anything is bought (the Buy tab)
// is what the user decided on the Build vs Buy tab, over a tree only the daemon
// can read - so that tree is asked for on every show of a part or an assembly,
// whichever tab is open, and the strip is rebuilt when it arrives.
//
// The 3D view is loaded on its own rather than imported: it needs WebGL, and a
// window without it throws as the view is built. Imported, that took every other
// tab down with it - the 2D tab included, which is exactly what such a window
// can still show. See 'sceneLoaded'.
//
// Everything but the 3D view is answered by the PartCAD daemon, which this
// renderer cannot reach: the panel's CSP forbids every network request, and the
// daemon is behind the extension host's JSON-RPC connection anyway. So a pane's
// contents are asked for ('fetchTab') and delivered ('tabData'), never fetched.
//

import { AssemblyView } from './assembly';
import { renderBom } from './bom';
import { BuildView } from './build';
import { BvbResult, BvbView, THUMBNAIL_SIZE, visibleRows } from './bvb';
import { hasCallouts } from './callouts';
import { CaeView } from './cae';
import { el, empty, placeholder } from './dom';
import {
    fetchDetails,
    fetchFormats,
    fetchTab,
    openSource,
    ready,
    reportError,
    reportFailure,
    saveChoices,
    saveRendered,
} from './host';
import {
    ANALYSIS_TABS,
    BomData,
    BvbData,
    CaeData,
    Choices,
    DRAFT_PLUGINS,
    DetailsMessage,
    FetchTabMessage,
    FormatsMessage,
    GuideData,
    HostMessage,
    PlanData,
    RENDER_TABS,
    RenderData,
    RenderFormat,
    ShowMessage,
    SupplyData,
    TabId,
    isAnalysisTab,
    isRenderTab,
} from './messages';
import { Choice, RenderView } from './render';
import { SupplyView } from './supply';
import { TabSpec, Tabs } from './tabs';
import { LinkFilter, OverlayRequest, Selection, Tree, filterIsEmpty } from './tree';

const panes: Record<TabId, HTMLElement> = {
    design: byId('pane-design'),
    analysis: byId('pane-analysis'),
    manufacturing: byId('pane-manufacturing'),
    validation: byId('pane-validation'),
    operations: byId('pane-operations'),
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '3d': byId('pane-3d'),
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '2d': byId('pane-2d'),
    draft: byId('pane-draft'),
    bvb: byId('pane-bvb'),
    build: byId('pane-build'),
    bom: byId('pane-bom'),
    supply: byId('pane-supply'),
    assembly: byId('pane-assembly'),
    fea: byId('pane-fea'),
    cfd: byId('pane-cfd'),
};

/** The tabs whose panes are rebuilt from scratch on every show. */
const DATA_TABS: TabId[] = ['bom', 'supply'];

const supplyView = new SupplyView(panes.supply);
// The three Manufacturing panes that hold controls of their own - switches, a
// checkbox, a format - own their panes for the life of the panel, as the
// analyses do: rebuilding one on every show would take back what the user set.
const bvbView = new BvbView(panes.bvb, { onChange: onChoicesChanged, requestDetails, openSource });
const buildView = new BuildView(panes.build, { onRecursive: () => requestPlan() });
const assemblyView = new AssemblyView(panes.assembly, {
    onChange: () => requestGuide(),
    onSave: () => saveRendered('assembly'),
});
// Each analysis owns its pane for the life of the panel: the implementation
// field is the user's, and rebuilding the pane on every show would take back
// what they typed into it.
const caeViews: Partial<Record<TabId, CaeView>> = {};
for (const tab of ANALYSIS_TABS) {
    caeViews[tab] = new CaeView(panes[tab], tab, (implementation) => runAnalysis(tab, implementation));
}
const tabs = new Tabs(byId('tabs'), onTabSelected);
const designTabs = new Tabs(byId('design-tabs'), (tab) => onInnerSelected('design', tab));
const analysisTabs = new Tabs(byId('analysis-tabs'), (tab) => onInnerSelected('analysis', tab));
const manufacturingTabs = new Tabs(byId('manufacturing-tabs'), (tab) => onInnerSelected('manufacturing', tab));

/** Each group of the panel's strip, and the strip of its own it holds. */
const groups: Partial<Record<TabId, Tabs>> = {
    design: designTabs,
    analysis: analysisTabs,
    manufacturing: manufacturingTabs,
};

/** The 3D view's module, once it has loaded; undefined before, and for good if it could not. */
type Scene = typeof import('./scene');
let scene: Scene | undefined;

/**
 * The 3D view, loaded apart from everything else.
 *
 * 'eager' keeps it in this bundle - the panel's CSP loads one script and no
 * other - while still running it only when asked, so that its failure is a
 * rejected promise here rather than an exception in the middle of loading this
 * file. What it cannot draw it says where it would have drawn it, and the
 * controls that only move a model go, since there is none to move.
 */
const sceneLoaded: Promise<Scene | undefined> = import(/* webpackMode: "eager" */ './scene').then(
    (module) => {
        scene = module;
        scene.setShowMetadata(metadataCheckbox?.checked ?? true);
        return module;
    },
    (error: unknown) => {
        reportFailure('The 3D view could not start', error);
        const controls = document.querySelector('.viewer-controls') as HTMLElement | null;
        if (controls !== null) {
            controls.hidden = true;
        }
        return undefined;
    },
);

/**
 * What is ticked, for the whole Design group.
 *
 * One answer across 3D, 2D and Draft: what somebody wants to look at is a
 * property of the object, not of the tab it is being looked at on, so switching
 * tabs shows the same selection and a box cleared on one is cleared on the
 * others. Cleared when the object changes, and only then -- the same object
 * shown again (an edit saved, a re-render) keeps it, for the reason the camera
 * is kept. See 'Selection'.
 */
const selection = new Selection();

/** The file types the 2D tab offers: PartCAD's own pictures. */
const PICTURES: Choice[] = [
    { value: 'png', label: 'PNG' },
    { value: 'jpeg', label: 'JPEG' },
    { value: 'svg', label: 'SVG' },
];

/** What a drawing is best looked at as, when the drawing package offers it. */
const PREFERRED_DRAFT_FORMATS = ['svg', 'png'];

const renderViews: Partial<Record<TabId, RenderView>> = {
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '2d': new RenderView(panes['2d'], {
        formats: PICTURES,
        onChange: () => renderTab('2d'),
        onSave: () => saveRendered('2d'),
    }),
    draft: new RenderView(panes.draft, {
        plugins: DRAFT_PLUGINS,
        onChange: () => renderTab('draft'),
        onPlugin: () => startDraft(),
        onSave: () => saveRendered('draft'),
    }),
};

/**
 * The control pane of each render tab: what the object is made of, as boxes.
 *
 * The same tree the 3D view has, asked for the same reason and read differently:
 * nothing here can switch a shape off on a stage, because the picture is made by
 * PartCAD and arrives as a file. So the ticked boxes become a filter sent with
 * the render ('Tree.filter()'), and on the 2D tab also the port overlays to draw
 * on it ('Tree.overlay()').
 *
 * Two options separate them from the 3D view's. Draft lists no ports or
 * interfaces: a dimensioned drawing is of the solid, and nothing is drawn at a
 * port in one. And both fix the root's box ticked -- the object is what is being
 * rendered, so there is no picture with it cleared.
 *
 * What starts out ticked is *not* one of them: all three share one selection, so
 * one of them deciding otherwise would show a different answer on each tab. So
 * the 2D tab's first picture of an object that declares ports has them drawn on
 * it, because that is what the panel beside it says -- the panel and the picture
 * agreeing is worth more than a cleaner default.
 */
const renderTrees: Partial<Record<TabId, Tree>> = {
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '2d': new Tree(renderViews['2d']!.treeHost, () => onBoxChanged(), undefined, {
        lockRoot: true,
        selection,
    }),
    draft: new Tree(renderViews.draft!.treeHost, () => onBoxChanged(), undefined, {
        ports: false,
        lockRoot: true,
        selection,
    }),
};

/**
 * How long a tick waits before the render it asks for is sent, in milliseconds.
 *
 * A render is a round trip to the daemon and a drawing is minutes of one, while
 * choosing what to look at is several ticks in a row: three boxes cleared one
 * after another would otherwise be three renders, the first two of them already
 * stale as they were asked for. Short enough to feel immediate, long enough to
 * gather a handful of clicks.
 */
const SELECTION_SETTLE_MS = 400;

const settling: Partial<Record<TabId, ReturnType<typeof setTimeout>>> = {};

/**
 * A box was ticked or cleared, on whichever tab is on screen.
 *
 * The selection is shared, so this is one handler for all three: the 3D view
 * redraws (it owns the geometry and can), and the two render tabs are answered
 * by the daemon, so what they had is no longer what the panel says -- their
 * pictures are forgotten and the one on screen is asked for again.
 */
function onBoxChanged(): void {
    scene?.showItems(objectTree.visible());
    for (const tab of RENDER_TABS) {
        // No longer the picture the panel describes. Dropped rather than
        // re-rendered: a tab nobody is looking at is rendered when it is opened,
        // which is the rule every other tab of this panel keeps.
        requested.delete(tab);
        awaiting.delete(tab);
    }
    const open = tabs.current === 'design' ? designTabs.current : undefined;
    if (open === undefined || !isRenderTab(open)) {
        return;
    }
    const pending = settling[open];
    if (pending !== undefined) {
        clearTimeout(pending);
    }
    settling[open] = setTimeout(() => {
        delete settling[open];
        if (tabs.current === 'design' && designTabs.current === open) {
            renderTab(open);
        }
    }, SELECTION_SETTLE_MS);
}

/**
 * The file types each drawing package renders to, once it has been asked.
 *
 * Kept across shows: it is what the package declares, not anything about the
 * object on screen, and asking means loading the package - from the network,
 * the first time.
 */
const draftFormats = new Map<string, RenderFormat[]>();

/** The 'fetchFormats' the Draft tab is waiting for. */
let awaitingFormats: number | undefined;

// What the 3D view is showing, as a tree of items to switch on and off. It lives
// beside the canvas rather than over it, with the Metadata and Animate boxes and
// the Opacity slider under it: all of them say what is drawn, so all of them are
// one pane.
const objectTree = new Tree(
    byId('tree'),
    () => onBoxChanged(),
    // Pointing at a part or a sub-assembly flickers it, which is the one thing that
    // says "this row is that shape" without moving the camera.
    (items) => scene?.flicker(items),
    { selection },
);

// What a shape's metadata says about its elements - the angle and direction of a
// sheet metal bend, written against its line - pinned to them as callouts. On by
// default: it is information the geometry cannot show. The box is offered only
// while the model on screen has something to pin (see 'offerMetadata'), and its
// state is kept across shows, so switching it off stays off for the next object.
const metadataControl = document.getElementById('metadata-control') as HTMLElement | null;
const metadataCheckbox = document.getElementById('metadata-checkbox') as HTMLInputElement;
if (metadataCheckbox) {
    metadataCheckbox.addEventListener('change', (event) => {
        scene?.setShowMetadata((event.target as HTMLInputElement).checked);
    });
}

// Initialize animation checkbox
const animateCheckbox = document.getElementById('animate-checkbox') as HTMLInputElement;
if (animateCheckbox) {
    animateCheckbox.addEventListener('change', (event) => {
        scene?.setAutoRotate((event.target as HTMLInputElement).checked);
    });
}

// Initialize opacity slider
const opacitySlider = document.getElementById('opacity-slider') as HTMLInputElement;
const opacityValue = document.getElementById('opacity-value') as HTMLSpanElement;
if (opacitySlider && opacityValue) {
    opacitySlider.addEventListener('input', (event) => {
        const value = parseInt((event.target as HTMLInputElement).value, 10);
        const opacity = value / 100;
        scene?.setOpacity(opacity);
        opacityValue.textContent = `${value}%`;
    });
}

/** Offer the Metadata box when, and only when, the object on screen has callouts. */
function offerMetadata(object: ShowMessage['object'] | undefined): void {
    if (metadataControl) {
        metadataControl.hidden = !hasCallouts(object);
    }
}

/** What the panel is showing, or undefined when it is empty. */
let shown: ShowMessage | undefined;

/** Which show call is current. Prevents stale geometry loads from overwriting newer tab state. */
let generation = 0;

/**
 * Which request each tab is waiting for, and the counter the tokens come from.
 *
 * A daemon round trip outlives a change of selection easily - a bill of
 * materials walks the whole assembly tree, a supply quote goes out to the
 * network, and an analysis runs a solver - so every request carries a token of
 * its own and an answer whose token is no longer the one this tab is waiting for
 * is dropped rather than painted over what is now on screen. The same reason
 * 'scene.ts' keeps a generation of its own.
 *
 * A token per *request* rather than per object, because the two analysis tabs
 * are asked more than once for the same object: a user who runs FEA, retypes the
 * implementation and runs it again has two solvers in flight over one part, and
 * the first to finish is not the one they asked last.
 */
let lastToken = 0;
const awaiting = new Map<TabId, number>();

/** The tabs already asked for, for the object now on screen. */
const requested = new Set<TabId>();

/** Ask the host to fill a tab in, and remember which answer to accept. */
function request(tab: TabId, extra: Omit<FetchTabMessage, 'type' | 'tab' | 'token'> = {}): void {
    lastToken += 1;
    awaiting.set(tab, lastToken);
    fetchTab({ type: 'fetchTab', tab, token: lastToken, ...extra });
}

/**
 * What the object on screen is made of and what the user chose for it, once the
 * daemon has said: what the Build and Buy tabs are enabled by. 'failed' when it
 * could not say - a daemon too old to have been asked - which leaves Buy enabled
 * as it always was and Build, which needs the same daemon, disabled.
 */
let manufacturing: { data: BvbData; result: BvbResult } | 'failed' | undefined;

/** The thumbnails and measurements still to ask for, and the batch in flight. */
let detailsQueue: { name: string; kind: string }[] = [];
let detailsToken: number | undefined;

/** How many objects one 'fetchDetails' asks about. The daemon answers one request at a time, so the table fills in steps rather than all at the end, and other tabs get a turn in between. */
const DETAILS_BATCH = 6;

/** Which half of the Build tab is in flight: the plan, or the pages. */
let buildPhase: 'plan' | 'document' = 'plan';

function byId(id: string): HTMLElement {
    return document.getElementById(id) as HTMLElement;
}

/**
 * Empty a pane and take back the class its last contents put on it.
 *
 * Each pane is styled by whatever drew into it - 'sheet' for a table, 'document'
 * for the paged instructions - so a pane reused for something else has to start
 * from the bare '.pane' it was written as.
 */
function reset(tab: TabId): HTMLElement {
    const pane = panes[tab];
    empty(pane);
    pane.className = 'pane';
    return pane;
}

/**
 * The panel's own strip for an object: the three groups, each enabled while any
 * of its tabs is.
 */
function tabsFor(message: ShowMessage | undefined): TabSpec[] {
    return [
        { id: 'design', label: 'Design', pane: panes.design },
        {
            id: 'analysis',
            label: 'Analysis',
            pane: panes.analysis,
            disabled: !Tabs.anyEnabled(analysisTabsFor(message)),
            hint: 'No engineering analysis configurations are defined for this object',
        },
        {
            id: 'manufacturing',
            label: 'Manufacturing',
            pane: panes.manufacturing,
            disabled: !Tabs.anyEnabled(manufacturingTabsFor(message)),
            hint: 'No manufacturing or procurement instructions are provided for this object',
        },
        // Placeholders for the groups to come: in the strip so that its shape is
        // the one it will keep, disabled because they hold no tabs yet.
        {
            id: 'validation',
            label: 'Validation',
            pane: panes.validation,
            disabled: true,
            hint: 'No validation instructions are provided for this object',
        },
        {
            id: 'operations',
            label: 'Operations',
            pane: panes.operations,
            disabled: true,
            hint: 'No operations data is collected for this object',
        },
    ];
}

/**
 * Analysis: FEA and CFD, both always shown, enabled for a part.
 *
 * Everything but the 3D view is a question put to the daemon about
 * '<package>:<name>', so an object whose package the sender did not tell us
 * about - a shape shown from a script, or a 'partcad' older than the field -
 * gets none of them rather than tabs that could only fail.
 *
 * Only a part is analysed. An assembly is a set of parts that each have boundary
 * conditions of their own, and a load on the whole of one says nothing about
 * which member carries it - so 'pc cae' takes a part, and so does this. Both are
 * enabled whether or not the part declares 'fea:'/'cfd:', because "this part
 * says nothing about FEA" is the answer somebody looking for the tab came to
 * read.
 */
function analysisTabsFor(message: ShowMessage | undefined): TabSpec[] {
    const analysed = Boolean(message?.package) && message?.kind === 'part';
    return [
        { id: 'fea', label: 'FEA', pane: panes.fea, disabled: !analysed },
        { id: 'cfd', label: 'CFD', pane: panes.cfd, disabled: !analysed },
    ];
}

/**
 * Manufacturing: what is built and what is bought, how to build it, what it is
 * made of, where to buy it and how it goes together - all five always shown,
 * and enabled for the two things that are made and bought, a part and an
 * assembly.
 *
 * A scene is where things are placed rather than a thing anybody builds or
 * orders, and a sketch and an interface are things to build with - so for those
 * three the whole group is disabled.
 *
 * Build and Buy are enabled by what the user chose on Build vs Buy: Build while
 * something needed is built, Buy while something needed is bought. Until the
 * daemon has said what the object is made of, neither is known, and both say
 * so. Build vs Buy itself is 'secondary' for a part that is one line - a part
 * with no stock - because a table of one line is not what somebody opening the
 * group came for; it is there to be clicked, and is not opened for them.
 * Assembly is the assembly instructions, which only an assembly has.
 */
function manufacturingTabsFor(message: ShowMessage | undefined): TabSpec[] {
    const known = Boolean(message?.package);
    const kind = message?.kind;
    const made = known && (kind === 'assembly' || kind === 'part');
    const state = message === undefined ? undefined : manufacturing;
    const pending = made && state === undefined;
    const working = 'Working out what is built and what is bought…';
    const result = state === undefined || state === 'failed' ? undefined : state.result;
    return [
        {
            id: 'bvb',
            label: 'Build vs Buy',
            pane: panes.bvb,
            disabled: !made,
            secondary: kind === 'part' && result !== undefined && visibleRows(result).length < 2,
        },
        {
            id: 'build',
            label: 'Build',
            pane: panes.build,
            disabled: !made || result === undefined || !result.anyBuild,
            hint: pending
                ? working
                : state === 'failed'
                  ? 'PartCAD could not say how this is made'
                  : 'Nothing is built: everything here is bought (see Build vs Buy)',
        },
        {
            id: 'bom',
            label: 'Bill of Materials',
            pane: panes.bom,
            disabled: !made,
        },
        {
            id: 'supply',
            label: 'Buy',
            pane: panes.supply,
            disabled: !made || pending || (result !== undefined && !result.anyBuy),
            hint: pending ? working : 'Nothing is bought: everything here is built (see Build vs Buy)',
        },
        {
            id: 'assembly',
            label: 'Assembly',
            pane: panes.assembly,
            disabled: !(known && kind === 'assembly'),
            hint: 'Only an assembly has assembly instructions',
        },
    ];
}

/** Rebuild every strip for an object: each group's own first, then the panel's. */
function setAllTabs(message: ShowMessage | undefined): void {
    // The groups' strips first, so that the panel's, opening a group, finds the
    // tab under it already chosen.
    designTabs.setTabs(designTabsFor(message));
    analysisTabs.setTabs(analysisTabsFor(message));
    manufacturingTabs.setTabs(manufacturingTabsFor(message));
    tabs.setTabs(tabsFor(message));
}

/**
 * The Design tab's own tabs for an object: all three always shown, 3D always
 * enabled - it is what an empty panel opens on too.
 *
 * 2D is anything PartCAD can render to a picture: a part, an assembly, a scene
 * or a sketch - not an interface, which is ports rather than a shape. Draft is a
 * dimensioned drawing, which is made of a solid: a part or an assembly. Both are
 * a render the daemon makes of '<package>:<name>', so an object with no package
 * gets neither.
 */
function designTabsFor(message: ShowMessage | undefined): TabSpec[] {
    const known = Boolean(message?.package);
    const kind = message?.kind ?? '';
    return [
        { id: '3d', label: '3D', pane: panes['3d'] },
        {
            id: '2d',
            label: '2D',
            pane: panes['2d'],
            disabled: !(known && ['part', 'assembly', 'scene', 'sketch'].includes(kind)),
        },
        {
            id: 'draft',
            label: 'Draft',
            pane: panes.draft,
            disabled: !(known && (kind === 'part' || kind === 'assembly')),
        },
    ];
}

/**
 * The 3D view's control pane - what is on screen and how it is drawn - only
 * while something is: with nothing shown it would be an empty list and controls
 * for a model that is not there.
 */
const controlPane = document.querySelector('.pane-3d > .controls') as HTMLElement | null;

function offerControls(shown: boolean): void {
    if (controlPane !== null) {
        controlPane.hidden = !shown;
    }
}

/** Take back what the render tabs showed for the previous object. */
function resetRenderTabs(text: string): void {
    for (const tab of RENDER_TABS) {
        renderViews[tab]?.setBusy(text);
    }
}

async function show(message: ShowMessage): Promise<void> {
    const mine = (generation += 1);
    shown = message;
    // Nothing in flight belongs to this object, whatever it was asked for.
    awaiting.clear();
    requested.clear();
    for (const tab of DATA_TABS) {
        reset(tab);
    }
    for (const tab of ANALYSIS_TABS) {
        caeViews[tab]?.setBusy('Select this tab to run the analysis.');
    }
    resetRenderTabs('Select this tab to render it.');
    resetManufacturing('Asking PartCAD what this is made of…');
    // Asked for now, whichever tab is open: which Manufacturing tabs apply
    // depends on the answer. No geometry is built for it.
    if (message.package && (message.kind === 'part' || message.kind === 'assembly')) {
        requested.add('bvb');
        request('bvb');
    }

    // Set up viewer configuration on the window object for access by scene.ts
    if (message.config) {
        (window as any).partcadConfig = message.config;
        if (message.config?.viewer?.performanceDebug) {
            console.log('[PartCAD Viewer] Config set:', message.config);
        }
    }

    // The pane first, and the visibility it asks for with it: an item that starts
    // out unticked - the ports of everything inside an assembly - must not be
    // drawn even for the one frame between the geometry arriving and the pane
    // being built.
    //
    // What the user had switched off is kept when the camera is: both mean "the
    // same object again", which is what a save and a re-render produce, and
    // losing a selection to one is as unwelcome as losing the camera.
    if (!message.keepCamera) {
        // A different object: what was ticked about the last one says nothing
        // about this one. Kept when the camera is, which is the same question -
        // "is this the same object again" - and a save and a re-render are.
        selection.clear();
    }
    if (message.object === null) {
        objectTree.clear();
        for (const tab of RENDER_TABS) {
            renderTrees[tab]?.clear();
            renderViews[tab]?.offerControls(false);
        }
    } else {
        objectTree.setObject(message.object);
        // The same object and the same selection, listed again for each pane.
        for (const tab of RENDER_TABS) {
            renderTrees[tab]?.setObject(message.object);
            renderViews[tab]?.offerControls(true);
        }
    }
    offerMetadata(message.object);
    offerControls(true);

    // Without a 3D view the geometry has nowhere to go, but the object still has
    // every other tab.
    const view = await sceneLoaded;
    if (generation !== mine) {
        return;
    }
    if (view !== undefined) {
        view.showItems(objectTree.visible());
        await view.showGeometry(message);
        // Newer show arrived while this one was loading; abandon it.
        if (generation !== mine) {
            return;
        }
        // Apply current opacity slider value to newly loaded geometry
        if (opacitySlider) {
            const opacity = parseInt(opacitySlider.value, 10) / 100;
            view.setOpacity(opacity);
        }
    }
    // Rebuilt on every show, which also re-asks for whatever tab the user is on:
    // the object may be the same one after an edit, and its answers may not be.
    setAllTabs(message);
}

function clear(): void {
    generation += 1;
    shown = undefined;
    awaiting.clear();
    requested.clear();
    scene?.clearGeometry();
    objectTree.clear();
    for (const tab of RENDER_TABS) {
        renderTrees[tab]?.clear();
        renderViews[tab]?.offerControls(false);
    }
    offerMetadata(undefined);
    offerControls(false);
    for (const tab of DATA_TABS) {
        reset(tab);
    }
    for (const tab of ANALYSIS_TABS) {
        caeViews[tab]?.setBusy('Nothing to analyse.');
    }
    resetRenderTabs('Nothing to render.');
    resetManufacturing('Nothing to show.');
    setAllTabs(undefined);
}

/** Take back what the Manufacturing tabs that own their panes showed for the previous object. */
function resetManufacturing(text: string): void {
    manufacturing = undefined;
    detailsQueue = [];
    detailsToken = undefined;
    bvbView.setBusy(text);
    buildView.forget();
    buildView.setBusy('Select this tab to see how this is built.');
    assemblyView.setManufacturable(undefined);
    assemblyView.setBusy('Select this tab to write the assembly instructions.');
}

/** The choices on screen: what the Build and Assembly tabs are asked with. */
function currentChoices(): Choices {
    return manufacturing !== undefined && manufacturing !== 'failed' ? manufacturing.data.choices : {};
}

/**
 * The user moved a switch on Build vs Buy.
 *
 * Kept on this machine by the host. What the Build and Assembly tabs showed is
 * no longer the plan, so both are asked again when next looked at - neither is
 * on screen while a switch on Build vs Buy is being moved - and the strip is
 * rebuilt, since what is built and what is bought decides what it offers.
 */
function onChoicesChanged(choices: Choices): void {
    if (manufacturing === undefined || manufacturing === 'failed' || shown === undefined) {
        return;
    }
    const result = bvbView.current;
    manufacturing = { data: { ...manufacturing.data, choices }, result: result ?? manufacturing.result };
    saveChoices({ type: 'saveChoices', object: manufacturing.data.object, choices });
    for (const tab of ['build', 'assembly'] as TabId[]) {
        requested.delete(tab);
        awaiting.delete(tab);
    }
    buildView.setBusy('Select this tab to see how this is built.');
    assemblyView.setBusy('Select this tab to write the assembly instructions.');
    manufacturingTabs.setTabs(manufacturingTabsFor(shown), { keepCurrent: true });
}

/** Queue thumbnails and measurements to ask for, a few at a time. */
function requestDetails(objects: { name: string; kind: string }[]): void {
    detailsQueue.push(...objects);
    pumpDetails();
}

function pumpDetails(): void {
    // Only while the table is on screen. The tree is asked for on every show,
    // since the strip needs it, but the pictures are a projection per line - an
    // assembly selected only to be turned in 3D would otherwise queue one for
    // each of its parts ahead of every other tab's request.
    const onScreen = tabs.current === 'manufacturing' && manufacturingTabs.current === 'bvb';
    if (!onScreen || detailsToken !== undefined || detailsQueue.length === 0) {
        return;
    }
    const batch = detailsQueue.splice(0, DETAILS_BATCH);
    lastToken += 1;
    detailsToken = lastToken;
    fetchDetails({
        type: 'fetchDetails',
        token: lastToken,
        objects: batch,
        width: THUMBNAIL_SIZE,
        height: THUMBNAIL_SIZE,
    });
}

function onDetails(message: DetailsMessage): void {
    if (message.token !== detailsToken) {
        return;
    }
    detailsToken = undefined;
    if (message.items !== undefined) {
        bvbView.setDetails(message.items);
    } else if (message.error !== undefined) {
        reportError(`failed to fetch the Build vs Buy details: ${message.error}`);
    }
    pumpDetails();
}

/** Ask for the Build tab's plan, and then for its pages. */
function requestPlan(): void {
    if (shown === undefined) {
        return;
    }
    requested.add('build');
    buildPhase = 'plan';
    buildView.setBusy('Working out the order things are made in…');
    request('build', { choices: currentChoices(), recursive: buildView.recursive, document: false });
}

/** Ask for the assembly instructions, as the Assembly tab is set. */
function requestGuide(): void {
    if (shown === undefined) {
        return;
    }
    requested.add('assembly');
    assemblyView.setBusy('Writing the assembly instructions… The first time takes a while: every step is drawn.');
    request('assembly', {
        choices: currentChoices(),
        recursive: assemblyView.recursive,
        buildParts: assemblyView.buildParts,
        format: assemblyView.format,
    });
}

/** Ask for an analysis again, with whatever implementation was typed in. */
function runAnalysis(tab: TabId, implementation: string): void {
    requested.add(tab);
    caeViews[tab]?.setBusy('Running the analysis…');
    request(tab, { implementation: implementation || undefined });
}

/**
 * Render the object to the file type a render tab has chosen.
 *
 * Again on every change of it, and never from a cache: a render is the object as
 * it is now, and the host keeps only the file on screen - which is the one Save
 * saves.
 */
function renderTab(tab: TabId): void {
    const view = renderViews[tab];
    if (view === undefined || shown === undefined) {
        return;
    }
    requested.add(tab);
    const format = view.format;
    if (format === undefined) {
        return;
    }
    // What the boxes beside the drawing ask for: which links to keep, and - on
    // the 2D tab, whose rows include the ports and the interfaces - which of
    // those to draw on top of the projection.
    const tree = renderTrees[tab];
    const filter = tree?.filter();
    if (filterIsEmpty(filter)) {
        // Every part has been unticked. There is no picture of that, and the
        // filter language has no way to ask for one either (an empty mask reads
        // as "everything"), so it is said here rather than sent.
        view.setBusy('Nothing is selected. Tick something on the left to render it.');
        awaiting.delete(tab);
        return;
    }
    const overlay = tree?.overlay();
    view.setBusy(
        tab === 'draft'
            ? 'Drawing… The first drawing can take a few minutes, while PartCAD installs what makes it.'
            : 'Rendering…',
    );
    request(tab, {
        format,
        plugin: tab === 'draft' ? view.plugin : undefined,
        filter,
        withPorts: overlay?.ports,
        withInterfaces: overlay?.interfaces,
        withInternals: overlay?.internals,
        // The ports themselves, so the picture draws the ones the panel says and
        // no others. Left out when the panel lists none - the Draft tab - so
        // that nothing narrows an overlay a file type asked for itself.
        ports: overlay !== undefined && overlay.select.length > 0 ? overlay.select : undefined,
    });
}

/**
 * Start the Draft tab: learn what the chosen package draws, then draw.
 *
 * What a drawing package offers is whatever its 'render:' section declares, so
 * the list is asked for rather than written here - once per package.
 */
function startDraft(): void {
    const view = renderViews.draft;
    const plugin = view?.plugin;
    if (view === undefined || plugin === undefined) {
        return;
    }
    requested.add('draft');
    awaiting.delete('draft');
    const known = draftFormats.get(plugin);
    if (known !== undefined) {
        view.setFormats(choicesOf(known), PREFERRED_DRAFT_FORMATS);
        renderTab('draft');
        return;
    }
    view.setFormats([]);
    view.setBusy(`Asking ${plugin} what it can draw…`);
    lastToken += 1;
    awaitingFormats = lastToken;
    fetchFormats({ type: 'fetchFormats', token: lastToken, plugin });
}

function onFormats(message: FormatsMessage): void {
    if (message.token !== awaitingFormats) {
        return;
    }
    awaitingFormats = undefined;
    const view = renderViews.draft;
    if (view === undefined || view.plugin !== message.plugin) {
        return;
    }
    if (message.error !== undefined || message.formats === undefined) {
        view.showError(message.error ?? `${message.plugin} said nothing about what it can draw.`);
        return;
    }
    if (message.formats.length === 0) {
        view.showError(`${message.plugin} does not draw anything: its 'render:' section is empty.`);
        return;
    }
    draftFormats.set(message.plugin, message.formats);
    view.setFormats(choicesOf(message.formats), PREFERRED_DRAFT_FORMATS);
    renderTab('draft');
}

function choicesOf(formats: RenderFormat[]): Choice[] {
    return formats.map((format) => ({
        value: format.name,
        label: format.name.toUpperCase(),
        title: format.desc ?? undefined,
    }));
}

/** The panel's strip opened a group: open whichever of its tabs it is on. */
function onTabSelected(tab: TabId): void {
    const inner = groups[tab]?.current;
    if (inner !== undefined) {
        onLeafSelected(inner);
    }
}

/**
 * A group's strip opened one of its tabs.
 *
 * A group's strip is rebuilt while another group may be the one on screen, and
 * nothing is fetched for a tab nobody can see.
 */
function onInnerSelected(group: TabId, tab: TabId): void {
    if (tabs.current === group) {
        onLeafSelected(tab);
    }
}

/** A tab with contents came on screen: draw it, asking for it if need be. */
function onLeafSelected(tab: TabId): void {
    if (tab === '3d') {
        // The canvas had no size at all while the tab was hidden, and a WebGL
        // renderer does not find out on its own that it has one again.
        scene?.resizeCanvas();
        return;
    }
    if (isAnalysisTab(tab)) {
        // Same reason as the 3D view: a result mesh is drawn on a canvas that
        // had no size while its tab was hidden.
        caeViews[tab]?.resize();
    }
    if (tab === 'bvb') {
        // The table's pictures waited for it to be looked at (see 'pumpDetails').
        pumpDetails();
    }
    if (requested.has(tab)) {
        return;
    }
    if (tab === 'draft') {
        startDraft();
        return;
    }
    if (tab === 'build') {
        requestPlan();
        return;
    }
    if (tab === 'assembly') {
        requestGuide();
        return;
    }
    if (tab === 'bvb') {
        requested.add('bvb');
        bvbView.setBusy('Asking PartCAD what this is made of…');
        request('bvb');
        return;
    }
    if (isRenderTab(tab)) {
        renderTab(tab);
        return;
    }
    requested.add(tab);
    if (isAnalysisTab(tab)) {
        // An analysis is not a lookup - a solver runs for as long as it runs -
        // so the pane says what is happening rather than going blank.
        caeViews[tab]?.setBusy('Running the analysis…');
    } else {
        reset(tab).appendChild(placeholder('Asking PartCAD…'));
    }
    request(tab);
}

function onTabData(
    tab: TabId,
    token: number,
    data: unknown,
    error: string | undefined,
    implementation: string | undefined,
): void {
    if (awaiting.get(tab) !== token) {
        // For an object that is no longer on screen, or for a run this tab has
        // since been asked to replace.
        return;
    }
    awaiting.delete(tab);

    if (isRenderTab(tab)) {
        const view = renderViews[tab];
        if (error !== undefined) {
            view?.showError(error);
        } else if (data === null || data === undefined) {
            view?.showError('PartCAD rendered nothing.');
        } else {
            try {
                view?.show(data as RenderData);
            } catch (e: unknown) {
                view?.showError(`Failed to display this: ${e}`);
                reportError(`failed to render the '${tab}' tab: ${e}`);
            }
        }
        return;
    }

    if (tab === 'bvb') {
        onBvb(data as BvbData | undefined, error);
        return;
    }
    if (tab === 'build') {
        onPlan(data as PlanData | undefined, error);
        return;
    }
    if (tab === 'assembly') {
        if (error !== undefined) {
            assemblyView.showError(error);
        } else if (data === null || data === undefined) {
            assemblyView.showError('PartCAD wrote no assembly instructions.');
        } else {
            try {
                assemblyView.show(data as GuideData);
            } catch (e: unknown) {
                assemblyView.showError(`Failed to display this: ${e}`);
                reportError(`failed to render the 'assembly' tab: ${e}`);
            }
        }
        return;
    }

    if (isAnalysisTab(tab)) {
        // The analysis panes are not rebuilt: they own a field the user types
        // into, and 'reset()' would take it away mid-sentence.
        const view = caeViews[tab];
        view?.suggest(implementation);
        if (error !== undefined) {
            view?.showError(error);
        } else if (data === null || data === undefined) {
            view?.showError('PartCAD had nothing to say about this.');
        } else {
            try {
                view?.render(data as CaeData);
            } catch (e: unknown) {
                view?.showError(`Failed to display this: ${e}`);
                reportError(`failed to render the '${tab}' tab: ${e}`);
            }
        }
        return;
    }

    const pane = reset(tab);

    if (error !== undefined) {
        // Not every refusal is a failure: asking for the instructions of an
        // assembly that has no assembly steps is answered with why, and that is
        // what the reader needs to see.
        pane.appendChild(el('p', 'error', error));
        return;
    }
    if (data === null || data === undefined) {
        pane.appendChild(placeholder('PartCAD had nothing to say about this.'));
        return;
    }

    try {
        render(tab, pane, data);
    } catch (e: unknown) {
        empty(pane);
        pane.appendChild(el('p', 'error', `Failed to display this: ${e}`));
        reportError(`failed to render the '${tab}' tab: ${e}`);
    }
}

/**
 * What the object is made of has arrived: draw the table, and rebuild the strip
 * it decides.
 *
 * Not with 'keepCurrent': this is the first the strip learns about the object,
 * and Build vs Buy of a part with nothing under it is not a tab to be left on.
 */
function onBvb(data: BvbData | undefined, error: string | undefined): void {
    if (error !== undefined || data === undefined || data === null) {
        manufacturing = 'failed';
        bvbView.showError(error ?? 'PartCAD had nothing to say about what this is made of.');
    } else {
        try {
            data.choices = data.choices ?? {};
            const result = bvbView.render(data);
            manufacturing = { data, result };
            // Known as soon as the tree is, which is long before the
            // instructions are written: the Assembly tab says so up front.
            assemblyView.setManufacturable(data.tree.manufacturable);
        } catch (e: unknown) {
            manufacturing = 'failed';
            bvbView.showError(`Failed to display this: ${e}`);
            reportError(`failed to render the 'bvb' tab: ${e}`);
        }
    }
    if (shown !== undefined) {
        manufacturingTabs.setTabs(manufacturingTabsFor(shown));
    }
}

/** The Build tab's plan, or its pages: the plan is drawn, and the pages asked for after it. */
function onPlan(data: PlanData | undefined, error: string | undefined): void {
    const phase = buildPhase;
    if (error !== undefined || data === undefined || data === null) {
        const message = error ?? 'PartCAD had nothing to say about how this is built.';
        if (phase === 'plan') {
            buildView.showError(message);
        } else {
            buildView.showDocumentError(message);
        }
        return;
    }
    if (phase === 'plan') {
        buildView.showPlan(data);
        buildPhase = 'document';
        request('build', { choices: currentChoices(), recursive: buildView.recursive, document: true });
        return;
    }
    buildView.showDocument(data);
}

function render(tab: TabId, pane: HTMLElement, data: unknown): void {
    switch (tab) {
        case 'bom':
            renderBom(pane, data as BomData);
            return;
        case 'supply':
            supplyView.render(data as SupplyData, shown?.kind ?? null);
            return;
        default:
            return;
    }
}

window.addEventListener('message', (event: MessageEvent<HostMessage>) => {
    const message = event.data;
    if (message.type === 'clear') {
        clear();
    } else if (message.type === 'show') {
        show(message);
    } else if (message.type === 'tabData') {
        onTabData(message.tab, message.token, message.data, message.error, message.implementation);
    } else if (message.type === 'formats') {
        onFormats(message);
    } else if (message.type === 'details') {
        onDetails(message);
    } else if (message.type === 'spaceMouseState') {
        if (scene !== undefined) {
            scene.spaceMouse.settings = message.settings;
            scene.spaceMouse.active = message.active;
            scene.spaceMouse.spacenavd = message.spacenavd;
            scene.spaceMouse.spacenavdDevice = message.spacenavdDevice;
        }
    } else if (message.type === 'spaceMouseEvent') {
        if (message.motion !== undefined) {
            scene?.spaceMouse.spacenavMotion(message.motion, performance.now());
        } else if (message.button !== undefined) {
            scene?.spaceMouse.spacenavButton(message.button, message.pressed === true);
        }
    } else if (message.type === 'updateConfig') {
        (window as any).partcadConfig = message.config;
        if (!message.config?.viewer?.performanceDebug) {
            // Clear diagnostic state when disabled
            delete (window as any).pcNodeTriangleCounts;
            const statsDisplay = (window as any).pcViewerStats?.statsDisplay;
            if (statsDisplay) {
                statsDisplay.remove();
                (window as any).pcViewerStats.statsDisplay = null;
            }
        }
    }
});

window.addEventListener('keydown', (event: KeyboardEvent) => {
    // The instructions are pages to flip through, and the arrow keys are how a
    // reader flips them. Only while that tab is the one on screen: the same keys
    // orbit the camera on the 3D one.
    if (
        tabs.current === 'manufacturing' &&
        manufacturingTabs.current === 'assembly' &&
        assemblyView.handleKey(event.key)
    ) {
        event.preventDefault();
    }
});

setAllTabs(undefined);
ready();
