//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The JS half of the PartCAD IDE viewer protocol. The normative description of
// the wire format lives next to the other half, in
// 'src/partcad_ide_client/protocol.py'; keep the two in step.
//
// A frame is a 10-byte header followed by its payload:
//
//     offset  size  field
//     0       4     magic, always "PCAD"
//     4       1     protocol version
//     5       1     payload kind: KIND_JSON or KIND_BINARY
//     6       4     payload length, big-endian uint32
//     10      n     payload
//
// A JSON payload is the message. A binary one is the message and the binary
// glTF it carries side by side - a length and the JSON, a count, then a length
// and the bytes of each blob - with every glTF payload in the message the index
// of its blob. Geometry in a JSON frame is base64 of a zlib stream, which is
// what every PartCAD before binary frames sent and what it is still sent as to
// an IDE that does not say it reads them.
//
// Which kinds this side reads, and that it can be offered geometry before it is
// sent it, is said in every acknowledgement (KEY_CAPABILITIES): a PartCAD sends
// a binary frame only to an IDE that said so, because one from before binary
// frames drops the connection at the first header it does not know. The
// Python module has the whole of it, offers included.

import * as zlib from 'zlib';

export const MAGIC = 'PCAD';
export const VERSION = 1;
export const KIND_JSON = 1;
/** The message and its glTF side by side; see the layout above. */
export const KIND_BINARY = 2;
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
 * Before a show: the digests of the geometry it will name. Answered with the ones
 * this side does not hold, under KEY_MISSING, and only those are sent. See
 * MSG_OFFER in the Python module.
 */
export const MSG_OFFER = 'offer';
/** Geometry this side said it lacks, ahead of the show that names it, as blobs. */
export const MSG_GEOMETRY = 'geometry';
export const KEY_DIGESTS = 'digests';
export const KEY_MISSING = 'missing';
/** On every acknowledgement: what this side accepts. */
export const KEY_CAPABILITIES = 'capabilities';
export const CAP_BINARY = 'binary';
export const CAP_OFFER = 'offer';
/** What this build accepts, as every acknowledgement says it. */
export const CAPABILITIES: readonly string[] = [CAP_BINARY, CAP_OFFER];
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
 * A glTF payload as it arrives: base64 of a zlib stream in a JSON frame, the
 * binary glTF itself - its blob - in a binary one, or null in a show's geometry
 * table for an entry this side was offered and said it holds.
 */
export type GltfPayload = string | ArrayBuffer | null;

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
     * This node's own geometry, or absent.
     *
     * What 'gltfRef' resolves to. PartCAD sends the reference and the table; a
     * node carries the payload itself only where nothing built a table.
     */
    gltf?: GltfPayload;
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
     * On the root node: every distinct piece of geometry in the tree, keyed by a
     * digest of the exact shape it came from. One entry however many nodes name
     * it through 'gltfRef'.
     */
    geometry?: Record<string, GltfPayload>;
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
    /** On an offer: the digests of the geometry the show will name. */
    digests?: string[];
    /** On a 'geometry' message: what was said to be lacking, by digest. */
    geometry?: Record<string, GltfPayload>;
}

export class ProtocolError extends Error {}

/** The two lengths every binary payload has before its blobs, and the one before each blob. */
const LENGTH = 4;

/**
 * 'message' with every glTF payload in it replaced by 'convert(payload)'.
 *
 * Looked for where a payload can be and nowhere else: a node's 'gltf' and the
 * entries of a 'geometry' table, on the nodes of the object ('object', and every
 * node in an 'assembly' or 'sketches' under it) and on the message itself, which
 * is where a 'geometry' message carries its table. Null stays null. Copies what it
 * changes and shares the rest. The mirror of 'map_payloads' in the Python module.
 */
export function mapPayloads<T>(message: T, convert: (payload: unknown) => unknown): T {
    const node = (value: unknown): unknown => {
        if (typeof value !== 'object' || value === null || Array.isArray(value)) {
            return value;
        }
        const mapped: Record<string, unknown> = { ...(value as Record<string, unknown>) };
        if (mapped.gltf !== undefined && mapped.gltf !== null) {
            mapped.gltf = convert(mapped.gltf);
        }
        const table = mapped.geometry;
        if (typeof table === 'object' && table !== null && !Array.isArray(table)) {
            mapped.geometry = Object.fromEntries(
                Object.entries(table).map(([digest, payload]) => [digest, payload === null ? null : convert(payload)]),
            );
        }
        if (Array.isArray(mapped.assembly)) {
            mapped.assembly = mapped.assembly.map(node);
        }
        const sketches = mapped.sketches;
        if (typeof sketches === 'object' && sketches !== null && !Array.isArray(sketches)) {
            mapped.sketches = Object.fromEntries(
                Object.entries(sketches).map(([reference, sketch]) => [reference, node(sketch)]),
            );
        }
        return mapped;
    };
    const mapped = node(message) as Record<string, unknown>;
    const object = (message as Record<string, unknown>)?.object;
    if (typeof object === 'object' && object !== null) {
        mapped.object = node(object);
    }
    return mapped as T;
}

/**
 * Serialize a message into a single frame.
 *
 * 'binary' writes a KIND_BINARY frame, with every ArrayBuffer or byte array at a
 * payload position a blob; this side only ever sends acknowledgements, which are
 * JSON, and the binary kind is here to build what PartCAD sends, in a test.
 */
export function encodeFrame(message: unknown, binary = false): Buffer {
    let kind = KIND_JSON;
    let payload: Buffer;
    if (binary) {
        const blobs: Buffer[] = [];
        const json = JSON.stringify(
            mapPayloads(message, (value) => {
                if (value instanceof ArrayBuffer || ArrayBuffer.isView(value)) {
                    const view = ArrayBuffer.isView(value)
                        ? Buffer.from(value.buffer, value.byteOffset, value.byteLength)
                        : Buffer.from(value);
                    blobs.push(view);
                    return blobs.length - 1;
                }
                return value;
            }),
        );
        const text = Buffer.from(json, 'utf-8');
        const parts: Buffer[] = [uint32(text.length), text, uint32(blobs.length)];
        for (const blob of blobs) {
            parts.push(uint32(blob.length), blob);
        }
        payload = Buffer.concat(parts);
        kind = KIND_BINARY;
    } else {
        payload = Buffer.from(JSON.stringify(message), 'utf-8');
    }
    if (payload.length > MAX_FRAME_LENGTH) {
        throw new ProtocolError(`message of ${payload.length} bytes exceeds the ${MAX_FRAME_LENGTH} byte frame limit`);
    }
    const header = Buffer.alloc(HEADER_LENGTH);
    header.write(MAGIC, 0, 4, 'ascii');
    header.writeUInt8(VERSION, 4);
    header.writeUInt8(kind, 5);
    header.writeUInt32BE(payload.length, 6);
    return Buffer.concat([header, payload]);
}

function uint32(value: number): Buffer {
    const buffer = Buffer.alloc(LENGTH);
    buffer.writeUInt32BE(value, 0);
    return buffer;
}

/** Validate a frame header and return the kind and the length of the payload that follows it. */
export function readHeader(header: Buffer): { kind: number; length: number } {
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
    if (kind !== KIND_JSON && kind !== KIND_BINARY) {
        throw new ProtocolError(`unsupported payload kind ${kind}`);
    }
    const length = header.readUInt32BE(6);
    if (length > MAX_FRAME_LENGTH) {
        throw new ProtocolError(`frame of ${length} bytes exceeds the ${MAX_FRAME_LENGTH} byte limit`);
    }
    return { kind, length };
}

/** Validate a frame header and return the payload length that follows it. */
export function decodeHeader(header: Buffer): number {
    return readHeader(header).length;
}

/** Parse a JSON frame payload into a message. */
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

/** Where the bytes of a payload are, which a binary payload is read out of. */
interface Bytes {
    readonly length: number;
    /** The bytes at 'offset', as a view where that is free and a copy where it is not. */
    view(offset: number, length: number): Buffer;
    /** The bytes at 'offset', in an ArrayBuffer of their own and exactly their size. */
    copy(offset: number, length: number): ArrayBuffer;
}

/** A Buffer, as 'Bytes'. */
function bytesOf(buffer: Buffer): Bytes {
    return {
        length: buffer.length,
        view: (offset, length) => buffer.subarray(offset, offset + length),
        copy: (offset, length) => exactArrayBuffer(buffer.subarray(offset, offset + length), true),
    };
}

/**
 * Parse a binary frame payload into a message, every blob where the message names it.
 *
 * A blob arrives as an ArrayBuffer of its own, exactly its size, rather than as a
 * view into the frame: it is handed to the webview as it is, and VS Code posts the
 * whole of the ArrayBuffer a view is over - which for a view into a frame is every
 * other blob of it too, again and again for as long as the view is kept.
 */
function decodeBinary(bytes: Bytes): ViewerMessage {
    const lengthAt = (offset: number): number => {
        if (offset + LENGTH > bytes.length) {
            throw new ProtocolError(`binary frame payload ends inside a length, at byte ${offset} of ${bytes.length}`);
        }
        return bytes.view(offset, LENGTH).readUInt32BE(0);
    };
    let offset = LENGTH + lengthAt(0);
    if (offset > bytes.length) {
        throw new ProtocolError('binary frame payload ends inside its message');
    }
    const message = decodePayload(bytes.view(LENGTH, offset - LENGTH));
    const count = lengthAt(offset);
    offset += LENGTH;
    const blobs: ArrayBuffer[] = [];
    for (let index = 0; index < count; index++) {
        const size = lengthAt(offset);
        offset += LENGTH;
        if (offset + size > bytes.length) {
            throw new ProtocolError(`binary frame payload ends inside blob ${index}`);
        }
        blobs.push(bytes.copy(offset, size));
        offset += size;
    }
    if (offset !== bytes.length) {
        throw new ProtocolError(`binary frame payload has ${bytes.length - offset} bytes after its last blob`);
    }
    return mapPayloads(message, (payload) => {
        if (typeof payload !== 'number') {
            return payload;
        }
        if (!Number.isInteger(payload) || payload < 0 || payload >= blobs.length) {
            throw new ProtocolError(`a payload names blob ${payload} of ${blobs.length}`);
        }
        return blobs[payload];
    });
}

/** Parse a binary frame payload into a message; see 'decodeBinary'. */
export function decodeBinaryPayload(payload: Buffer): ViewerMessage {
    return decodeBinary(bytesOf(payload));
}

/**
 * The bytes of 'view' as an ArrayBuffer that holds exactly them: its own when it
 * already does, else a copy - always a copy when 'copy' says so.
 *
 * What is posted to the webview and kept for the next show is this, never a view:
 * a view keeps alive, and gets posted along with it, whatever else its ArrayBuffer
 * holds - a frame's other blobs, or Node's pool of small allocations.
 */
export function exactArrayBuffer(view: Uint8Array, copy = false): ArrayBuffer {
    if (!copy && view.byteOffset === 0 && view.byteLength === view.buffer.byteLength) {
        return view.buffer as ArrayBuffer;
    }
    const exact = new Uint8Array(view.byteLength);
    exact.set(view);
    return exact.buffer;
}

/** Whether 'data' begins with a zlib header (RFC 1950); a GLB's "glTF" never does. See 'is_zlib' in Python. */
export function isZlib(data: Uint8Array): boolean {
    return data.length >= 2 && (data[0] & 0x0f) === 8 && data[0] >> 4 <= 7 && ((data[0] << 8) | data[1]) % 31 === 0;
}

/**
 * The binary glTF a payload carries, whichever spelling it arrived in.
 *
 * A blob is the glTF itself; text is base64 of a zlib stream, at whatever level a
 * PartCAD wrote it at. Either is sniffed rather than trusted, since a PartCAD
 * from before binary frames may have cached a compressed one.
 */
export function decodeGltf(payload: string | ArrayBuffer | Uint8Array): Buffer {
    const data =
        typeof payload === 'string'
            ? Buffer.from(payload, 'base64')
            : payload instanceof ArrayBuffer
              ? Buffer.from(payload)
              : Buffer.from(payload.buffer, payload.byteOffset, payload.byteLength);
    return isZlib(data) ? zlib.inflateSync(data) : data;
}

/** 'decodeGltf', as an ArrayBuffer of exactly the glTF (see 'exactArrayBuffer'). */
export function glbOf(payload: string | ArrayBuffer | Uint8Array): ArrayBuffer {
    if (payload instanceof ArrayBuffer && !isZlib(new Uint8Array(payload, 0, Math.min(2, payload.byteLength)))) {
        return payload;
    }
    return exactArrayBuffer(decodeGltf(payload));
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
 * A binary frame is not put together at all: each of its blobs is copied out of
 * the chunks into an ArrayBuffer of its own (see 'decodeBinary'), which is the
 * one copy a blob has to have, rather than the frame being joined first and the
 * blobs copied out of that.
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
    /** The kind of that frame. */
    private kind = KIND_JSON;

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
                const { kind, length } = readHeader(this.peek(HEADER_LENGTH));
                this.kind = kind;
                this.frameLength = HEADER_LENGTH + length;
            }
            if (this.pending < this.frameLength) {
                return messages;
            }
            if (this.kind === KIND_BINARY) {
                const length = this.frameLength - HEADER_LENGTH;
                messages.push(
                    decodeBinary({
                        length,
                        view: (offset, size) => this.view(HEADER_LENGTH + offset, size),
                        copy: (offset, size) => this.copy(HEADER_LENGTH + offset, size),
                    }),
                );
            } else {
                messages.push(decodePayload(this.peek(this.frameLength).subarray(HEADER_LENGTH)));
            }
            this.consume(this.frameLength);
            this.frameLength = -1;
        }
    }

    /** The first 'length' pending bytes, which must be there: a view where one chunk holds them, else a copy. */
    private peek(length: number): Buffer {
        return this.view(0, length);
    }

    /**
     * The 'length' pending bytes at 'offset', which must be there: a view where one
     * chunk holds them, else a copy.
     */
    private view(offset: number, length: number): Buffer {
        const [first, skip] = this.locate(offset);
        const chunk = this.chunks[first];
        if (chunk.length - skip >= length) {
            return chunk.subarray(skip, skip + length);
        }
        const out = Buffer.allocUnsafe(length);
        this.fill(out, first, skip);
        return out;
    }

    /** The same bytes, always copied, into an ArrayBuffer of exactly their size. */
    private copy(offset: number, length: number): ArrayBuffer {
        const out = new Uint8Array(length);
        if (length > 0) {
            const [first, skip] = this.locate(offset);
            this.fill(out, first, skip);
        }
        return out.buffer;
    }

    /** Which chunk the pending byte at 'offset' is in, and how far into it. */
    private locate(offset: number): [number, number] {
        let index = 0;
        while (offset >= this.chunks[index].length) {
            offset -= this.chunks[index].length;
            index++;
        }
        return [index, offset];
    }

    /** Fill 'out' with the pending bytes from 'skip' into chunk 'index' on. */
    private fill(out: Uint8Array, index: number, skip: number): void {
        let written = 0;
        while (written < out.length) {
            const chunk = this.chunks[index++];
            const take = Math.min(chunk.length - skip, out.length - written);
            out.set(chunk.subarray(skip, skip + take), written);
            written += take;
            skip = 0;
        }
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
