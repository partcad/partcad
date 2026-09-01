//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// How the viewer's port is bound.
//

import * as assert from 'assert';
import * as net from 'net';

import { listenOptions } from '../../viewer/PartcadViewerServer';
import { PARTCAD_IDE_HOST, PARTCAD_IDE_PORT } from '../../viewer/protocol';

type MaybeReusePort = net.ListenOptions & { reusePort?: boolean };

suite('Binding the viewer port', () => {
    test('the port and the loopback host are always asked for', () => {
        const options = listenOptions(PARTCAD_IDE_PORT, PARTCAD_IDE_HOST);
        assert.strictEqual(options.port, PARTCAD_IDE_PORT);
        assert.strictEqual(options.host, PARTCAD_IDE_HOST);
    });

    test('SO_REUSEPORT is asked for only where libuv has it', () => {
        // Where it does not -- Windows, macOS -- `listen` fails with ENOTSUP
        // rather than ignoring the option, which took the viewer down entirely
        // on both as soon as VS Code shipped a Node that passes the option
        // through (22.12). There is nothing to ask for instead: Node's `listen`
        // has no `reuseAddr`, and libuv sets neither SO_REUSEADDR nor
        // SO_EXCLUSIVEADDRUSE for a TCP server on Windows.
        const options = listenOptions(PARTCAD_IDE_PORT, PARTCAD_IDE_HOST) as MaybeReusePort;
        assert.strictEqual(options.reusePort, process.platform === 'linux' ? true : undefined);
    });

    test('the options really bind', async () => {
        // The assertion the two above cannot make: whatever this platform is,
        // a server started with these options listens.
        const server = net.createServer();
        try {
            await new Promise<void>((resolve, reject) => {
                server.once('error', reject);
                // Port 0: the constant one may be held by a viewer this very
                // window is running.
                server.listen({ ...listenOptions(0, PARTCAD_IDE_HOST) }, resolve);
            });
            assert.ok(server.listening);
        } finally {
            server.close();
        }
    });
});
