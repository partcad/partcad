//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A client of spacenavd, the daemon that owns a 3Dconnexion SpaceMouse on Linux.
//
// The PartCAD Viewer reads the device through the Gamepad API wherever Chromium
// offers it as one, which is Windows and macOS. On Linux it does not: the kernel
// reports a SpaceMouse's axes as relative motion rather than as a joystick, and
// spacenavd holds the device besides. So the extension host reads spacenavd and
// forwards each event to the panel, and the renderer converts it
// ('src/webview/spacemouse.ts', 'fromSpacenav').
//
// Everything on the socket is native-endian 32-bit integers. An event is eight of
// them - the event type, then six axis values and the milliseconds since the
// previous motion for a motion, or the button number for a button - and that is
// all a client of the original protocol (v0) ever receives.
//
// One thing is asked of the daemon, and it is why this is not a v0 client: which
// device is attached. spacenavd renumbers the buttons of the larger devices into
// a contiguous range of its own, so the "Fit" key is button 1 on a two-button
// SpaceMouse, 5 on a SpaceMouse Pro and 13 on an Enterprise, and nothing in a
// button event says which of those it came from. So the client asks for protocol
// v1 on connecting - one tagged integer, answered with the version granted - and
// then asks for the device type (REQ_DEV_TYPE), again whenever spacenavd says a
// device came or went. A spacenavd older than 1.0 does not answer the first
// question; it reads the integer as a sensitivity, which is a NaN and ignored by
// every version that checks, and the client puts it back to 1 for the ones that
// do not - which is what libspnav does. Nothing else about the daemon is changed.
//
// It runs in the extension host, which is on the machine the workspace is on. On
// a remote workspace that is not the machine the SpaceMouse is plugged into, and
// there is no spacenavd to find; the Gamepad API is the road there, since the
// webview is always drawn locally.
//

import * as net from 'net';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

/** The event types, as spacenavd's 'proto.h' orders them. */
const UEV_MOTION = 0;
const UEV_PRESS = 1;
const UEV_RELEASE = 2;
/** A device was added or removed; v1 only. */
const UEV_DEV = 3;

/** What marks a request, and a response to one, apart from an event. */
export const REQ_TAG = 0x7faa0000;
export const REQ_CHANGE_PROTO = 0x5500;
export const REQ_DEV_TYPE = 0x2005;
/** The protocol this client asks for. */
const PROTO_VERSION = 1;

/** One event, or one response to a request: eight 32-bit integers. */
export const EVENT_BYTES = 32;
/** The answer to a protocol change: one. */
const PROTO_BYTES = 4;

/** How long a spacenavd that speaks v1 takes to say so; libspnav waits as long. */
const PROTO_TIMEOUT_MS = 300;

/** What can arrive on the socket. */
export type SpacenavMessage =
    | { motion: number[] }
    | { button: number; pressed: boolean }
    /** A device was plugged in or out, so the device type is to be asked again. */
    | { deviceChanged: true }
    /** The protocol version the daemon granted. */
    | { protocol: number }
    /** The answer to a request: its type, its seven integers, and its status. */
    | { response: number; data: number[]; status: number };

export type SpacenavEvent = { motion: number[] } | { button: number; pressed: boolean };

/**
 * Where spacenavd listens, in the order libspnav looks.
 *
 * '/var/run/spnav.sock' is the default of every packaged spacenavd; the runtime
 * directory is where one started by the user, without root, puts it.
 */
export function socketPaths(env: NodeJS.ProcessEnv = process.env): string[] {
    const paths = ['/var/run/spnav.sock'];
    if (env.XDG_RUNTIME_DIR) {
        // POSIX whatever the host: spacenavd is a Unix daemon, and 'path.join'
        // would spell this with backslashes on Windows.
        paths.push(path.posix.join(env.XDG_RUNTIME_DIR, 'spnav.sock'));
    }
    return paths;
}

/** One integer of the protocol, in the byte order it is written in. */
function int32(value: number, endianness: 'LE' | 'BE'): Buffer {
    const buffer = Buffer.alloc(4);
    if (endianness === 'LE') {
        buffer.writeInt32LE(value | 0);
    } else {
        buffer.writeInt32BE(value | 0);
    }
    return buffer;
}

/** The request asking for protocol v1. */
export function protocolRequest(endianness: 'LE' | 'BE' = os.endianness()): Buffer {
    return int32(REQ_TAG | REQ_CHANGE_PROTO | PROTO_VERSION, endianness);
}

/** A v1 request with no arguments, such as REQ_DEV_TYPE. */
export function request(type: number, endianness: 'LE' | 'BE' = os.endianness()): Buffer {
    return Buffer.concat([int32(REQ_TAG | type, endianness), Buffer.alloc(EVENT_BYTES - 4)]);
}

/**
 * The whole messages in 'buffer', and what is left over of the next one.
 *
 * A stream socket cuts its data wherever it likes, so a message can arrive in two
 * reads; the remainder is kept and prepended to the next. What a message is can
 * be told from its first integer: an event's is its type, a small number; a
 * response's is the request it answers, tagged; and the answer to a protocol
 * change is that one tagged integer on its own - which is also why it can be
 * found wherever it lands between events. Events of a type this does not know
 * are skipped rather than misread. The integers are in the byte order of the
 * machine spacenavd runs on, which is this one: it is a local socket.
 */
export function decodeMessages(
    buffer: Buffer,
    endianness: 'LE' | 'BE' = os.endianness(),
): { messages: SpacenavMessage[]; rest: Buffer } {
    const messages: SpacenavMessage[] = [];
    let offset = 0;
    const int = (at: number) => (endianness === 'LE' ? buffer.readInt32LE(at) : buffer.readInt32BE(at));
    while (offset + PROTO_BYTES <= buffer.length) {
        const first = int(offset);
        if ((first & 0xffffff00) === (REQ_TAG | REQ_CHANGE_PROTO)) {
            messages.push({ protocol: first & 0xff });
            offset += PROTO_BYTES;
            continue;
        }
        if (offset + EVENT_BYTES > buffer.length) {
            break;
        }
        const at = (index: number) => int(offset + index * 4);
        if ((first & 0xffff0000) === REQ_TAG) {
            messages.push({
                response: first & 0xffff,
                data: [at(1), at(2), at(3), at(4), at(5), at(6)],
                status: at(7),
            });
        } else if (first === UEV_MOTION) {
            messages.push({ motion: [at(1), at(2), at(3), at(4), at(5), at(6)] });
        } else if (first === UEV_PRESS || first === UEV_RELEASE) {
            messages.push({ button: at(1), pressed: first === UEV_PRESS });
        } else if (first === UEV_DEV) {
            messages.push({ deviceChanged: true });
        }
        offset += EVENT_BYTES;
    }
    return { messages, rest: buffer.subarray(offset) };
}

/** How long to wait before looking for spacenavd again, after it was not there or went away. */
const RETRY_MS = 5000;

/**
 * A connection to spacenavd that keeps itself up.
 *
 * spacenavd may start after VS Code, or be restarted under it (a device plugged
 * in, a package upgraded), so a connection that failed or closed is retried on a
 * timer for as long as this exists - a connect to a socket file that does not
 * exist costs nothing. Whether it is connected, and which device it serves, are
 * state of their own: the renderer stops consulting the Gamepad API while it is
 * connected, and needs the device to know which button is "Fit".
 */
export class SpacenavClient implements vscode.Disposable {
    private readonly eventEmitter = new vscode.EventEmitter<SpacenavEvent>();
    private readonly stateEmitter = new vscode.EventEmitter<void>();
    public readonly onEvent = this.eventEmitter.event;
    /** 'connected' or 'device' changed. */
    public readonly onDidChangeState = this.stateEmitter.event;

    private socket: net.Socket | undefined;
    private timer: NodeJS.Timeout | undefined;
    private disposed = false;
    private _connected = false;
    private _device: number | undefined;

    constructor(private readonly paths: string[] = socketPaths()) {
        this.connect(0);
    }

    public get connected(): boolean {
        return this._connected;
    }

    /**
     * The attached device, as spacenavd's 'DEV_*' enumeration numbers it.
     *
     * Undefined until it has been asked, and for good with a spacenavd too old
     * to be asked.
     */
    public get device(): number | undefined {
        return this._device;
    }

    private connect(index: number): void {
        if (this.disposed) {
            return;
        }
        if (index >= this.paths.length) {
            this.timer = setTimeout(() => this.connect(0), RETRY_MS);
            return;
        }
        let rest: Buffer = Buffer.alloc(0);
        let opened = false;
        let negotiation: NodeJS.Timeout | undefined;
        const socket = net.connect(this.paths[index]);
        this.socket = socket;
        socket.on('connect', () => {
            opened = true;
            this.setState(true, undefined);
            socket.write(protocolRequest());
            negotiation = setTimeout(() => {
                // No answer: a spacenavd from before v1, which took the request
                // for a sensitivity. Put that back, and carry on with v0.
                const one = Buffer.alloc(4);
                if (os.endianness() === 'LE') {
                    one.writeFloatLE(1);
                } else {
                    one.writeFloatBE(1);
                }
                socket.write(one);
            }, PROTO_TIMEOUT_MS);
        });
        socket.on('data', (data: Buffer) => {
            const decoded = decodeMessages(rest.length > 0 ? Buffer.concat([rest, data]) : data);
            rest = decoded.rest;
            for (const message of decoded.messages) {
                if ('protocol' in message) {
                    clearTimeout(negotiation);
                    if (message.protocol >= 1) {
                        socket.write(request(REQ_DEV_TYPE));
                    }
                } else if ('deviceChanged' in message) {
                    socket.write(request(REQ_DEV_TYPE));
                } else if ('response' in message) {
                    if (message.response === REQ_DEV_TYPE) {
                        this.setState(true, message.status >= 0 ? message.data[0] : undefined);
                    }
                } else {
                    this.eventEmitter.fire(message);
                }
            }
        });
        // 'close' follows 'error', so the retry is decided there and only there.
        socket.on('error', () => undefined);
        socket.on('close', () => {
            clearTimeout(negotiation);
            if (this.socket !== socket) {
                return;
            }
            this.socket = undefined;
            this.setState(false, undefined);
            if (opened) {
                // It was there and went away: look for it again from the top.
                this.timer = setTimeout(() => this.connect(0), RETRY_MS);
            } else {
                this.connect(index + 1);
            }
        });
    }

    private setState(connected: boolean, device: number | undefined): void {
        if (this._connected !== connected || this._device !== device) {
            this._connected = connected;
            this._device = device;
            this.stateEmitter.fire();
        }
    }

    public dispose(): void {
        this.disposed = true;
        if (this.timer !== undefined) {
            clearTimeout(this.timer);
        }
        const socket = this.socket;
        this.socket = undefined;
        socket?.destroy();
        this.eventEmitter.dispose();
        this.stateEmitter.dispose();
    }
}
