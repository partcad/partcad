//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Drive a throwaway VS Code over the DevTools protocol, and take pictures of it.
//
// Everything a screenshot needs is done the way a person would do it - the
// command palette, a click on a row of the PartCAD Explorer, keys typed into the
// terminal - so that what is captured is what a user sees. See
// docs/notes/screenshots.md for why each choice below was made.

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright-core';

export { sleep };

// The window, in CSS pixels, and how many device pixels each of them is. Twice
// the size of a 1792 x 1064 window is what the screenshots this replaced were
// (a Retina MacBook's), and what keeps text sharp when a page scales one down.
export const WIDTH = 1792;
export const HEIGHT = 1064;
export const SCALE = 2;

// The Digital Thread's port for this VS Code, so that what PartCAD shows reaches
// this window and not a VS Code of your own (see 'PARTCAD_IDE_PORT').
export const IDE_PORT = '9238';

const DEVTOOLS_PORT = 9339;

/**
 * Start VS Code on 'folder' and connect to it.
 *
 * 'profile' is a directory of its own for this one run: VS Code's user data
 * there is created from 'settings' every time, so nothing a previous run left
 * open - an editor, a panel's size - leaks into this one.
 */
export async function launch({ code, profile, extensions, settings, folder, env = {} }) {
    fs.rmSync(profile, { recursive: true, force: true });
    fs.mkdirSync(path.join(profile, 'User'), { recursive: true });
    fs.writeFileSync(path.join(profile, 'User', 'settings.json'), JSON.stringify(settings, null, 2));
    const args = [
        `--user-data-dir=${profile}`,
        `--extensions-dir=${extensions}`,
        `--remote-debugging-port=${DEVTOOLS_PORT}`,
        `--force-device-scale-factor=${SCALE}`,
        // A VS Code downloaded for testing has no setuid sandbox helper; its own
        // test runner starts it this way too.
        '--no-sandbox',
        // Keep drawing while another window covers this one, as it will
        // while a run goes on on somebody's desktop: a window Chromium thinks
        // nobody can see produces no frames, and a screenshot waits for one.
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--disable-background-timer-throttling',
        // Let Chromium draw WebGL in software where there is no graphics card
        // (a virtual display, a cloud machine). Without it the Digital Thread
        // falls back to its canvas painter and says "Drawn without a graphics
        // card" in the picture; with a GPU this changes nothing.
        '--enable-unsafe-swiftshader',
        '--disable-workspace-trust',
        '--skip-release-notes',
        '--skip-welcome',
        '--disable-telemetry',
        '--new-window',
        folder,
    ];
    const child = spawn(code, args, {
        env: { ...process.env, PARTCAD_IDE_PORT: IDE_PORT, ...env },
        stdio: 'ignore',
        detached: true,
    });
    child.unref();

    let browser;
    for (let i = 0; i < 120 && !browser; i++) {
        try {
            browser = await chromium.connectOverCDP(`http://127.0.0.1:${DEVTOOLS_PORT}`);
        } catch {
            await sleep(500);
        }
    }
    if (!browser) {
        throw new Error('VS Code did not open its DevTools port');
    }
    let page;
    for (let i = 0; i < 120 && !page; i++) {
        for (const context of browser.contexts()) {
            for (const candidate of context.pages()) {
                if (candidate.url().includes('workbench')) {
                    page = candidate;
                }
            }
        }
        if (!page) {
            await sleep(500);
        }
    }
    if (!page) {
        throw new Error('VS Code opened no window');
    }
    await page.waitForSelector('.monaco-workbench', { timeout: 60000 });
    // The window's real size is whatever the desktop gave it; the picture is
    // drawn at this one instead, whatever the screen.
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: WIDTH,
        height: HEIGHT,
        deviceScaleFactor: SCALE,
        mobile: false,
    });
    // A window where nothing moves stops producing frames, and a screenshot is
    // a wait for the next one: every capture after the first then times out.
    // The Digital Thread redraws all the time and hides this; a window without
    // it does not. So one pixel in the corner is redrawn on every frame, at an
    // opacity no picture can show.
    await page.evaluate(() => {
        const dot = document.createElement('div');
        dot.style.cssText =
            'position:fixed;right:0;bottom:0;width:1px;height:1px;pointer-events:none;z-index:100000;background:#000';
        document.body.appendChild(dot);
        let odd = false;
        const tick = () => {
            odd = !odd;
            dot.style.opacity = odd ? '0.01' : '0.02';
            requestAnimationFrame(tick);
        };
        tick();
    });
    return {
        page,
        async close() {
            await browser.close().catch(() => {});
            // Not asked to quit: a window with a terminal running in it asks
            // whether to end that first, and nobody is there to answer.
            try {
                process.kill(-child.pid, 'SIGKILL');
            } catch {
                // already gone
            }
            await sleep(2000);
        },
    };
}

/**
 * The command line half of a VS Code: 'bin/code' beside the binary, which runs
 * the same program as a CLI rather than opening a window.
 */
export function cli(code) {
    return path.join(path.dirname(code), 'bin', 'code');
}

/** Install a '.vsix' into an extensions directory, with the VS Code that will load it. */
export function installExtension(code, profile, extensions, vsix) {
    const result = spawnSync(
        cli(code),
        [`--user-data-dir=${profile}`, `--extensions-dir=${extensions}`, '--install-extension', vsix, '--force'],
        { encoding: 'utf8', timeout: 300000 },
    );
    if (result.status !== 0) {
        throw new Error(`could not install ${vsix}: ${result.stderr}`);
    }
}

/** Run a command by the title the command palette shows for it. */
export async function command(page, title) {
    await page.keyboard.press('Control+Shift+P');
    await page.waitForSelector('.quick-input-widget input', { state: 'visible', timeout: 10000 });
    await page.keyboard.type(title, { delay: 10 });
    await sleep(500);
    await page.keyboard.press('Enter');
    await sleep(800);
}

/** Type a line into the terminal and run it. */
export async function terminal(page, line) {
    await command(page, 'Terminal: Focus Terminal');
    await sleep(500);
    await page.keyboard.type(line, { delay: 5 });
    await page.keyboard.press('Enter');
}

/** The bounding box of a part of the workbench: 'sidebar', 'editor', 'panel', ... */
export async function part(page, name) {
    return await page.locator(`[id="workbench.parts.${name}"]`).boundingBox();
}

/** Drag the vertical sash nearest to 'x' over to 'toX'. */
async function dragVerticalSash(page, x, toX, minY = 0) {
    const sashes = await page.$$eval('.monaco-sash.vertical', (els) =>
        els.map((e) => {
            const r = e.getBoundingClientRect();
            return { x: r.left + r.width / 2, y: r.top + r.height / 2, ok: r.width > 0 && r.height > 50 };
        }),
    );
    const sash = sashes
        .filter((s) => s.ok && s.y >= minY)
        .sort((a, b) => Math.abs(a.x - x) - Math.abs(b.x - x))[0];
    await page.mouse.move(sash.x, sash.y);
    await page.mouse.down();
    await page.mouse.move(toX, sash.y, { steps: 10 });
    await page.mouse.up();
    await sleep(500);
}

/**
 * Lay the window out: the side bar 'sidebar' wide, the first editor group
 * 'editor' wide (the Digital Thread beside it takes the rest), and the panel
 * 'panel' high - all in CSS pixels.
 */
export async function layout(page, { sidebar, editor, panel } = {}) {
    if (sidebar !== undefined) {
        const box = await part(page, 'sidebar');
        await dragVerticalSash(page, box.x + box.width, box.x + sidebar);
    }
    if (editor !== undefined) {
        const groups = await page.$$eval('.editor-group-container', (els) =>
            els.map((e) => e.getBoundingClientRect().toJSON()).sort((a, b) => a.x - b.x),
        );
        if (groups.length > 1) {
            await dragVerticalSash(page, groups[0].x + groups[0].width, groups[0].x + editor, groups[0].y);
        }
    }
    if (panel !== undefined) {
        const box = await part(page, 'panel');
        const sashes = await page.$$eval('.monaco-sash.horizontal', (els) =>
            els.map((e) => e.getBoundingClientRect().toJSON()),
        );
        const sash = sashes
            .filter((s) => s.width > 200)
            .sort((a, b) => Math.abs(a.y - box.y) - Math.abs(b.y - box.y))[0];
        const x = sash.x + sash.width / 2;
        await page.mouse.move(x, sash.y + sash.height / 2);
        await page.mouse.down();
        await page.mouse.move(x, box.y + box.height - panel, { steps: 10 });
        await page.mouse.up();
        await sleep(500);
    }
}

/** Show the PartCAD side bar, with these of its panes expanded. */
export async function partcadView(page, expand = []) {
    // The command rather than a click on the activity bar: a click on the view
    // that is already showing hides the side bar instead.
    await command(page, 'View: Show PartCAD');
    await sleep(1500);
    for (const name of expand) {
        const header = page.locator(`.pane-header[aria-label^="${name}"]`).first();
        if ((await header.getAttribute('aria-expanded')) !== 'true') {
            await header.click();
            await sleep(1000);
        }
    }
}

/** Give the side bar's pane 'name' 'height' CSS pixels, by dragging the sash above it. */
export async function paneHeight(page, name, height) {
    const header = await page.locator(`.pane-header[aria-label^="${name}"]`).first().boundingBox();
    const sidebar = await part(page, 'sidebar');
    const sashes = await page.$$eval('.monaco-sash.horizontal', (els) => els.map((e) => e.getBoundingClientRect().toJSON()));
    const sash = sashes
        .filter((s) => s.x >= sidebar.x - 2 && s.x + s.width <= sidebar.x + sidebar.width + 2 && s.width > 50)
        .sort((a, b) => Math.abs(a.y - header.y) - Math.abs(b.y - header.y))[0];
    const x = sash.x + sash.width / 2;
    await page.mouse.move(x, sash.y + sash.height / 2);
    await page.mouse.down();
    await page.mouse.move(x, sidebar.y + sidebar.height - height - header.height, { steps: 10 });
    await page.mouse.up();
    await sleep(500);
}

const ROWS = '.pane-body .monaco-list-row';

/**
 * The PartCAD Explorer row that reads 'text' at depth 'level' (1 is the top).
 *
 * Matched on what the row shows, not on its accessible name: an object's
 * accessible name is its description, which is long and changes.
 */
async function findRow(page, text, level) {
    for (const row of await page.$$(ROWS)) {
        if (level !== undefined && (await row.getAttribute('aria-level')) !== String(level)) {
            continue;
        }
        const label = await row.$('.label-name, .monaco-highlighted-label');
        if (label && (await label.textContent()).trim() === text) {
            return row;
        }
    }
    return undefined;
}

/**
 * Wait for an Explorer row to appear, and return it.
 *
 * The Explorer only puts the rows on screen in the page, so a row further down
 * is looked for by scrolling down to it - and a row that is not there yet, by
 * scrolling back up and waiting for the package to finish loading.
 */
export async function row(page, text, level, timeout = 240000) {
    const deadline = Date.now() + timeout;
    const explorer = page.locator('.pane-header[aria-label^="Explorer"] + .pane-body').first();
    for (;;) {
        for (let scrolls = 0; scrolls < 40; scrolls++) {
            const found = await findRow(page, text, level);
            if (found) {
                await found.scrollIntoViewIfNeeded();
                return found;
            }
            const box = await explorer.boundingBox();
            await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
            await page.mouse.wheel(0, box.height / 2);
            await sleep(200);
        }
        const box = await explorer.boundingBox();
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await page.mouse.wheel(0, -100000);
        if (Date.now() > deadline) {
            throw new Error(`no Explorer row '${text}' at level ${level}`);
        }
        await sleep(1000);
    }
}

/** Expand Explorer rows, one per level, each waiting for the one before it to load. */
export async function expand(page, texts) {
    for (let i = 0; i < texts.length; i++) {
        const found = await row(page, texts[i], i + 1);
        if ((await found.getAttribute('aria-expanded')) !== 'true') {
            await (await found.$('.monaco-tl-twistie')).click();
            await sleep(1500);
        }
    }
}

/** Select an Explorer row: PartCAD shows what it is in the Inspector and the Digital Thread. */
export async function select(page, text, level) {
    await (await row(page, text, level)).click();
    await sleep(1500);
}

/** Click one of the actions a row offers on hover ('Edit', ...). */
export async function rowAction(page, text, level, action) {
    const found = await row(page, text, level);
    await found.hover();
    await sleep(300);
    await (await found.$(`.action-label[aria-label="${action}"]`)).click();
    await sleep(1500);
}

/** The webview frame with an element matching 'selector' in it. */
export async function webviewFrame(page, selector, timeout = 60000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
        for (const frame of page.frames()) {
            try {
                if (await frame.$(selector)) {
                    return frame;
                }
            } catch {
                // a frame that went away while it was being asked
            }
        }
        await sleep(500);
    }
    throw new Error(`no webview has ${selector}`);
}

/** The Digital Thread. */
export async function viewer(page) {
    return await webviewFrame(page, '#viewer');
}

/** Stop the 3D view turning on its own, so that every show is framed the same way. */
export async function stopTurning(page) {
    const box = (await viewer(page)).locator('#animate-checkbox');
    if (await box.isChecked()) {
        await box.click();
    }
}

/**
 * Wait until the 3D view has drawn 'name' - what its object tree calls the
 * object at its root, the same text the Explorer shows.
 *
 * The name and not only the loading overlay: the overlay is already out of the
 * way from the show before, for the moment it takes the next one to arrive.
 */
export async function shown(page, name, timeout = 600000) {
    const frame = await viewer(page);
    const deadline = Date.now() + timeout;
    // Polled from here rather than with 'waitForFunction', which evaluates a
    // string in the page - and the webview's content security policy forbids
    // that.
    for (;;) {
        const done = await frame.evaluate((expected) => {
            const overlay = document.getElementById('overlay');
            const root = document.querySelector('#tree .tree-name');
            return (
                overlay !== null &&
                getComputedStyle(overlay).display === 'none' &&
                root !== null &&
                root.textContent.trim() === expected
            );
        }, name);
        if (done) {
            break;
        }
        if (Date.now() > deadline) {
            throw new Error(`the Digital Thread never showed '${name}'`);
        }
        await sleep(1000);
    }
    await sleep(3000);
}

/**
 * Show the Explorer row 'text' in the Digital Thread, from where a show puts the
 * camera, and still.
 *
 * The 3D view turns on its own until its "Animate" box is cleared, and that box
 * is not there until something has been shown. So: show it, clear the box, show
 * something else ('other', a row at the same level) and show it again - a show
 * of a new object puts the camera back where every show starts.
 */
export async function showStill(page, text, level, other) {
    await select(page, text, level);
    await shown(page, text);
    await stopTurning(page);
    await select(page, other, level);
    await shown(page, other);
    await select(page, text, level);
    await shown(page, text);
}

/** Where the 3D view is drawn, on the page. */
export async function canvas(page) {
    return await (await viewer(page)).locator('#viewer').boundingBox();
}

/**
 * Turn the 3D view's camera by dragging across it.
 *
 * The 3D view's orbit control turns the camera by a full circle for a drag as
 * long as the view is high, sideways for 'left' and up or down for 'up' -
 * both in degrees here. The camera a show starts from looks from (0.6, 0.5,
 * 0.8) in the view's Y-up frame: 36.9 degrees round from +Z and 63.4 down from
 * +Y. So '{ left: 36.9, up: 63.4 }' is looking straight down PartCAD's -Z, with
 * +Y at the top of the picture - a plan view; turning further up than straight
 * down stops there.
 */
export async function orbit(page, { left = 0, up = 0 }) {
    const box = await canvas(page);
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    const steps = 30;
    for (let i = 1; i <= steps; i++) {
        await page.mouse.move(x + ((left / 360) * box.height * i) / steps, y + ((up / 360) * box.height * i) / steps);
        await sleep(16);
    }
    await page.mouse.up();
    // The orbit control eases into where it was dragged to.
    await sleep(3000);
}

/** Set a range input of a webview to 'value', as dragging its thumb would. */
export async function slide(frame, selector, value) {
    await frame.locator(selector).evaluate((input, v) => {
        input.value = String(v);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }, value);
    await sleep(1000);
}

/** Dismiss every notification, and move the pointer where it hovers nothing. */
export async function tidy(page) {
    await command(page, 'Notifications: Clear All Notifications');
    const panel = await part(page, 'panel');
    if (panel) {
        await page.mouse.move(panel.x + panel.width * 0.8, panel.y + panel.height * 0.6);
    } else {
        await page.mouse.move(WIDTH - 10, HEIGHT / 2);
    }
    await sleep(1500);
}

/** Take the picture: the whole window, or 'clip' of it (CSS pixels). */
export async function shot(page, file, clip) {
    await page.screenshot({ path: file, clip, animations: 'disabled', caret: 'initial', timeout: 120000 });
    console.log(`wrote ${file}`);
}

/**
 * 'clip' narrowed to what is drawn in it, with 'margin' CSS pixels round it.
 *
 * The 3D view frames the whole of what it shows with room to spare, and a
 * port's axes are much longer than its boundary is wide: a picture of the
 * view as it is is mostly background. So the region is captured once, the
 * picture is read back in the window itself - where an <img> can decode a PNG
 * without anything installed for it - and everything that is the background
 * colour of its corner is cut off.
 */
export async function trimmed(page, clip, margin = 24) {
    const png = await page.screenshot({ clip, animations: 'disabled' });
    const box = await page.evaluate(async (data) => {
        const image = new Image();
        image.src = `data:image/png;base64,${data}`;
        await image.decode();
        const surface = new OffscreenCanvas(image.width, image.height);
        const context = surface.getContext('2d');
        context.drawImage(image, 0, 0);
        const { data: pixels, width, height } = context.getImageData(0, 0, image.width, image.height);
        const at = (x, y) => (y * width + x) * 4;
        const background = [pixels[0], pixels[1], pixels[2]];
        let left = width, top = height, right = -1, bottom = -1;
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const i = at(x, y);
                const differs =
                    Math.abs(pixels[i] - background[0]) + Math.abs(pixels[i + 1] - background[1]) + Math.abs(pixels[i + 2] - background[2]) > 24;
                if (differs) {
                    left = Math.min(left, x);
                    right = Math.max(right, x);
                    top = Math.min(top, y);
                    bottom = Math.max(bottom, y);
                }
            }
        }
        return right < 0 ? null : { left, top, right, bottom, width, height };
    }, png.toString('base64'));
    if (box === null) {
        return clip;
    }
    // Device pixels back to CSS pixels.
    const scale = box.width / clip.width;
    const x = Math.max(clip.x, clip.x + box.left / scale - margin);
    const y = Math.max(clip.y, clip.y + box.top / scale - margin);
    const right = Math.min(clip.x + clip.width, clip.x + (box.right + 1) / scale + margin);
    const bottom = Math.min(clip.y + clip.height, clip.y + (box.bottom + 1) / scale + margin);
    return { x, y, width: right - x, height: bottom - y };
}

/**
 * Move the 3D view's camera 'factor' times closer to what it looks at, with the
 * mouse wheel. Each notch of the orbit control's wheel is 1/0.95 closer.
 */
export async function zoom(page, factor) {
    const box = await canvas(page);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    const notches = Math.round(Math.log(factor) / Math.log(1 / 0.95));
    for (let i = 0; i < notches; i++) {
        await page.mouse.wheel(0, -100);
        await sleep(30);
    }
    await sleep(2000);
}

/**
 * Open a file anywhere on disk, by typing its path into VS Code's own open
 * dialog ('files.simpleDialog.enable', which the settings turn on - the
 * desktop's dialog is out of reach of the DevTools protocol).
 */
export async function openFile(page, file) {
    await command(page, 'File: Open File...');
    await page.waitForSelector('.quick-input-widget input', { state: 'visible', timeout: 10000 });
    await page.keyboard.press('Control+A');
    await page.keyboard.type(file, { delay: 5 });
    await sleep(500);
    await page.keyboard.press('Enter');
    await sleep(2000);
}

/**
 * Wait until the terminal on screen shows text matching 'pattern'.
 *
 * Read off the terminal's DOM, which is only there with its GPU renderer off
 * ('terminal.integrated.gpuAcceleration', which the settings turn off).
 */
export async function terminalShows(page, pattern, timeout = 600000) {
    const deadline = Date.now() + timeout;
    for (;;) {
        const text = await page.$$eval('.terminal-wrapper.active .xterm-rows, .xterm-rows', (els) =>
            els.map((e) => e.textContent).join('\n'),
        );
        if (pattern.test(text)) {
            return;
        }
        if (Date.now() > deadline) {
            throw new Error(`the terminal never showed ${pattern}`);
        }
        await sleep(2000);
    }
}
