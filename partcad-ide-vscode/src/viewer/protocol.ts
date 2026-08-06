//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The JS half of the PartCAD IDE viewer protocol. The normative description of
// the wire format lives next to the other half, in
// 'partcad-ide-client/src/partcad_ide_client/protocol.py'; keep the two in step.
//
// A frame is a 10-byte header followed by a UTF-8 JSON payload:
//
//     offset  size  field
//     0       4     magic, always "PCAD"
//     4       1     protocol version
//     5       1     payload kind
//     6       4     payload length, big-endian uint32
//     10      n     payload
//
// Geometry rides inside a "show" message as deflate-compressed, base64-encoded
// binary glTF. It is deflate and not zstd (which PartCAD's BREP envelopes use)
// precisely so that this side can decompress it with Node's built-in zlib:
// zstd only reached Node in 23.8, well past what VS Code ships.

import * as zlib from 'zlib';

export const MAGIC = 'PCAD';
export const VERSION = 1;
export const KIND_JSON = 1;
export const HEADER_LENGTH = 10;

/** The constant port the viewer listens on. See the Python side for why it is fixed. */
export const PARTCAD_IDE_PORT = 9137;
export const PARTCAD_IDE_HOST = '127.0.0.1';

/**
 * A single frame is capped so a desynchronized or hostile peer cannot make us
 * allocate an arbitrary buffer. Must match MAX_FRAME_LENGTH on the Python side.
 */
export const MAX_FRAME_LENGTH = 256 * 1024 * 1024;

export const MSG_SHOW = 'show';
export const MSG_CLEAR = 'clear';
export const MSG_PING = 'ping';
export const MSG_ACK = 'ack';

/** A displayable object: compressed glTF plus the names to label it with. */
export interface ViewerObject {
    name?: string | null;
    label?: string | null;
    gltf: string;
}

/** A bare coordinate frame (a PartCAD interface port), as a packed location. */
export interface ViewerMarker {
    name?: string | null;
    // [[tx, ty, tz], [ax, ay, az], angleInDegrees]
    location: [[number, number, number], [number, number, number], number];
}

export interface ViewerMessage {
    type: string;
    id?: string;
    name?: string | null;
    kind?: string | null;
    keepCamera?: boolean;
    objects?: ViewerObject[];
    markers?: ViewerMarker[];
}

export class ProtocolError extends Error {}

/** Serialize a message into a single frame. */
export function encodeFrame(message: unknown): Buffer {
    const payload = Buffer.from(JSON.stringify(message), 'utf-8');
    if (payload.length > MAX_FRAME_LENGTH) {
        throw new ProtocolError(`message of ${payload.length} bytes exceeds the ${MAX_FRAME_LENGTH} byte frame limit`);
    }
    const header = Buffer.alloc(HEADER_LENGTH);
    header.write(MAGIC, 0, 4, 'ascii');
    header.writeUInt8(VERSION, 4);
    header.writeUInt8(KIND_JSON, 5);
    header.writeUInt32BE(payload.length, 6);
    return Buffer.concat([header, payload]);
}

/** Validate a frame header and return the payload length that follows it. */
export function decodeHeader(header: Buffer): number {
    if (header.length !== HEADER_LENGTH) {
        throw new ProtocolError(`frame header must be ${HEADER_LENGTH} bytes, got ${header.length}`);
    }
    if (header.toString('ascii', 0, 4) !== MAGIC) {
        throw new ProtocolError(`bad frame magic ${JSON.stringify(header.toString('ascii', 0, 4))}`);
    }
    const version = header.readUInt8(4);
    if (version !== VERSION) {
        throw new ProtocolError(`unsupported protocol version ${version} (this viewer speaks ${VERSION})`);
    }
    const kind = header.readUInt8(5);
    if (kind !== KIND_JSON) {
        throw new ProtocolError(`unsupported payload kind ${kind}`);
    }
    const length = header.readUInt32BE(6);
    if (length > MAX_FRAME_LENGTH) {
        throw new ProtocolError(`frame of ${length} bytes exceeds the ${MAX_FRAME_LENGTH} byte limit`);
    }
    return length;
}

/** Parse a frame payload into a message. */
export function decodePayload(payload: Buffer): ViewerMessage {
    let parsed: unknown;
    try {
        parsed = JSON.parse(payload.toString('utf-8'));
    } catch (e) {
        throw new ProtocolError(`frame payload is not valid JSON: ${e}`);
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new ProtocolError('frame payload must be a JSON object');
    }
    const message = parsed as ViewerMessage;
    if (typeof message.type !== 'string') {
        throw new ProtocolError('frame payload has no message type');
    }
    return message;
}

/** Turn a wire payload back into the binary glTF buffer it carries. */
export function decodeGltf(payload: string): Buffer {
    return zlib.inflateSync(Buffer.from(payload, 'base64'));
}

/**
 * Reassembles frames from a byte stream.
 *
 * TCP gives no message boundaries, so a show large enough to matter always
 * arrives split across several 'data' events; this buffers until a whole frame
 * is present. It is deliberately a plain class rather than a stream transform so
 * that a protocol error can be surfaced to the caller as a thrown error and the
 * connection dropped, instead of being swallowed by a pipeline.
 */
export class FrameReader {
    private buffer: Buffer = Buffer.alloc(0);

    /** Append received bytes and return every complete message they contain. */
    public push(chunk: Buffer): ViewerMessage[] {
        this.buffer = this.buffer.length === 0 ? chunk : Buffer.concat([this.buffer, chunk]);

        const messages: ViewerMessage[] = [];
        for (;;) {
            if (this.buffer.length < HEADER_LENGTH) {
                return messages;
            }
            const length = decodeHeader(this.buffer.subarray(0, HEADER_LENGTH));
            if (this.buffer.length < HEADER_LENGTH + length) {
                return messages;
            }
            messages.push(decodePayload(this.buffer.subarray(HEADER_LENGTH, HEADER_LENGTH + length)));
            this.buffer = this.buffer.subarray(HEADER_LENGTH + length);
        }
    }
}
