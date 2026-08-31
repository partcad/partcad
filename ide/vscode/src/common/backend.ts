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
import * as path from 'path';
import * as vscode from 'vscode';
import { Disposable } from 'vscode';
import {
    createMessageConnection,
    MessageConnection,
    StreamMessageReader,
    StreamMessageWriter,
} from 'vscode-jsonrpc/node';

import { traceError, traceInfo } from './log/logging';
import { cliBeside, ensureServiceExecutable, locateCommand, resolveServicePath } from './provision';
import { writeTerminal } from '../terminal';
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
    /**
     * Whether the service renders the ANSI log display for this connection.
     *
     * When it does, its output already carries the level prefixes and colours,
     * so anything the extension prints beside it is a duplicate.
     */
    rendersLogs?: boolean;
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
    /** Whether the service is drawing the log display for us (see `requestRenderedLogs`). */
    public rendersLogs = false;
    private readonly cliPath: string | undefined;
    private readonly cwd: string;
    private readonly sharedDaemon: boolean;

    constructor(
        private readonly connection: MessageConnection,
        // May be asynchronous: the stdio channel's cleanup terminates a process
        // and waits for it to be gone, because the caller that stops a backend
        // before an update is about to replace the files it runs from.
        private readonly cleanup: () => void | Promise<void>,
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
        this.requestRenderedLogs();
    }

    /**
     * Ask the service to render its log display for us, and send the bytes.
     *
     * The colours and the multi-line progress footer are a state machine
     * (`partcad_utils.logging_ansi_terminal`) that the CLI runs on its own side.
     * This extension cannot: it is TypeScript, and a second implementation of
     * that footer is a second thing to keep correct. So the service runs it
     * instead, once per connection, and sends what it drew -- which arrives on
     * `?/partcad/terminal` and goes into the pty verbatim.
     *
     * From then on this connection gets no `?/partcad/log` events at all. They
     * carry the same information as the bytes, so the service sends one or the
     * other; the handler for them stays as the fallback for a service too old to
     * know this request.
     *
     * Not awaited: requests go out in order on one connection and the daemon
     * serialises them, so this is settled before the first thing that logs.
     */
    private requestRenderedLogs(): void {
        this.connection.sendRequest('log.mode', { ansi: true }).then(
            () => {
                this.rendersLogs = true;
                traceInfo('PartCAD service: rendering the log display service-side');
            },
            (e) => {
                // A service that predates `log.mode` answers "method not found".
                // Nothing is broken: the plain `?/partcad/log` rendering stands.
                traceInfo(`PartCAD service: no service-side log rendering (${e}); using plain log lines`);
            },
        );
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
        await this.cleanup();
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
     * what was last saved. `flavor`, when the caller knows it, says whether the
     * file is an assembly or a scene; without it `pc lint` decides. Reported
     * back in the shape the LSP backend's command returns, so the caller cannot
     * tell the two backends apart.
     */
    private async lintFile(arg: {
        path?: string;
        text?: string;
        flavor?: string;
    }): Promise<{ path: string; diagnostics: any[] }> {
        const path = arg?.path ?? '';
        const args = [
            'lint',
            '--file',
            path,
            ...(arg?.text === undefined ? [] : ['--stdin']),
            // Which schema to check against. Omitted when the caller does not
            // know, and then `pc lint` works it out from the `partcad.yaml`
            // files around the file -- see `PartcadLint.flavorOf`.
            ...(arg?.flavor === undefined ? [] : ['--schema', arg.flavor]),
        ];
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
     * Open one file in a third-party application with `pc open`.
     *
     * Never over this connection, and there is no RPC method for it: the daemon
     * can be remote, where the window would open on somebody else's screen and
     * the path would name a file nobody has. So it is the CLI, run here, on this
     * machine, with this machine's display -- the same rule as `pc lint --file`.
     *
     * Whether a container may be used is the user's setting rather than
     * something worked out here: PartCAD decides how to run the application, and
     * this only says what it is allowed to do.
     */
    private async openExternal(arg: { path?: string; tool?: string }): Promise<{ detail: string; method: string }> {
        const config = vscode.workspace.getConfiguration('partcad');
        const image = (config.get<string>('open.dockerImage') ?? '').trim();
        const args = [
            'open',
            '--with',
            arg?.tool ?? 'freecad',
            ...(config.get<boolean>('open.useDocker') === true ? ['--use-docker'] : []),
            ...(image ? ['--docker-image', image] : []),
            arg?.path ?? '',
            '--json',
        ];
        const stdout = await runCli(this.cliPath, args, this.cwd, this.outputChannel, undefined, {
            // The reason for a failure is in the JSON -- which X server to
            // install, how to allow a container -- and it is the whole answer.
            // Rejecting on the exit code would throw it away and leave the user
            // with "the command failed".
            allowFailure: true,
        });
        let parsed: any;
        try {
            parsed = JSON.parse(stdout);
        } catch {
            // Nothing parseable on stdout: a `pc` too old to know the command
            // says so on stderr and prints nothing here. Reporting that beats
            // showing the user a JSON parser error.
            throw new Error('This PartCAD cannot open files in other applications; update PartCAD and try again.');
        }
        if (!parsed?.ok) {
            throw new Error(parsed?.error ?? 'PartCAD could not open the file.');
        }
        return { detail: parsed.detail ?? '', method: parsed.method ?? '' };
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
        reg('partcad.showScene', (a) => this.send('inspect.scene', { package: a.pkg, name: a.name, params: a.params }));
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
        reg('partcad.exportScene', (type, path, pkg, name, params) =>
            this.send('export.scene', { type, path, package: pkg, name, params }),
        );
        reg('partcad.addPartReal', (a) =>
            this.send('add.part', { kind: a.kind, path: a.path, package: a.packageName, config: a.config }),
        );
        reg('partcad.addAssemblyReal', (a) =>
            this.send('add.assembly', { kind: a.kind, path: a.path, package: a.packageName }),
        );
        reg('partcad.addSceneReal', (a) =>
            this.send('add.scene', { kind: a.kind, path: a.path, package: a.packageName }),
        );
        reg('partcad.packagePath', (a) => this.send('package.path', { package: a.packageName, callback: a.callback }));
        reg('partcad.inspectFile', (path) => this.send('inspect.file', { path: typeof path === 'string' ? path : '' }));
        // Through the CLI, not over this connection. Checking an ASSY file is
        // the client's own work on the client's own file -- usually one the
        // editor has not saved -- so it never goes to the daemon, and it keeps
        // answering when the daemon is down or the package will not load
        // because of the very file being typed into.
        reg('partcad.lintFile', (a) => this.lintFile(typeof a === 'string' ? { path: a } : a));
        // Through the CLI for the same reason, and a stronger one: a daemon can
        // be remote, and "open this in FreeCAD" is meaningless anywhere but on
        // the machine sitting in front of the user.
        reg('partcad.openExternal', (a) => this.openExternal(typeof a === 'string' ? { path: a } : a));
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
 * The environment a `pc` invocation runs in: the caller's, with the child's
 * text encoding pinned to UTF-8.
 *
 * What travels between the two processes is UTF-8 either way -- Node writes a
 * string to a pipe as UTF-8 and decodes what comes back the same way -- but
 * Python chooses the encoding of its own streams from the locale, which is
 * UTF-8 on Linux and macOS and the ANSI code page on Windows. So a `pc lint
 * --stdin` there was handed an editor buffer it decoded with cp1252: a
 * description with an umlaut in it arrived as mojibake, and a byte the code
 * page has no character for killed the decoder and took the findings with it.
 * `pc` reads its own end as UTF-8 as well (see `_lint_files`); this is the
 * other half of the same agreement, and covers every `pc` this runs.
 */
function utf8Env(env?: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
    return {
        ...(env ?? process.env),
        // eslint-disable-next-line @typescript-eslint/naming-convention
        PYTHONUTF8: '1',
        // eslint-disable-next-line @typescript-eslint/naming-convention
        PYTHONIOENCODING: 'utf-8',
    };
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
        const proc = cp.execFile(cliPath, ['--no-ansi', ...args], { cwd, env: utf8Env(env) }, (err, stdout, stderr) => {
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
 * This installation has no daemon to connect to, whatever the setting says.
 *
 * Not the same thing as a daemon that failed to start: it means `pc` answered
 * the question and the answer was "not here". The caller runs a service of its
 * own over stdio instead, which is what the user gets either way -- the daemon
 * only makes it warm and shared.
 */
class NoDaemonChannel extends Error {}

/**
 * The endpoint in `pc daemon start`'s output, or undefined if it printed none.
 *
 * It prints one line: an absolute path to a Unix socket, or a `\\.\pipe\...`
 * name on Windows. A `pc` with no daemon for this platform answers with a
 * sentence saying so instead -- on stdout, with a zero exit status -- and
 * "the first non-empty line" handed that sentence to `net.connect`, which
 * reported ENOENT about a filename made of English and left the window with no
 * backend at all. So what is printed has to look like an endpoint before it is
 * treated as one; anything else means no daemon channel here.
 *
 * Exported for the test suite: this is the parse that decides whether a
 * platform has a daemon, and it cannot be exercised from a machine that has one.
 */
export function daemonEndpointIn(stdout: string): string | undefined {
    return stdout
        .split(/\r?\n/)
        .map((line) => line.trim())
        .find((line) => /^\\\\[.?]\\pipe\\./.test(line) || (line.length > 0 && path.isAbsolute(line)));
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
    const endpoint = daemonEndpointIn(stdout);
    if (!endpoint) {
        const said = stdout.trim().split(/\r?\n/)[0];
        throw new NoDaemonChannel(`\`pc daemon start\` printed no endpoint: ${said || '(nothing)'}`);
    }
    return endpoint;
}

/** How long to keep trying an endpoint `pc` has said is being served. */
const CONNECT_TIMEOUT_MS = 10000;
const CONNECT_RETRY_MS = 100;

/** Connect failures worth trying again: the endpoint is not there *yet*. */
const CONNECT_RETRY_CODES = ['ENOENT', 'ECONNREFUSED', 'EBUSY', 'EAGAIN'];

/**
 * Connect to the daemon's endpoint, retrying while it is not there yet.
 *
 * `pc daemon start` waits for the daemon to answer before printing where it is,
 * so the first attempt normally succeeds and this costs nothing. It is for the
 * moment either side of that -- and for the difference between the two
 * transports: a POSIX daemon binds and listens before it prints, so a client
 * that arrives early simply queues, while a Windows daemon is a separate
 * process whose named pipe does not exist until it is ready, and connecting to
 * a pipe that is not there fails outright rather than waiting.
 */
async function connectEndpoint(endpoint: string): Promise<net.Socket> {
    const deadline = Date.now() + CONNECT_TIMEOUT_MS;
    for (;;) {
        try {
            return await new Promise<net.Socket>((resolve, reject) => {
                const socket = net.connect(endpoint);
                socket.once('connect', () => resolve(socket));
                socket.once('error', (e) => {
                    socket.destroy();
                    reject(e);
                });
            });
        } catch (e: any) {
            if (!CONNECT_RETRY_CODES.includes(e?.code) || Date.now() >= deadline) {
                throw e;
            }
            await new Promise((resolve) => setTimeout(resolve, CONNECT_RETRY_MS));
        }
    }
}

async function connectSocket(
    execPath: string,
    args: string[],
    cwd: string,
    env: NodeJS.ProcessEnv,
    outputChannel: vscode.LogOutputChannel,
): Promise<JsonRpcBackend> {
    const cliPath = cliBeside(execPath);
    if (!cliPath) {
        // Where the daemon is, and whether one is running, is `pc`'s to answer
        // -- the extension deliberately keeps no second copy of those rules. No
        // `pc` is therefore not a broken daemon but no daemon channel at all,
        // and the service beside it still serves this window perfectly well
        // over stdio.
        throw new NoDaemonChannel(`there is no \`pc\` beside ${execPath} to ask where the daemon is`);
    }
    const socketPath = await daemonEndpoint(cliPath, args, cwd, env, outputChannel);
    traceInfo(`PartCAD service: connecting to daemon at ${socketPath}`);
    const socket = await connectEndpoint(socketPath);
    const connection = createMessageConnection(new StreamMessageReader(socket), new StreamMessageWriter(socket));
    return new JsonRpcBackend(
        connection,
        () => {
            socket.destroy();
        },
        outputChannel,
        { cliPath, cwd, sharedDaemon: true },
    );
}

/** How long to wait for a terminated service process to actually be gone. */
const TERMINATE_TIMEOUT_MS = 5000;

/**
 * Stop the private service process, and everything it started.
 *
 * `kill()` signals the process itself, which is the whole story on POSIX: the
 * service and the sandboxed runtimes it launched share a process group and go
 * down together. Windows has no such group -- the children of a terminated
 * process keep running, and they keep the bundle directory open, which is the
 * one thing that makes replacing it fail there -- so the tree is taken down by
 * pid instead. `taskkill` is part of Windows; a machine without it, or a
 * process that has already exited, falls through to `kill()`.
 */
async function terminate(proc: cp.ChildProcess): Promise<void> {
    if (proc.exitCode !== null || proc.signalCode !== null) {
        return;
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    const exited = new Promise<void>((resolve) => {
        proc.once('exit', () => resolve());
        // Waiting is not the same as waiting forever: a service wedged in a
        // signal handler must not hold up the window's shutdown.
        timer = setTimeout(resolve, TERMINATE_TIMEOUT_MS);
    });
    let killed = false;
    if (process.platform === 'win32' && proc.pid !== undefined) {
        killed = await new Promise<boolean>((resolve) => {
            cp.execFile('taskkill', ['/pid', String(proc.pid), '/t', '/f'], (err) => resolve(!err));
        });
    }
    if (!killed) {
        try {
            proc.kill();
        } catch {
            // Already gone.
        }
    }
    await exited;
    if (timer !== undefined) {
        clearTimeout(timer);
    }
}

function connectStdio(
    execPath: string,
    args: string[],
    cwd: string,
    env: NodeJS.ProcessEnv,
    outputChannel: vscode.LogOutputChannel,
): JsonRpcBackend {
    traceInfo(`PartCAD service: launching ${execPath} --stdio`);
    const proc = cp.spawn(execPath, ['--stdio', ...args], {
        cwd,
        env: utf8Env(env),
    }) as cp.ChildProcessWithoutNullStreams;
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
        () => terminate(proc),
        outputChannel,
        // A private service process, so `pc daemon stop` must not be used on it
        // -- but `pc lint --file` still is: it acts on a file, not on a daemon.
        { cliPath: cliBeside(execPath), cwd },
    );
}

/**
 * Tell the user, in the `PartCAD` terminal view, that there is no backend.
 *
 * It lists where `resolveServicePath` looked, because the common way to arrive
 * here with PartCAD *installed* is a Python environment the extension host
 * cannot see: `pip install partcad` puts `partcad-json-rpc` in the environment's
 * `bin`/`Scripts`, and that directory is on PATH only inside an activated shell.
 * The extension host inherits the PATH of whatever launched VS Code -- a desktop
 * launcher, the Dock, an unactivated shell -- so the last of the five lookups
 * misses an installation the user can run by hand in the integrated terminal.
 * Naming `partcad.servicePath` beside the list is the fix that always works.
 */
function reportNoService(context: vscode.ExtensionContext, serverId: string): void {
    const searched: string[] = [];
    resolveServicePath(context, serverId, searched);

    const lines = [
        'ERROR: No PartCAD service (partcad-json-rpc) is available.',
        'ERROR: Until there is one, this window has no package tree, no viewer and no checking.',
        'ERROR: Looked for it in:',
        ...searched.map((where) => `ERROR:   - ${where}`),
        'ERROR: Run "Restart PartCAD" to be asked again, and either download it or choose',
        'ERROR: "Find installed PartCAD" and point at the environment it is installed in.',
        'ERROR: If it is already installed and was not found, VS Code very likely cannot see that',
        'ERROR: environment: the PATH above is the one VS Code was started with, not the one an',
        `ERROR: activated terminal has. \`${locateCommand()} partcad-json-rpc\` in a terminal where PartCAD`,
        'ERROR: works prints the path to point at (or to put in the "partcad.servicePath" setting).',
    ];
    writeTerminal(lines.map((line) => `${line}\r\n`).join(''));
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
    const resolution = await ensureServiceExecutable(context, serverId);
    // The tools directory only exists once something is installed, and this is
    // where a first install happens: `ensureServiceExecutable` downloads the
    // bundle when there is none. Activation already ran and found nothing, so
    // without this a user who accepts the download prompt gets a working PartCAD
    // and a terminal with no `pc` in it until the next window. Refresh here, not
    // only after `updateServiceBundle`, which covers upgrades and not first
    // installs.
    refreshToolsPath(context, serverId);
    // What the Explorer's welcome view says when there is nothing to connect to.
    // Set from here because this is the only place that can tell "no service" apart
    // from "a service that has not answered yet", and the two used to look the
    // same in that view: it said "being initialized" indefinitely.
    await vscode.commands.executeCommand('setContext', 'partcad.serviceMissing', resolution.kind === 'none');
    if (resolution.kind === 'restarting') {
        // "Find installed PartCAD": the chosen environment went into
        // `partcad.servicePath`, and that change reaches the configuration
        // handler, which restarts. Standing down here is what keeps that the
        // only start -- nothing serialises two of them.
        traceInfo('PartCAD: service path set to a local Python environment; the configuration change restarts.');
        return undefined;
    }
    if (resolution.kind === 'none') {
        // Declining used to fall back to the Python backend. There is nothing to
        // fall back to now, and nothing to invent: the user has told us not to
        // download and not to point at an installation, so the honest outcome is
        // no backend and a message saying how to supply one.
        //
        // Said in the terminal view as well as the log. Without a backend the
        // window is inert -- no package tree, no viewer, no lint -- and the
        // output channel this used to go to alone is not open by default, so the
        // failure looked like nothing happening at all.
        traceInfo('PartCAD: no PartCAD service available; install one with `pip install partcad`.');
        reportNoService(context, serverId);
        return undefined;
    }
    const execPath = resolution.execPath;
    const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd();
    const args = serviceArgs(serverId);
    const env = serviceEnv(serverId);
    try {
        if (getServiceChannelFromSetting(serverId) === 'stdio') {
            return connectStdio(execPath, args, cwd, env, outputChannel);
        }
        return await connectSocket(execPath, args, cwd, env, outputChannel);
    } catch (e) {
        if (e instanceof NoDaemonChannel) {
            // The installation has no daemon for this platform. That is a
            // reason to run the service a different way, not a reason to leave
            // the window with no PartCAD in it: everything works over stdio,
            // just per-window and cold. Said out loud, because a user who set
            // `partcad.serviceChannel` to "socket" is entitled to know they did
            // not get it.
            traceInfo(`PartCAD: ${e.message}; running a dedicated service over stdio instead`);
            writeTerminal(
                `WARNING: This PartCAD has no daemon to share, so this window runs a service of its own.\r\n` +
                    `WARNING: ${e.message}\r\n`,
            );
            return connectStdio(execPath, args, cwd, env, outputChannel);
        }
        // Invisible for the same reason as the case above: this leaves the
        // window with no backend, and the output channel is not open.
        traceError(`Failed to start the PartCAD service: ${e}`);
        writeTerminal(
            `ERROR: Failed to start the PartCAD service at ${execPath}\r\n` +
                `ERROR: ${e}\r\n` +
                'ERROR: Run "Restart PartCAD" to try again.\r\n',
        );
        return undefined;
    }
}
