//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The JS half of the PartCAD IDE viewer protocol. The normative description of
// the wire format lives next to the other half, in
// 'src/partcad_ide_client/protocol.py'; keep the two in step.
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
 * The port to listen on: the constant one, unless PARTCAD_IDE_PORT says otherwise.
 *
 * The Python client honours the same variable, so both ends move together - a
 * developer running two IDE windows, or pointing a process at a throwaway
 * server, sets it once in the environment. An unparseable or out-of-range value
 * falls back to the constant rather than failing to bind, matching the client.
 *
 * The grammar has to match '_port()' in
 * 'src/partcad_ide_client/client.py' exactly, or the two
 * ends read the same variable differently and this one binds a port the client
 * never connects to: plain decimal digits only (Number() would also take
 * "1e4" and "0x270f"), and 1..65535.
 */
export function listenPort(env: NodeJS.ProcessEnv = process.env): number {
    const raw = env.PARTCAD_IDE_PORT;
    if (!raw || !/^[0-9]+$/.test(raw)) {
        // Unset, empty, or not a decimal number.
        return PARTCAD_IDE_PORT;
    }
    const override = Number(raw);
    // From 1: port 0 means "any free port", which cannot be the far end of a
    // protocol whose whole point is that the client knows where to connect.
    if (override >= 1 && override <= 65535) {
        return override;
    }
    return PARTCAD_IDE_PORT;
}

/**
 * A single frame is capped so a desynchronized or hostile peer cannot make us
 * allocate an arbitrary buffer. Must match MAX_FRAME_LENGTH on the Python side.
 */
export const MAX_FRAME_LENGTH = 256 * 1024 * 1024;

export const MSG_SHOW = 'show';
export const MSG_CLEAR = 'clear';
export const MSG_PING = 'ping';
export const MSG_ACK = 'ack';
/**
 * What the IDE is showing, for `pc ide state`: answered in the acknowledgement,
 * under KEY_STATE. The shape is specified once, beside `MSG_STATE` in
 * `src/partcad_ide_client/protocol.py`.
 */
export const MSG_STATE = 'state';
export const KEY_STATE = 'state';

/** A packed rigid placement: [[tx, ty, tz], [ax, ay, az], angleInDegrees]. */
export type ViewerLocation = [[number, number, number], [number, number, number], number];

/** One port a node declares: a coordinate frame, and what it is part of. */
export interface ViewerPort {
    name?: string | null;
    /** Where it is, in the frame of the object that declares it. */
    location: ViewerLocation;
    /** The interface instance it belongs to, or absent for a port that belongs to none. */
    interface?: string | null;
    instance?: string | null;
    /** The sketch the port is drawn with, as '<package>:<name>', where it has one. */
    sketch?: string | null;
}

/** One interface instance a node implements, and the ports it is made of. */
export interface ViewerInterface {
    name?: string | null;
    instance?: string | null;
    ports?: string[];
}

/**
 * One node of the object being shown.
 *
 * Every subject is a tree of these and nothing else: a part or a sketch is one
 * node deep, an assembly is a node per thing it holds, an interface is a node per
 * port. PartCAD builds it - it is the very hierarchy it instantiates an assembly
 * as, with glTF at the nodes instead of BREP - and the normative description is
 * in 'src/partcad_ide_client/protocol.py'.
 *
 * Placements are not baked in: 'gltf' is the node's own geometry in its own
 * coordinate system and 'location' says where the node sits inside its parent, so
 * whoever draws the tree composes the locations down it. A port's location is in
 * the same frame, and moves with the node that holds it.
 */
export interface ViewerNode {
    /** The object: '<package>:<object>', shared by every node that holds it. */
    name?: string | null;
    /**
     * The link: what the node holding this one addresses it by, and so what
     * tells a hundred placements of one bolt apart. The 'name:' of the ASSY link
     * that placed it, or - for a child nothing named - its position in its
     * parent; never a fallback to the object's own name. That is what makes it
     * the name a request coming back can carry, which is how the panel beside
     * the 2D and Draft tabs composes a filter out of the rows it is showing.
     */
    label?: string | null;
    location?: ViewerLocation | null;
    /** Which entry of the root's 'geometry' table is this node's geometry. */
    gltfRef?: string;
    /**
     * This node's own geometry, compressed and base64-encoded, or absent.
     *
     * What 'gltfRef' resolves to. PartCAD sends the reference and the table; a
     * node carries the payload itself only where nothing built a table.
     */
    gltf?: string;
    ports?: ViewerPort[];
    interfaces?: ViewerInterface[];
    /** What is inside this node, or absent for a leaf. */
    assembly?: ViewerNode[];
    /**
     * On the root node: the sketches the ports anywhere in the tree are drawn
     * with, keyed by the reference those ports name in their own 'sketch'. One
     * entry per sketch however many ports point at it.
     */
    sketches?: Record<string, ViewerNode>;
    /**
     * On the root node: every distinct piece of geometry in the tree, compressed
     * and base64-encoded, keyed by a digest of the exact shape it came from. One
     * entry however many nodes name it through 'gltfRef'.
     */
    geometry?: Record<string, string>;
    /**
     * What was learnt about this node's shape as it was built, passed through as
     * PartCAD carries it. The viewer pins its 'annotations' to the elements they
     * describe; see 'src/webview/callouts.ts'.
     */
    metadata?: Record<string, unknown>;
}

export interface ViewerMessage {
    type: string;
    id?: string;
    name?: string | null;
    kind?: string | null;
    /**
     * The package the shown object belongs to.
     *
     * The viewer shows more than geometry - what an assembly is made of, how it
     * goes together, where to buy its parts - and asks the PartCAD daemon for
     * all of it by '<package>:<name>', which a name on its own cannot spell.
     * Absent for a shape that belongs to no package; the tabs that need it are
     * then not offered.
     */
    package?: string | null;
    keepCamera?: boolean;
    /**
     * On a show: the viewer tab to open on ('3d', 'fea', 'supply', ...), or
     * absent to stay on the one that is open. See KEY_TAB in the Python module.
     */
    tab?: string | null;
    /**
     * On a show with a 'tab' that lists scenarios (the Simulation tab, each
     * analysis tab): which of them to select, by the name the object declares
     * it under, or absent for the first. See KEY_SCENARIO in the Python module.
     */
    scenario?: string | null;
    /**
     * On a show: the cross-section the object was cut to, as PartCAD normalized
     * it - '{"x": [lo, hi], ...}', the axes that cut - or null for the whole
     * object. Absent from a PartCAD that cannot cut. See KEY_SECTION in the
     * Python module.
     */
    section?: Record<string, [number, number]> | null;
    /** The object itself, as the root node of its tree. */
    object?: ViewerNode | null;
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
 *
 * What it buffers is the list of chunks as they arrived, and a running count of
 * their bytes, rather than one buffer they are appended to. The reader runs on
 * the extension host's main thread, which every extension in the window shares,
 * and appending a ~64 KiB 'data' event to everything received so far copies all
 * of it: quadratic in the frame, so a 20 MiB show arriving over a real socket
 * held that thread for six seconds, and a 40 MiB one for over ten. Now nothing
 * is copied until a whole frame is present, and then only that frame, once - or
 * not at all when it lies inside one chunk, which is what several small frames
 * arriving together do. The 20 MiB show takes under a tenth of a second.
 *
 * A bad header or payload throws on every push from then on, as it always has:
 * nothing is consumed until it has been decoded, so the stream never resumes
 * mid-frame and reads the rest of a frame as a header.
 */
export class FrameReader {
    /** The bytes received and not yet returned, in arrival order; none of them empty. */
    private chunks: Buffer[] = [];
    /** How many bytes 'chunks' holds altogether. */
    private pending = 0;
    /** The length, header included, of the frame at the front once its header is in; -1 before. */
    private frameLength = -1;

    /** Append received bytes and return every complete message they contain. */
    public push(chunk: Buffer): ViewerMessage[] {
        if (chunk.length > 0) {
            this.chunks.push(chunk);
            this.pending += chunk.length;
        }

        const messages: ViewerMessage[] = [];
        for (;;) {
            if (this.frameLength < 0) {
                if (this.pending < HEADER_LENGTH) {
                    return messages;
                }
                // Validated as soon as it is in, not once the payload is: a
                // peer that is not speaking this protocol is refused at its
                // first ten bytes rather than after up to MAX_FRAME_LENGTH more.
                this.frameLength = HEADER_LENGTH + decodeHeader(this.peek(HEADER_LENGTH));
            }
            if (this.pending < this.frameLength) {
                return messages;
            }
            messages.push(decodePayload(this.peek(this.frameLength).subarray(HEADER_LENGTH)));
            this.consume(this.frameLength);
            this.frameLength = -1;
        }
    }

    /** The first 'length' pending bytes, which must be there: a view where one chunk holds them, else a copy. */
    private peek(length: number): Buffer {
        const first = this.chunks[0];
        if (first.length >= length) {
            return first.subarray(0, length);
        }
        let count = 0;
        let collected = 0;
        while (collected < length) {
            collected += this.chunks[count].length;
            count++;
        }
        // Truncated to 'length', so of the last chunk only what the frame
        // takes is copied.
        return Buffer.concat(this.chunks.slice(0, count), length);
    }

    /** Drop the first 'length' pending bytes, which must be there. */
    private consume(length: number): void {
        this.pending -= length;
        let count = 0;
        while (count < this.chunks.length && length >= this.chunks[count].length) {
            length -= this.chunks[count].length;
            count++;
        }
        // One splice per frame rather than a shift per chunk: a frame spanning
        // hundreds of chunks would otherwise move the array as many times.
        this.chunks.splice(0, count);
        if (length > 0) {
            this.chunks[0] = this.chunks[0].subarray(length);
        }
    }
}
