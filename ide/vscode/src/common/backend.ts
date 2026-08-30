//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// How the extension talks to PartCAD: the standalone `partcad-json-rpc`
// service, over a framed JSON-RPC connection. It connects to the per-workspace
// socket daemon by default (run the launcher, read the printed socket path,
// connect), or over stdio when `partcad.serviceChannel` is "stdio". Either way
// it registers the `partcad.*` commands the extension issues, translating each
// to the CLI-shaped JSON-RPC method, and routes the service's notifications
// back under the `?/partcad/*` names the extension's handlers listen on.
//
// There used to be a second implementation beside this one: a Python language
// server, bundled with its own copy of PartCAD's dependencies, selected by
// `partcad.backend: "python"`. It is gone. It could never have worked off
// Linux/CPython 3.13 anyway -- `bundled/libs` held compiled wheels and the
// ".vsix" is built once -- and everything it did, this does, for every command:
// a `pip install partcad` puts `partcad-json-rpc` on PATH, which
// `resolveServicePath` finds, so a user with their own Python needs no download.
//

import * as cp from 'child_process';
import * as net from 'net';
import * as vscode from 'vscode';
import { Disposable } from 'vscode';
import {
    createMessageConnection,
    MessageConnection,
    StreamMessageReader,
    StreamMessageWriter,
} from 'vscode-jsonrpc/node';

import { traceError, traceInfo } from './log/logging';
import { cliBeside, ensureServiceExecutable } from './provision';
import { refreshToolsPath } from './terminalPath';
import { getServiceChannelFromSetting } from './settings';

/** The subset of the language client the extension depends on. */
export interface PartcadBackend {
    onNotification(method: string, handler: (params: any) => void): Disposable;
    setTrace(value: any): Promise<void>;
    isRunning(): boolean;
    stop(): Promise<void>;
    /** Terminate the shared daemon (socket channel only); no-op otherwise. */
    stopDaemon?(): Promise<void>;
}

// The extension subscribes and the legacy server published under this prefix.
const NOTIFICATION_PREFIX = '?/partcad/';

/** How this backend reaches the `pc` CLI, and what that CLI may be used for. */
type CliAccess = {
    /** The `pc` beside the service executable, when there is one. */
    cliPath?: string;
    /** Where to run it: `pc` derives the workspace it acts on from its cwd. */
    cwd?: string;
    /**
     * Whether the connected service is the workspace daemon `pc` manages. False
     * for the stdio channel, which owns a private process -- `pc daemon stop`
     * there would stop a daemon this window never connected to. Linting does not
     * care either way: it acts on a file, not on a daemon.
     */
    sharedDaemon?: boolean;
};

/** Talks to the standalone `partcad-json-rpc` service over a framed connection. */
class JsonRpcBackend implements PartcadBackend {
    private readonly handlers = new Map<string, ((params: any) => void)[]>();
    private readonly commandDisposables: Disposable[] = [];
    private running = false;
    private readonly cliPath: string | undefined;
    private readonly cwd: string;
    private readonly sharedDaemon: boolean;

    constructor(
        private readonly connection: MessageConnection,
        private readonly cleanup: () => void,
        private readonly outputChannel: vscode.LogOutputChannel,
        cli: CliAccess = {},
    ) {
        this.cliPath = cli.cliPath;
        this.cwd = cli.cwd ?? process.cwd();
        this.sharedDaemon = cli.sharedDaemon ?? false;
        this.connection.onNotification((method: string, params: any) => this.fire(method, params));
        this.connection.onError((e) => traceError(`PartCAD service connection error: ${JSON.stringify(e)}`));
        this.connection.onClose(() => {
            this.running = false;
        });
        this.connection.listen();
        this.running = true;
        this.registerServerCommands();
    }

    private fire(event: string, params: any): void {
        for (const handler of this.handlers.get(event) ?? []) {
            try {
                handler(params);
            } catch (e) {
                traceError(`PartCAD notification handler for '${event}' failed: ${e}`);
            }
        }
    }

    onNotification(method: string, handler: (params: any) => void): Disposable {
        // The extension subscribes with the legacy "?/partcad/<event>" names;
        // the service emits bare "<event>" names.
        const event = method.startsWith(NOTIFICATION_PREFIX) ? method.slice(NOTIFICATION_PREFIX.length) : method;
        const list = this.handlers.get(event) ?? [];
        list.push(handler);
        this.handlers.set(event, list);
        return new Disposable(() => {
            const current = this.handlers.get(event);
            if (current) {
                const i = current.indexOf(handler);
                if (i >= 0) {
                    current.splice(i, 1);
                }
            }
        });
    }

    async setTrace(_value: any): Promise<void> {
        // The service has no LSP trace level; logging verbosity is a launch flag.
    }

    isRunning(): boolean {
        return this.running;
    }

    async stop(): Promise<void> {
        // Close only this client's connection; the shared daemon keeps running so
        // other windows/CLI invocations for the workspace stay served.
        this.running = false;
        this.commandDisposables.forEach((d) => d.dispose());
        this.commandDisposables.length = 0;
        try {
            this.connection.dispose();
        } catch {
            // ignore
        }
        this.cleanup();
    }

    async stopDaemon(): Promise<void> {
        // Through the CLI, not over this connection: `pc daemon stop` is the one
        // implementation of "stop the daemon serving this workspace", and it
        // waits for the process to be gone rather than for the acknowledgement.
        // Falls back to asking over the wire if `pc` is not reachable, which
        // still gets the daemon to exit -- just without the wait.
        if (this.sharedDaemon) {
            try {
                await runCli(this.cliPath, ['daemon', 'stop'], this.cwd, this.outputChannel);
                return;
            } catch (e) {
                traceInfo(`PartCAD: 'pc daemon stop' unavailable (${e}); asking the daemon directly`);
            }
        }
        try {
            await this.connection.sendRequest('daemon.stop', {});
        } catch {
            // The daemon closes the connection as it exits; ignore.
        }
    }

    private send(method: string, params: any): Promise<any> {
        return Promise.resolve(this.connection.sendRequest(method, params));
    }

    /**
     * Check one file with `pc lint --file`, in a process of its own.
     *
     * The buffer travels on stdin so what is checked is what is on screen, not
     * what was last saved. Reported back in the shape the LSP backend's command
     * returns, so the caller cannot tell the two backends apart.
     */
    private async lintFile(arg: { path?: string; text?: string }): Promise<{ path: string; diagnostics: any[] }> {
        const path = arg?.path ?? '';
        const args = ['lint', '--file', path, ...(arg?.text === undefined ? [] : ['--stdin'])];
        const stdout = await runCli(this.cliPath, [...args, '--json'], this.cwd, this.outputChannel, undefined, {
            stdin: arg?.text,
            // Findings are reported in the JSON; a non-zero exit only repeats
            // that this file has errors, and rejecting on it would throw the
            // findings away.
            allowFailure: true,
        });
        const parsed = JSON.parse(stdout);
        const file = (parsed?.files ?? [])[0];
        return { path, diagnostics: file?.diagnostics ?? [] };
    }

    /**
     * Register the `partcad.*` commands the extension invokes, mapping each to
     * the CLI-shaped JSON-RPC method with translated parameters. This replaces
     * what the LanguageClient's ExecuteCommandFeature did for the LSP backend.
     */
    private registerServerCommands(): void {
        const reg = (name: string, fn: (...args: any[]) => Thenable<any>) => {
            this.commandDisposables.push(vscode.commands.registerCommand(name, fn));
        };

        reg('partcad.showPart', (a) => this.send('inspect.part', { package: a.pkg, name: a.name, params: a.params }));
        reg('partcad.showSketch', (a) =>
            this.send('inspect.sketch', { package: a.pkg, name: a.name, params: a.params }),
        );
        reg('partcad.showInterface', (a) =>
            this.send('inspect.interface', { package: a.pkg, name: a.name, params: a.params }),
        );
        reg('partcad.showAssembly', (a) =>
            this.send('inspect.assembly', { package: a.pkg, name: a.name, params: a.params }),
        );
        // What the PartCAD Viewer's tabs beside the 3D one are filled from. Each
        // is the CLI's own operation -- 'pc bom', the assembly instruction book
        // 'pc render -t html' writes, 'pc supply quote' -- asked for as data
        // rather than as a file, because the panel has to draw it.
        reg('partcad.bom', (a) =>
            this.send('bom', {
                package: a.pkg,
                object: a.name,
                params: a.params,
                // eslint-disable-next-line @typescript-eslint/naming-convention
                stop_at_purchasable: a.stopAtPurchasable,
            }),
        );
        reg('partcad.assemblyGuide', (a) =>
            this.send('assembly.guide', {
                package: a.pkg,
                object: a.name,
                // eslint-disable-next-line @typescript-eslint/naming-convention
                ignore_manufacturability: a.ignoreManufacturability,
            }),
        );
        reg('partcad.supplyQuote', (a) =>
            this.send('supply.quote', { package: a.pkg, object: a.name, qos: a.qos, recursive: a.recursive }),
        );
        reg('partcad.exportPart', (type, path, pkg, name, params) =>
            this.send('export.part', { type, path, package: pkg, name, params }),
        );
        reg('partcad.exportAssembly', (type, path, pkg, name, params) =>
            this.send('export.assembly', { type, path, package: pkg, name, params }),
        );
        reg('partcad.addPartReal', (a) =>
            this.send('add.part', { kind: a.kind, path: a.path, package: a.packageName, config: a.config }),
        );
        reg('partcad.addAssemblyReal', (a) =>
            this.send('add.assembly', { kind: a.kind, path: a.path, package: a.packageName }),
        );
        reg('partcad.packagePath', (a) => this.send('package.path', { package: a.packageName, callback: a.callback }));
        reg('partcad.inspectFile', (path) => this.send('inspect.file', { path: typeof path === 'string' ? path : '' }));
        // Through the CLI, not over this connection. Checking an ASSY file is
        // the client's own work on the client's own file -- usually one the
        // editor has not saved -- so it never goes to the daemon, and it keeps
        // answering when the daemon is down or the package will not load
        // because of the very file being typed into.
        reg('partcad.lintFile', (a) => this.lintFile(typeof a === 'string' ? { path: a } : a));
        reg('partcad.testReal', (a) => this.send('test', { package: a.packageName, object: a.objectName }));
        reg('partcad.getStats', () => this.send('info', {}));
        reg('partcad.activate', () => this.send('activate', {}));
        reg('partcad.initPackage', (p) => this.send('init', { path: typeof p === 'string' ? p : '' }));
        reg('partcad.loadPackage', (p) => this.send('package.load', { path: typeof p === 'string' ? p : '' }));
        reg('partcad.refresh', () => this.send('package.refresh', {}));
        // The package's own dependencies, not the PartCAD tool: the operation
        // runs against the session's loaded context, which 'package.load'
        // established from the workspace's `partcad.packagePath`.
        reg('partcad.installPackageReal', () => this.send('install', {}));
        reg('partcad.loadPackageContents', (name) =>
            this.send('list.all', { name: typeof name === 'string' ? name : '//' }),
        );
        // Bootstrapping the Python module is meaningless for the frozen service:
        // it already carries PartCAD. Report success so the extension's install
        // flow advances straight to activation.
        reg('partcad.install', async () => this.fire('installed', undefined));
        reg('partcad.reinstall', async () => this.fire('installed', undefined));
    }
}

function serviceArgs(serverId: string): string[] {
    const config = vscode.workspace.getConfiguration(serverId);
    const args: string[] = [];
    const verbosity = config.get<string>('verbosity') ?? 'info';
    if (verbosity === 'debug') {
        args.push('--verbose');
    } else if (verbosity === 'error') {
        args.push('--quiet');
    }
    // No AI provider keys: the generative-AI feature was retired, the settings
    // are gone from package.json, and the service no longer accepts the flags --
    // passing them (from a stale user settings.json) would fail its argument
    // parsing and the service would not start.
    const sandbox = config.get<string>('pythonSandbox');
    if (sandbox) {
        args.push('--python-sandbox', sandbox);
    }
    if ((config.get<string>('forceUpdate') ?? 'false') === 'true') {
        args.push('--force-update');
    }
    // The daemon reads this once, at launch. Toggling the setting restarts the
    // backend (checkIfConfigurationChanged lists it), so the running daemon
    // always reflects the current value.
    if (config.get<boolean>('develIndex') === true) {
        args.push('--devel-index');
    }
    return args;
}

/** The environment the service is launched with. */
function serviceEnv(serverId: string): NodeJS.ProcessEnv {
    const config = vscode.workspace.getConfiguration(serverId);
    const env = { ...process.env };
    // '--devel-index' is a flag, so it can ask for the development index but
    // never against it: a 'PC_DEVEL_INDEX=true' inherited from whatever started
    // VS Code would outrank an extension setting of false. The environment can
    // spell out both answers, so the setting travels through it either way.
    env.PC_DEVEL_INDEX = config.get<boolean>('develIndex') === true ? 'true' : 'false';
    return env;
}

/**
 * Run a `pc` subcommand and resolve with its stdout.
 *
 * `--no-ansi` because the progress renderer would otherwise interleave control
 * characters into the very line this parses; it also routes logging to stderr,
 * leaving stdout to the command's own output.
 */
function runCli(
    cliPath: string | undefined,
    args: string[],
    cwd: string,
    outputChannel: vscode.LogOutputChannel,
    env?: NodeJS.ProcessEnv,
    options?: { stdin?: string; allowFailure?: boolean },
): Promise<string> {
    return new Promise((resolve, reject) => {
        if (!cliPath) {
            reject(new Error('no `pc` executable beside the PartCAD service'));
            return;
        }
        const proc = cp.execFile(cliPath, ['--no-ansi', ...args], { cwd, env }, (err, stdout, stderr) => {
            if (stderr) {
                outputChannel.append(stderr);
            }
            if (err && !options?.allowFailure) {
                reject(new Error(`pc ${args.join(' ')} failed: ${err.message}: ${stderr}`));
                return;
            }
            resolve(stdout);
        });
        // Always closed, with the content when there is any. `pc` never prompts,
        // so a child left holding an open stdin would only ever be one that
        // cannot tell "nothing yet" from "nothing at all".
        proc.stdin?.end(options?.stdin ?? '');
    });
}

/**
 * Ask the CLI where this workspace's daemon is, starting one if none is running.
 *
 * Deliberately not reimplemented here. Which socket serves which workspace, and
 * whether anything is answering on it, is `partcad_client` -- a second
 * copy of those rules in TypeScript is a copy that can disagree, and a
 * disagreement means the extension quietly starting a daemon of its own beside
 * the one `pc` is using.
 */
async function daemonEndpoint(
    cliPath: string | undefined,
    args: string[],
    cwd: string,
    env: NodeJS.ProcessEnv,
    outputChannel: vscode.LogOutputChannel,
): Promise<string> {
    const stdout = await runCli(cliPath, [...args, 'daemon', 'start'], cwd, outputChannel, env);
    const line = stdout.split(/\r?\n/).find((l) => l.trim().length > 0);
    if (!line) {
        throw new Error('`pc daemon start` did not print a socket path');
    }
    return line.trim();
}

async function connectSocket(
    execPath: string,
    args: string[],
    cwd: string,
    env: NodeJS.ProcessEnv,
    outputChannel: vscode.LogOutputChannel,
): Promise<JsonRpcBackend> {
    const cliPath = cliBeside(execPath);
    const socketPath = await daemonEndpoint(cliPath, args, cwd, env, outputChannel);
    traceInfo(`PartCAD service: connecting to daemon at ${socketPath}`);
    const socket: net.Socket = await new Promise((resolve, reject) => {
        const s = net.connect(socketPath);
        s.once('connect', () => resolve(s));
        s.once('error', reject);
    });
    const connection = createMessageConnection(new StreamMessageReader(socket), new StreamMessageWriter(socket));
    return new JsonRpcBackend(connection, () => socket.destroy(), outputChannel, { cliPath, cwd, sharedDaemon: true });
}

function connectStdio(
    execPath: string,
    args: string[],
    cwd: string,
    env: NodeJS.ProcessEnv,
    outputChannel: vscode.LogOutputChannel,
): JsonRpcBackend {
    traceInfo(`PartCAD service: launching ${execPath} --stdio`);
    const proc = cp.spawn(execPath, ['--stdio', ...args], { cwd, env }) as cp.ChildProcessWithoutNullStreams;
    proc.stderr.on('data', (d: Buffer) => outputChannel.append(d.toString()));
    // Without an 'error' listener, a failed launch (ENOENT/EACCES) is emitted
    // asynchronously as an uncaught exception in the extension host rather than
    // a logged failure. 'exit' covers the service dying after a successful spawn.
    proc.on('error', (err: Error) => {
        traceError(`PartCAD service: failed to launch ${execPath}: ${err.message}`);
        outputChannel.appendLine(`PartCAD service failed to launch: ${err.message}`);
    });
    proc.on('exit', (code: number | null, signal: NodeJS.Signals | null) => {
        traceInfo(`PartCAD service exited (code=${code}, signal=${signal})`);
    });
    const connection = createMessageConnection(
        new StreamMessageReader(proc.stdout),
        new StreamMessageWriter(proc.stdin),
    );
    return new JsonRpcBackend(
        connection,
        () => {
            try {
                proc.kill();
            } catch {
                // ignore
            }
        },
        outputChannel,
        // A private service process, so `pc daemon stop` must not be used on it
        // -- but `pc lint --file` still is: it acts on a file, not on a daemon.
        { cliPath: cliBeside(execPath), cwd },
    );
}

/**
 * (Re)start the configured backend. Returns undefined if it could not start;
 * when the user declines the service download, the backend setting is switched
 * to "python" (which re-triggers startup through the configuration-change path).
 */
export async function restartBackend(
    serverId: string,
    _serverName: string,
    outputChannel: vscode.LogOutputChannel,
    context: vscode.ExtensionContext,
    existing: PartcadBackend | undefined,
): Promise<PartcadBackend | undefined> {
    if (existing) {
        try {
            await existing.stop();
        } catch (e) {
            traceError(`Failed to stop the previous backend: ${e}`);
        }
    }
    const execPath = await ensureServiceExecutable(context, serverId);
    // The tools directory only exists once something is installed, and this is
    // where a first install happens: `ensureServiceExecutable` downloads the
    // bundle when there is none. Activation already ran and found nothing, so
    // without this a user who accepts the download prompt gets a working PartCAD
    // and a terminal with no `pc` in it until the next window. Refresh here, not
    // only after `updateServiceBundle`, which covers upgrades and not first
    // installs.
    refreshToolsPath(context, serverId);
    if (!execPath) {
        // Declining used to fall back to the Python backend. There is nothing to
        // fall back to now, and nothing to invent: the user has told us not to
        // download, so the honest outcome is no backend and a message saying how
        // to supply one.
        traceInfo('PartCAD: no PartCAD service available; install one with `pip install partcad`.');
        return undefined;
    }
    const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();
    const args = serviceArgs(serverId);
    const env = serviceEnv(serverId);
    try {
        if (getServiceChannelFromSetting(serverId) === 'stdio') {
            return connectStdio(execPath, args, cwd, env, outputChannel);
        }
        return await connectSocket(execPath, args, cwd, env, outputChannel);
    } catch (e) {
        traceError(`Failed to start the PartCAD service: ${e}`);
        return undefined;
    }
}
