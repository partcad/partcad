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
import { CaeView } from './cae';
import { DocumentView } from './document';
import { el, empty, placeholder } from './dom';
import { fetchTab, ready, reportError } from './host';
import {
    ANALYSIS_TABS,
    BomData,
    CaeData,
    GuideData,
    HostMessage,
    ShowMessage,
    SupplyData,
    TabId,
    isAnalysisTab,
} from './messages';
import { clearGeometry, resizeCanvas, showGeometry } from './scene';
import { SupplyView } from './supply';
import { TabSpec, Tabs } from './tabs';

const panes: Record<TabId, HTMLElement> = {
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '3d': byId('pane-3d'),
    bom: byId('pane-bom'),
    instructions: byId('pane-instructions'),
    supply: byId('pane-supply'),
    fea: byId('pane-fea'),
    cfd: byId('pane-cfd'),
};

/** The tabs whose panes are rebuilt from scratch on every show. */
const DATA_TABS: TabId[] = ['bom', 'instructions', 'supply'];

const supplyView = new SupplyView(panes.supply);
// Each analysis owns its pane for the life of the panel: the implementation
// field is the user's, and rebuilding the pane on every show would take back
// what they typed into it.
const caeViews: Partial<Record<TabId, CaeView>> = {};
for (const tab of ANALYSIS_TABS) {
    caeViews[tab] = new CaeView(panes[tab], tab, (implementation) => runAnalysis(tab, implementation));
}
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
    if (message.kind === 'part') {
        // Only a part is analysed. An assembly is a set of parts that each have
        // boundary conditions of their own, and a load on the whole of one says
        // nothing about which member carries it - so 'pc cae' takes a part, and
        // so does this. The tab is offered whether or not the part declares
        // 'fea:'/'cfd:', because "this part says nothing about FEA" is the
        // answer somebody looking for the tab came to read.
        specs.push({ id: 'fea', label: 'FEA', pane: panes.fea });
        specs.push({ id: 'cfd', label: 'CFD', pane: panes.cfd });
    }
    specs.push({ id: 'supply', label: 'Supply', pane: panes.supply });
    return specs;
}

function show(message: ShowMessage): void {
    shown = message;
    generation += 1;
    requested.clear();
    instructions = undefined;
    for (const tab of DATA_TABS) {
        reset(tab);
    }
    for (const tab of ANALYSIS_TABS) {
        caeViews[tab]?.setBusy('Select this tab to run the analysis.');
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
    clearGeometry();
    for (const tab of DATA_TABS) {
        reset(tab);
    }
    for (const tab of ANALYSIS_TABS) {
        caeViews[tab]?.setBusy('Nothing to analyse.');
    }
    tabs.setTabs([{ id: '3d', label: '3D', pane: panes['3d'] }]);
}

/** Ask for an analysis again, with whatever implementation was typed in. */
function runAnalysis(tab: TabId, implementation: string): void {
    requested.add(tab);
    caeViews[tab]?.setBusy('Running the analysis…');
    fetchTab({ type: 'fetchTab', tab, token: generation, implementation: implementation || undefined });
}

function onTabSelected(tab: TabId): void {
    if (tab === '3d') {
        // The canvas had no size at all while the tab was hidden, and a WebGL
        // renderer does not find out on its own that it has one again.
        resizeCanvas();
        return;
    }
    if (isAnalysisTab(tab)) {
        // Same reason as the 3D view: a result mesh is drawn on a canvas that
        // had no size while its tab was hidden.
        caeViews[tab]?.resize();
    }
    if (requested.has(tab)) {
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
    fetchTab({ type: 'fetchTab', tab, token: generation });
}

function onTabData(
    tab: TabId,
    token: number,
    data: unknown,
    error: string | undefined,
    implementation: string | undefined,
): void {
    if (token !== generation) {
        // For an object that is no longer on screen.
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

function render(tab: TabId, pane: HTMLElement, data: unknown): void {
    switch (tab) {
        case 'bom':
            renderBom(pane, data as BomData);
            return;
        case 'instructions':
            instructions = new DocumentView(pane, (data as GuideData).document);
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
