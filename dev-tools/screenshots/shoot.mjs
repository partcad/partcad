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
    webviewFrame,
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

// The package docs/source/tutorial_printed_stand.rst builds, as it stands at its
// step 11. Each picture is of a copy of it in the work directory, changed the
// way the tutorial has changed it by then.
const TUTORIAL_STAND = path.join(REPO, 'dev-tools', 'screenshots', 'tutorial-stand');

/**
 * The window below its title bar, as a rectangle to cut a screenshot to.
 *
 * The title bar names the folder, and -- where the editor runs as root, as it
 * does in a container -- says '[Superuser]' after it, which is about the machine
 * the picture was taken on and not about anything the picture shows.
 */
async function belowTitle(page) {
    const title = await page.locator('.part.titlebar').first().boundingBox();
    const size = page.viewportSize() ?? (await page.evaluate(() => ({ width: innerWidth, height: innerHeight })));
    const top = title ? title.y + title.height : 0;
    return { x: 0, y: top, width: size.width, height: size.height - top };
}

/** A fresh copy of the tutorial's package, its 'partcad.yaml' put through 'change'. */
function tutorialStand(change = (text) => text) {
    const folder = path.join(WORK, 'printed-stand');
    fs.rmSync(folder, { recursive: true, force: true });
    fs.mkdirSync(folder, { recursive: true });
    const yaml = fs.readFileSync(path.join(TUTORIAL_STAND, 'partcad.yaml'), 'utf8');
    fs.writeFileSync(path.join(folder, 'partcad.yaml'), change(yaml));
    fs.copyFileSync(path.join(TUTORIAL_STAND, 'stand-with-block.assy'), path.join(folder, 'stand-with-block.assy'));
    return folder;
}

// Step 9 is the scenario as the skill writes it, which says nothing about how far
// the stand may move; step 10 adds that by hand.
const withoutParams = (text) => text.replace(/\n {8}params:\n(?: {10}.*\n)+/, '\n');
// Step 13: printed denser.
const denser = (text) => text.replace('infill: 10%', 'infill: 40%');

/** The Digital Thread on 'object' of the tutorial's package, on the tab 'group'/'sub'. */
async function tutorialObject(page, object, group, sub, { assembly = false, editor = 640 } = {}) {
    await partcadView(page, ['Explorer']);
    if (assembly) {
        // An assembly's row opens its ASSY file in the editor group the
        // Digital Thread would open in: selected first, the file goes there
        // and the Digital Thread beside it.
        await select(page, object, 1);
    }
    await openViewer(page);
    await layout(page, { sidebar: 300, editor });
    await showStill(page, object, 1);
    if (group) {
        await tab(page, group, sub, 8000);
    }
}

/** Run 'line' in a terminal of its own, maximized, and wait for 'pattern'. */
async function tutorialTerminal(page, line, pattern) {
    await command(page, 'View: Close Primary Side Bar');
    await command(page, 'Terminal: Create New Terminal');
    await sleep(2000);
    await command(page, 'View: Toggle Maximized Panel');
    // Cleared first, on its own: a 'clear' on the same line would clear the
    // command off the picture with everything else.
    await terminal(page, 'clear');
    await sleep(1000);
    await terminal(page, line);
    await terminalShows(page, pattern);
    await sleep(2000);
}

// Where the stand's top is cut to show its inside: 62 mm up its 64, half way
// through the top's 4 mm, between its solid skins. In the view panel's steps,
// a thousand from the bottom of the object to its top.
const THROUGH_THE_TOP = Math.round((62 / 64) * 1000);

/**
 * Cut the shown object with the Z slider of the view panel of 'pane' -- every tab that draws in 3D has a panel of
 * its own -- and wait for the cut geometry to arrive.
 */
async function tutorialSection(page, pane = '3d') {
    await viewPanel(page, true);
    const frame = await viewer(page);
    await slide(frame, `#pane-${pane} input[aria-label="Z to"]`, THROUGH_THE_TOP);
    // The panel says it is cutting while the daemon works; the preview is up at
    // once and the cut geometry replaces it when it comes.
    const deadline = Date.now() + 900000;
    for (;;) {
        await sleep(3000);
        const { busy, failed } = await frame.evaluate((id) => {
            const notes = [...document.querySelectorAll(`#pane-${id} .view-note`)];
            const error = notes.find((note) => note.classList.contains('error') && note.textContent.trim());
            return {
                busy: notes.some((note) => /cutting|loading/i.test(note.textContent)),
                failed: error ? error.textContent.trim() : undefined,
            };
        }, pane);
        // A cut that failed leaves what was drawn before on the stage: a picture
        // of that is not a picture of the section.
        if (failed) {
            throw new Error(`the section could not be drawn: ${failed}`);
        }
        if (!busy) {
            break;
        }
        if (Date.now() > deadline) {
            throw new Error('the section never arrived');
        }
    }
    await sleep(3000);
    // Looked at more from above and closer, once the cut has arrived (a new
    // geometry is fitted to the view): a line of infill is a millimetre wide,
    // and the whole stand is 120.
    await orbit(page, { up: 35 });
    await zoom(page, 1.25);
}

/** The FEA tab of the stand, once it has run its scenario. */
async function tutorialFea(page) {
    await tutorialObject(page, 'stand', 'analysis', 'fea');
    // Opening the tab runs the scenario: the print first, then the solver.
    await filled(page, '.cae-model canvas');
    await sleep(3000);
}

function tutorialStandShots() {
    const name = (step) => `tutorial-stand-${step}`;
    return {
        // Step 1: the package 'pc init' writes, open in the IDE.
        async [name('01-package')]() {
            const folder = path.join(WORK, 'printed-stand-new');
            fs.rmSync(folder, { recursive: true, force: true });
            fs.mkdirSync(folder, { recursive: true });
            spawnSync(PC, ['--no-ansi', 'init'], { cwd: folder, stdio: 'ignore' });
            await inVSCode(folder, async (page) => {
                await partcadView(page, ['Explorer']);
                await openFile(page, path.join(folder, 'partcad.yaml'));
                await layout(page, { sidebar: 300 });
                await tidy(page);
                await shot(page, out(name('01-package')), await belowTitle(page));
            });
        },

        // Step 3: the design, solid, in the 3D view.
        async [name('02-design')]() {
            await inVSCode(tutorialStand(), async (page) => {
                await tutorialObject(page, 'stand-design');
                await tidy(page);
                await shot(page, out(name('02-design')), await panel(page));
            });
        },

        // Step 4: the print, cut through its top: walls, skins and the sparse
        // infill between them.
        async [name('03-print')]() {
            await inVSCode(tutorialStand(), async (page) => {
                await tutorialObject(page, 'stand');
                // The names of its feet and its pad, which step 2 was about, are
                // in the way of its inside, which this step is about.
                const frame = await viewer(page);
                await frame.evaluate(() => {
                    for (const label of document.querySelectorAll('#pane-3d label.control-label')) {
                        const box = label.querySelector('input[type="checkbox"]');
                        if (box?.checked && /^(Port|Interface) names$/.test(label.textContent.trim())) {
                            box.click();
                        }
                    }
                });
                await sleep(2000);
                await tutorialSection(page);
                await tidy(page);
                await shot(page, out(name('03-print')), await panel(page));
            });
        },

        // Step 6: the block on the stand.
        async [name('04-assembly')]() {
            await inVSCode(tutorialStand(), async (page) => {
                await tutorialObject(page, 'stand-with-block', null, null, { assembly: true });
                await tidy(page);
                await shot(page, out(name('04-assembly')), await panel(page));
            });
        },

        // Step 7: the simulation, passed, with what holds the assembly up.
        async [name('05-simulation')]() {
            await inVSCode(tutorialStand(), async (page) => {
                await tutorialObject(page, 'stand-with-block', 'qualification', 'simulation', {
                    assembly: true,
                    editor: 260,
                });
                await filled(page, '.simulation-figure, .simulation-video-media, .simulation-pictures');
                const frame = await webviewFrame(page, 'button.simulation-detail-tab[data-detail="after"]');
                await frame.locator('button.simulation-detail-tab[data-detail="after"]').first().evaluate((b) => b.click());
                await sleep(1500);
                // What the step is about is the loads, further down the state
                // than the panel is tall: scrolled to, in whatever scrolls them.
                await frame.evaluate(() => {
                    const shown = [...document.querySelectorAll('pre, code')].find((e) => e.textContent.includes('"loads"'));
                    if (!shown) {
                        return;
                    }
                    const lines = shown.textContent.split('\n');
                    const at = lines.findIndex((line) => line.includes('"loads"'));
                    for (let box = shown; box; box = box.parentElement) {
                        if (box.scrollHeight > box.clientHeight + 4) {
                            box.scrollTop = (shown.scrollHeight / lines.length) * Math.max(at - 3, 0);
                            break;
                        }
                    }
                });
                await sleep(500);
                await tidy(page);
                await shot(page, out(name('05-simulation')), await panel(page));
            });
        },

        // Step 8: the same simulation in the terminal, and what it ended in.
        async [name('06-cli-simulation')]() {
            await inVSCode(tutorialStand(), async (page) => {
                await tutorialTerminal(
                    page,
                    'pc --no-ansi qual test --simulation -a stand-with-block -f stands --after after.yaml 2>&1 | tail -3; cat after.yaml',
                    /joints:/,
                );
                await tidy(page);
                await shot(page, out(name('06-cli-simulation')), await belowTitle(page));
            });
        },

        // Step 9: the scenario the skill adds, in the editor.
        async [name('07-scenario')]() {
            const folder = tutorialStand(withoutParams);
            await inVSCode(folder, async (page) => {
                await partcadView(page, ['Explorer']);
                await openFile(page, path.join(folder, 'partcad.yaml'));
                await lineOf(page, path.join(folder, 'partcad.yaml'), /^ {4}fea:/, /^ {8}gravity:/);
                await tidy(page);
                await shot(page, out(name('07-scenario')), await belowTitle(page));
            });
        },

        // Step 10: the same, with how far it may move said by hand.
        async [name('08-yaml')]() {
            const folder = tutorialStand();
            await inVSCode(folder, async (page) => {
                await partcadView(page, ['Explorer']);
                await openFile(page, path.join(folder, 'partcad.yaml'));
                await lineOf(page, path.join(folder, 'partcad.yaml'), /^ {8}params:/, /max_displacement:/);
                await tidy(page);
                await shot(page, out(name('08-yaml')), await belowTitle(page));
            });
        },

        // Step 11: the analysis, failed.
        async [name('09-fea-fails')]() {
            await inVSCode(tutorialStand(), async (page) => {
                await tutorialFea(page);
                await filled(page, '.cae-finding');
                await tidy(page);
                await shot(page, out(name('09-fea-fails')), await panel(page));
            });
        },

        // Step 12: the check, failed, in the terminal.
        async [name('10-cli-fails')]() {
            await inVSCode(tutorialStand(), async (page) => {
                await tutorialTerminal(page, 'pc --no-ansi qual test -f fea :stand; echo "exit status $?"', /exit status \d/);
                await tidy(page);
                await shot(page, out(name('10-cli-fails')), await belowTitle(page));
            });
        },

        // Step 13: the CAM tab, the infill raised to 40% and not saved yet, cut
        // through the top as in step 4.
        async [name('11-cam')]() {
            await inVSCode(tutorialStand(), async (page) => {
                await tutorialObject(page, 'stand', 'design', 'cam');
                await filled(page, '.cam-field');
                const frame = await webviewFrame(page, 'input.cam-field[aria-label="Infill"]');
                await frame.locator('input.cam-field[aria-label="Infill"]').evaluate((input) => {
                    input.value = '40%';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                });
                // The print is made again with the new infill before anything is cut.
                await sleep(5000);
                await tutorialSection(page, 'cam');
                await tidy(page);
                await shot(page, out(name('11-cam')), await panel(page));
            });
        },

        // Step 13: the check again, printed denser.
        async [name('12-cli-passes')]() {
            await inVSCode(tutorialStand(denser), async (page) => {
                await tutorialTerminal(page, 'pc --no-ansi qual test -f fea :stand; echo "exit status $?"', /exit status \d/);
                await tidy(page);
                await shot(page, out(name('12-cli-passes')), await belowTitle(page));
            });
        },

        // Step 14: the analysis, passed.
        async [name('13-fea-passes')]() {
            await inVSCode(tutorialStand(denser), async (page) => {
                await tutorialFea(page);
                await tidy(page);
                await shot(page, out(name('13-fea-passes')), await panel(page));
            });
        },
    };
}

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
            await showStill(page, 'examples/wormgear', 5);
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
            await showStill(page, 'connect-mates', 2);
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
            await showStill(page, 'm3', 2);
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
            await showStill(page, 'example-motor', 2);
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
    // 'dt-manufacturing' is Build vs Buy, 'dt-validation' is Qualification -> Basic. Those pages
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
            await showStill(page, 'connect-mates', 2);
            await zoom(page, 1.5);
            await tidy(page);
            await shot(page, out('dt-design'), await panel(page));
        });
    },

    // The 3D tab with the view panel out: the gizmo, the axis views, the
    // viewpoint with its projection and the section sliders, which is what
    // that page is about.
    async 'dt-design-3d'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 700 });
            await showStill(page, 'connect-mates', 2);
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
            await showStill(page, 'connect-mates', 2);
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
            await showStill(page, 'example-bracket', 2);
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
            await showStill(page, 'cantilever', 2);
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
                    await showStill(page, object, 2);
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
            await showStill(page, 'assembly', 2);
            await tab(page, 'manufacturing', 'bvb');
            await filled(page, '.bvb .thumbnail');
            await tidy(page);
            await shot(page, out('dt-manufacturing'), await panel(page));
        });
    },

    // Qualification -> Basic: every basic test 'pc qual test' runs, with its verdict. The tests are
    // run by opening the tab, so this one waits for a verdict to appear.
    async 'dt-validation'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, FEATURE_INTERFACE);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'example-bracket', 2);
            await tab(page, 'qualification', 'basic', 8000);
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
            await showStill(page, 'assembly', 2);
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
            await showStill(page, 'nut', 2);
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
            await showStill(page, 'connect-mates', 2);
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
            await showStill(page, 'connect-mates', 2);
            await tab(page, 'manufacturing', 'assembly');
            await filled(page, '.document-pages canvas, .document-pages img');
            await tidy(page);
            await shot(page, out('dt-manufacturing-assembly'), await panel(page));
        });
    },

    // Qualification -> Simulation: a run, played back. Opening the tab runs the
    // first simulation the scene declares, which for 'stable' is a stack that
    // stands - the clearest before-and-after there is.
    async 'dt-validation-simulation'() {
        await inVSCode(EXAMPLES, async (page) => {
            await partcadView(page, ['Explorer']);
            await expand(page, ['feature_simulate']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            await showStill(page, 'stable', 2);
            await tab(page, 'qualification', 'simulation', 8000);
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
            await showStill(page, 'pendulum', 2);
            await tab(page, 'qualification', 'simulation', 8000);
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
            await showStill(page, 'arm', 2);
            await tab(page, 'qualification', 'simulation', 8000);
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
            await expand(page, ['produce_part_wrapper']);
            await openViewer(page);
            await layout(page, { sidebar: 300, editor: 820 });
            // No zoom: a show already frames this one, and a box fills the frame.
            await showStill(page, 'demo', 2);
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
            await showStill(page, 'bolt', 3);
            await zoom(page, 1.5);
            await tidy(page);
            await shot(page, out('plugin-repository'), await panel(page));
        });
    },

    // Running the integration tests in the dev container, from VS Code's
    // terminal: docs/source/contributing.rst.
    // The tutorial "A printed stand under load", a picture per step: see
    // TUTORIAL_STAND below.
    ...tutorialStandShots(),

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

// 'builtin' for an application that carries the extension already -- the
// PartCAD IDE, which refuses to have a built-in extension replaced: swap the
// one under its 'resources/app/extensions' for the checkout's instead (see
// docs/notes/screenshots.md).
/**
 * Select the lines of the editor's file from the first that matches 'pattern' to the first after it that
 * matches 'until' (or that one line alone), so that the picture points at them.
 */
async function lineOf(page, file, pattern, until = null) {
    const lines = fs.readFileSync(file, 'utf8').split('\n');
    const index = lines.findIndex((line) => pattern.test(line));
    if (index < 0) {
        throw new Error(`no line of ${file} matches ${pattern}`);
    }
    const last = until ? lines.findIndex((line, at) => at > index && until.test(line)) : index;
    await command(page, 'Go to Line/Column...');
    await page.keyboard.type(String(index + 1), { delay: 10 });
    await page.keyboard.press('Enter');
    await sleep(500);
    await command(page, 'View: Scroll Line Up');
    for (let at = index; at <= Math.max(last, index); at++) {
        await page.keyboard.press('Control+L');
    }
    await sleep(800);
}

const vsix = process.env.PC_SCREENSHOT_VSIX ?? path.join(REPO, 'ide', 'vscode', 'partcad.vsix');
fs.mkdirSync(WORK, { recursive: true });
fs.rmSync(EXTENSIONS, { recursive: true, force: true });
if (vsix !== 'builtin') {
    if (!fs.existsSync(vsix)) {
        throw new Error(`No ${vsix}: run 'npm run vsce-package' in ide/vscode first`);
    }
    installExtension(CODE, PROFILE, EXTENSIONS, vsix);
}

const wanted = process.argv.slice(2);
for (const name of wanted.length ? wanted : Object.keys(SHOTS)) {
    const take = SHOTS[name];
    if (!take) {
        throw new Error(`No screenshot '${name}'; known: ${Object.keys(SHOTS).join(', ')}`);
    }
    console.log(`taking ${name}`);
    await take();
}
