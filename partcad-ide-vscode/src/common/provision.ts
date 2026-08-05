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

function cachedBundleRoot(context: vscode.ExtensionContext): string {
    return path.join(context.globalStorageUri.fsPath, 'partcad-bundle');
}

/**
 * Return the path to a usable `partcad-json-rpc`, or undefined if none is
 * present. Checked in order: the explicit setting, the install.sh location, a
 * previously downloaded bundle in the extension's storage, then PATH.
 */
export function resolveServicePath(context: vscode.ExtensionContext, serverId: string): string | undefined {
    const configured = getServicePathFromSetting(serverId);
    if (configured && isFile(configured)) {
        return configured;
    }

    const home = os.homedir();
    const xdgData = process.env.XDG_DATA_HOME || path.join(home, '.local', 'share');
    const candidates = [
        // install.sh unpacks the bundle to <install-dir>/partcad/ with the
        // executables inside it.
        path.join(xdgData, 'partcad', 'partcad', EXE),
        path.join(home, '.local', 'bin', EXE),
        path.join(cachedBundleRoot(context), 'partcad', EXE),
    ];
    for (const candidate of candidates) {
        if (isFile(candidate)) {
            return candidate;
        }
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

    const root = cachedBundleRoot(context);
    await fs.promises.rm(root, { recursive: true, force: true });
    await fs.promises.mkdir(root, { recursive: true });
    const archivePath = path.join(root, archive);

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
    await extract(archivePath, root, pa.ext);
    await fs.promises.rm(archivePath, { force: true });

    const exe = path.join(root, 'partcad', EXE);
    if (!isFile(exe)) {
        throw new Error('the service executable was not found in the downloaded bundle');
    }
    if (process.platform !== 'win32') {
        await fs.promises.chmod(exe, 0o755).catch(() => undefined);
    }
    traceInfo(`PartCAD: installed service executable at ${exe}`);
    return exe;
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
