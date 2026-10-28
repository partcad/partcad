//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The files the Digital Thread's tabs are filled with: bytes, whichever way the
// daemon sent them (see 'viewer/payloads.ts'), and shown through Blob URLs that
// go when what showed them goes (see 'webview/blobs.ts').
//

import * as assert from 'assert';
import { resolveObjectURL } from 'buffer';

import { detailsBytes, filesAsBytes } from '../../viewer/payloads';
import { ObjectUrls } from '../../webview/blobs';

const PNG = new Uint8Array([137, 80, 78, 71]);
const PNG_BASE64 = 'iVBORw==';

function isBytes(value: unknown, expected: Uint8Array): boolean {
    return value instanceof Uint8Array && !Buffer.isBuffer(value) && Buffer.from(value).equals(Buffer.from(expected));
}

suite('The files a tab is filled with', () => {
    test('a render is bytes, from a daemon that sends them and from one that sends base64', () => {
        const attached = { object: '//p:a', extension: 'png', content: PNG };
        assert.strictEqual((filesAsBytes('2d', attached) as typeof attached).content, PNG);

        const older = filesAsBytes('draft', { object: '//p:a', extension: 'png', content: PNG_BASE64 }) as {
            content: unknown;
        };
        assert.ok(isBytes(older.content, PNG));
    });

    test("an analysis's models are bytes, the only one's included, and a missing one stays missing", () => {
        const data = filesAsBytes('fea', {
            content: PNG_BASE64,
            analyses: [{ content: PNG_BASE64 }, { content: null }, { error: 'no solver' }],
        }) as { content: unknown; analyses: Record<string, unknown>[] };
        assert.ok(isBytes(data.content, PNG));
        assert.ok(isBytes(data.analyses[0].content, PNG));
        assert.strictEqual(data.analyses[1].content, null);
        assert.ok(!('content' in data.analyses[2]));
    });

    test("a run's pictures and its video are bytes", () => {
        const data = filesAsBytes('simulation', {
            simulations: [
                {
                    images: { before: { extension: 'png', content: PNG_BASE64 } },
                    recording: { extension: 'webm', content: PNG_BASE64 },
                },
                { images: undefined },
            ],
        }) as { simulations: { images: Record<string, { content: unknown }>; recording?: { content: unknown } }[] };
        assert.ok(isBytes(data.simulations[0].images.before.content, PNG));
        assert.ok(isBytes(data.simulations[0].recording?.content, PNG));
        assert.ok(!('recording' in data.simulations[1]));
    });

    test("a document's pictures are bytes where they came as bytes, and data URIs are left alone", () => {
        const uri = `data:image/png;base64,${PNG_BASE64}`;
        const data = filesAsBytes('assembly', {
            document: {
                pages: [
                    {
                        blocks: [
                            { type: 'images', images: [{ content: PNG_BASE64, type: 'image/png' }, { src: uri }] },
                        ],
                    },
                    { blocks: [{ type: 'paragraph', text: 'Put it together.' }] },
                ],
            },
        }) as { document: { pages: { blocks: { images?: Record<string, unknown>[] }[] }[] } };
        const [bytes, legacy] = data.document.pages[0].blocks[0].images ?? [];
        assert.ok(isBytes(bytes.content, PNG));
        assert.strictEqual(legacy.src, uri);
        assert.ok(!('content' in legacy));
    });

    test('a tab that carries no file is passed on as it came', () => {
        const data = { items: [{ name: 'bolt', content: 'not a file' }] };
        assert.strictEqual(filesAsBytes('bom', data), data);
        assert.strictEqual(data.items[0].content, 'not a file');
        assert.strictEqual(filesAsBytes('2d', undefined), undefined);
    });

    test('the thumbnails of a Build vs Buy table are bytes', () => {
        const items = [{ name: 'a', thumbnail: PNG_BASE64 }, { name: 'b', thumbnail: null }, { name: 'c' }];
        detailsBytes(items);
        assert.ok(isBytes(items[0].thumbnail, PNG));
        assert.strictEqual(items[1].thumbnail, null);
        assert.ok(!('thumbnail' in items[2]));
        detailsBytes(undefined);
    });
});

suite('The Blob URLs a pane shows its pictures through', () => {
    test('one URL per file, of its bytes and its type, however often it is asked for', async () => {
        const urls = new ObjectUrls();
        const url = urls.of(PNG, 'image/png');
        assert.strictEqual(urls.of(PNG, 'image/png'), url);
        // Two views of one buffer are one file: how a webview is handed an
        // illustration that one message names twice.
        const buffer = new Uint8Array([1, 2, 3]).buffer;
        assert.strictEqual(urls.of(new Uint8Array(buffer), 'image/svg+xml'), urls.of(new Uint8Array(buffer), 'x'));

        const blob = resolveObjectURL(url);
        assert.ok(blob, `${url} names nothing`);
        assert.strictEqual(blob.type, 'image/png');
        assert.ok(Buffer.from(await blob.arrayBuffer()).equals(Buffer.from(PNG)));
        urls.revoke();
    });

    test('revoking lets go of every one, and the next is made afresh', () => {
        const urls = new ObjectUrls();
        const first = urls.of(PNG, 'image/png');
        const second = urls.of(new Uint8Array([9]), 'image/png');
        urls.revoke();
        assert.strictEqual(resolveObjectURL(first), undefined);
        assert.strictEqual(resolveObjectURL(second), undefined);
        const again = urls.of(PNG, 'image/png');
        assert.notStrictEqual(again, first);
        assert.ok(resolveObjectURL(again));
        urls.revoke();
    });
});
