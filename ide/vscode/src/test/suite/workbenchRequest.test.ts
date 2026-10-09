//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// `pc ide open <folder>` leaves a request for the window that opens the folder.
// The file is written by `partcad_client.ide.write_request`; what is pinned here
// is which window takes it, and that nothing is left behind.
//

import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

import { REQUEST_TTL_S, requestsDirectory, takeRequests } from '../../workbenchRequest';

suite('Workbench requests', () => {
    let home: string;

    setup(() => {
        home = fs.mkdtempSync(path.join(os.tmpdir(), 'partcad-requests-'));
        fs.mkdirSync(requestsDirectory(home), { recursive: true });
    });

    teardown(() => {
        fs.rmSync(home, { recursive: true, force: true });
    });

    function leave(name: string, request: unknown): string {
        const file = path.join(requestsDirectory(home), name);
        fs.writeFileSync(file, JSON.stringify(request));
        return file;
    }

    test('the window whose workspace is the folder takes the request, and deletes it', () => {
        const folder = path.join(home, 'pkg');
        fs.mkdirSync(folder);
        const file = leave('a.json', { folder, view: 'workbench', requested: 1000 });

        assert.strictEqual(takeRequests([path.join(home, 'other')], { home, now: 1001 }), false);
        assert.strictEqual(fs.existsSync(file), true);

        assert.strictEqual(takeRequests([folder], { home, now: 1001 }), true);
        assert.strictEqual(fs.existsSync(file), false);
    });

    test('a request nobody took in time is ignored and deleted', () => {
        const folder = path.join(home, 'pkg');
        const file = leave('a.json', { folder, view: 'workbench', requested: 1000 });

        assert.strictEqual(takeRequests([folder], { home, now: 1000 + REQUEST_TTL_S + 1 }), false);
        assert.strictEqual(fs.existsSync(file), false);
    });

    test('a file that is not a request is deleted, and one being written is left alone', () => {
        const broken = leave('b.json', 'not a request');
        const partial = leave('.c.tmp', { folder: home, view: 'workbench', requested: 1000 });

        assert.strictEqual(takeRequests([home], { home, now: 1000 }), false);
        assert.strictEqual(fs.existsSync(broken), false);
        assert.strictEqual(fs.existsSync(partial), true);
    });

    test('no requests directory is no request', () => {
        fs.rmSync(requestsDirectory(home), { recursive: true });
        assert.strictEqual(takeRequests([home], { home }), false);
    });
});
