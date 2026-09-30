//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//

import * as net from 'net';
import * as vscode from 'vscode';
import { traceError, traceLog, traceVerbose } from '../common/log/logging';
import {
    FrameReader,
    MSG_ACK,
    MSG_CLEAR,
    MSG_PING,
    MSG_SHOW,
    PARTCAD_IDE_HOST,
    ViewerMessage,
    encodeFrame,
    listenPort,
} from './protocol';

/**
 * Where SO_REUSEPORT can be asked for.
 *
 * libuv implements the option only where it also load-balances the incoming
 * connections -- Linux, FreeBSD, DragonFly, Solaris 11.4, AIX 7.2.5 -- and
 * *rejects the bind* with ENOTSUP everywhere else, rather than ignoring it.
 * Only the one this is exercised on is listed: an AIX or Solaris too old for it
 * would fail the bind exactly as Windows does, and what is bought is an
 * optimisation, not the viewer.
 */
const REUSEPORT_PLATFORMS: ReadonlySet<string> = new Set(['linux']);

/**
 * How to bind the viewer port on this platform.
 *
 * SO_REUSEPORT lets two windows each hold the port and have the kernel hand
 * each connection to one of them, instead of the second window losing the race
 * and having no viewer at all. It is asked for only where it exists: `listen`
 * fails outright with ENOTSUP on a platform libuv does not support it on, and
 * that is not a failure this can shrug off -- it is the whole viewer, silently,
 * with only a line in the output channel to show for it. It went unnoticed
 * because Node ignored the option until 22.12 and VS Code shipped an older one;
 * a VS Code on Node 22.12 or later takes the viewer down on Windows and macOS.
 *
 * There is nothing to ask for instead on Windows. Node's `listen` has no
 * `reuseAddr` option (`dgram` has one, for UDP sockets, and this is TCP), and
 * libuv deliberately sets neither SO_REUSEADDR nor SO_EXCLUSIVEADDRUSE for a
 * TCP server there -- on Windows SO_REUSEADDR does not mean "rebind a port in
 * TIME_WAIT", it means "take a port another process is using". So the second
 * window falls back to what it always did: the EADDRINUSE branch of the error
 * handler, which says another window is serving the viewer.
 *
 * Exported for the test suite, which has to check the platforms it is not
 * running on.
 */
export function listenOptions(port: number, host: string): net.ListenOptions {
    const options: net.ListenOptions = { port, host };
    if (REUSEPORT_PLATFORMS.has(process.platform)) {
        // Not in the object literal above: `reusePort` reached Node's typings
        // in 22.12, and this compiles against the older ones VS Code ships.
        (options as net.ListenOptions & { reusePort?: boolean }).reusePort = true;
    }
    return options;
}

/**
 * Listens for PartCAD processes that want to display something.
 *
 * The IDE is the server half of the protocol: 'partcad' runs in a subprocess (or
 * in a terminal, or in a notebook) and connects in. The port is a constant, so a
 * PartCAD process that the IDE did not start can still find the viewer without
 * any discovery handshake.
 *
 * Bound to loopback only. The payloads are the user's own geometry and the
 * protocol has no authentication, so it must not be reachable off the machine.
 */
export class PartcadViewerServer implements vscode.Disposable {
    private server: net.Server | undefined;
    private sockets = new Set<net.Socket>();
    private readonly onMessageEmitter = new vscode.EventEmitter<ViewerMessage>();

    /** Fires for every well-formed message received from any connected PartCAD. */
    public readonly onMessage = this.onMessageEmitter.event;

    constructor(
        private readonly port: number = listenPort(),
        private readonly host: string = PARTCAD_IDE_HOST,
    ) {}

    public async start(): Promise<void> {
        if (this.server !== undefined) {
            return;
        }

        const server = net.createServer((socket) => this.handleConnection(socket));
        this.server = server;

        server.on('error', (error: NodeJS.ErrnoException) => {
            if (error.code === 'EADDRINUSE') {
                // With SO_REUSEPORT this means another VS Code window got there
                // first on a platform that does not support the option, so that
                // window owns the viewer. Not fatal: everything except showing
                // geometry in this window still works.
                traceError(
                    `PartCAD Viewer port ${this.port} is already in use. ` +
                        'Another window is most likely serving the viewer.',
                );
            } else {
                traceError(`PartCAD Viewer server error: ${error.message}`);
            }
            this.stop();
        });

        await new Promise<void>((resolve) => {
            server.once('listening', () => {
                traceLog(`PartCAD Viewer listening on ${this.host}:${this.port}`);
                resolve();
            });
            server.once('error', () => resolve());

            server.listen(listenOptions(this.port, this.host));
        });
    }

    private handleConnection(socket: net.Socket): void {
        traceVerbose('PartCAD Viewer: a PartCAD process connected');
        this.sockets.add(socket);
        socket.setNoDelay(true);

        const reader = new FrameReader();
        socket.on('data', (chunk: Buffer) => {
            let messages: ViewerMessage[];
            try {
                messages = reader.push(chunk);
            } catch (error: any) {
                // The stream is desynchronized and there is no way back into
                // sync, so drop it rather than keep reinterpreting garbage.
                traceError(`PartCAD Viewer: ${error.message}`);
                socket.destroy();
                return;
            }

            for (const message of messages) {
                this.dispatch(socket, message);
            }
        });

        socket.on('error', (error) => {
            traceVerbose(`PartCAD Viewer: connection error: ${error.message}`);
        });
        socket.on('close', () => {
            this.sockets.delete(socket);
        });
    }

    private dispatch(socket: net.Socket, message: ViewerMessage): void {
        let ok = true;
        try {
            switch (message.type) {
                case MSG_SHOW:
                case MSG_CLEAR:
                    this.onMessageEmitter.fire(message);
                    break;
                case MSG_PING:
                    break;
                default:
                    traceVerbose(`PartCAD Viewer: ignoring unknown message type '${message.type}'`);
                    break;
            }
        } catch (error: any) {
            // Reported rather than rethrown, so that the ack below still goes
            // out: a handler that threw must not also leave the caller blocked.
            ok = false;
            traceError(`PartCAD Viewer: failed to handle a '${message.type}' message: ${error.message}`);
        }

        // Every message is acknowledged, including the ones this build does not
        // understand and the ones that failed: the client blocks on the reply,
        // so staying silent would hang an older or newer PartCAD rather than
        // degrade it.
        if (!socket.destroyed) {
            socket.write(encodeFrame({ type: MSG_ACK, id: message.id ?? null, ok }));
        }
    }

    public stop(): void {
        for (const socket of this.sockets) {
            socket.destroy();
        }
        this.sockets.clear();

        const server = this.server;
        this.server = undefined;
        // Only if it is actually listening: this is also the path taken when the
        // bind failed, and closing a server that never opened re-raises 'error'
        // on some Node versions - straight back into the handler that called us.
        if (server !== undefined && server.listening) {
            server.close();
        }
    }

    public dispose(): void {
        this.stop();
        this.onMessageEmitter.dispose();
    }
}
