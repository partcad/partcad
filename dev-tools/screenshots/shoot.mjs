//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Retake the screenshots under docs/source/images.
//
//   cd dev-tools/screenshots && npm install
//   node shoot.mjs                    # every screenshot this script knows
//   node shoot.mjs vscode1 vscode2    # some of them
//
// It runs on the host, with a desktop, and needs a 'partcad-json-rpc' of the
// PartCAD to be pictured (PC_SCREENSHOT_SERVICE, or the one on the PATH) and the
// extension built from this checkout (ide/vscode/partcad.vsix: 'npm run
// vsce-package' there). docs/notes/screenshots.md says why it is done this way,
// what each screenshot is of, and which ones this script does not take.

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
    canvas,
    command,
    expand,
    filled,
    installExtension,
    launch,
    layout,
    openFile,
    orbit,
    paneHeight,
    partcadView,
    rowAction,
    select,
    shot,
    shown,
    showStill,
    sleep,
    slide,
    tab,
    terminal,
    terminalShows,
    tidy,
    trimmed,
    viewer,
    viewPanel,
    zoom,
} from './vscode.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const EXAMPLES = path.join(REPO, 'examples');
const OUT = process.env.PC_SCREENSHOT_OUT ?? path.join(REPO, 'docs', 'source', 'images');
const WORK = process.env.PC_SCREENSHOT_WORK ?? path.join(os.tmpdir(), 'partcad-screenshots');

/** The VS Code to drive: the newest one the extension's tests downloaded, unless told otherwise. */
function vscodeBinary() {
    if (process.env.PC_SCREENSHOT_CODE) {
        return process.env.PC_SCREENSHOT_CODE;
    }
    const downloads = path.join(REPO, 'ide', 'vscode', '.vscode-test');
    const builds = fs.existsSync(downloads)
        ? fs.readdirSync(downloads).filter((name) => name.startsWith('vscode-')).sort()
        : [];
    if (!builds.length) {
        throw new Error('No VS Code to drive: run the extension tests once (npm test in ide/vscode), or set PC_SCREENSHOT_CODE');
    }
    return path.join(downloads, builds[builds.length - 1], 'code');
}

/** The 'partcad-json-rpc' the extension is pointed at. */
function serviceBinary() {
    if (process.env.PC_SCREENSHOT_SERVICE) {
        return process.env.PC_SCREENSHOT_SERVICE;
    }
    const found = spawnSync('which', ['partcad-json-rpc'], { encoding: 'utf8' }).stdout.trim();
    if (!found) {
        throw new Error('No partcad-json-rpc on the PATH: install this checkout somewhere and set PC_SCREENSHOT_SERVICE');
    }
    return found;
}

const CODE = vscodeBinary();
const SERVICE = serviceBinary();
const PC = path.join(path.dirname(SERVICE), 'pc');
const PROFILE = path.join(WORK, 'profile');
const EXTENSIONS = path.join(WORK, 'extensions');

// What the window looks like: VS Code's default dark theme, nothing that greets
// or suggests, and a terminal with a prompt that says nothing about whoever took
// the picture.
const SETTINGS = {
    'partcad.servicePath': SERVICE,
    'workbench.colorTheme': 'Default Dark Modern',
    'workbench.startupEditor': 'none',
    'workbench.welcomePage.walkthroughs.openOnInstall': false,
    'workbench.tips.enabled': false,
    'workbench.enableExperiments': false,
    'workbench.secondarySideBar.defaultVisibility': 'hidden',
    // A tree keeps the row being expanded under a sticky header of its parents,
    // and a header over a twistie is a header that takes the click meant for it
    // ("intercepts pointer events"). Off, so that 'expand()' walks a path -- and
    // so that a picture of the Explorer is the tree rather than the tree with
    // part of itself repeated at the top.
    'workbench.tree.enableStickyScroll': false,
    'security.workspace.trust.enabled': false,
    'update.mode': 'none',
    'extensions.autoUpdate': false,
    'extensions.autoCheckUpdates': false,
    'extensions.ignoreRecommendations': true,
    'telemetry.telemetryLevel': 'off',
    'chat.disableAIFeatures': true,
    'window.restoreWindows': 'none',
    'window.titleBarStyle': 'custom',
    // A native dialog stops the window drawing until somebody answers it, and
    // nobody will; drawn by VS Code instead, it is at least in the picture.
    'window.dialogStyle': 'custom',
    'git.enabled': false,
    'terminal.integrated.enablePersistentSessions': false,
    'terminal.integrated.profiles.linux': {
        plain: { path: 'bash', args: ['--noprofile', '--norc'], env: { PS1: '\\W $ ' } },
    },
    'terminal.integrated.defaultProfile.linux': 'plain',
    'files.simpleDialog.enable': true,
    'editor.fontSize': 14,
    'terminal.integrated.fontSize': 13,
    'terminal.integrated.gpuAcceleration': 'off',
};

/**
 * Open VS Code on 'folder', run 'steps' in it, and close it again.
 *
 * The workspace's PartCAD daemon is stopped first, so that the one the extension
 * starts is a child of this VS Code: it inherits PARTCAD_IDE_PORT from it, which
 * is what sends what it shows to this window.
 */
async function inVSCode(folder, steps) {
    spawnSync(PC, ['--no-ansi', 'daemon', 'stop'], { cwd: folder, stdio: 'ignore' });
    const vscode = await launch({ code: CODE, profile: PROFILE, extensions: EXTENSIONS, settings: SETTINGS, folder });
    try {
        // The extension's own terminals, its first load of the package.
        await sleep(15000);
        await command(vscode.page, 'View: Close All Editors');
        await steps(vscode.page);
    } catch (error) {
        // What the window looked like when it went wrong is most of the answer.
        await shot(vscode.page, path.join(WORK, 'failed.png')).catch(() => {});
        throw error;
    } finally {
        await vscode.close();
    }
}

const out = (name) => path.join(OUT, `${name}.png`);

/**
 * The Digital Thread panel alone, as a rectangle to cut a screenshot to.
 *
 * The tab strips are above the 3D view and outside '#viewer', so this is the
 * webview's own frame element rather than the canvas: a picture of a tab has to
 * have the tab in it.
 */
async function panel(page) {
    const box = await page.locator('iframe.webview, .webview').last().boundingBox();
    if (!box) {
        throw new Error('the Digital Thread panel is not on screen');
    }
    return box;
}

/** Open the Digital Thread beside the editor. */
async function openViewer(page) {
    await command(page, 'Open Digital Thread');
    await sleep(3000);
}

const FEATURE_INTERFACE = ['feature_interface'];

const SHOTS = {
    // The README's picture of the extension: a package's assembly open in the
    // editor and drawn in the Digital Thread, with what PartCAD said while doing
    // it in the terminal.
    async vscode1() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Context', 'Explorer', 'Inspector']);
            await expand(page, ['//pub', 'robotics', 'parts', 'gobilda']);
            // Loading a package from //pub goes on for a moment after its row is
            // there, and a request that arrives while it does can fail.
            await sleep(10000);
            await rowAction(page, 'examples/wormgear', 5, 'Edit');
            await openViewer(page);
            await layout(page, { sidebar: 330, editor: 520, panel: 250 });
            await paneHeight(page, 'Inspector', 200);
            await showStill(page, 'examples/wormgear', 5, 'examples/worm_drive');
            await tidy(page);
            await shot(page, out('vscode1'));
        });
    },

    // The same, for an assembly that takes parameters: the Inspector lists them.
    async vscode2() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Context', 'Explorer', 'Inspector']);
            await expand(page, FEATURE_INTERFACE);
            await sleep(5000);
            await rowAction(page, 'connect-mates', 2, 'Edit');
            await openViewer(page);
            await layout(page, { sidebar: 330, editor: 520, panel: 250 });
            await paneHeight(page, 'Inspector', 260);
            await showStill(page, 'connect-mates', 2, 'connect-ports');
            await zoom(page, 1.5);
            await tidy(page);
            await shot(page, out('vscode2'));
        });
    },

    // A port, and the sketch that is its boundary, as the Digital Thread draws
    // them: docs/source/config_interfaces.rst, "Port boundary".
    async 'interface-m3'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { editor: 300 });
            await showStill(page, 'm3', 2, 'm3-hole-4.5');
            await tidy(page);
            await shot(page, out('interface-m3'), await trimmed(page, await canvas(page)));
        });
    },

    // The four mounting ports of a NEMA-17 motor, seen from above, each one's
    // X axis pointing at the next one round: "Matching multiple ports". The
    // second picture is the same view with the motor itself made invisible
    // (the opacity slider), which leaves the ports.
    async 'interface-orientation'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { editor: 300 });
            await showStill(page, 'example-motor', 2, 'example-bracket');
            await orbit(page, { left: 36.87, up: 70 });
            // Seen end on, the motor is a small square in a view framed for
            // all 60 mm of its length.
            await zoom(page, 1.9);
            await tidy(page);
            // Both pictures cut to the motor, so that the second one is the
            // first one without it.
            const clip = await trimmed(page, await canvas(page));
            await shot(page, out('interface-orientation'), clip);
            await slide(await viewer(page), '#opacity-slider', 0);
            await tidy(page);
            await shot(page, out('interface-orientation-2'), clip);
        });
    },

    // Adding the part selected in the Explorer to an ASSY file by completion:
    // docs/source/tutorial.rst, "Add a part to the assembly".
    async 'assy-autocompletion'() {
        const assy = path.join(WORK, 'tutorial.assy');
        fs.writeFileSync(assy, 'links:\n');
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await select(page, 'example-bracket', 2);
            // Selecting it shows it, too; the completion only needs it selected.
            await command(page, 'View: Close All Editors');
            await openFile(page, assy);
            await page.keyboard.press('Control+End');
            await page.keyboard.type('- pa', { delay: 80 });
            await page.keyboard.press('Control+Space');
            await page.waitForSelector('.suggest-widget.visible', { timeout: 20000 });
            await sleep(1500);
            const editor = await page.locator('.editor-group-container .monaco-editor').first().boundingBox();
            const widget = await page.locator('.suggest-widget.visible').boundingBox();
            await shot(page, out('assy-autocompletion'), {
                x: editor.x,
                y: editor.y,
                width: Math.min(editor.width, widget.x + widget.width + 40 - editor.x),
                height: widget.y + widget.height + 12 - editor.y,
            });
            await page.keyboard.press('Enter');
            await sleep(1500);
            await page.mouse.move(editor.x + editor.width - 20, editor.y + editor.height - 20);
            await sleep(500);
            await shot(page, out('assy-autocompletion-done'), {
                x: editor.x,
                y: editor.y,
                width: Math.min(editor.width, 620),
                height: 19 * 7 + 8,
            });
        });
    },

    // --- The Digital Thread, one picture per tab ----------------------------
    //
    // docs/source/digital_thread/lifecycle/*.rst, each in its "In the UI"
    // section: one picture per phase ('dt-<phase>') and one per sub-tab of it
    // ('dt-<phase>-<tab>'). All of them are the panel alone rather than the
    // whole window: what is being shown is the tab, and the editor beside it
    // would be the same picture twenty times over.
    //
    // The first sub-tab of a group has no picture of its own, because the
    // group's own picture is taken on it: 'dt-analysis' *is* the FEA tab,
    // 'dt-manufacturing' is Build vs Buy, 'dt-validation' is Test. Those pages
    // use that file, and nothing here takes the same picture twice.
    //
    // The view panel stays folded in every picture but 'dt-design-3d', whose
    // page is about it.

    // Design: the object itself, and the tree of what it is made of.
    async 'dt-design'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'connect-mates', 2, 'connect-ports');
            await zoom(page, 1.5);
            await tidy(page);
            await shot(page, out('dt-design'), await panel(page));
        });
    },

    // The 3D tab with the view panel out: the gizmo, the axis views, the
    // section sliders and the viewpoint, which is what that page is about.
    async 'dt-design-3d'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 700 });
            await showStill(page, 'connect-mates', 2, 'connect-ports');
            await viewPanel(page, true);
            await tidy(page);
            await shot(page, out('dt-design-3d'), await panel(page));
        });
    },

    // The 2D tab: the object rendered to a picture, as 'pc render' renders it.
    async 'dt-design-2d'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'connect-mates', 2, 'connect-ports');
            await tab(page, 'design', '2d');
            await filled(page, '.render-body img, .render-body canvas, .image-view');
            await tidy(page);
            await shot(page, out('dt-design-2d'), await panel(page));
        });
    },

    // The Draft tab: a dimensioned drawing. The first one is slow - PartCAD
    // installs the drawing package into a sandbox before it can draw anything -
    // so this waits as long as 'filled' allows.
    async 'dt-design-draft'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'example-bracket', 2, 'example-motor');
            await tab(page, 'design', 'draft');
            await filled(page, '.render-body img, .render-body canvas, .image-view');
            await tidy(page);
            await shot(page, out('dt-design-draft'), await panel(page));
        });
    },

    // Analysis: the FEA tab of a part that declares scenarios of it, which is
    // the scenario list and what was found, not a run started by the shutter.
    async 'dt-analysis'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, ['feature_cae']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'cantilever', 2, 'pipe');
            await tab(page, 'analysis', 'fea');
            await tidy(page);
            await shot(page, out('dt-analysis'), await panel(page));
        });
    },

    // The other three analyses of the same part, each its own question. One
    // function, three names: what differs is the tab and the output file.
    ...Object.fromEntries(
        [
            ['dt-analysis-dynamic', 'dynamic', 'cantilever'],
            ['dt-analysis-thermal', 'thermal', 'cantilever'],
            ['dt-analysis-cfd', 'cfd', 'pipe'],
        ].map(([name, id, object]) => [
            name,
            async () => {
                await inVSCode(EXAMPLES, async (page) => {
                    await partcadView(page, ['Explorer']);
                    await expand(page, ['feature_cae']);
                    await openViewer(page);
                    await layout(page, { sidebar: 300, editor: 820 });
                    await showStill(page, object, 2, object === 'pipe' ? 'cantilever' : 'pipe');
                    await tab(page, 'analysis', id);
                    await filled(page, '.cae-model canvas, .cae-model img, .cae-findings-heading');
                    await tidy(page);
                    await shot(page, out(name), await panel(page));
                });
            },
        ]),
    ),

    // Manufacturing: Build vs Buy, the choice that decides the other four tabs.
    async 'dt-manufacturing'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, ['provider_manufacturer']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'assembly', 2, 'cylinder');
            await tab(page, 'manufacturing', 'bvb');
            await filled(page, '.bvb .thumbnail');
            await tidy(page);
            await shot(page, out('dt-manufacturing'), await panel(page));
        });
    },

    // Validation: every check 'pc test' runs, with its verdict. The checks are
    // run by opening the tab, so this one waits for a verdict to appear.
    async 'dt-validation'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'example-bracket', 2, 'example-motor');
            await tab(page, 'validation', 'test', 8000);
            await filled(page, '.test-verdict');
            await tidy(page);
            await shot(page, out('dt-validation'), await panel(page));
        });
    },

    // Build: the order to make something in. Nothing here clicks a switch in
    // Build vs Buy first, so the object has to be one whose lines can only be
    // built - and a part made *from stock* is not one: its stock is bought, so
    // its Build tab is disabled until somebody chooses to build it.
    // 'provider_manufacturer' is made by its provider, so both of its lines say
    // Build already, which is what 'dt-manufacturing' shows.
    async 'dt-manufacturing-build'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, ['provider_manufacturer']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'assembly', 2, 'cylinder');
            await tab(page, 'manufacturing', 'build');
            await filled(page, '.build-tree .build-node');
            await tidy(page);
            await shot(page, out('dt-manufacturing-build'), await panel(page));
        });
    },

    // Buy: what is bought, from whom, and for how much. It has to be an object
    // that is *bought*: 'provider_manufacturer's parts are made by their
    // provider, so both of its lines are built and its Buy tab is disabled.
    // 'provider_store:nut' is a gobilda part with a vendor and an SKU, in a
    // package that lists a supplier carrying it, so there is a quote to show.
    async 'dt-manufacturing-buy'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, ['provider_store']);
            // Loading what the alias points at goes on for a moment after the
            // row is there, and a request that arrives while it does can fail.
            await sleep(10000);
            await openViewer(page);
            await layout(page, { sidebar: 330, editor: 820 });
            await showStill(page, 'nut', 2, 'bracket');
            await tab(page, 'manufacturing', 'supply');
            await filled(page, 'table.grid, .option, .placeholder');
            await tidy(page);
            await shot(page, out('dt-manufacturing-buy'), await panel(page));
        });
    },

    // Bill of Materials: what has to be procured to have the assembly. An
    // assembly of several *different* things, so that the list is a list:
    // 'connect-mates' is a bracket, a motor and six screws of two sizes.
    async 'dt-manufacturing-bom'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'connect-mates', 2, 'connect-ports');
            await tab(page, 'manufacturing', 'bom');
            await filled(page, 'table.grid');
            await tidy(page);
            await shot(page, out('dt-manufacturing-bom'), await panel(page));
        });
    },

    // Assembly: the instruction book. 'connect-mates' is put together by
    // connections rather than by coordinates, so it has steps to write.
    async 'dt-manufacturing-assembly'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'connect-mates', 2, 'connect-ports');
            await tab(page, 'manufacturing', 'assembly');
            await filled(page, '.document-pages canvas, .document-pages img');
            await tidy(page);
            await shot(page, out('dt-manufacturing-assembly'), await panel(page));
        });
    },

    // Validation -> Simulation: a run, played back. Opening the tab runs the
    // first simulation the scene declares, which for 'stable' is a stack that
    // stands - the clearest before-and-after there is.
    async 'dt-validation-simulation'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, ['feature_simulate']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'stable', 2, 'unstable');
            await tab(page, 'validation', 'simulation', 8000);
            await filled(page, '.simulation-figure, .simulation-video-media, .simulation-pictures');
            await tidy(page);
            await shot(page, out('dt-validation-simulation'), await panel(page));
        });
    },

    // The Requirements tab, which is only there for an object that declares
    // 'requirements:'. Nothing under examples/ does - the tree is what PartCAD
    // renders and tests, and a requirement on an example would be one more
    // thing for its checks to be about - so this one writes a package of its
    // own, outside the repository, and opens VS Code on that.
    async 'dt-requirements'() {
        const folder = path.join(WORK, 'requirements');
        fs.mkdirSync(folder, { recursive: true });
        fs.writeFileSync(
            path.join(folder, 'partcad.yaml'),
            [
                'desc: A shelf bracket, with the requirements it was asked to meet',
                '',
                'interfaces:',
                '  mount:',
                '    desc: Where the bracket bolts to the wall',
                '    ports:',
                '      hole: [[0, 0, 2.5], [0, 0, 1], 0]',
                '',
                'parts:',
                '  bracket:',
                '    type: build123d',
                '    path: bracket.py',
                '    desc: An L bracket that carries a shelf',
                '    implements:',
                '      mount: [[-20, 0, 0], [0, 0, 1], 0]',
                '    requirements:',
                '      features:',
                '        mounting: Bolts to the wall through the holes of a 40 mm square, from the front',
                '        shelf-load: Holds a 2 kg shelf at its free end without visible bending',
                '      interfaces:',
                '        mount: null',
                '      physics:',
                '        mass: "<0.05"',
                '',
            ].join('\n'),
        );
        fs.writeFileSync(
            path.join(folder, 'bracket.py'),
            [
                'from build123d import *',
                '',
                'with BuildPart() as bracket:',
                '    Box(50, 40, 5)',
                '    with Locations(Plane.XY.offset(0)):',
                '        with GridLocations(40, 30, 2, 2):',
                '            Hole(1.6)',
                '',
                'show_object(bracket.part)',
                '',
            ].join('\n'),
        );
        await inVSCode(folder, async (page) => {
            await partcadView(page, ['Explorer']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await select(page, 'bracket');
            await shown(page, 'bracket');
            // Selecting a scripted part opens its script, and with no editor
            // open yet that lands on top of the Digital Thread - whose tabs are
            // then not on screen, and not clickable. Ask for it again.
            await openViewer(page);
            await tab(page, 'requirements', 8000);
            await filled(page, 'table.grid.requirement-features');
            await tidy(page);
            await shot(page, out('dt-requirements'), await panel(page));
        });
    },

    // --- The simulation examples --------------------------------------------
    //
    // docs/source/digital_thread/lifecycle/simulation.rst, "Examples". The
    // first of the three is 'dt-validation-simulation' above, which is that
    // package's 'stable'.

    // A mechanism: the pendulum, held to its closed form.
    async 'sim-example-pendulum'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, ['feature_simulate_joints']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'pendulum', 2, 'nudged');
            await tab(page, 'validation', 'simulation', 8000);
            await filled(page, '.simulation-figure, .simulation-video-media, .simulation-pictures');
            await tidy(page);
            await shot(page, out('sim-example-pendulum'), await panel(page));
        });
    },

    // The arm whose simulation an FEA scenario is then written from.
    async 'sim-example-arm'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, ['feature_simulate_fea']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'arm', 2, 'knee-gear');
            await tab(page, 'validation', 'simulation', 8000);
            await filled(page, '.simulation-figure, .simulation-video-media, .simulation-pictures');
            await tidy(page);
            await shot(page, out('sim-example-arm'), await panel(page));
        });
    },

    // --- A result per plugin kind -------------------------------------------

    // A part built by a package-defined partType: docs/source/plugins/part_types.rst.
    async 'plugin-part-type'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            // Two packages, because 'produce_part_wrapper' holds one object and
            // framing a show the same way every time needs a second one to show
            // in between. 'produce_part_sweep' is that second one because it is
            // the package immediately above this one: 'row()' finds a row by
            // scrolling to it, so two packages far apart in the tree is two
            // searches of a long tree and one of them runs out of time.
            await expand(page, ['produce_part_sweep']);
            await expand(page, ['produce_part_wrapper']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            // No zoom: a show already frames this one, and a box fills the frame.
            await showStill(page, 'demo', 2, 'pipe');
            await tidy(page);
            await shot(page, out('plugin-part-type'), await panel(page));
        });
    },

    // A part served by a repository plugin rather than by a file:
    // docs/source/plugins/repositories.rst. 'example' is a package with no
    // source tree at all - the CSV plugin beside it answers for it.
    async 'plugin-repository'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, ['plugin_repository_basic', 'example']);
            await openViewer(page);
            await layout(page, { sidebar: 330, editor: 820 });
            await showStill(page, 'bolt', 3, 'cube');
            await zoom(page, 1.5);
            await tidy(page);
            await shot(page, out('plugin-repository'), await panel(page));
        });
    },

    // Running the integration tests in the dev container, from VS Code's
    // terminal: docs/source/contributing.rst.
    async 'vs-code-behave'() {
        await inVSCode(REPO, async (page) => {
            await command(page, 'View: Close Primary Side Bar');
            await command(page, 'Terminal: Create New Terminal');
            await sleep(2000);
            await command(page, 'View: Toggle Maximized Panel');
            await terminal(page, 'clear; npx --yes @devcontainers/cli exec --workspace-folder . poetry run behave features/config.feature');
            // behave's summary, at the end of the run.
            await terminalShows(page, /\d+ steps? passed/);
            await sleep(3000);
            await tidy(page);
            await shot(page, out('vs-code-behave'));
        });
    },
};

const vsix = process.env.PC_SCREENSHOT_VSIX ?? path.join(REPO, 'ide', 'vscode', 'partcad.vsix');
if (!fs.existsSync(vsix)) {
    throw new Error(`No ${vsix}: run 'npm run vsce-package' in ide/vscode first`);
}
fs.mkdirSync(WORK, { recursive: true });
fs.rmSync(EXTENSIONS, { recursive: true, force: true });
installExtension(CODE, PROFILE, EXTENSIONS, vsix);

const wanted = process.argv.slice(2);
for (const name of wanted.length ? wanted : Object.keys(SHOTS)) {
    const take = SHOTS[name];
    if (!take) {
        throw new Error(`No screenshot '${name}'; known: ${Object.keys(SHOTS).join(', ')}`);
    }
    console.log(`taking ${name}`);
    await take();
}
