//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The framing the extension reads PartCAD's answers with: LSP's, and the raw
// bytes of the files a message carries after its body (see 'common/framing.ts').
//
// Driven over a PassThrough stream, the way the backend drives it over a socket
// or a pipe, and through vscode-jsonrpc's own connection for the part that has
// to fit into it. The frame with attachments below is pinned byte for byte by
// 'tests/partcad_utils/test_framing.py' too, so the two ends cannot drift apart.
//

import * as assert from 'assert';
import { PassThrough } from 'stream';
import { createMessageConnection, Message } from 'vscode-jsonrpc/node';

import { AttachmentMessageReader, AttachmentMessageWriter, bytesOf } from '../../common/framing';

/** What 'partcad_utils.framing.encode_message' writes for this message, with attachments. */
const BODY =
    '{"id": 1, "result": {"content": {"$attachment": 0}, "again": {"$attachment": 0}, "other": {"$attachment": 1}}}';
const FRAME = Buffer.concat([
    Buffer.from(`Content-Length: ${Buffer.byteLength(BODY)}\r\nAttachment-Lengths: 3,2\r\n\r\n${BODY}`, 'utf8'),
    Buffer.from([0, 255, 10]),
    Buffer.from('ok', 'ascii'),
]);

function plain(message: object): Buffer {
    const body = Buffer.from(JSON.stringify(message), 'utf8');
    return Buffer.concat([Buffer.from(`Content-Length: ${body.byteLength}\r\n\r\n`, 'ascii'), body]);
}

/** A reader over a stream of its own, and every message it hands on. */
function reading(): { stream: PassThrough; messages: Message[]; errors: Error[]; reader: AttachmentMessageReader } {
    const stream = new PassThrough();
    const reader = new AttachmentMessageReader(stream);
    const messages: Message[] = [];
    const errors: Error[] = [];
    reader.onError((error) => errors.push(error));
    reader.listen((message) => messages.push(message));
    return { stream, messages, errors, reader };
}

/** Feed `data` straight to the reader in pieces of `size`, as a socket might deliver it. */
function feed(reader: AttachmentMessageReader, data: Buffer, size: number): void {
    for (let offset = 0; offset < data.length; offset += size) {
        reader.onData(data.subarray(offset, offset + size));
    }
}

function result(message: Message): Record<string, unknown> {
    return (message as unknown as { result: Record<string, unknown> }).result;
}

suite('The framing PartCAD answers with', () => {
    test('a message without attachments is read as LSP framing is', () => {
        const { reader, messages, errors } = reading();
        feed(reader, Buffer.concat([plain({ id: 1, result: 'café ☕' }), plain({ id: 2, result: [1, 2] })]), 1 << 16);
        assert.deepStrictEqual(errors, []);
        assert.deepStrictEqual(messages, [
            { id: 1, result: 'café ☕' },
            { id: 2, result: [1, 2] },
        ]);
    });

    test('an attachment is put where the body names it, as bytes of its own', () => {
        const { reader, messages, errors } = reading();
        feed(reader, FRAME, FRAME.length);
        assert.deepStrictEqual(errors, []);
        assert.strictEqual(messages.length, 1);
        const { content, again, other } = result(messages[0]) as Record<string, Uint8Array>;
        assert.ok(content instanceof Uint8Array && !Buffer.isBuffer(content));
        assert.deepStrictEqual([...content], [0, 255, 10]);
        assert.deepStrictEqual(Buffer.from(other).toString('ascii'), 'ok');
        // Named twice, read once: the one object, which a webview is then
        // handed once.
        assert.strictEqual(again, content);
        // Memory of its own, the size of the file: what a webview is posted is
        // the whole of the buffer under it.
        assert.strictEqual(content.byteOffset, 0);
        assert.strictEqual(content.buffer.byteLength, 3);
    });

    test('a message is read whole however the stream cuts it up', () => {
        const big = Buffer.alloc(300_000);
        for (let i = 0; i < big.length; i++) {
            big[i] = (i * 7) % 251;
        }
        const body = '{"id": 3, "result": {"content": {"$attachment": 0}}}';
        const frame = Buffer.concat([
            Buffer.from(`Content-Length: ${body.length}\r\nAttachment-Lengths: ${big.length}\r\n\r\n${body}`),
            big,
        ]);
        const stream = Buffer.concat([plain({ id: 1 }), frame, FRAME, plain({ id: 4 })]);
        for (const size of [1, 2, 3, 7, 64, 65536, stream.length]) {
            const { reader, messages, errors } = reading();
            feed(reader, stream, size);
            assert.deepStrictEqual(errors, [], `in pieces of ${size}`);
            assert.deepStrictEqual(
                messages.map((message) => (message as { id?: number }).id),
                [1, 3, 1, 4],
                `in pieces of ${size}`,
            );
            const content = result(messages[1]).content as Uint8Array;
            assert.ok(Buffer.from(content).equals(big), `in pieces of ${size}`);
        }
    });

    test('a header that does not parse is reported, not taken for a message', () => {
        const { reader, messages, errors } = reading();
        feed(reader, Buffer.from('Content-Length: many\r\n\r\n{}'), 64);
        assert.deepStrictEqual(messages, []);
        assert.strictEqual(errors.length, 1);
        assert.match(errors[0].message, /Content-Length/);
    });

    test('a body naming an attachment it does not carry is reported', () => {
        const body = '{"id": 1, "result": {"$attachment": 1}}';
        const { reader, messages, errors } = reading();
        feed(reader, Buffer.from(`Content-Length: ${body.length}\r\nAttachment-Lengths: 1\r\n\r\n${body}x`), 64);
        assert.deepStrictEqual(messages, []);
        assert.strictEqual(errors.length, 1);
    });

    test('every message written says this end reads attachments', async () => {
        const stream = new PassThrough();
        const chunks: Buffer[] = [];
        stream.on('data', (chunk: Buffer) => chunks.push(chunk));
        const writer = new AttachmentMessageWriter(stream);
        await writer.write({ jsonrpc: '2.0', id: 1, method: 'render.inline', params: { name: 'Ø' } } as Message);
        const written = Buffer.concat(chunks).toString('utf8');
        const [header, body] = written.split('\r\n\r\n');
        assert.deepStrictEqual(header.split('\r\n'), [
            `Content-Length: ${Buffer.byteLength(body)}`,
            'Accept-Attachments: 1',
        ]);
        assert.deepStrictEqual(JSON.parse(body).params, { name: 'Ø' });
    });

    test('a request answered with an attachment resolves to the bytes, through vscode-jsonrpc', async () => {
        // The daemon's half, by hand: read the request, see that it says it
        // reads attachments, and answer with one.
        const toDaemon = new PassThrough();
        const fromDaemon = new PassThrough();
        const daemon = new AttachmentMessageReader(toDaemon);
        const declared: boolean[] = [];
        toDaemon.on('data', (chunk: Buffer) =>
            declared.push(chunk.toString('latin1').includes('Accept-Attachments: 1')),
        );
        daemon.listen((message) => {
            const id = (message as unknown as { id: number }).id;
            const answer = `{"jsonrpc": "2.0", "id": ${id}, "result": {"filename": "a.png", "content": {"$attachment": 0}}}`;
            fromDaemon.write(`Content-Length: ${Buffer.byteLength(answer)}\r\nAttachment-Lengths: 4\r\n\r\n${answer}`);
            fromDaemon.write(Buffer.from([137, 80, 78, 71]));
        });

        const connection = createMessageConnection(
            new AttachmentMessageReader(fromDaemon),
            new AttachmentMessageWriter(toDaemon),
        );
        connection.listen();
        try {
            const answer = (await connection.sendRequest('render.inline', { format: 'png' })) as {
                filename: string;
                content: Uint8Array;
            };
            assert.strictEqual(answer.filename, 'a.png');
            assert.ok(answer.content instanceof Uint8Array);
            assert.deepStrictEqual([...answer.content], [137, 80, 78, 71]);
            assert.ok(declared.includes(true));
        } finally {
            connection.dispose();
        }
    });

    test('a file is bytes whichever way it came', () => {
        // An attachment, as it is.
        const bytes = new Uint8Array([1, 2, 3]);
        assert.strictEqual(bytesOf(bytes), bytes);
        // Base64, from a daemon that sends no attachments.
        assert.deepStrictEqual([...(bytesOf('AQID') as Uint8Array)], [1, 2, 3]);
        // Never a Buffer, which a webview would be posted as an array of numbers.
        const fromBuffer = bytesOf(Buffer.from([4, 5]));
        assert.ok(fromBuffer instanceof Uint8Array && !Buffer.isBuffer(fromBuffer));
        assert.deepStrictEqual([...(fromBuffer as Uint8Array)], [4, 5]);
        assert.ok(!Buffer.isBuffer(bytesOf('AQID')));
        assert.strictEqual(bytesOf(undefined), undefined);
        assert.strictEqual(bytesOf(null), undefined);
    });
});
