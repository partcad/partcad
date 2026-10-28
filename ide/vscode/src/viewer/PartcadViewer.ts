//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { bytesOf } from '../common/framing';
import { readChoices, writeChoices } from '../common/garage';
import { traceError, traceInfo, traceVerbose } from '../common/log/logging';
import { getViewerPerformanceDebugFromSetting } from '../common/settings';
import * as utils from '../utils';
import { detailsBytes, filesAsBytes } from './payloads';
import { MSG_CLEAR, MSG_SHOW, ViewerMessage, ViewerNode, decodeGltf } from './protocol';
import { SpacenavClient } from './spacenav';

/**
 * One node as the webview is handed it: the same node, with its glTF
 * decompressed into base64 and measured.
 *
 * Decompressed here, in the extension host, rather than in the webview: Node has
 * zlib built in, a webview would need either a bundled inflater or
 * DecompressionStream. The size travels because the renderer shows what it is
 * loading, and it is the size of the buffer rather than of the payload.
 */
interface WebviewNode extends Omit<ViewerNode, 'assembly' | 'sketches' | 'geometry'> {
    size?: number;
    assembly?: WebviewNode[];
    sketches?: Record<string, WebviewNode>;
    /** The root's geometry table, decompressed: each entry measured as it is inflated. */
    geometry?: Record<string, { gltf: string; size: number }>;
}

/**
 * The tabs the panel offers, and the daemon operation behind each.
 *
 * The 3D view is not here: its contents arrive over the viewer protocol from
 * whichever 'partcad' asked for the shape to be shown, and are already in the
 * webview by the time a tab is looked at. Everything else is a question about
 * '<package>:<name>' that only this side can put to the daemon, so the renderer
 * asks and this answers -- see 'fetchTab'.
 */
const TAB_COMMANDS: Record<string, string> = {
    // What the object is required to be, and with 'verify' whether the model is
    // it - the verdicts 'pc test -f requirements' reaches.
    requirements: 'partcad.requirements',
    // Every check 'pc test' runs on the object, and with 'verify' its verdict.
    test: 'partcad.testReport',
    // What the object is made of and what each part of it declares; the user's
    // choices are added here, from this machine (see 'common/garage.ts').
    bvb: 'partcad.manufacturingTree',
    // The build plan, and the instruction pages it points into.
    build: 'partcad.manufacturingPlan',
    bom: 'partcad.bom',
    supply: 'partcad.supplyQuote',
    // The assembly instructions, as a document and as the file Save writes.
    assembly: 'partcad.assemblyGuide',
    // What a part declares for every analysis, read rather than run: asked once
    // for all four tabs, under the id of the group they are in, because which
    // of them apply is what decides whether the group does.
    analysis: 'partcad.caeList',
    // Running one scenario of one analysis. Every analysis is the one
    // operation; which of them is asked for travels as an argument, exactly as
    // every 'pc cae <analysis>' is one operation with the analysis in the
    // request - and the tab's id is that argument.
    fea: 'partcad.cae',
    dynamic: 'partcad.cae',
    thermal: 'partcad.cae',
    cfd: 'partcad.cae',
    // One object to one file: a picture PartCAD renders itself, or a drawing
    // a package renders ('pc render -e').
    // eslint-disable-next-line @typescript-eslint/naming-convention
    '2d': 'partcad.renderInline',
    draft: 'partcad.renderInline',
    // What the object declares under 'simulate:', read rather than run; a
    // request naming one of them runs it instead (see 'SIMULATION_RUN').
    simulation: 'partcad.simulateList',
};

/** What the Simulation tab asks when it names a simulation: run it, 'pc sim -f <name>'. */
const SIMULATION_RUN = 'partcad.simulateRun';

/** What the view panel's section sliders ask, on the 3D tab: show the object again, cut. */
const SHOW_SECTION = 'partcad.showSection';

/** The tabs that render the object to a file, which is then kept and can be saved. */
const RENDER_TABS = new Set(['2d', 'draft']);

/**
 * What shows an object of each kind, as the explorer does: what the panel asks
 * for when it wants another object on screen (see 'showObject').
 */
const INSPECT_COMMANDS: Record<string, string> = {
    part: 'partcad.inspectPart',
    assembly: 'partcad.inspectAssembly',
    scene: 'partcad.inspectScene',
    sketch: 'partcad.inspectSketch',
    interface: 'partcad.inspectInterface',
};

/** The tabs whose answer carries a file to keep for Save: the render tabs, and the assembly instructions. */
const FILE_TABS = new Set([...RENDER_TABS, 'assembly']);

/** What the renderer sends with a 'fetchTab'; see 'FetchTabMessage' in 'webview/messages.ts'. */
interface FetchTabRequest extends RenderRequest {
    tab: string;
    token: number;
    implementation?: string;
    format?: string;
    plugin?: string;
    choices?: Record<string, 'build' | 'buy'>;
    recursive?: boolean;
    buildParts?: boolean;
    document?: boolean;
    verify?: boolean;
    /**
     * On the Simulation tab: the simulation to run, by name; absent, the tab
     * asks what there is. On an analysis tab: the scenario to run, by name
     * ('pc cae <analysis> -f'); absent, every scenario is run.
     */
    scenario?: string;
    /** On the 2D and Simulation tabs: where the picture is looked at from, as the view panel says. */
    viewportOrigin?: number[];
    viewportUp?: number[];
    /** On the 2D and Draft tabs: what to cut the object to, as the view panel's sliders say. */
    section?: Record<string, [number, number]>;
}

/** A file a render tab is showing, kept until the next one replaces it. */
interface RenderedFile {
    /** Where it is kept: a temporary directory of this panel's. */
    file: string;
    /** The name PartCAD gave it, which is what the save dialog proposes. */
    filename: string;
    extension: string;
}

/**
 * The tabs that run an analysis rather than ask a question about the object,
 * each named after the analysis it asks 'cae.analyze' for. The renderer's
 * 'ANALYSIS_TABS' is the same list, in the order it draws the strip in.
 */
const ANALYSIS_TABS = new Set(['fea', 'dynamic', 'thermal', 'cfd']);

/**
 * The "Digital Thread" editor tab.
 *
 * A webview panel rather than a view in the side bar: a 3D model wants the whole
 * editor area, and it has to survive being switched away from, which is what
 * 'retainContextWhenHidden' buys (reloading the webview would drop the model,
 * the camera the user set up, and every tab already fetched).
 */
export class PartcadViewer implements vscode.Disposable {
    public static readonly viewType = 'partcadViewer';
    public static readonly title = 'Digital Thread';

    private panel: vscode.WebviewPanel | undefined;
    private lastShow: ViewerMessage | undefined;
    /** The `pc ide state` questions the webview has not answered yet, by token. */
    private readonly stateReplies = new Map<number, (reply: ViewerStateReply | undefined) => void>();
    private stateRequests = 0;
    /** The configured CAE implementations, once the daemon has been asked. */
    private configuredCae: Record<string, string> | undefined;
    /**
     * spacenavd, while the panel exists and the SpaceMouse is enabled - on Linux,
     * where the renderer cannot see the device itself. See 'spacenav.ts'.
     */
    private spacenav: SpacenavClient | undefined;
    /** Whether a remote window has said why spacenavd is not there; once is enough. */
    private spacenavHinted = false;
    private readonly disposables: vscode.Disposable[] = [];
    /**
     * What each render tab is showing, as a file on this machine.
     *
     * The daemon sends the bytes rather than a path - it may be on another
     * machine - and they are written here, into a temporary directory, so that
     * Save is a copy of the file on screen rather than a second render that
     * could come out different. One per tab: a new render replaces the file.
     */
    private readonly rendered = new Map<string, RenderedFile>();
    /**
     * The newest request of each render tab. The renderer drops an answer that
     * is not the one it waits for, and so must this side: a PNG asked for and
     * then an SVG can come back the other way round, and the file kept for Save
     * has to be the one on screen.
     */
    private readonly latestRender = new Map<string, number>();
    private renderDirectory: string | undefined;

    constructor(private readonly extensionUri: vscode.Uri) {
        this.disposables.push(
            vscode.workspace.onDidChangeConfiguration((event) => {
                if (event.affectsConfiguration('partcad.spaceMouse')) {
                    this.updateSpaceMouse();
                }
                if (event.affectsConfiguration('partcad.viewer.performanceDebug')) {
                    this.updateViewerConfig();
                }
            }),
            // Whether this panel is where the user is changes with the window's focus
            // as well as with the panel's own visibility.
            vscode.window.onDidChangeWindowState(() => this.postSpaceMouseState()),
        );
    }

    /** Whether the viewer tab currently exists. */
    public get isOpen(): boolean {
        return this.panel !== undefined;
    }

    /** Open the viewer (or bring it forward) without changing what it displays. */
    public reveal(preserveFocus = true): void {
        if (this.panel !== undefined) {
            this.panel.reveal(undefined, preserveFocus);
            return;
        }
        this.create(vscode.ViewColumn.Beside, preserveFocus);
        if (this.lastShow !== undefined) {
            // Reopening after a close should not leave an empty canvas when we
            // still know what was in it.
            this.handle(this.lastShow);
        }
    }

    /** Adopt a panel VS Code restored from a previous session. */
    public restore(panel: vscode.WebviewPanel): void {
        this.panel?.dispose();
        this.attach(panel);
    }

    /** Route a protocol message from a connected PartCAD to the webview. */
    public handle(message: ViewerMessage): void {
        if (message.type === MSG_CLEAR) {
            this.lastShow = undefined;
            void this.panel?.webview.postMessage({ type: 'clear' });
            return;
        }
        if (message.type !== MSG_SHOW) {
            return;
        }

        let object: WebviewNode | null;
        try {
            object = message.object ? inflate(message.object) : null;
        } catch (error: any) {
            traceError(`Digital Thread: failed to decode the geometry: ${error.message}`);
            void vscode.window.showErrorMessage(`Digital Thread: failed to decode the geometry: ${error.message}`);
            return;
        }

        this.lastShow = message;
        // A file rendered for the previous object is not this one's to save.
        this.forgetRendered();

        // Showing something is what opens the viewer: the user asked to inspect
        // an item, and an inspection with nowhere to draw is not useful.
        if (this.panel === undefined) {
            this.create(vscode.ViewColumn.Beside, true);
        }

        let performanceDebug = false;
        try {
            performanceDebug = getViewerPerformanceDebugFromSetting('partcad');
        } catch (error: any) {
            traceVerbose(`Digital Thread: failed to read performanceDebug setting: ${error?.message ?? error}`);
        }

        void this.panel?.webview.postMessage({
            type: 'show',
            name: message.name ?? null,
            kind: message.kind ?? null,
            // What the panel's other tabs are about. A 'partcad' that does not
            // send it (an older one, or a shape belonging to no package) leaves
            // the renderer showing the 3D view alone.
            package: message.package ?? null,
            keepCamera: message.keepCamera === true,
            // Which tab to open on, when the show asked for one. Passed as it
            // came: the renderer is what knows its tabs, and what applies.
            tab: typeof message.tab === 'string' ? message.tab : null,
            // And which of that tab's scenarios to select, when it lists them
            // ('pc ide view --analysis-fea --scenario loaded'). Passed as it
            // came, for the same reason: what the object declares is the
            // renderer's to know.
            scenario: typeof message.scenario === 'string' ? message.scenario : null,
            // What the object was cut to, and null for the whole of it -- passed
            // as it came, absent included: a PartCAD that does not send it
            // cannot cut, and the view panel offers it no section sliders.
            section: message.section === undefined ? undefined : (message.section ?? null),
            // The object as it arrived, geometry aside: the hierarchy, the
            // placements, the ports and the interfaces are PartCAD's account of
            // what is on screen, and this side knows nothing about assemblies,
            // ports or interfaces.
            object,
            config: {
                viewer: {
                    performanceDebug,
                },
            },
        });
    }

    /**
     * Fill one of the panel's tabs in, on the renderer's request.
     *
     * 'token' is the renderer's generation of the object the request was made
     * for; it comes back untouched so that an answer arriving after the user
     * moved on can be dropped there rather than painted over what is now on
     * screen. A refusal is an answer too: asking for the instructions of an
     * assembly that has no assembly steps is told why, and the reader sees that
     * instead of an empty tab.
     */
    private async fetchTab(message: FetchTabRequest): Promise<void> {
        const { tab, token, implementation, format, plugin } = message;
        // What a render tab's control pane asked for; see 'RenderRequest'.
        const render: RenderRequest = message;
        if (FILE_TABS.has(tab)) {
            // Before anything is awaited: two requests in flight reach the
            // awaits below in either order, and the one to keep the file of is
            // the newest asked for, not the last to get this far. Tokens only
            // grow, so the larger one is the newer.
            this.latestRender.set(tab, Math.max(token, this.latestRender.get(tab) ?? 0));
        }
        const analysis = ANALYSIS_TABS.has(tab);
        // Every file in the answer as bytes, which the panel makes a Blob URL
        // of, whether the daemon sent it so or as base64 (see 'payloads.ts').
        const post = (payload: { data?: unknown; error?: string }) => {
            filesAsBytes(tab, payload.data);
            void this.panel?.webview.postMessage({ type: 'tabData', tab, token, ...payload });
        };

        const command = tab === 'simulation' && message.scenario ? SIMULATION_RUN : TAB_COMMANDS[tab];
        if (command === undefined) {
            post({ error: `There is nothing to fill the '${tab}' tab with.` });
            return;
        }
        const target = this.lastShow;
        if (!target?.package || !target.name) {
            post({ error: 'PartCAD did not say which package this object belongs to.' });
            return;
        }

        try {
            // The commands are registered by the backend, so an absent one means
            // no PartCAD is connected -- which is worth saying plainly rather
            // than reporting as a missing command.
            if (!(await vscode.commands.getCommands(true)).includes(command)) {
                throw new Error('PartCAD is not connected. Use "Restart PartCAD" to reconnect.');
            }
            const args: Record<string, unknown> = { pkg: target.package, name: target.name };
            if (RENDER_TABS.has(tab)) {
                args.kind = target.kind ?? 'part';
                args.format = format;
                args.plugin = plugin;
                // What the control pane beside the drawing asked for: the links
                // to keep, and which of the port overlays to draw. Passed on as
                // it arrived -- the filter is a mask of link names, which this
                // side neither composes nor reads (see 'Tree.filter()').
                args.filter = render?.filter;
                args.withPorts = render?.withPorts;
                args.withInterfaces = render?.withInterfaces;
                args.withInternals = render?.withInternals;
                args.ports = render?.ports;
                // What the view panel beside it says: where the picture is looked
                // at from, and what the object is cut to first.
                args.viewportOrigin = message.viewportOrigin;
                args.viewportUp = message.viewportUp;
                args.section = message.section;
                const data = filesAsBytes(tab, await vscode.commands.executeCommand(command, args)) as
                    RenderedData | undefined;
                if (data?.content && this.lastShow === target && this.latestRender.get(tab) === token) {
                    this.keepRendered(tab, data);
                }
                post({ data });
                return;
            }
            if (tab === 'bvb') {
                args.kind = target.kind ?? 'part';
                const data = (await vscode.commands.executeCommand(command, args)) as { object?: string } | undefined;
                // The daemon names the object in full; that name, not the one
                // the viewer was shown under, is what the choices are kept by.
                const object = data?.object ?? `${target.package}:${target.name}`;
                post({ data: data ? { ...data, choices: readChoices(object) } : data });
                return;
            }
            if (tab === 'requirements' || tab === 'test') {
                args.kind = target.kind ?? 'part';
                args.verify = message.verify === true;
                post({ data: await vscode.commands.executeCommand(command, args) });
                return;
            }
            if (tab === 'analysis') {
                const data = (await vscode.commands.executeCommand(command, args)) as
                    Record<string, unknown> | undefined;
                // With what each analysis runs under when neither the user nor
                // the scenario names one -- the user configuration, which the
                // field over the model is pre-filled with for such a scenario --
                // added here as the garage's choices are added to the tree.
                post({ data: data ? { ...data, defaults: await this.caeDefaults() } : data });
                return;
            }
            if (tab === 'simulation') {
                args.kind = target.kind ?? 'part';
                // A run carries its pictures back as bytes, for the reason a
                // render does: the daemon may be on another machine.
                args.scenario = message.scenario;
                // Another plugin than the simulation names: 'pc sim --plugin'.
                args.plugin = message.plugin;
                // And where its pictures are taken from, when the view panel says.
                args.viewportOrigin = message.viewportOrigin;
                args.viewportUp = message.viewportUp;
                post({ data: await vscode.commands.executeCommand(command, args) });
                return;
            }
            if (tab === 'build') {
                args.kind = target.kind ?? 'part';
                args.choices = message.choices ?? {};
                args.recursive = message.recursive === true;
                args.document = message.document === true;
                post({ data: await vscode.commands.executeCommand(command, args) });
                return;
            }
            if (tab === 'assembly') {
                args.choices = message.choices ?? {};
                args.recursive = message.recursive === true;
                args.buildParts = message.buildParts === true;
                args.format = format;
                // Written whether or not the assembly is meant to be made: the
                // tab says which, in a banner, rather than refusing to show the
                // steps (the daemon answers 'manufacturable' either way).
                args.ignoreManufacturability = true;
                const data = (await vscode.commands.executeCommand(command, args)) as
                    { file?: { filename: string; extension: string; content: unknown } } | undefined;
                const file = data?.file;
                const content = bytesOf(file?.content);
                if (file && content && this.lastShow === target && this.latestRender.get(tab) === token) {
                    this.keepRendered(tab, { filename: file.filename, extension: file.extension, content });
                }
                // The file stays here, which is where Save copies it from; the
                // renderer only needs to know there is one.
                post({
                    data: data
                        ? { ...data, file: file ? { filename: file.filename, extension: file.extension } : undefined }
                        : data,
                });
                return;
            }
            if (analysis) {
                args.analysis = tab;
                args.scenario = message.scenario;
                // Only what the user typed. Left out, the daemon runs the
                // scenario with the implementation it names, and failing that
                // with the configured default -- which is why the default is
                // never filled in here: sent as an override, it would outrank
                // the scenario's own.
                args.implementation = implementation || undefined;
                // The panel is a webview with no file system in reach, so the
                // model has to arrive as bytes rather than as the path the
                // daemon wrote it to -- which may not even be this machine.
                args.inline = true;
            }
            post({ data: await vscode.commands.executeCommand(command, args) });
        } catch (error: any) {
            traceError(`Digital Thread: failed to fetch the '${tab}' tab: ${error?.message ?? error}`);
            post({ error: `${error?.message ?? error}` });
        }
    }

    /**
     * Show the object on screen again, cut to 'section' or whole (null): the 3D
     * tab's section sliders.
     *
     * Through the daemon, which cuts the object and shows it the way it shows
     * anything - over the viewer protocol, into 'handle' - with the section it
     * was cut to on the show. What is answered here is only whether the daemon
     * could, so that the panel stops saying it is cutting.
     */
    private async showSection(token: number, section: unknown): Promise<void> {
        const post = (error?: string) =>
            void this.panel?.webview.postMessage({ type: 'sectionShown', token, ...(error ? { error } : {}) });
        const target = this.lastShow;
        if (!target?.package || !target.name) {
            post('PartCAD did not say which package this object belongs to.');
            return;
        }
        try {
            if (!(await vscode.commands.getCommands(true)).includes(SHOW_SECTION)) {
                throw new Error('PartCAD is not connected. Use "Restart PartCAD" to reconnect.');
            }
            await vscode.commands.executeCommand(SHOW_SECTION, {
                pkg: target.package,
                name: target.name,
                kind: target.kind ?? undefined,
                section: section ?? null,
            });
            post();
        } catch (error: any) {
            traceError(`Digital Thread: failed to cut the object: ${error?.message ?? error}`);
            post(`${error?.message ?? error}`);
        }
    }

    /** Answer the Draft tab: which file types a drawing package renders to. */
    private async fetchFormats(token: number, plugin: string): Promise<void> {
        const post = (payload: { formats?: unknown; error?: string }) =>
            void this.panel?.webview.postMessage({ type: 'formats', token, plugin, ...payload });
        try {
            if (!(await vscode.commands.getCommands(true)).includes('partcad.renderFormats')) {
                throw new Error('PartCAD is not connected. Use "Restart PartCAD" to reconnect.');
            }
            const answer = (await vscode.commands.executeCommand('partcad.renderFormats', { package: plugin })) as
                { formats?: unknown } | undefined;
            post({ formats: answer?.formats ?? [] });
        } catch (error: any) {
            traceError(`Digital Thread: failed to ask ${plugin} for its formats: ${error?.message ?? error}`);
            post({ error: `${error?.message ?? error}` });
        }
    }

    /**
     * Fill the Build vs Buy table's pictures and measurements in, a few objects
     * at a time. Not a tab of its own: one table asks this many times over.
     */
    private async fetchDetails(token: number, objects: unknown, width?: number, height?: number): Promise<void> {
        const post = (payload: { items?: unknown; error?: string }) =>
            void this.panel?.webview.postMessage({ type: 'details', token, ...payload });
        try {
            if (!(await vscode.commands.getCommands(true)).includes('partcad.manufacturingDetails')) {
                throw new Error('PartCAD is not connected. Use "Restart PartCAD" to reconnect.');
            }
            const answer = (await vscode.commands.executeCommand('partcad.manufacturingDetails', {
                objects,
                width,
                height,
            })) as { items?: unknown } | undefined;
            // Each thumbnail as bytes, as 'fetchTab' posts every file.
            detailsBytes(answer?.items);
            post({ items: answer?.items ?? [] });
        } catch (error: any) {
            traceError(`Digital Thread: failed to fetch the Build vs Buy details: ${error?.message ?? error}`);
            post({ error: `${error?.message ?? error}` });
        }
    }

    /**
     * Open the file an object is made from, beside the viewer.
     *
     * The path is the daemon's, which is this machine's whenever the workspace
     * is local - the ordinary case. When it is not (a daemon elsewhere), there
     * is nothing here to open, and the user is told where the file is rather
     * than shown an editor for a path that does not exist.
     */
    private async openSource(file: string): Promise<void> {
        if (!fs.existsSync(file)) {
            void vscode.window.showWarningMessage(
                `PartCAD: ${file} is not on this machine (it is where the PartCAD daemon runs), so it cannot be opened here.`,
            );
            return;
        }
        try {
            await vscode.window.showTextDocument(vscode.Uri.file(file), {
                viewColumn: vscode.ViewColumn.One,
                preview: false,
            });
        } catch (error: any) {
            // Not text - a STEP file opens as one, but a binary 3MF does not:
            // hand it to whatever VS Code opens such a file with.
            traceVerbose(`Digital Thread: ${file} is not a text document: ${error?.message ?? error}`);
            await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(file), vscode.ViewColumn.One);
        }
    }

    /**
     * Show another object in the panel, as the explorer would: what a Test tab
     * artifact opens with (an interference's two parts and what they share).
     *
     * Through the explorer's own command, so that it is shown the one way
     * anything is - by the daemon, which pushes it in here - and not remembered
     * as the selection ('doNotMemorize'): nothing declares such an object, so a
     * window reopened on it might find nothing to show.
     */
    private async showObject(
        pkg: string | undefined,
        name: string | undefined,
        kind: string | undefined,
    ): Promise<void> {
        const command = INSPECT_COMMANDS[kind ?? ''];
        if (!pkg || !name || command === undefined) {
            traceError(`Digital Thread: cannot show '${pkg}:${name}', a '${kind}'`);
            return;
        }
        try {
            await vscode.commands.executeCommand(command, { name, pkg }, {}, true);
        } catch (error: any) {
            void vscode.window.showErrorMessage(`PartCAD could not show ${pkg}:${name}: ${error?.message ?? error}`);
        }
    }

    /** Keep what the user chose to build and to buy, on this machine. */
    private saveChoices(object: string, choices: Record<string, 'build' | 'buy'>): void {
        try {
            writeChoices(object, choices);
        } catch (error: any) {
            traceError(`Digital Thread: failed to save the Build vs Buy choices: ${error?.message ?? error}`);
            void vscode.window.showErrorMessage(`Could not save the Build vs Buy choices: ${error?.message ?? error}`);
        }
    }

    /** Write what a render tab received to a file of its own, replacing the last one. */
    private keepRendered(tab: string, data: Omit<RenderedData, 'object' | 'format'>): void {
        try {
            if (this.renderDirectory === undefined) {
                this.renderDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-viewer-'));
            }
            this.forgetRendered(tab);
            // A directory per file, so that it keeps the name PartCAD gave it
            // and the two tabs cannot write over each other.
            const directory = fs.mkdtempSync(path.join(this.renderDirectory, `${tab}-`));
            const file = path.join(directory, path.basename(data.filename));
            fs.writeFileSync(file, data.content);
            this.rendered.set(tab, { file, filename: path.basename(data.filename), extension: data.extension });
        } catch (error: any) {
            // Shown all the same: the picture is in the message. Only Save needs
            // the file, and it says so if there is none.
            traceError(`Digital Thread: failed to keep the rendered file: ${error?.message ?? error}`);
        }
    }

    /** Drop the kept file of one render tab, or of all of them. */
    private forgetRendered(tab?: string): void {
        for (const [key, kept] of [...this.rendered]) {
            if (tab === undefined || key === tab) {
                removeQuietly(path.dirname(kept.file));
                this.rendered.delete(key);
            }
        }
    }

    /** Save what a render tab is showing, wherever the user says. */
    private async saveRendered(tab: string): Promise<void> {
        const kept = this.rendered.get(tab);
        if (kept === undefined || !fs.existsSync(kept.file)) {
            void vscode.window.showErrorMessage('There is no rendered file to save. Render it again, then save.');
            return;
        }
        const folder = vscode.workspace.workspaceFolders?.[0]?.uri;
        const target = await vscode.window.showSaveDialog({
            defaultUri: folder ? vscode.Uri.joinPath(folder, kept.filename) : undefined,
            filters: { [`${kept.extension.toUpperCase()} files`]: [kept.extension] },
            saveLabel: 'Save',
            title: `Save ${kept.filename}`,
        });
        if (target === undefined) {
            return;
        }
        try {
            await vscode.workspace.fs.copy(vscode.Uri.file(kept.file), target, { overwrite: true });
            vscode.window.setStatusBarMessage(`PartCAD: saved ${target.fsPath}`, 5000);
        } catch (error: any) {
            traceError(`Digital Thread: failed to save ${target.fsPath}: ${error?.message ?? error}`);
            void vscode.window.showErrorMessage(`Could not save ${target.fsPath}: ${error?.message ?? error}`);
        }
    }

    /**
     * The implementation each analysis runs under when nobody has said
     * otherwise, by analysis.
     *
     * Asked of the daemon once per panel and remembered, because it is the
     * user's configuration rather than anything about the object on screen. A
     * PartCAD too old to answer, or none connected at all, leaves the field
     * empty rather than failing the fetch: the analysis itself will report the
     * real problem a moment later.
     */
    private async caeDefaults(): Promise<Record<string, string>> {
        if (this.configuredCae === undefined) {
            try {
                this.configuredCae =
                    ((await vscode.commands.executeCommand('partcad.caeDefaults')) as Record<string, string>) ?? {};
            } catch (error: any) {
                traceVerbose(`Digital Thread: no CAE defaults: ${error?.message ?? error}`);
                this.configuredCae = {};
            }
        }
        return this.configuredCae;
    }

    /**
     * What the panel is showing, for `pc ide state`, with a screenshot of the sub-tab on screen.
     *
     * The webview is asked: the tabs, the trees and the controls are all in it.
     * It sends the screenshot as a PNG and this side writes it -- the webview has
     * no filesystem -- into the temporary directory, where `pc` is told to look.
     * The panel is not brought forward to take it: a question about what
     * somebody is looking at must not change what they are looking at.
     */
    public async state(): Promise<unknown> {
        const panel = this.panel;
        if (panel === undefined) {
            return { open: false };
        }
        const token = ++this.stateRequests;
        const reply = await new Promise<ViewerStateReply | undefined>((resolve) => {
            const timer = setTimeout(() => finish(undefined), VIEWER_STATE_REPLY_MS);
            const finish = (answer: ViewerStateReply | undefined) => {
                clearTimeout(timer);
                this.stateReplies.delete(token);
                resolve(answer);
            };
            this.stateReplies.set(token, finish);
            panel.webview.postMessage({ type: 'state', token }).then(
                (delivered) => {
                    if (!delivered) {
                        finish(undefined);
                    }
                },
                () => finish(undefined),
            );
        });
        const base = { open: true, visible: panel.visible };
        if (reply === undefined) {
            return { ...base, error: `the Digital Thread did not answer within ${VIEWER_STATE_REPLY_MS / 1000}s` };
        }
        const { screenshot, screenshotError, state } = reply;
        let written: string | null = null;
        let failure = screenshotError ?? null;
        if (screenshot) {
            try {
                written = writeScreenshot(screenshot, state);
            } catch (error: any) {
                failure = `the screenshot could not be written: ${error?.message ?? error}`;
            }
        }
        return { ...base, ...state, screenshot: written, ...(failure ? { screenshotError: failure } : {}) };
    }

    private create(column: vscode.ViewColumn, preserveFocus: boolean): void {
        const panel = vscode.window.createWebviewPanel(
            PartcadViewer.viewType,
            PartcadViewer.title,
            { viewColumn: column, preserveFocus },
            this.webviewOptions(),
        );
        this.attach(panel);
    }

    private attach(panel: vscode.WebviewPanel): void {
        panel.webview.options = this.webviewOptions();
        panel.iconPath = utils.joinPath(this.extensionUri, 'resources', 'logo.svg');
        panel.webview.html = this.html(panel.webview);
        panel.onDidDispose(() => {
            if (this.panel === panel) {
                this.panel = undefined;
                this.updateSpaceMouse();
            }
        });
        panel.onDidChangeViewState(() => this.postSpaceMouseState());
        panel.webview.onDidReceiveMessage(
            (
                message: Partial<FetchTabRequest> & {
                    type: string;
                    message?: string;
                    object?: string;
                    path?: string;
                    package?: string;
                    name?: string;
                    kind?: string;
                    objects?: unknown;
                    width?: number;
                    height?: number;
                } & Partial<ViewerStateReply>,
            ) => {
                if (message.type === 'state') {
                    this.stateReplies.get(message.token ?? 0)?.(message as ViewerStateReply);
                } else if (message.type === 'error') {
                    traceError(`Digital Thread: ${message.message}`);
                } else if (message.type === 'ready') {
                    this.postSpaceMouseState();
                    if (this.lastShow !== undefined) {
                        // The webview finished booting after we had already been
                        // asked to show something (a restored tab, or a show that
                        // raced the panel's first paint).
                        this.handle(this.lastShow);
                    }
                } else if (message.type === 'fetchTab') {
                    void this.fetchTab({ ...message, tab: message.tab ?? '', token: message.token ?? 0 });
                } else if (message.type === 'fetchDetails') {
                    void this.fetchDetails(message.token ?? 0, message.objects ?? [], message.width, message.height);
                } else if (message.type === 'openSource') {
                    if (message.path) {
                        void this.openSource(message.path);
                    }
                } else if (message.type === 'saveChoices') {
                    if (message.object) {
                        this.saveChoices(message.object, message.choices ?? {});
                    }
                } else if (message.type === 'fetchFormats') {
                    void this.fetchFormats(message.token ?? 0, message.plugin ?? '');
                } else if (message.type === 'save') {
                    void this.saveRendered(message.tab ?? '');
                } else if (message.type === 'showObject') {
                    void this.showObject(message.package, message.name, message.kind);
                } else if (message.type === 'showSection') {
                    void this.showSection(message.token ?? 0, message.section);
                } else {
                    traceVerbose(`Digital Thread: ${message.type}`);
                }
            },
        );
        this.panel = panel;
        this.updateSpaceMouse();
    }

    /**
     * Start or stop reading spacenavd, and tell the renderer how to behave.
     *
     * spacenavd is read only while there is a panel to move, and never on
     * Windows, where there is no spacenavd and the Gamepad API sees the device.
     */
    private updateSpaceMouse(): void {
        const wanted = this.panel !== undefined && spaceMouseSettings().enabled && process.platform !== 'win32';
        if (wanted && this.spacenav === undefined) {
            const client = new SpacenavClient();
            client.onDidChangeState(() => {
                traceVerbose(
                    `Digital Thread: spacenavd ${client.connected ? `connected, device ${client.device}` : 'disconnected'}`,
                );
                if (client.missing) {
                    this.hintSpacenav(client.paths);
                }
                this.postSpaceMouseState();
            });
            client.onEvent((event) => {
                // Only to the panel the user is looking at: spacenavd reports every
                // push to every client, whichever window has the focus.
                if (this.spaceMouseActive()) {
                    void this.panel?.webview.postMessage({ type: 'spaceMouseEvent', ...event });
                }
            });
            this.spacenav = client;
        } else if (!wanted && this.spacenav !== undefined) {
            this.spacenav.dispose();
            this.spacenav = undefined;
        }
        this.postSpaceMouseState();
    }

    /**
     * Say why a SpaceMouse does nothing in a remote window, once.
     *
     * The extension host runs where the workspace is - a dev container, an SSH
     * host, WSL - and spacenavd where the device is plugged in. Nothing else in
     * that situation says anything: the cap is pushed and the model just sits
     * there. Locally a missing spacenavd needs no such note; the README says to
     * install it, and on most machines that look finds nothing because there is
     * no SpaceMouse.
     */
    private hintSpacenav(paths: readonly string[]): void {
        if (this.spacenavHinted || vscode.env.remoteName === undefined) {
            return;
        }
        this.spacenavHinted = true;
        traceInfo(
            `Digital Thread: no spacenavd at ${paths.join(' or ')} where this workspace runs ` +
                `(${vscode.env.remoteName}). A SpaceMouse on a Linux machine reaches the viewer only through ` +
                `spacenavd's socket, so forward it from there to one of those paths - see "3Dconnexion SpaceMouse" ` +
                `in the PartCAD extension's README. On Windows and macOS the viewer reads the device itself.`,
        );
    }

    /** Whether the panel is visible in the focused window, which is where a SpaceMouse push is meant for. */
    private spaceMouseActive(): boolean {
        return this.panel?.visible === true && vscode.window.state.focused;
    }

    private postSpaceMouseState(): void {
        void this.panel?.webview.postMessage({
            type: 'spaceMouseState',
            settings: spaceMouseSettings(),
            active: this.spaceMouseActive(),
            spacenavd: this.spacenav?.connected === true,
            spacenavdDevice: this.spacenav?.device ?? null,
        });
    }

    private updateViewerConfig(): void {
        let performanceDebug = false;
        try {
            performanceDebug = getViewerPerformanceDebugFromSetting('partcad');
        } catch (error) {
            traceVerbose(
                `Digital Thread: failed to read performanceDebug setting: ${(error as Error)?.message ?? error}`,
            );
        }
        void this.panel?.webview.postMessage({
            type: 'updateConfig',
            config: {
                viewer: {
                    performanceDebug,
                },
            },
        });
    }

    private webviewOptions(): vscode.WebviewPanelOptions & vscode.WebviewOptions {
        return {
            enableScripts: true,
            // Switching to another editor tab must not throw the model away.
            retainContextWhenHidden: true,
            localResourceRoots: [this.extensionUri],
        };
    }

    private html(webview: vscode.Webview): string {
        const scriptUri = webview.asWebviewUri(utils.joinPath(this.extensionUri, 'dist', 'viewer.js'));
        const styleUri = webview.asWebviewUri(utils.joinPath(this.extensionUri, 'resources', 'css', 'viewer.css'));
        const nonce = getNonce();

        // No 'connect-src': the geometry arrives over postMessage and is parsed
        // from memory, so the viewer never issues a network request. Nothing
        // here may be relaxed to load an asset from a CDN.
        return `<!DOCTYPE html>
			<html lang="en">
			<head>
				<meta charset="UTF-8">
				<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; img-src ${webview.cspSource} data: blob:; script-src 'nonce-${nonce}';">
				<meta name="viewport" content="width=device-width, initial-scale=1.0">
				<link href="${styleUri}" rel="stylesheet">
				<title>${PartcadViewer.title}</title>
			</head>
			<body>
				<div class="panel">
					<div id="tabs" class="tabs" hidden></div>
					<div class="panes">
						<div id="pane-requirements" class="pane" hidden></div>
						<div id="pane-design" class="pane pane-group">
						<div id="design-tabs" class="tabs sub-tabs" hidden></div>
						<div class="panes">
						<div id="pane-3d" class="pane pane-3d">
							<div class="controls" hidden>
								<div id="tree" class="tree" role="tree"></div>
								<div class="viewer-controls" id="metadata-control" hidden>
									<label class="control-label"><input type="checkbox" id="metadata-checkbox" checked> Metadata</label>
								</div>
							</div>
							<div id="viewer" class="viewer">
								<div id="overlay" class="overlay">Nothing to display yet.</div>
							</div>
						</div>
						<div id="pane-2d" class="pane" hidden></div>
						<div id="pane-draft" class="pane" hidden></div>
						</div>
						</div>
						<div id="pane-analysis" class="pane pane-group" hidden>
						<div id="analysis-tabs" class="tabs sub-tabs" hidden></div>
						<div class="panes">
						<div id="pane-fea" class="pane" hidden></div>
						<div id="pane-dynamic" class="pane" hidden></div>
						<div id="pane-thermal" class="pane" hidden></div>
						<div id="pane-cfd" class="pane" hidden></div>
						</div>
						</div>
						<div id="pane-manufacturing" class="pane pane-group" hidden>
						<div id="manufacturing-tabs" class="tabs sub-tabs" hidden></div>
						<div class="panes">
						<div id="pane-bvb" class="pane" hidden></div>
						<div id="pane-build" class="pane" hidden></div>
						<div id="pane-bom" class="pane" hidden></div>
						<div id="pane-supply" class="pane" hidden></div>
						<div id="pane-assembly" class="pane" hidden></div>
						</div>
						</div>
						<div id="pane-validation" class="pane pane-group" hidden>
						<div id="validation-tabs" class="tabs sub-tabs" hidden></div>
						<div class="panes">
						<div id="pane-test" class="pane" hidden></div>
						<div id="pane-simulation" class="pane" hidden></div>
						<div id="pane-emulation" class="pane" hidden></div>
						</div>
						</div>
						<div id="pane-operations" class="pane" hidden></div>
					</div>
				</div>
				<script nonce="${nonce}" src="${scriptUri}"></script>
			</body>
			</html>`;
    }

    public dispose(): void {
        this.panel?.dispose();
        this.panel = undefined;
        this.forgetRendered();
        if (this.renderDirectory !== undefined) {
            removeQuietly(this.renderDirectory);
            this.renderDirectory = undefined;
        }
        this.spacenav?.dispose();
        this.spacenav = undefined;
        this.disposables.forEach((disposable) => disposable.dispose());
    }
}

/**
 * Delete a temporary file or directory, and only log if that fails.
 *
 * 'force' covers a path that is already gone and nothing else: on Windows an
 * antivirus scanner or the indexer holding the file open fails it with EBUSY or
 * EPERM. A file left in the temporary directory costs nothing; letting that
 * throw would stop the next object being shown, or the panel being disposed.
 */
function removeQuietly(target: string): void {
    try {
        fs.rmSync(target, { recursive: true, force: true });
    } catch (error: any) {
        traceVerbose(`Digital Thread: could not remove ${target}: ${error?.message ?? error}`);
    }
}

/**
 * What a render tab asks for beside the file type: the control pane's answer.
 *
 * 'filter' is a mask of link names ('pc render --filter'), composed in the panel
 * and read by PartCAD; nothing on this side looks inside it. The three flags are
 * '--with-ports'/'--with-interfaces'/'--with-internals'.
 */
interface RenderRequest {
    filter?: unknown;
    withPorts?: boolean;
    withInterfaces?: boolean;
    withInternals?: boolean;
    /** Which ports to draw, by the name PartCAD reports each under. */
    ports?: string[];
}

/** What 'render.inline' answers with; see 'RenderData' in 'webview/messages.ts'. */
interface RenderedData {
    object: string;
    format: string;
    filename: string;
    extension: string;
    /** The file, as 'filesAsBytes' leaves it: its bytes. */
    content: Uint8Array;
}

/** The 'partcad.spaceMouse.*' settings, in the shape the renderer takes them. */
function spaceMouseSettings(): { enabled: boolean; sensitivity: number; invert: string[] } {
    const config = vscode.workspace.getConfiguration('partcad.spaceMouse');
    const sensitivity = config.get<number>('sensitivity', 1);
    return {
        enabled: config.get<boolean>('enabled', true),
        sensitivity: Number.isFinite(sensitivity) && sensitivity > 0 ? sensitivity : 1,
        invert: config.get<string[]>('invert', []),
    };
}

/** A node, and everything under it, with its geometry decompressed and measured.
 *
 * The geometry is decompressed once per distinct shape rather than once per node,
 * because that is how it arrives: the table on the root holds one entry however
 * many nodes name it, and the nodes themselves carry only the name. An assembly
 * that places one bolt a hundred times is a hundred nodes and one inflate.
 */
function inflate(node: ViewerNode): WebviewNode {
    // The three that change shape on the way through are taken out of the spread
    // rather than overwritten after it: a compressed table and an inflated one are
    // different types under one name, and spreading the first into the second is
    // the kind of mismatch TypeScript resolves optimistically on a recursive type.
    const { geometry, assembly, sketches, ...rest } = node;
    const inflated: WebviewNode = { ...rest };
    if (node.gltf !== undefined) {
        const gltf = decodeGltf(node.gltf);
        inflated.gltf = gltf.toString('base64');
        inflated.size = gltf.length;
    }
    if (geometry !== undefined) {
        inflated.geometry = Object.fromEntries(
            Object.entries(geometry).map(([digest, payload]) => {
                const gltf = decodeGltf(payload);
                return [digest, { gltf: gltf.toString('base64'), size: gltf.length }];
            }),
        );
    }
    if (assembly !== undefined) {
        inflated.assembly = assembly.map(inflate);
    }
    if (sketches !== undefined) {
        // The sketches the ports are drawn with are nodes like any other, and
        // name their geometry the same way.
        inflated.sketches = Object.fromEntries(
            Object.entries(sketches).map(([reference, sketch]) => [reference, inflate(sketch)]),
        );
    }
    return inflated;
}

function getNonce(): string {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}

/** How long the Digital Thread's webview has to collect its state and take the screenshot. */
const VIEWER_STATE_REPLY_MS = 10000;

/** What the Digital Thread's webview answers a `state` with; see `webview/state.ts`. */
export interface ViewerStateReply {
    type: 'state';
    token: number;
    state: Record<string, unknown>;
    /** The sub-tab on screen as a PNG, base64, or absent with `screenshotError` saying why. */
    screenshot?: string;
    screenshotError?: string;
}

/**
 * Write a screenshot where `pc ide state` says it is, and return the path.
 *
 * Into the temporary directory -- /tmp on Linux -- named after the tab and the
 * sub-tab it shows and the time it was taken, so that two answers in a row are
 * two files and an agent comparing before and after has both.
 */
export function writeScreenshot(base64: string, state: Record<string, unknown> | undefined): string {
    const part = (value: unknown) => String(value ?? 'none').replace(/[^A-Za-z0-9_-]/g, '-');
    const name = `partcad-viewer-${part(state?.tab)}-${part(state?.subTab)}-${Date.now()}.png`;
    const file = path.join(os.tmpdir(), name);
    fs.writeFileSync(file, Buffer.from(base64, 'base64'));
    return file;
}
