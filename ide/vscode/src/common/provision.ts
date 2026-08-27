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

// What a release says it carries, published beside the archives by
// `dev-tools/release/platforms-manifest.sh`.
const MANIFEST_NAME = 'platforms.json';

/**
 * The release manifest: `{version, bundle: {os: {arch: [platform, ...]}}, ide: ...}`,
 * each list ordered newest build first.
 */
interface ReleaseManifest {
    version?: string;
    [kind: string]: unknown;
}

interface HostPlatform {
    os: string;
    arch: string;
    /**
     * The extension `dev-tools/pyinstaller/build.sh` packs the bundle with: xz
     * everywhere but Windows, because the bundle is native code and an unpacked
     * OpenSCAD, on which xz is worth about a quarter of the download over gzip.
     * `extract()` reads the compression out of the archive, so this only names
     * the file.
     */
    ext: 'tar.xz' | 'zip';
}

/** This machine, in the names the manifest uses. */
function hostPlatform(): HostPlatform | undefined {
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
    return { os: osName, arch, ext: osName === 'windows' ? 'zip' : 'tar.xz' };
}

/**
 * This machine's OS release as `<name>-<version>`, or undefined when it cannot
 * be established.
 *
 * The same two answers `install.sh` can give: an Ubuntu version out of
 * `/etc/os-release`, or a macOS major version. Everything else is deliberately
 * unknown -- a non-Ubuntu Linux cannot be lined up against a build named after
 * an Ubuntu release, and the Windows builds are named after the runner image,
 * which is not a version this machine has.
 */
function hostRelease(): string | undefined {
    if (process.platform === 'linux') {
        try {
            const text = fs.readFileSync('/etc/os-release', 'utf8');
            const fields = new Map<string, string>();
            for (const line of text.split('\n')) {
                const separator = line.indexOf('=');
                if (separator > 0) {
                    fields.set(
                        line.slice(0, separator).trim(),
                        line
                            .slice(separator + 1)
                            .trim()
                            .replace(/^["']|["']$/g, ''),
                    );
                }
            }
            const version = fields.get('VERSION_ID');
            return fields.get('ID') === 'ubuntu' && version ? `ubuntu-${version}` : undefined;
        } catch {
            return undefined;
        }
    }
    if (process.platform === 'darwin') {
        try {
            // The major version is the compatibility boundary; the point release
            // is not, which is why the builds are `macos-15` and not `macos-15.3`.
            const product = cp.execFileSync('sw_vers', ['-productVersion'], { encoding: 'utf8' }).trim();
            const major = product.split('.')[0];
            return major ? `macos-${major}` : undefined;
        } catch {
            return undefined;
        }
    }
    return undefined;
}

/** A comparable version. Non-digits are dropped, missing fields count as 0. */
function versionFields(value: string): number[] {
    return value.split('.').map((field) => {
        const digits = field.replace(/\D/g, '');
        return digits ? Number(digits) : 0;
    });
}

/** True when `left <= right`, padding the shorter one with zeroes. */
function versionLe(left: number[], right: number[]): boolean {
    for (let i = 0; i < Math.max(left.length, right.length); i++) {
        const difference = (left[i] ?? 0) - (right[i] ?? 0);
        if (difference !== 0) {
            return difference < 0;
        }
    }
    return true;
}

/** `["ubuntu", [24, 4]]` for `"ubuntu-24.04"`; undefined without a version. */
function splitRelease(value: string): [string, number[]] | undefined {
    const separator = value.indexOf('-');
    if (separator <= 0 || separator === value.length - 1) {
        return undefined;
    }
    return [value.slice(0, separator), versionFields(value.slice(separator + 1))];
}

/**
 * The OS release a build was frozen on, from its platform id.
 *
 * `ubuntu-24.04-x86_64` is `["ubuntu", [24, 4]]`; `linux-x86_64` -- an IDE
 * archive, built once per operating system rather than per OS version -- has no
 * release and is undefined.
 */
function platformRelease(platformId: string): [string, number[]] | undefined {
    const separator = platformId.lastIndexOf('-');
    return separator > 0 ? splitRelease(platformId.slice(0, separator)) : undefined;
}

/**
 * The builds in `manifest` worth trying on this machine, best first.
 *
 * `manifest[kind][os][arch]` is what the release actually published, newest
 * build first. This applies the policy `install.sh` applies to its own
 * hardcoded lists, and for the same reason: a frozen bundle needs the C library
 * of the machine that froze it or newer, so a build newer than this machine is
 * dropped rather than offered and left to fail at first start. A machine whose
 * release cannot be established -- Windows, a non-Ubuntu Linux -- gets the list
 * backwards instead, oldest and therefore most portable build first. An OS
 * older than every build is still offered the oldest one, as the only candidate
 * with a chance.
 */
export function selectPlatforms(
    manifest: ReleaseManifest,
    kind: string,
    osName: string,
    arch: string,
    release: string | undefined,
): string[] {
    const byOs = (manifest?.[kind] ?? {}) as Record<string, Record<string, unknown>>;
    const raw = byOs?.[osName]?.[arch];
    const published = (Array.isArray(raw) ? raw : []).filter(
        (entry): entry is string => typeof entry === 'string' && !!entry,
    );
    if (published.length === 0) {
        return [];
    }
    const host = release ? splitRelease(release) : undefined;
    const releases = published.map((entry) => platformRelease(entry));
    if (!host || !releases.some((found) => found && found[0] === host[0])) {
        return [...published].reverse();
    }
    const usable = published.filter((_entry, index) => {
        const found = releases[index];
        return !!found && found[0] === host[0] && versionLe(found[1], host[1]);
    });
    return usable.length > 0 ? usable : [published[published.length - 1]];
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
 * `install.sh` and `pc upgrade` produce, and the reason an upgrade can be
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
        'PartCAD needs its standalone service (partcad-json-rpc). This is a one-time download ' +
            '(roughly 60 MB compressed). If you would rather not download it, PartCAD can use a Python ' +
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
 * The extension implements none of this: it runs `pc upgrade` from the bundle it
 * is already using, which is the same command a user would type in a terminal.
 * (`pc update` is a different thing -- it refetches a package's imports.)
 * `pc` decides whether anything is newer, stops every daemon
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
        // the one flow that has to ask before spending 60MB of somebody's link.
        const downloaded = await ensureServiceExecutable(context, serverId);
        return { updated: !!downloaded, execPath: downloaded };
    }

    const cli = cliBeside(execPath);
    if (cli) {
        const env = { ...process.env };
        const repo = getServiceDownloadRepositoryFromSetting(serverId);
        if (repo) {
            // The same override install.sh and `pc upgrade` read.
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
                async () => runStreaming(cli, ['--no-ansi', 'upgrade'], outputChannel, { cwd, env }),
            );
            // Whether anything was installed is a question about the filesystem,
            // not about the command's output: an update lands in a directory
            // named after the new version, so the resolved path moves.
            const updatedPath = resolveServicePath(context, serverId);
            return { updated: !!updatedPath && updatedPath !== execPath, execPath: updatedPath ?? execPath };
        } catch (e) {
            // A bundle older than `pc upgrade` rejects the command outright --
            // and that is exactly the installation with the most to gain from
            // being upgraded. Fall through to downloading the release.
            traceInfo(`PartCAD: 'pc upgrade' failed (${e}); downloading the release instead`);
        }
    }

    // No `pc` beside the service (a bare wheel install of the service alone), or
    // one too old to know `pc upgrade`. Download the release here, the way
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
    const host = hostPlatform();
    if (!host) {
        throw new Error(`unsupported platform ${process.platform}/${process.arch}`);
    }
    const repo = getServiceDownloadRepositoryFromSetting(serverId);

    progress.report({ message: 'resolving the latest release...' });
    const version = await latestRelease(repo);
    const base = `https://github.com/${repo}/releases/download/${version}`;

    // Which bundles a release carries is a property of the release, not of this
    // machine: they are named after the OS version they were frozen on, and that
    // set changes as builders come and go. So the release says, and this reads
    // it, rather than guessing a name that may not exist.
    const manifest = await fetchManifest(base);
    const candidates = selectPlatforms(manifest, 'bundle', host.os, host.arch, hostRelease());
    if (candidates.length === 0) {
        throw new Error(`release ${version} publishes no PartCAD bundle for ${host.os}/${host.arch}`);
    }

    // Unpacked beside any bundle already there, under a directory named after
    // its version: the same layout `install.sh` and `pc upgrade` produce, so all
    // three install and find each other's bundles. Staged first, because a
    // failed download must not take the working installation with it.
    const root = cachedBundleRoot(context);
    const staging = path.join(root, `.staging-${version}`);
    await fs.promises.rm(staging, { recursive: true, force: true });
    await fs.promises.mkdir(staging, { recursive: true });

    const { url, archivePath } = await downloadFirstPublished(base, version, candidates, host.ext, staging, progress);

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
    await extract(archivePath, staging, host.ext);
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
 * Remove every bundle under `root` except `keep`. A bundle is ~180MB unpacked,
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

/**
 * Download the first candidate the release actually has, into `staging`.
 *
 * The manifest says what was published, so the first candidate is normally the
 * one that arrives. It can still be absent -- a builder that failed after the
 * manifest was written -- and every later candidate is a bundle this machine can
 * run too, so a missing one moves on the way `install.sh` does.
 */
async function downloadFirstPublished(
    base: string,
    version: string,
    candidates: string[],
    ext: string,
    staging: string,
    progress: vscode.Progress<{ message?: string }>,
): Promise<{ url: string; archivePath: string }> {
    for (let i = 0; i < candidates.length; i++) {
        const archive = `partcad-${version}-${candidates[i]}.${ext}`;
        const url = `${base}/${archive}`;
        const archivePath = path.join(staging, archive);
        progress.report({ message: `downloading ${archive}...` });
        try {
            await downloadFile(url, archivePath);
            return { url, archivePath };
        } catch (e: any) {
            if (e?.status === 404 && i < candidates.length - 1) {
                traceInfo(`PartCAD: ${url} is not published, trying the next build`);
                continue;
            }
            throw e;
        }
    }
    throw new Error(`no build of ${version} for this machine. Tried: ${candidates.join(', ')}`);
}

/**
 * The release manifest published beside the archives.
 *
 * A release made before the manifest existed cannot be resolved: there is no
 * host-only way back to a name like `ubuntu-24.04-x86_64`, and guessing one is
 * how this broke in the first place. Say so instead.
 */
async function fetchManifest(base: string): Promise<ReleaseManifest> {
    const url = `${base}/${MANIFEST_NAME}`;
    let body: Buffer;
    try {
        body = await httpsGet(url);
    } catch (e: any) {
        throw new Error(
            `${url} is not published, so there is no way to tell which PartCAD bundles this release ` +
                `carries. Install one with install.sh, or use a release that publishes ${MANIFEST_NAME} (${e?.message ?? e}).`,
        );
    }
    let manifest: unknown;
    try {
        manifest = JSON.parse(body.toString());
    } catch (e: any) {
        throw new Error(`${url} is not valid JSON: ${e?.message ?? e}`);
    }
    if (!manifest || typeof manifest !== 'object') {
        throw new Error(`${url} does not contain a release manifest`);
    }
    return manifest as ReleaseManifest;
}

/** An HTTP response that was not a success, carrying its status for the caller. */
class HttpError extends Error {
    constructor(
        readonly status: number,
        url: string,
    ) {
        super(`HTTP ${status} for ${url}`);
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
                    reject(new HttpError(status, url));
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
                    reject(new HttpError(status, url));
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

async function extract(archivePath: string, dest: string, ext: 'tar.xz' | 'zip'): Promise<void> {
    if (ext === 'zip') {
        if (process.platform === 'win32') {
            // Windows 10+ ships bsdtar, which unpacks zip archives.
            await run('tar', ['-xf', archivePath, '-C', dest], dest);
        } else {
            await run('unzip', ['-q', '-o', archivePath, '-d', dest], dest);
        }
    } else {
        // `-xf`, not `-xzf`: tar reads the compression from the archive, which
        // is what lets this stay right whichever way the bundle was packed.
        await run('tar', ['-xf', archivePath, '-C', dest], dest);
    }
}
