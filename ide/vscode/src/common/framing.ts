//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The framing the extension speaks to PartCAD with: the Language Server
// Protocol's `Content-Length` and a JSON body -- which is what vscode-jsonrpc's
// own reader and writer speak -- and, after the body, the raw bytes of the files
// a message carries. `partcad_utils/framing.py` is the normative description;
// this is its one TypeScript copy, and the two have to stay in step.
//
//     Content-Length: <body bytes>\r\n
//     Attachment-Lengths: <bytes>,<bytes>,...\r\n
//     \r\n
//     <body><segment 0><segment 1>...
//
// The body names each segment where it belongs, as {"$attachment": <index>},
// and the reader puts the segment there as a Uint8Array.
//
// A file used to cross as base64 inside the JSON instead: a third bigger, and
// decoded on the extension host's event loop -- a forty-megabyte render held
// it for a quarter of a second, and every webview of the window with it. The
// daemon sends attachments only to a client that says it reads them, which
// this writer says on every message (`Accept-Attachments: 1`); a daemon from
// before them never looks, and goes on sending base64 under the same keys. So
// a field that carries a file is read with `bytesOf`, which takes either.
//

import { Readable, Writable } from 'stream';
import {
    AbstractMessageReader,
    AbstractMessageWriter,
    DataCallback,
    Disposable,
    Message,
    MessageReader,
    MessageWriter,
} from 'vscode-jsonrpc/node';

/** The lengths of the raw segments that follow a message's body, in order. */
export const ATTACHMENT_LENGTHS = 'attachment-lengths';
/** "You may send me attachments"; the value is the form of them read, and there is one. */
export const ACCEPT_ATTACHMENTS = 'Accept-Attachments: 1';
/** How a body names a segment. */
export const ATTACHMENT_KEY = '$attachment';

const CR = 13;
const LF = 10;

/**
 * The bytes of a file a message carried, whichever way it was carried.
 *
 * A Uint8Array when it came as an attachment, base64 text from a daemon that
 * sends none, and undefined for no file. Always a plain Uint8Array that owns
 * its memory, never a Node `Buffer`: a Buffer posted to a webview is turned
 * into a JSON array of numbers by its `toJSON`, where a Uint8Array is handed
 * over as it is.
 */
export function bytesOf(value: unknown): Uint8Array | undefined {
    if (typeof value === 'string') {
        return copied(Buffer.from(value, 'base64'));
    }
    if (value instanceof Uint8Array) {
        return Buffer.isBuffer(value) ? copied(value) : value;
    }
    return undefined;
}

function copied(source: Uint8Array): Uint8Array {
    const bytes = new Uint8Array(source.byteLength);
    bytes.set(source);
    return bytes;
}

/** A frame whose header has been read, and how far into the rest of it the reader is. */
interface Frame {
    length: number;
    attachments: number[];
    /** The body, once all of it has arrived. */
    body?: string;
    /** The segments begun so far, the last of them perhaps still filling. */
    segments: Uint8Array[];
    /** How much of the last of them is filled. */
    filled: number;
}

/**
 * Reads framed messages, attachments and all, off a stream.
 *
 * The bytes received are kept as the list of chunks they arrived in. Joining
 * every new chunk onto what came before is the alternative, and it copies a
 * large message once per chunk -- forty megabytes in 64 KiB chunks is six
 * hundred copies of an ever longer buffer. A segment is copied once, into
 * memory of its own the size of the file, and as its chunks arrive rather than
 * all at the end: the last chunk of a large file is then as quick to take in as
 * any other, where one copy of all of it held the event loop for some fifty
 * milliseconds.
 */
export class AttachmentMessageReader extends AbstractMessageReader implements MessageReader {
    private readonly chunks: Uint8Array[] = [];
    private buffered = 0;
    /** How far the search for the end of the header got, so it never starts over. */
    private scanned = 0;
    private scanState = 0;
    private frame: Frame | undefined;
    private callback: DataCallback | undefined;
    private readonly decoder = new TextDecoder('utf-8');

    constructor(private readonly readable: Readable) {
        super();
    }

    public listen(callback: DataCallback): Disposable {
        this.callback = callback;
        const onData = (data: Buffer | string) => this.onData(typeof data === 'string' ? Buffer.from(data) : data);
        const onError = (error: Error) => this.fireError(error);
        const onClose = () => this.fireClose();
        this.readable.on('data', onData);
        this.readable.on('error', onError);
        this.readable.on('close', onClose);
        return Disposable.create(() => {
            this.readable.off('data', onData);
            this.readable.off('error', onError);
            this.readable.off('close', onClose);
        });
    }

    /** Take in what arrived, and hand on every message it completes. */
    public onData(data: Uint8Array): void {
        if (data.byteLength === 0) {
            return;
        }
        this.chunks.push(data);
        this.buffered += data.byteLength;
        for (;;) {
            let message: Message | undefined;
            try {
                message = this.next();
            } catch (error) {
                // Nothing after a frame that does not parse can be found again.
                this.frame = undefined;
                this.chunks.length = 0;
                this.buffered = 0;
                this.scanned = 0;
                this.scanState = 0;
                this.fireError(error);
                return;
            }
            if (message === undefined) {
                return;
            }
            try {
                this.callback?.(message);
            } catch (error) {
                this.fireError(error);
            }
        }
    }

    /** The next whole message, or undefined until all of it has arrived. */
    private next(): Message | undefined {
        if (this.frame === undefined) {
            const headers = this.takeHeaders();
            if (headers === undefined) {
                return undefined;
            }
            this.frame = { ...parseFrame(headers), segments: [], filled: 0 };
        }
        const frame = this.frame;
        if (frame.body === undefined) {
            if (this.buffered < frame.length) {
                return undefined;
            }
            frame.body = this.decoder.decode(this.take(frame.length));
        }
        for (;;) {
            let segment = frame.segments[frame.segments.length - 1];
            if (segment === undefined || frame.filled === segment.byteLength) {
                if (frame.segments.length === frame.attachments.length) {
                    break;
                }
                // Memory of its own, the size of the file: a view into a chunk
                // would keep the whole chunk alive, and hand a webview all of it.
                segment = new Uint8Array(frame.attachments[frame.segments.length]);
                frame.segments.push(segment);
                frame.filled = 0;
                continue;
            }
            if (this.buffered === 0) {
                return undefined;
            }
            frame.filled += this.fill(segment, frame.filled);
        }
        this.frame = undefined;
        const message = JSON.parse(frame.body);
        return (frame.segments.length > 0 ? materialize(message, frame.segments) : message) as Message;
    }

    /** The header lines, when the blank line that ends them has arrived. */
    private takeHeaders(): Map<string, string> | undefined {
        let position = 0;
        for (const chunk of this.chunks) {
            if (position + chunk.byteLength <= this.scanned) {
                position += chunk.byteLength;
                continue;
            }
            for (let i = this.scanned - position; i < chunk.byteLength; i++) {
                const byte = chunk[i];
                // CR LF CR LF, counted as it goes: 1, 2, 3 and 4 bytes of it.
                if (byte === CR) {
                    this.scanState = this.scanState === 2 ? 3 : 1;
                } else if (byte === LF && (this.scanState === 1 || this.scanState === 3)) {
                    this.scanState += 1;
                } else {
                    this.scanState = 0;
                }
                if (this.scanState === 4) {
                    const end = position + i + 1;
                    this.scanned = 0;
                    this.scanState = 0;
                    return parseHeaders(this.decoder.decode(this.take(end)));
                }
            }
            position += chunk.byteLength;
            this.scanned = position;
        }
        return undefined;
    }

    /** The next `length` bytes, all of which have arrived: a view where they lie in one chunk. */
    private take(length: number): Uint8Array {
        const first = this.chunks[0];
        if (first !== undefined && first.byteLength >= length) {
            this.buffered -= length;
            if (first.byteLength === length) {
                this.chunks.shift();
            } else {
                this.chunks[0] = first.subarray(length);
            }
            return first.subarray(0, length);
        }
        const bytes = new Uint8Array(length);
        this.fill(bytes, 0);
        return bytes;
    }

    /** Copy what has arrived into `target`, from `offset` on, up to its end; returns how much. */
    private fill(target: Uint8Array, offset: number): number {
        const wanted = target.byteLength - offset;
        let copied = 0;
        let used = 0;
        while (copied < wanted && used < this.chunks.length) {
            const chunk = this.chunks[used];
            const count = Math.min(chunk.byteLength, wanted - copied);
            target.set(count === chunk.byteLength ? chunk : chunk.subarray(0, count), offset + copied);
            copied += count;
            if (count === chunk.byteLength) {
                used++;
            } else {
                this.chunks[used] = chunk.subarray(count);
            }
        }
        // At once rather than a shift per chunk: a large file is hundreds of them.
        this.chunks.splice(0, used);
        this.buffered -= copied;
        return copied;
    }
}

function parseHeaders(text: string): Map<string, string> {
    const headers = new Map<string, string>();
    for (const line of text.split('\r\n')) {
        if (line.trim() === '') {
            continue;
        }
        const colon = line.indexOf(':');
        if (colon === -1) {
            throw new Error(`A message header must separate its name and value with ':': ${line}`);
        }
        headers.set(line.slice(0, colon).trim().toLowerCase(), line.slice(colon + 1).trim());
    }
    return headers;
}

function parseFrame(headers: Map<string, string>): { length: number; attachments: number[] } {
    const length = Number.parseInt(headers.get('content-length') ?? '', 10);
    if (!Number.isFinite(length) || length < 0) {
        throw new Error(`A message header must give a Content-Length: ${JSON.stringify(Object.fromEntries(headers))}`);
    }
    const announced = headers.get(ATTACHMENT_LENGTHS);
    const attachments = announced ? announced.split(',').map((size) => Number.parseInt(size.trim(), 10)) : [];
    if (attachments.some((size) => !Number.isFinite(size) || size < 0)) {
        throw new Error(`Attachment-Lengths must be a list of byte counts: ${announced}`);
    }
    return { length, attachments };
}

/** Put each segment where the body names it. */
export function materialize(value: unknown, segments: Uint8Array[]): unknown {
    if (Array.isArray(value)) {
        for (let i = 0; i < value.length; i++) {
            value[i] = materialize(value[i], segments);
        }
        return value;
    }
    if (value !== null && typeof value === 'object') {
        const record = value as Record<string, unknown>;
        const keys = Object.keys(record);
        if (keys.length === 1 && keys[0] === ATTACHMENT_KEY && typeof record[ATTACHMENT_KEY] === 'number') {
            const segment = segments[record[ATTACHMENT_KEY] as number];
            if (segment === undefined) {
                throw new Error(`A message names attachment ${record[ATTACHMENT_KEY]}, of ${segments.length}`);
            }
            return segment;
        }
        for (const key of keys) {
            record[key] = materialize(record[key], segments);
        }
    }
    return value;
}

/**
 * Writes framed messages, saying in each that this end reads attachments.
 *
 * Writes none itself: no method takes a file, so a request has nothing to
 * attach, and a client that never sends one need not know whether its daemon
 * could read it. Otherwise what vscode-jsonrpc's own writer writes.
 */
export class AttachmentMessageWriter extends AbstractMessageWriter implements MessageWriter {
    private errorCount = 0;

    constructor(private readonly writable: Writable) {
        super();
        this.writable.on('error', (error: Error) => this.fireError(error));
        this.writable.on('close', () => this.fireClose());
    }

    public write(msg: Message): Promise<void> {
        return new Promise<void>((resolve, reject) => {
            const body = Buffer.from(JSON.stringify(msg), 'utf8');
            const header = Buffer.from(`Content-Length: ${body.byteLength}\r\n${ACCEPT_ATTACHMENTS}\r\n\r\n`, 'ascii');
            // One write, so that nothing written meanwhile lands between the two.
            this.writable.write(Buffer.concat([header, body]), (error?: Error | null) => {
                if (error) {
                    this.errorCount++;
                    this.fireError(error, msg, this.errorCount);
                    reject(error);
                } else {
                    resolve();
                }
            });
        });
    }

    public end(): void {
        this.writable.end();
    }
}
