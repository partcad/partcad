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
    ProtocolError,
    VERSION,
    decodeGltf,
    decodeHeader,
    decodePayload,
    encodeFrame,
} from '../../viewer/protocol';

function header(magic: string, version: number, kind: number, length: number): Buffer {
    const buffer = Buffer.alloc(HEADER_LENGTH);
    buffer.write(magic, 0, 4, 'ascii');
    buffer.writeUInt8(version, 4);
    buffer.writeUInt8(kind, 5);
    buffer.writeUInt32BE(length, 6);
    return buffer;
}

suite('PartCAD Viewer protocol', () => {
    test('a frame round-trips', () => {
        const message = { type: MSG_SHOW, id: 'abc', objects: [] };
        const frame = encodeFrame(message);

        const length = decodeHeader(frame.subarray(0, HEADER_LENGTH));
        assert.strictEqual(length, frame.length - HEADER_LENGTH);
        assert.deepStrictEqual(decodePayload(frame.subarray(HEADER_LENGTH)), message);
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
