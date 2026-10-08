//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// `pc ide state`: what the window reports about its three views, and how the
// answer travels back over the viewer's socket.
//

import * as assert from 'assert';
import * as fs from 'fs';
import * as net from 'net';
import * as os from 'os';

import { inspectorState } from '../../PartcadInspector';
import { explorerEntry } from '../../ideState';
import { PartcadViewerServer } from '../../viewer/PartcadViewerServer';
import { writeScreenshot } from '../../viewer/PartcadViewer';
import { FrameReader, KEY_STATE, MSG_STATE, PARTCAD_IDE_HOST, encodeFrame } from '../../viewer/protocol';

suite('pc ide state: the Explorer', () => {
    test('an object is reported by its full path and its kind', () => {
        const entry = explorerEntry({
            name: 'cube',
            pkg: '//pub/examples',
            itemType: 'part',
            itemPath: '/w/cube.py',
            config: { type: 'cadquery' },
        });
        assert.deepStrictEqual(entry, {
            kind: 'part',
            path: '//pub/examples:cube',
            package: '//pub/examples',
            name: 'cube',
            type: 'cadquery',
            file: '/w/cube.py',
        });
    });

    test("a package's full path is its own name, not its parent's", () => {
        const entry = explorerEntry({ name: '//pub/examples', pkg: '//pub', itemType: 'package' });
        assert.strictEqual(entry.path, '//pub/examples');
        assert.strictEqual(entry.package, '//pub/examples');
        assert.strictEqual(entry.file, null);
    });
});

suite('pc ide state: the Inspector', () => {
    const shown = {
        kind: 'part',
        item: {
            pkg: '//pub/examples',
            name: 'cube',
            itemPath: undefined,
            config: {
                type: 'cadquery',
                parameters: { size: { type: 'float', default: 10 }, hollow: { type: 'bool' } },
            },
        },
        params: { size: 20 },
    };

    test('what a field holds now wins over what was applied: Update may not have been pressed', () => {
        const state = inspectorState(shown, { properties: { name: 'cube' }, values: { size: '25.0' } });
        assert.deepStrictEqual(state.parameters, {
            size: { type: 'float', default: 10, value: '25.0' },
            hollow: { type: 'bool', value: null },
        });
        assert.deepStrictEqual(state.applied, { size: 20 });
        assert.deepStrictEqual(state.properties, { name: 'cube' });
        assert.strictEqual(state.live, true);
        assert.strictEqual(state.path, '//pub/examples:cube');
    });

    test('without the webview, the applied values are reported, and said to be', () => {
        const state = inspectorState(shown, undefined);
        assert.strictEqual((state.parameters as any).size.value, 20);
        assert.strictEqual(state.live, false);
        assert.strictEqual(state.properties, null);
    });

    test('a parameter nobody set reports its default', () => {
        const state = inspectorState({ ...shown, params: {} }, undefined);
        assert.strictEqual((state.parameters as any).size.value, 10);
    });
});

suite('pc ide state: the screenshot', () => {
    test('is written into the temporary directory, named after where it was taken', () => {
        const png = Buffer.from([0x89, 0x50, 0x4e, 0x47]);
        const file = writeScreenshot(png.toString('base64'), { tab: 'design', subTab: '2d' });
        try {
            assert.ok(file.startsWith(os.tmpdir()));
            assert.match(file, /partcad-viewer-design-2d-\d+\.png$/);
            assert.deepStrictEqual(fs.readFileSync(file), png);
        } finally {
            fs.rmSync(file, { force: true });
        }
    });

    test('a tab name cannot walk out of the directory', () => {
        const file = writeScreenshot('', { tab: '../../etc', subTab: 'x/y' });
        try {
            assert.ok(!file.slice(os.tmpdir().length + 1).includes('/'));
        } finally {
            fs.rmSync(file, { force: true });
        }
    });
});

/** Ask a server 'state' over a real socket, as `pc ide state` does. */
async function ask(port: number): Promise<Record<string, unknown>> {
    const socket = net.connect(port, PARTCAD_IDE_HOST);
    const reader = new FrameReader();
    try {
        return await new Promise((resolve, reject) => {
            socket.on('data', (chunk: Buffer) => {
                const [reply] = reader.push(chunk);
                if (reply !== undefined) {
                    resolve(reply as unknown as Record<string, unknown>);
                }
            });
            socket.on('error', reject);
            socket.write(encodeFrame({ type: MSG_STATE, id: 'q1' }));
        });
    } finally {
        socket.destroy();
    }
}

async function freePort(): Promise<number> {
    const probe = net.createServer();
    await new Promise<void>((resolve) => probe.listen(0, PARTCAD_IDE_HOST, resolve));
    const port = (probe.address() as net.AddressInfo).port;
    await new Promise<void>((resolve) => probe.close(() => resolve()));
    return port;
}

suite('pc ide state: over the socket', () => {
    test('the state comes back in the acknowledgement', async () => {
        const server = new PartcadViewerServer(await freePort());
        await server.start();
        server.setStateProvider(async () => ({ viewer: { open: false } }));
        try {
            const port = (server as any).port as number;
            const reply = await ask(port);
            assert.strictEqual(reply.id, 'q1');
            assert.strictEqual(reply.ok, true);
            assert.deepStrictEqual(reply[KEY_STATE], { viewer: { open: false } });
        } finally {
            server.dispose();
        }
    });

    test('a provider that fails is a failure saying why, not a hang', async () => {
        const server = new PartcadViewerServer(await freePort());
        await server.start();
        server.setStateProvider(async () => {
            throw new Error('the Viewer is busy');
        });
        try {
            const reply = await ask((server as any).port);
            assert.strictEqual(reply.ok, false);
            assert.strictEqual(reply.error, 'the Viewer is busy');
            assert.ok(!(KEY_STATE in reply));
        } finally {
            server.dispose();
        }
    });

    test('a window not ready yet says so', async () => {
        const server = new PartcadViewerServer(await freePort());
        await server.start();
        try {
            const reply = await ask((server as any).port);
            assert.strictEqual(reply.ok, false);
            assert.match(String(reply.error), /not ready/);
        } finally {
            server.dispose();
        }
    });
});
