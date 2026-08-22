//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The backend abstraction the extension talks to. Two implementations satisfy
// the same small interface the extension uses (notifications + lifecycle):
//
//   * LspBackend     - the legacy Python language server (unchanged behavior),
//                      selected by the `partcad.backend: "python"` setting.
//   * JsonRpcBackend - the standalone `partcad-json-rpc` service, the default.
//                      It connects over the per-workspace socket daemon by
//                      default (run the launcher, read the printed socket path,
//                      connect), or over stdio when `partcad.serviceChannel` is
//                      "stdio". Either way it registers the same `partcad.*`
//                      commands the LSP client used to auto-register, translating
//                      each to the CLI-shaped JSON-RPC method, and routes the
//                      service's notifications back under the legacy
//                      `?/partcad/*` names so the extension's handlers are
//                      unchanged.
//

import * as cp from 'child_process';
import * as net from 'net';
import * as vscode from 'vscode';
import { Disposable } from 'vscode';
import { LanguageClient } from 'vscode-languageclient/node';
import {
    createMessageConnection,
    MessageConnection,
    StreamMessageReader,
    StreamMessageWriter,
} from 'vscode-jsonrpc/node';

import { traceError, traceInfo } from './log/logging';
import { cliBeside, ensureServiceExecutable } from './provision';
import { getBackendFromSetting, getServiceChannelFromSetting, setBackendSetting } from './settings';
import { restartServer } from './server';

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

/** Wraps the legacy LanguageClient so it satisfies PartcadBackend. */
class LspBackend implements PartcadBackend {
    constructor(public readonly client: LanguageClient) {}

    onNotification(method: string, handler: (params: any) => void): Disposable {
        return this.client.onNotification(method, handler);
    }
    setTrace(value: any): Promise<void> {
        return this.client.setTrace(value);
    }
    isRunning(): boolean {
        return this.client.isRunning();
    }
    stop(): Promise<void> {
        return this.client.stop();
    }
}

/** Talks to the standalone `partcad-json-rpc` service over a framed connection. */
class JsonRpcBackend implements PartcadBackend {
    private readonly handlers = new Map<string, ((params: any) => void)[]>();
    private readonly commandDisposables: Disposable[] = [];
    private running = false;

    constructor(
        private readonly connection: MessageConnection,
        private readonly cleanup: () => void,
        private readonly outputChannel: vscode.LogOutputChannel,
        private readonly cliPath: string | undefined = undefined,
        private readonly cwd: string = process.cwd(),
    ) {
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
        try {
            await runCli(this.cliPath, ['daemon', 'stop'], this.cwd, this.outputChannel);
            return;
        } catch (e) {
            traceInfo(`PartCAD: 'pc daemon stop' unavailable (${e}); asking the daemon directly`);
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
        reg('partcad.regeneratePartCb', (a) =>
            this.send('ai.regenerate', { package: a.pkg, name: a.name, config: a.config }),
        );
        reg('partcad.changePartCb', (a) => this.send('ai.change', { package: a.pkg, name: a.name, config: a.config }));
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
        reg('partcad.testReal', (a) => this.send('test', { package: a.packageName, object: a.objectName }));
        reg('partcad.getStats', () => this.send('info', {}));
        reg('partcad.activate', () => this.send('activate', {}));
        reg('partcad.initPackage', (p) => this.send('init', { path: typeof p === 'string' ? p : '' }));
        reg('partcad.loadPackage', (p) => this.send('package.load', { path: typeof p === 'string' ? p : '' }));
        reg('partcad.refresh', () => this.send('package.refresh', {}));
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
    return args;
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
): Promise<string> {
    return new Promise((resolve, reject) => {
        if (!cliPath) {
            reject(new Error('no `pc` executable beside the PartCAD service'));
            return;
        }
        cp.execFile(cliPath, ['--no-ansi', ...args], { cwd, env }, (err, stdout, stderr) => {
            if (stderr) {
                outputChannel.append(stderr);
            }
            if (err) {
                reject(new Error(`pc ${args.join(' ')} failed: ${err.message}: ${stderr}`));
                return;
            }
            resolve(stdout);
        });
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
    return new JsonRpcBackend(connection, () => socket.destroy(), outputChannel, cliPath, cwd);
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
    );
}

/**
 * (Re)start the configured backend. Returns undefined if it could not start;
 * when the user declines the service download, the backend setting is switched
 * to "python" (which re-triggers startup through the configuration-change path).
 */
export async function restartBackend(
    serverId: string,
    serverName: string,
    outputChannel: vscode.LogOutputChannel,
    context: vscode.ExtensionContext,
    existing: PartcadBackend | undefined,
): Promise<PartcadBackend | undefined> {
    if (getBackendFromSetting(serverId) === 'service') {
        if (existing) {
            try {
                await existing.stop();
            } catch (e) {
                traceError(`Failed to stop the previous backend: ${e}`);
            }
        }
        const execPath = await ensureServiceExecutable(context, serverId);
        if (!execPath) {
            traceInfo('PartCAD: service download declined; switching to the Python backend.');
            await setBackendSetting(serverId, 'python');
            return undefined;
        }
        const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();
        const args = serviceArgs(serverId);
        const env = { ...process.env };
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

    // Python / legacy LSP backend.
    let previousClient: LanguageClient | undefined;
    if (existing instanceof LspBackend) {
        previousClient = existing.client;
    } else if (existing) {
        try {
            await existing.stop();
        } catch (e) {
            traceError(`Failed to stop the previous backend: ${e}`);
        }
    }
    const client = await restartServer(serverId, serverName, outputChannel, previousClient);
    return client ? new LspBackend(client) : undefined;
}
