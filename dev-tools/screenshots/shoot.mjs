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
    explorerTop,
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
    showStill,
    sleep,
    slide,
    terminal,
    terminalShows,
    tidy,
    trimmed,
    viewer,
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
            // Every row down to the selected one fits in the pane from the top.
            await explorerTop(page);
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
            await tidy(page);
            await shot(page, out('vscode2'));
        });
    },

    // A port, and the sketch that is its boundary, as the Digital Thread draws
    // them: docs/source/config_geometry.rst, "Port boundary".
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
