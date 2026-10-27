//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//

import * as assert from 'assert';
import * as zlib from 'zlib';

import {
    FrameReader,
    HEADER_LENGTH,
    KIND_BINARY,
    KIND_JSON,
    MAGIC,
    MAX_FRAME_LENGTH,
    MSG_SHOW,
    PARTCAD_IDE_PORT,
    ProtocolError,
    VERSION,
    ViewerMessage,
    decodeBinaryPayload,
    decodeGltf,
    decodeHeader,
    decodePayload,
    encodeFrame,
    glbOf,
    isZlib,
    listenPort,
    readHeader,
} from '../../viewer/protocol';

function header(magic: string, version: number, kind: number, length: number): Buffer {
    const buffer = Buffer.alloc(HEADER_LENGTH);
    buffer.write(magic, 0, 4, 'ascii');
    buffer.writeUInt8(version, 4);
    buffer.writeUInt8(kind, 5);
    buffer.writeUInt32BE(length, 6);
    return buffer;
}

suite('Digital Thread protocol', () => {
    test('a frame round-trips', () => {
        // 'package' is what the panel's tabs beside the 3D one are about: they
        // ask the daemon about '<package>:<name>', which a name cannot spell.
        const message: ViewerMessage = {
            type: MSG_SHOW,
            id: 'abc',
            name: 'part',
            package: '//pkg',
            object: { name: '//pkg:part', label: 'part' },
        };
        const frame = encodeFrame(message);

        const length = decodeHeader(frame.subarray(0, HEADER_LENGTH));
        assert.strictEqual(length, frame.length - HEADER_LENGTH);
        const decoded = decodePayload(frame.subarray(HEADER_LENGTH));
        assert.deepStrictEqual(decoded, message);
        assert.strictEqual(decoded.package, '//pkg');
    });

    test('the object tree and everything on its nodes survive a frame', () => {
        // One payload for every kind of subject: the hierarchy, the placements,
        // the geometry of each node and what each declares about connections.
        // PartCAD builds it ('partcad/shape_envelope.py'); this side only carries
        // it, so what a frame must not do is lose any of it.
        const message: ViewerMessage = {
            type: MSG_SHOW,
            name: 'mount',
            kind: 'assembly',
            object: {
                name: '//pkg:mount',
                label: 'mount',
                ports: [{ name: 'hold', location: [[0, 0, 5], [0, 0, 1], 0] }],
                assembly: [
                    {
                        name: '//pkg:plate',
                        label: 'bottom',
                        location: [[0, 0, 20], [0, 0, 1], 0],
                        gltf: 'Z2xURg==',
                        ports: [
                            {
                                name: 'TL-thru-m3',
                                location: [[-10, 10, 0], [0, 0, 1], 0],
                                interface: '//pkg:m3-thru',
                                instance: 'TL',
                                sketch: '//pkg:m3',
                            },
                        ],
                        interfaces: [{ name: '//pkg:m3-thru', instance: 'TL', ports: ['TL-thru-m3'] }],
                    },
                ],
            },
        };

        const frame = encodeFrame(message);
        const decoded = decodePayload(frame.subarray(HEADER_LENGTH));

        assert.deepStrictEqual(decoded, message);
        // A node's placement is its own and is not baked into its geometry: the
        // tree is composed as it is drawn, so losing one would put a part at the
        // origin rather than fail.
        assert.deepStrictEqual(decoded.object?.assembly?.[0].location, [[0, 0, 20], [0, 0, 1], 0]);
    });

    test('the header is self-describing', () => {
        const frame = encodeFrame({ type: MSG_SHOW });
        assert.strictEqual(frame.toString('ascii', 0, 4), MAGIC);
        assert.strictEqual(frame.readUInt8(4), VERSION);
    });

    test('a frame split across chunks is reassembled', () => {
        // What TCP actually does to a payload big enough to matter: this is the
        // case a naive one-message-per-'data'-event reader gets wrong.
        const message = { type: MSG_SHOW, id: 'split', objects: [] };
        const frame = encodeFrame(message);
        const reader = new FrameReader();

        for (let i = 0; i < frame.length - 1; i++) {
            assert.deepStrictEqual(reader.push(frame.subarray(i, i + 1)), [], `byte ${i} completed a frame early`);
        }
        assert.deepStrictEqual(reader.push(frame.subarray(frame.length - 1)), [message]);
    });

    test('several frames arriving in one chunk are all returned', () => {
        const first = { type: MSG_SHOW, id: 'one', objects: [] };
        const second = { type: MSG_SHOW, id: 'two', objects: [] };
        const reader = new FrameReader();

        const messages = reader.push(Buffer.concat([encodeFrame(first), encodeFrame(second)]));
        assert.deepStrictEqual(messages, [first, second]);
    });

    test('a trailing partial frame is held until the rest arrives', () => {
        const first = { type: MSG_SHOW, id: 'one', objects: [] };
        const second = { type: MSG_SHOW, id: 'two', objects: [] };
        const secondFrame = encodeFrame(second);
        const reader = new FrameReader();

        assert.deepStrictEqual(reader.push(Buffer.concat([encodeFrame(first), secondFrame.subarray(0, 4)])), [first]);
        assert.deepStrictEqual(reader.push(secondFrame.subarray(4)), [second]);
    });

    test('a header split across chunks is read once its last byte arrives', () => {
        // The reader keeps the chunks as they came rather than one buffer, so a
        // header straddling them is the case it has to put together itself.
        const message = { type: MSG_SHOW, id: 'header', objects: [] };
        const next = { type: MSG_SHOW, id: 'next', objects: [] };
        const frame = encodeFrame(message);
        const nextFrame = encodeFrame(next);
        const reader = new FrameReader();

        assert.deepStrictEqual(reader.push(frame.subarray(0, 3)), []);
        assert.deepStrictEqual(reader.push(frame.subarray(3, 7)), []);
        assert.deepStrictEqual(reader.push(frame.subarray(7, HEADER_LENGTH + 1)), []);
        // The rest of this frame and the first half of the next one's header.
        assert.deepStrictEqual(
            reader.push(Buffer.concat([frame.subarray(HEADER_LENGTH + 1), nextFrame.subarray(0, 5)])),
            [message],
        );
        assert.deepStrictEqual(reader.push(nextFrame.subarray(5)), [next]);
    });

    test('a stream of frames cut into tiny chunks of every size comes back whole and in order', () => {
        const messages = Array.from({ length: 7 }, (_, i) => ({
            type: MSG_SHOW,
            id: `m${i}`,
            objects: [],
            pad: 'x'.repeat(i * 13),
        }));
        const stream = Buffer.concat(messages.map((message) => encodeFrame(message)));

        for (let size = 1; size <= 23; size++) {
            const reader = new FrameReader();
            const received: ViewerMessage[] = [];
            for (let i = 0; i < stream.length; i += size) {
                received.push(...reader.push(stream.subarray(i, i + size)));
            }
            assert.deepStrictEqual(received, messages, `chunks of ${size} bytes`);
        }
    });

    test('a frame spanning hundreds of chunks is reassembled, and a frame after it in its last chunk too', () => {
        // The shape of a real show of a large assembly: megabytes of base64
        // geometry, delivered by the socket a few KiB at a time.
        const big = { type: MSG_SHOW, id: 'big', objects: [], blob: 'g'.repeat(2 * 1024 * 1024) };
        const small = { type: MSG_SHOW, id: 'small', objects: [] };
        const bigFrame = encodeFrame(big);
        const stream = Buffer.concat([bigFrame, encodeFrame(small)]);
        const chunk = 4096;
        const reader = new FrameReader();

        const received: ViewerMessage[] = [];
        let pushes = 0;
        for (let i = 0; i < stream.length; i += chunk) {
            const messages = reader.push(stream.subarray(i, i + chunk));
            pushes++;
            if (i + chunk < bigFrame.length) {
                assert.deepStrictEqual(messages, [], `chunk ${pushes} completed a frame early`);
            }
            received.push(...messages);
        }
        assert.ok(pushes > 500, `only ${pushes} chunks`);
        assert.deepStrictEqual(received, [big, small]);
    });

    test('a frame inside one chunk is decoded where it lies', () => {
        // Nothing to copy when the bytes are already contiguous: several small
        // frames in one 'data' event are each decoded from a view of it.
        const reader = new FrameReader();
        const frames = [0, 1, 2].map((i) => encodeFrame({ type: MSG_SHOW, id: `${i}` }));
        const chunk = Buffer.concat([...frames, frames[0].subarray(0, 2)]);

        assert.deepStrictEqual(
            reader.push(chunk).map((message) => message.id),
            ['0', '1', '2'],
        );
        assert.deepStrictEqual(
            reader.push(frames[0].subarray(2)).map((message) => message.id),
            ['0'],
        );
    });

    test('the reader refuses a bad header as soon as it is in, and goes on refusing it', () => {
        // The caller drops the connection on the first throw, but a reader that
        // consumed the bad bytes would read whatever followed as a header.
        const bad = header('NOPE', VERSION, 1, 1000);
        const reader = new FrameReader();

        assert.deepStrictEqual(reader.push(bad.subarray(0, 6)), []);
        // No payload yet: the header alone is enough to know.
        assert.throws(() => reader.push(bad.subarray(6)), ProtocolError);
        assert.throws(() => reader.push(encodeFrame({ type: MSG_SHOW })), ProtocolError);
    });

    test('the reader refuses a payload that is not a message, and goes on refusing it', () => {
        const payload = Buffer.from('not json', 'utf-8');
        const frame = Buffer.concat([header(MAGIC, VERSION, 1, payload.length), payload]);
        const reader = new FrameReader();

        assert.deepStrictEqual(reader.push(frame.subarray(0, 12)), []);
        assert.throws(() => reader.push(frame.subarray(12)), ProtocolError);
        assert.throws(() => reader.push(encodeFrame({ type: MSG_SHOW })), ProtocolError);
    });

    test('a bad header is rejected rather than reinterpreted', () => {
        assert.throws(() => decodeHeader(header('NOPE', VERSION, 1, 0)), ProtocolError);
        assert.throws(() => decodeHeader(header(MAGIC, VERSION + 1, 1, 0)), ProtocolError);
        assert.throws(() => decodeHeader(header(MAGIC, VERSION, 99, 0)), ProtocolError);
        assert.throws(() => decodeHeader(header(MAGIC, VERSION, 1, MAX_FRAME_LENGTH + 1)), ProtocolError);
        assert.throws(() => decodeHeader(Buffer.from(MAGIC, 'ascii')), ProtocolError);
    });

    test('a payload that is not a message object is rejected', () => {
        assert.throws(() => decodePayload(Buffer.from('[1,2,3]', 'utf-8')), ProtocolError);
        assert.throws(() => decodePayload(Buffer.from('not json', 'utf-8')), ProtocolError);
        assert.throws(() => decodePayload(Buffer.from('{"id":"no-type"}', 'utf-8')), ProtocolError);
    });

    test('the listen port follows PARTCAD_IDE_PORT, as the Python client does', () => {
        // An environment, built through a helper rather than as an object
        // literal per case: the variable's name is not camelCase (it cannot be),
        // and spelling it inline trips the naming-convention rule five times.
        const env = (value?: string): NodeJS.ProcessEnv => ({ ['PARTCAD_IDE_PORT']: value });

        // Both ends have to honour it, or "set PARTCAD_IDE_PORT" moves only one
        // of them and they stop finding each other.
        assert.strictEqual(listenPort({}), PARTCAD_IDE_PORT);
        assert.strictEqual(listenPort(env('9999')), 9999);
        // Unparseable or out of range falls back rather than failing to bind,
        // matching partcad_ide_client.client._port().
        assert.strictEqual(listenPort(env('not-a-port')), PARTCAD_IDE_PORT);
        assert.strictEqual(listenPort(env('70000')), PARTCAD_IDE_PORT);
        assert.strictEqual(listenPort(env('')), PARTCAD_IDE_PORT);
        assert.strictEqual(listenPort(env(undefined)), PARTCAD_IDE_PORT);
        // 0 would bind an arbitrary free port, which the client could not find.
        assert.strictEqual(listenPort(env('0')), PARTCAD_IDE_PORT);
        // Spellings Number() would take and Python's _port() would not: the two
        // parsers have to agree on the grammar, not just on the range.
        assert.strictEqual(listenPort(env('1e4')), PARTCAD_IDE_PORT);
        assert.strictEqual(listenPort(env('0x270f')), PARTCAD_IDE_PORT);
        assert.strictEqual(listenPort(env(' 9999 ')), PARTCAD_IDE_PORT);
        assert.strictEqual(listenPort(env('+9999')), PARTCAD_IDE_PORT);
        assert.strictEqual(listenPort(env('99.5')), PARTCAD_IDE_PORT);
    });

    test('glTF payloads written by a PartCAD from before binary frames are readable here', () => {
        // What every 'encode_gltf' wrote then, and a JSON frame still carries:
        // base64(zlib.compress(glb, level)), spelled in Node, at every level.
        const glb = Buffer.concat([Buffer.from('glTF\x02\x00\x00\x00', 'binary'), Buffer.alloc(4096)]);
        for (const level of [0, 1, 6, 9]) {
            const payload = zlib.deflateSync(glb, { level }).toString('base64');
            assert.deepStrictEqual(decodeGltf(payload), glb, `level ${level}`);
            assert.deepStrictEqual(Buffer.from(glbOf(payload)), glb, `level ${level}`);
        }
    });

    test('a blob is the glTF itself, and is handed on as it is', () => {
        const glb = new Uint8Array(Buffer.from('glTF\x02\x00\x00\x00 the rest', 'binary')).buffer;
        assert.strictEqual(glbOf(glb), glb);
        assert.ok(!isZlib(new Uint8Array(glb)));
        // A zlib stream in a blob - a cached one from before - is inflated all the same.
        const stream = zlib.deflateSync(Buffer.from(glb));
        assert.deepStrictEqual(Buffer.from(glbOf(new Uint8Array(stream).slice().buffer)), Buffer.from(glb));
    });

    test('a binary frame laid out by hand is read, every blob where the message names it', () => {
        // The layout as 'src/partcad_ide_client/protocol.py' states it, written
        // out here rather than through a helper both sides could share a bug in.
        const bolt = Buffer.from('glTF bolt');
        const sketch = Buffer.from('glTF sketch');
        const message = {
            type: MSG_SHOW,
            id: 'one',
            object: {
                name: '//pkg:assy',
                assembly: [{ name: '//pkg:bolt', gltfRef: 'bolt' }],
                geometry: { bolt: 0, nut: null },
                sketches: { circle: { name: '//pkg:circle', gltf: 1 } },
                // Integers in a package's own words are its own.
                metadata: { gltf: 1, count: 0 },
            },
        };
        const frame = binaryFrame(message, [bolt, sketch]);

        const decoded = decodeBinaryPayload(frame.subarray(HEADER_LENGTH));
        const object = decoded.object!;
        assert.deepStrictEqual(Buffer.from(object.geometry!.bolt as ArrayBuffer), bolt);
        assert.strictEqual(object.geometry!.nut, null);
        assert.deepStrictEqual(Buffer.from(object.sketches!.circle.gltf as ArrayBuffer), sketch);
        assert.deepStrictEqual(object.metadata, { gltf: 1, count: 0 });
        assert.deepStrictEqual(object.assembly, message.object.assembly);
        // Each in an ArrayBuffer of its own, exactly its size: posted to the
        // webview, a view would take the whole frame with it.
        assert.strictEqual((object.geometry!.bolt as ArrayBuffer).byteLength, bolt.length);
        assert.deepStrictEqual(readHeader(frame.subarray(0, HEADER_LENGTH)), {
            kind: KIND_BINARY,
            length: frame.length - HEADER_LENGTH,
        });
    });

    test('a binary frame is read whatever chunks it arrives in, its blobs copied out once', () => {
        const blobs = [0, 1, 2].map((index) => Buffer.alloc(10000 + index, index + 1));
        const message = { type: MSG_SHOW, id: 'chunked', object: { geometry: { a: 0, b: 1, c: 2 } } };
        const stream = Buffer.concat([binaryFrame(message, blobs), encodeFrame({ type: MSG_SHOW, id: 'after' })]);
        for (const size of [1, 7, 4096, stream.length]) {
            const reader = new FrameReader();
            const received: ViewerMessage[] = [];
            for (let i = 0; i < stream.length; i += size) {
                received.push(...reader.push(stream.subarray(i, i + size)));
            }
            assert.deepStrictEqual(
                received.map((m) => m.id),
                ['chunked', 'after'],
                `chunks of ${size}`,
            );
            const table = received[0].object!.geometry!;
            for (const [index, digest] of ['a', 'b', 'c'].entries()) {
                const glb = table[digest] as ArrayBuffer;
                assert.ok(glb instanceof ArrayBuffer);
                assert.strictEqual(glb.byteLength, blobs[index].length);
                assert.deepStrictEqual(Buffer.from(glb), blobs[index], `blob ${digest} in chunks of ${size}`);
            }
        }
    });

    test('a binary frame this side builds is one it reads', () => {
        const glb = Buffer.from('glTF built here');
        const frame = encodeFrame({ type: MSG_SHOW, id: 'x', object: { geometry: { d: glb } } }, true);
        const [message] = new FrameReader().push(frame);
        assert.deepStrictEqual(Buffer.from(message.object!.geometry!.d as ArrayBuffer), glb);
        assert.strictEqual(readHeader(frame.subarray(0, HEADER_LENGTH)).kind, KIND_BINARY);
        assert.strictEqual(readHeader(encodeFrame({ type: MSG_SHOW }).subarray(0, HEADER_LENGTH)).kind, KIND_JSON);
    });

    test('a binary payload that does not add up is refused', () => {
        const good = binaryFrame({ type: MSG_SHOW, object: { geometry: { a: 0 } } }, [Buffer.from('glTF')]).subarray(
            HEADER_LENGTH,
        );
        const cases: [Buffer, RegExp][] = [
            [Buffer.from([0, 0]), /inside a length/],
            [Buffer.concat([uint32(1000), Buffer.from('{}')]), /inside its message/],
            [good.subarray(0, good.length - 2), /inside blob 0/],
            [Buffer.concat([good, Buffer.from('!')]), /after its last blob/],
            [
                binaryFrame({ type: MSG_SHOW, object: { geometry: { a: 1 } } }, [Buffer.from('glTF')]).subarray(
                    HEADER_LENGTH,
                ),
                /names blob 1 of 1/,
            ],
        ];
        for (const [payload, error] of cases) {
            assert.throws(() => decodeBinaryPayload(payload), error);
        }
        // And a reader goes on refusing, as it does a bad JSON frame.
        const reader = new FrameReader();
        const bad = Buffer.concat([header(MAGIC, VERSION, KIND_BINARY, 2), Buffer.from([0, 0])]);
        assert.throws(() => reader.push(bad), ProtocolError);
        assert.throws(() => reader.push(encodeFrame({ type: MSG_SHOW })), ProtocolError);
    });
});

function uint32(value: number): Buffer {
    const buffer = Buffer.alloc(4);
    buffer.writeUInt32BE(value, 0);
    return buffer;
}

/** A KIND_BINARY frame, by hand: the length of the JSON and the JSON, the count, then each blob's length and bytes. */
function binaryFrame(message: unknown, blobs: Buffer[]): Buffer {
    const json = Buffer.from(JSON.stringify(message), 'utf-8');
    const parts = [uint32(json.length), json, uint32(blobs.length)];
    for (const blob of blobs) {
        parts.push(uint32(blob.length), blob);
    }
    const payload = Buffer.concat(parts);
    return Buffer.concat([header(MAGIC, VERSION, KIND_BINARY, payload.length), payload]);
}
