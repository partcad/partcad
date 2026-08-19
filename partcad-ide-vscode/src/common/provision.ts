//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Locates, and if necessary downloads, the standalone `partcad-json-rpc`
// executable that the service backend runs. It reuses the same release-archive
// naming and layout as `install.sh`, so an existing standalone installation is
// picked up rather than downloaded again.
//

import * as cp from 'child_process';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as https from 'https';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

// HTTP header names are not camelCase; that is not a code-style choice.
/* eslint-disable @typescript-eslint/naming-convention */

import { traceError, traceInfo } from './log/logging';
import { getServiceDownloadRepositoryFromSetting, getServicePathFromSetting } from './settings';

const EXE = process.platform === 'win32' ? 'partcad-json-rpc.exe' : 'partcad-json-rpc';

interface PlatformArchive {
    platform: string;
    ext: 'tar.gz' | 'zip';
}

function platformArchive(): PlatformArchive | undefined {
    let osName: string;
    switch (process.platform) {
        case 'linux':
            osName = 'linux';
            break;
        case 'darwin':
            osName = 'macos';
            break;
        case 'win32':
            osName = 'windows';
            break;
        default:
            return undefined;
    }
    let arch: string;
    switch (process.arch) {
        case 'x64':
            arch = 'x86_64';
            break;
        case 'arm64':
            arch = 'arm64';
            break;
        default:
            return undefined;
    }
    return { platform: `${osName}-${arch}`, ext: osName === 'windows' ? 'zip' : 'tar.gz' };
}

function isFile(p: string): boolean {
    try {
        return !!p && fs.existsSync(p) && fs.statSync(p).isFile();
    } catch {
        return false;
    }
}

function whichOnPath(exe: string): string | undefined {
    for (const dir of (process.env.PATH ?? '').split(path.delimiter)) {
        const candidate = path.join(dir, exe);
        if (isFile(candidate)) {
            return candidate;
        }
    }
    return undefined;
}

/**
 * The `pc` executable beside a resolved `partcad-json-rpc`, if there is one.
 *
 * The extension defers to the CLI for everything about daemons -- where they
 * are, whether they are alive, stopping them, and updating the installation
 * under them -- so this is how it finds the CLI to defer to.
 */
export function cliBeside(execPath: string): string | undefined {
    const candidate = path.join(path.dirname(execPath), process.platform === 'win32' ? 'pc.exe' : 'pc');
    return isFile(candidate) ? candidate : undefined;
}

function cachedBundleRoot(context: vscode.ExtensionContext): string {
    return path.join(context.globalStorageUri.fsPath, 'partcad-bundle');
}

/** Compare two version strings numerically, oldest first. */
function compareVersions(a: string, b: string): number {
    const parts = (v: string) => (v.match(/\d+/g) ?? []).map(Number);
    const [left, right] = [parts(a), parts(b)];
    for (let i = 0; i < Math.max(left.length, right.length); i++) {
        const diff = (left[i] ?? 0) - (right[i] ?? 0);
        if (diff !== 0) {
            return diff;
        }
    }
    return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * The newest bundle installed under `root`, or undefined if there is none.
 *
 * A bundle lives in a directory named after its version -- the layout both
 * `install.sh` and `pc update` produce, and the reason an update can be
 * installed beside the running copy instead of over it. `<root>/partcad/` is the
 * flat layout older versions of this extension downloaded into; it is still
 * accepted so an existing installation keeps working, and it sorts oldest so a
 * versioned bundle always wins.
 */
function newestBundleIn(root: string): string | undefined {
    let entries: string[];
    try {
        entries = fs.readdirSync(root);
    } catch {
        return undefined;
    }
    const found = entries
        .filter((name) => name !== 'partcad' && isFile(path.join(root, name, EXE)))
        .sort(compareVersions);
    const newest = found[found.length - 1];
    if (newest) {
        return path.join(root, newest, EXE);
    }
    const legacy = path.join(root, 'partcad', EXE);
    return isFile(legacy) ? legacy : undefined;
}

/**
 * Return the path to a usable `partcad-json-rpc`, or undefined if none is
 * present. Checked in order: the explicit setting, the newest bundle at the
 * install.sh location, the newest bundle previously downloaded into the
 * extension's storage, the launcher symlink in `~/.local/bin`, then PATH.
 */
export function resolveServicePath(context: vscode.ExtensionContext, serverId: string): string | undefined {
    const configured = getServicePathFromSetting(serverId);
    if (configured && isFile(configured)) {
        return configured;
    }

    const home = os.homedir();
    const xdgData = process.env.XDG_DATA_HOME || path.join(home, '.local', 'share');
    const roots = [path.join(xdgData, 'partcad'), cachedBundleRoot(context)];
    for (const root of roots) {
        const found = newestBundleIn(root);
        if (found) {
            return found;
        }
    }

    const linked = path.join(home, '.local', 'bin', EXE);
    if (isFile(linked)) {
        return linked;
    }

    return whichOnPath(EXE);
}

/**
 * Ensure a `partcad-json-rpc` executable is available, prompting before a large
 * download. Returns its path, or undefined if the user declined (in which case
 * the caller falls back to the Python backend).
 */
export async function ensureServiceExecutable(
    context: vscode.ExtensionContext,
    serverId: string,
): Promise<string | undefined> {
    const existing = resolveServicePath(context, serverId);
    if (existing) {
        traceInfo(`PartCAD: using service executable at ${existing}`);
        return existing;
    }

    const choice = await vscode.window.showInformationMessage(
        'PartCAD needs its standalone service (partcad-json-rpc). This is a large one-time download ' +
            '(roughly 290 MB compressed). If you would rather not download it, PartCAD can use a Python ' +
            'environment instead (the "python" backend), which requires a working Python interpreter.',
        { modal: true },
        'Download',
        'Use Python instead',
    );
    if (choice !== 'Download') {
        return undefined;
    }

    return vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'Downloading PartCAD', cancellable: false },
        async (progress) => {
            try {
                return await downloadAndExtract(context, serverId, progress);
            } catch (e: any) {
                traceError(`PartCAD service download failed: ${e?.stack ?? e}`);
                vscode.window.showErrorMessage(`Failed to download PartCAD: ${e?.message ?? e}`);
                return undefined;
            }
        },
    );
}

/**
 * Update the standalone installation to the latest release.
 *
 * The extension implements none of this: it runs `pc update --partcad-only`
 * from the bundle it is already using, which is the same command a user would
 * type in a terminal. `pc` decides whether anything is newer, stops every daemon
 * running on the machine and waits for them, installs the new version beside the
 * old one, and leaves no superseded bundle behind. The extension's part is to
 * show what is happening and to hand back the executable to reconnect to -- a
 * different path once a new version is in.
 *
 * Returns `updated: false` when the installation was already current -- not a
 * failure, and the reason the caller can reconnect to the same executable.
 */
export async function updateServiceBundle(
    context: vscode.ExtensionContext,
    serverId: string,
    outputChannel: vscode.LogOutputChannel,
): Promise<{ updated: boolean; execPath?: string }> {
    const execPath = resolveServicePath(context, serverId);
    if (!execPath) {
        // Nothing installed yet: an update of nothing is an install, and that is
        // the one flow that has to ask before spending 290MB of somebody's link.
        const downloaded = await ensureServiceExecutable(context, serverId);
        return { updated: !!downloaded, execPath: downloaded };
    }

    const cli = cliBeside(execPath);
    if (cli) {
        const env = { ...process.env };
        const repo = getServiceDownloadRepositoryFromSetting(serverId);
        if (repo) {
            // The same override install.sh and `pc update` read.
            env.PARTCAD_REPOSITORY = repo;
        }
        // The workspace folder, because `pc` derives the daemon it stops from
        // its working directory -- the same way this extension's own connection
        // does. Run it anywhere else and it stops a daemon nobody was using
        // while the one holding these files stays up.
        const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();
        try {
            await vscode.window.withProgress(
                { location: vscode.ProgressLocation.Notification, title: 'Updating PartCAD', cancellable: false },
                async () => runStreaming(cli, ['--no-ansi', 'update', '--partcad-only'], outputChannel, { cwd, env }),
            );
            // Whether anything was installed is a question about the filesystem,
            // not about the command's output: an update lands in a directory
            // named after the new version, so the resolved path moves.
            const updatedPath = resolveServicePath(context, serverId);
            return { updated: !!updatedPath && updatedPath !== execPath, execPath: updatedPath ?? execPath };
        } catch (e) {
            // A bundle older than `pc update --partcad-only` rejects the option
            // outright -- and that is exactly the installation with the most to
            // gain from being updated. Fall through to downloading the release.
            traceInfo(`PartCAD: 'pc update' failed (${e}); downloading the release instead`);
        }
    }

    // No `pc` beside the service (a bare wheel install of the service alone), or
    // one too old to understand the command. Download the release here, the way
    // the first install does. No prompt: the user asked for this, and consented
    // to the download size when they installed what is being replaced.
    const downloaded = await downloadLatest(context, serverId);
    return { updated: !!downloaded, execPath: downloaded ?? execPath };
}

/** Download and install the latest release, without asking first. */
function downloadLatest(context: vscode.ExtensionContext, serverId: string): Thenable<string | undefined> {
    return vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'Updating PartCAD', cancellable: false },
        async (progress) => {
            try {
                return await downloadAndExtract(context, serverId, progress);
            } catch (e: any) {
                traceError(`PartCAD service download failed: ${e?.stack ?? e}`);
                vscode.window.showErrorMessage(`Failed to update PartCAD: ${e?.message ?? e}`);
                return undefined;
            }
        },
    );
}

/** Run a command, streaming both its streams to the channel, and return stdout. */
function runStreaming(
    cmd: string,
    args: string[],
    outputChannel: vscode.LogOutputChannel,
    options?: cp.SpawnOptions,
): Promise<string> {
    return new Promise((resolve, reject) => {
        outputChannel.appendLine(`> ${cmd} ${args.join(' ')}`);
        const proc = cp.spawn(cmd, args, options ?? {});
        let stdout = '';
        proc.stdout?.on('data', (d: Buffer) => {
            stdout += d.toString();
            outputChannel.append(d.toString());
        });
        proc.stderr?.on('data', (d: Buffer) => outputChannel.append(d.toString()));
        proc.on('error', reject);
        proc.on('close', (code) =>
            code === 0 ? resolve(stdout) : reject(new Error(`${path.basename(cmd)} exited with ${code}`)),
        );
    });
}

async function downloadAndExtract(
    context: vscode.ExtensionContext,
    serverId: string,
    progress: vscode.Progress<{ message?: string }>,
): Promise<string | undefined> {
    const pa = platformArchive();
    if (!pa) {
        throw new Error(`unsupported platform ${process.platform}/${process.arch}`);
    }
    const repo = getServiceDownloadRepositoryFromSetting(serverId);

    progress.report({ message: 'resolving the latest release...' });
    const version = await latestRelease(repo);
    const archive = `partcad-${version}-${pa.platform}.${pa.ext}`;
    const url = `https://github.com/${repo}/releases/download/${version}/${archive}`;

    // Unpacked beside any bundle already there, under a directory named after
    // its version: the same layout `install.sh` and `pc update` produce, so all
    // three install and find each other's bundles. Staged first, because a
    // failed download must not take the working installation with it.
    const root = cachedBundleRoot(context);
    const staging = path.join(root, `.staging-${version}`);
    await fs.promises.rm(staging, { recursive: true, force: true });
    await fs.promises.mkdir(staging, { recursive: true });
    const archivePath = path.join(staging, archive);

    progress.report({ message: `downloading ${archive}...` });
    await downloadFile(url, archivePath);

    // The HTTPS transfer is already authenticated; the checksum only guards
    // against a corrupted download, so an *unavailable* checksum is a warning.
    // A checksum that is available and does not match is fatal -- it must not
    // be swallowed here, or a corrupted bundle would be extracted and executed.
    let expected: string | undefined;
    try {
        const sumPath = `${archivePath}.sha256`;
        await downloadFile(`${url}.sha256`, sumPath);
        expected = (await fs.promises.readFile(sumPath, 'utf8')).trim().split(/\s+/)[0];
    } catch (e) {
        traceInfo(`PartCAD: checksum verification skipped: ${e}`);
    }
    if (expected) {
        const actual = await sha256(archivePath);
        if (expected !== actual) {
            await fs.promises.rm(archivePath, { force: true });
            throw new Error('checksum mismatch, the download is corrupted');
        }
        traceInfo('PartCAD: download checksum verified');
    }

    progress.report({ message: 'extracting...' });
    await extract(archivePath, staging, pa.ext);
    await fs.promises.rm(archivePath, { force: true });

    const unpacked = path.join(staging, 'partcad');
    if (!isFile(path.join(unpacked, EXE))) {
        await fs.promises.rm(staging, { recursive: true, force: true });
        throw new Error('the service executable was not found in the downloaded bundle');
    }
    const target = path.join(root, version);
    await fs.promises.rm(target, { recursive: true, force: true });
    await fs.promises.rename(unpacked, target);
    await fs.promises.rm(staging, { recursive: true, force: true });

    const exe = path.join(target, EXE);
    if (process.platform !== 'win32') {
        await fs.promises.chmod(exe, 0o755).catch(() => undefined);
    }
    await pruneBundles(root, target);
    traceInfo(`PartCAD: installed service executable at ${exe}`);
    return exe;
}

/**
 * Remove every bundle under `root` except `keep`. A bundle is ~875MB unpacked,
 * so leaving the superseded ones behind is not an option; failing to remove one
 * (a file still open on Windows) is, and is only logged.
 *
 * Callers stop the daemon first: `root` is the extension's own storage, so the
 * only thing that runs from these bundles is a PartCAD daemon this extension
 * started. A daemon in another window is stopped by its own reconnect.
 */
async function pruneBundles(root: string, keep: string): Promise<void> {
    let entries: string[];
    try {
        entries = await fs.promises.readdir(root);
    } catch {
        return;
    }
    for (const name of entries) {
        const entry = path.join(root, name);
        if (entry === keep || !isFile(path.join(entry, EXE))) {
            continue;
        }
        try {
            await fs.promises.rm(entry, { recursive: true, force: true });
            traceInfo(`PartCAD: removed the previous bundle at ${entry}`);
        } catch (e) {
            traceInfo(`PartCAD: could not remove the previous bundle at ${entry}: ${e}`);
        }
    }
}

async function latestRelease(repo: string): Promise<string> {
    const body = await httpsGet(`https://api.github.com/repos/${repo}/releases/latest`, {
        Accept: 'application/vnd.github+json',
    });
    const tag = JSON.parse(body.toString()).tag_name;
    if (!tag) {
        throw new Error(`could not determine the latest release of ${repo}`);
    }
    return tag;
}

function httpsGet(url: string, headers: Record<string, string> = {}): Promise<Buffer> {
    return new Promise((resolve, reject) => {
        https
            .get(url, { headers: { 'User-Agent': 'partcad-vscode', ...headers } }, (res) => {
                const status = res.statusCode ?? 0;
                if (status >= 300 && status < 400 && res.headers.location) {
                    res.resume();
                    resolve(httpsGet(res.headers.location, headers));
                    return;
                }
                if (status !== 200) {
                    res.resume();
                    reject(new Error(`HTTP ${status} for ${url}`));
                    return;
                }
                const chunks: Buffer[] = [];
                res.on('data', (c) => chunks.push(c));
                res.on('end', () => resolve(Buffer.concat(chunks)));
            })
            .on('error', reject);
    });
}

function downloadFile(url: string, dest: string): Promise<void> {
    return new Promise((resolve, reject) => {
        https
            .get(url, { headers: { 'User-Agent': 'partcad-vscode' } }, (res) => {
                const status = res.statusCode ?? 0;
                if (status >= 300 && status < 400 && res.headers.location) {
                    res.resume();
                    downloadFile(res.headers.location, dest).then(resolve, reject);
                    return;
                }
                if (status !== 200) {
                    res.resume();
                    reject(new Error(`HTTP ${status} for ${url}`));
                    return;
                }
                const file = fs.createWriteStream(dest);
                res.pipe(file);
                file.on('finish', () => file.close((err) => (err ? reject(err) : resolve())));
                file.on('error', reject);
            })
            .on('error', reject);
    });
}

function sha256(file: string): Promise<string> {
    return new Promise((resolve, reject) => {
        const hash = crypto.createHash('sha256');
        const stream = fs.createReadStream(file);
        stream.on('data', (d) => hash.update(d));
        stream.on('end', () => resolve(hash.digest('hex')));
        stream.on('error', reject);
    });
}

function run(cmd: string, args: string[], cwd: string): Promise<void> {
    return new Promise((resolve, reject) => {
        const proc = cp.spawn(cmd, args, { cwd });
        let stderr = '';
        proc.stderr?.on('data', (d) => (stderr += d.toString()));
        proc.on('error', reject);
        proc.on('close', (code) =>
            code === 0 ? resolve() : reject(new Error(`${cmd} exited with ${code}: ${stderr}`)),
        );
    });
}

async function extract(archivePath: string, dest: string, ext: 'tar.gz' | 'zip'): Promise<void> {
    if (ext === 'zip') {
        if (process.platform === 'win32') {
            // Windows 10+ ships bsdtar, which unpacks zip archives.
            await run('tar', ['-xf', archivePath, '-C', dest], dest);
        } else {
            await run('unzip', ['-q', '-o', archivePath, '-d', dest], dest);
        }
    } else {
        await run('tar', ['-xzf', archivePath, '-C', dest], dest);
    }
}
