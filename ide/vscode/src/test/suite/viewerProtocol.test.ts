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
    MAGIC,
    MAX_FRAME_LENGTH,
    MSG_SHOW,
    PARTCAD_IDE_PORT,
    ProtocolError,
    VERSION,
    ViewerMessage,
    decodeGltf,
    decodeHeader,
    decodePayload,
    encodeFrame,
    listenPort,
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

    test('glTF payloads written by the Python client are readable here', () => {
        // 'partcad_ide_client.protocol.encode_gltf' is base64(zlib.compress(glb,
        // 6)); this is that, spelled in Node, and decodeGltf has to undo it.
        const glb = Buffer.concat([Buffer.from('glTF\x02\x00\x00\x00', 'binary'), Buffer.alloc(4096)]);
        const payload = zlib.deflateSync(glb, { level: 6 }).toString('base64');

        assert.deepStrictEqual(decodeGltf(payload), glb);
        // Compression really happened: base64 alone would grow the input by 4/3.
        assert.ok(payload.length < glb.length);
    });
});
