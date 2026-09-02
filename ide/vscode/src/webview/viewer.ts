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
//     3D  |  Bill of Materials  |  Instructions  |  Supply
//
// Which of them exist depends on what is being shown - see 'tabsFor()' - and the
// 3D view is always the first, because that is what "show this part" means.
//
// This file is the shell: it owns the tab strip and the panes, routes what the
// extension host posts in, and asks for the contents of a tab the first time it
// is looked at. Each pane draws itself ('scene.ts', 'bom.ts', 'document.ts',
// 'supply.ts'); none of them talks to the host directly.
//
// Everything but the 3D view is answered by the PartCAD daemon, which this
// renderer cannot reach: the panel's CSP forbids every network request, and the
// daemon is behind the extension host's JSON-RPC connection anyway. So a pane's
// contents are asked for ('fetchTab') and delivered ('tabData'), never fetched.
//

import { renderBom } from './bom';
import { DocumentView } from './document';
import { el, empty, placeholder } from './dom';
import { fetchTab, ready, reportError } from './host';
import { BomData, CamData, GuideData, HostMessage, ShowMessage, SupplyData, TabId } from './messages';
import { ModelView, base64ToArrayBuffer } from './model';
import { clearGeometry, resizeCanvas, showGeometry } from './scene';
import { SupplyView } from './supply';
import { TabSpec, Tabs } from './tabs';

const panes: Record<TabId, HTMLElement> = {
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '3d': byId('pane-3d'),
    bom: byId('pane-bom'),
    instructions: byId('pane-instructions'),
    cam: byId('pane-cam'),
    supply: byId('pane-supply'),
};

const supplyView = new SupplyView(panes.supply);
// Built on first use: a WebGL context is not something to hold open for a tab
// most objects never have.
let camView: ModelView | undefined;
const tabs = new Tabs(byId('tabs'), onTabSelected);

/** What the panel is showing, or undefined when it is empty. */
let shown: ShowMessage | undefined;

/**
 * Which object the panes belong to.
 *
 * A daemon round trip outlives a change of selection easily - a bill of
 * materials walks the whole assembly tree, a supply quote goes out to the
 * network - so every request carries the generation it was made for and an
 * answer for an older one is dropped rather than painted over what is now on
 * screen. The same reason 'scene.ts' keeps a generation of its own.
 */
let generation = 0;

/** The tabs already asked for, for the current generation. */
const requested = new Set<TabId>();

/** The instructions, once they have arrived: it owns the paging. */
let instructions: DocumentView | undefined;

/**
 * What this object's CAM visualization is written as, once the host has said.
 *
 * Undefined until the answer arrives and null when there is none, and those are
 * not the same: the tab is offered only for the first.
 */
let camVisual: string | null | undefined;

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
 * The tabs an object gets.
 *
 * Everything but the 3D view is a question put to the daemon about
 * '<package>:<name>', so an object whose package the sender did not tell us
 * about - a shape shown from a script, or a 'partcad' older than the field -
 * gets the 3D view alone rather than tabs that could only fail.
 */
function tabsFor(message: ShowMessage): TabSpec[] {
    const specs: TabSpec[] = [{ id: '3d', label: '3D', pane: panes['3d'] }];
    if (!message.package) {
        return specs;
    }
    if (message.kind === 'assembly' || message.kind === 'scene') {
        specs.push({ id: 'bom', label: 'Bill of Materials', pane: panes.bom });
    }
    if (message.kind === 'assembly') {
        // Instructions are the steps that put an assembly together, and a scene
        // says only where things ended up - deliberately, so it has no steps to
        // show. See 'partcad.scene'.
        specs.push({ id: 'instructions', label: 'Instructions', pane: panes.instructions });
    }
    if (camVisual) {
        // Only where the object's package declares a 'cam:' file type whose
        // implementation can draw what it writes. Most packages declare none,
        // and a tab that could only ever say so is worse than no tab.
        specs.push({ id: 'cam', label: 'CAM', pane: panes.cam });
    }
    specs.push({ id: 'supply', label: 'Supply', pane: panes.supply });
    return specs;
}

function show(message: ShowMessage): void {
    shown = message;
    generation += 1;
    requested.clear();
    instructions = undefined;
    camVisual = undefined;
    camView?.dispose();
    for (const tab of ['bom', 'instructions', 'cam', 'supply'] as TabId[]) {
        reset(tab);
    }

    void showGeometry(message);
    // Rebuilt on every show, which also re-asks for whatever tab the user is on:
    // the object may be the same one after an edit, and its answers may not be.
    tabs.setTabs(tabsFor(message));
}

function clear(): void {
    shown = undefined;
    generation += 1;
    requested.clear();
    instructions = undefined;
    camVisual = undefined;
    camView?.dispose();
    clearGeometry();
    for (const tab of ['bom', 'instructions', 'cam', 'supply'] as TabId[]) {
        reset(tab);
    }
    tabs.setTabs([{ id: '3d', label: '3D', pane: panes['3d'] }]);
}

function onTabSelected(tab: TabId): void {
    if (tab === '3d') {
        // The canvas had no size at all while the tab was hidden, and a WebGL
        // renderer does not find out on its own that it has one again.
        resizeCanvas();
        return;
    }
    if (requested.has(tab)) {
        // Same for the CAM canvas, which is a second WebGL context of its own.
        if (tab === 'cam') {
            camView?.resize();
        }
        return;
    }
    requested.add(tab);
    reset(tab).appendChild(placeholder('Asking PartCAD…'));
    fetchTab({ type: 'fetchTab', tab, token: generation });
}

function onTabData(tab: TabId, token: number, data: unknown, error: string | undefined): void {
    if (token !== generation) {
        // For an object that is no longer on screen.
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

function render(tab: TabId, pane: HTMLElement, data: unknown): void {
    switch (tab) {
        case 'bom':
            renderBom(pane, data as BomData);
            return;
        case 'instructions':
            instructions = new DocumentView(pane, (data as GuideData).document);
            return;
        case 'cam':
            renderCam(pane, data as CamData);
            return;
        case 'supply':
            supplyView.render(data as SupplyData, shown?.kind ?? null);
            return;
        default:
            return;
    }
}

/**
 * Draw the CAM model, and say what it is.
 *
 * A caption, because what is on screen is easy to mistake for the part: it is
 * what the machine will actually lay down or take away, which is a different
 * shape and the reason for looking at it.
 */
function renderCam(pane: HTMLElement, data: CamData): void {
    pane.className = 'pane pane-cam';
    const caption = el('p', 'caption', 'What the manufacturing instructions produce, not the part itself.');
    pane.appendChild(caption);
    if (camView === undefined) {
        camView = new ModelView();
    }
    pane.appendChild(camView.element);
    void camView.show(base64ToArrayBuffer(data.gltf));
}

function onTabs(token: number, cam: string | null): void {
    if (token !== generation || shown === undefined) {
        return;
    }
    camVisual = cam;
    tabs.setTabs(tabsFor(shown));
}

window.addEventListener('message', (event: MessageEvent<HostMessage>) => {
    const message = event.data;
    if (message.type === 'clear') {
        clear();
    } else if (message.type === 'show') {
        show(message);
    } else if (message.type === 'tabData') {
        onTabData(message.tab, message.token, message.data, message.error);
    } else if (message.type === 'tabs') {
        onTabs(message.token, message.cam);
    }
});

window.addEventListener('keydown', (event: KeyboardEvent) => {
    // The instructions are pages to flip through, and the arrow keys are how a
    // reader flips them. Only while that tab is the one on screen: the same keys
    // orbit the camera on the 3D one.
    if (tabs.current === 'instructions' && instructions?.handleKey(event.key)) {
        event.preventDefault();
    }
});

tabs.setTabs([{ id: '3d', label: '3D', pane: panes['3d'] }]);
ready();
