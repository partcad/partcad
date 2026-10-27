//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the Digital Thread keeps of the geometry it was shown, at both hops: the
// host's copy of each binary glTF, which answers PartCAD's offer of the next
// show; its account of what the webview holds parsed, which decides what is
// posted to it; and the webview's cache itself, which does what that account
// says. See 'src/viewer/geometryStore.ts' and 'src/webview/geometryCache.ts'.
//
// The webview's cache is generic in what it parses into, so it is exercised here
// with strings standing in for three.js groups; 'scene.ts' cannot be loaded in
// this suite (it builds a renderer as it loads).
//

import * as assert from 'assert';

import { ByteLru, GeometryExchange, GeometryStore, WebviewLedger } from '../../viewer/geometryStore';
import { MSG_GEOMETRY, MSG_SHOW, ViewerMessage } from '../../viewer/protocol';
import { GeometryCache } from '../../webview/geometryCache';

function glb(size: number): ArrayBuffer {
    return new ArrayBuffer(size);
}

suite('Keeping the geometry of earlier shows', () => {
    test('the least recently used goes first, past the budget, and never what is pinned', () => {
        const lru = new ByteLru<string>(100);
        lru.set('a', 'A', 40);
        lru.set('b', 'B', 40);
        lru.get('a');
        // 'b' is now the oldest.
        assert.deepStrictEqual(lru.set('c', 'C', 40), ['b']);
        assert.deepStrictEqual(lru.keys(), ['a', 'c']);
        assert.strictEqual(lru.bytes, 80);

        // On screen, whatever its size: only the rest goes.
        assert.deepStrictEqual(lru.pin(['a', 'd']), []);
        assert.deepStrictEqual(lru.set('d', 'D', 200), ['c']);
        assert.deepStrictEqual(lru.keys(), ['a', 'd']);
        // And once it is no longer on screen, it goes as anything else does.
        assert.deepStrictEqual(lru.pin(['d']), ['a']);
        assert.deepStrictEqual(lru.pin([]), ['d']);
    });

    test('the webview is posted only what it does not hold, and told what to let go of', () => {
        const ledger = new WebviewLedger(100);

        let plan = ledger.plan(
            new Map([
                ['bolt', 30],
                ['nut', 30],
            ]),
        );
        assert.deepStrictEqual([...plan.send].sort(), ['bolt', 'nut']);
        assert.deepStrictEqual(plan.evict, []);

        // An edit: the nut is now a washer. The bolt is held; nothing is over budget.
        plan = ledger.plan(
            new Map([
                ['bolt', 30],
                ['washer', 30],
            ]),
        );
        assert.deepStrictEqual([...plan.send], ['washer']);
        assert.deepStrictEqual(plan.evict, []);

        // A large object: what is not in it goes, oldest first - never what it shows.
        plan = ledger.plan(
            new Map([
                ['bolt', 30],
                ['frame', 60],
            ]),
        );
        assert.deepStrictEqual([...plan.send], ['frame']);
        assert.deepStrictEqual(plan.evict, ['nut', 'washer']);

        // A webview that reloaded holds nothing.
        ledger.clear();
        plan = ledger.plan(new Map([['bolt', 30]]));
        assert.deepStrictEqual([...plan.send], ['bolt']);
    });

    test('an offer is answered from the store and from what came ahead of the show', () => {
        const exchange = new GeometryExchange<string>(new GeometryStore(1000));
        const bolt = glb(10);
        const nut = glb(20);

        assert.deepStrictEqual(exchange.offer('daemon', ['bolt', 'nut', 7]), ['bolt', 'nut']);
        exchange.stage('daemon', { type: MSG_GEOMETRY, geometry: { bolt, nut } });
        assert.deepStrictEqual(exchange.offer('daemon', ['bolt', 'nut']), []);
        // Sent ahead over one connection is not held for another until it is shown.
        assert.deepStrictEqual(exchange.offer('terminal', ['bolt']), ['bolt']);

        const show: ViewerMessage = { type: MSG_SHOW, object: { geometry: { bolt: null, nut: null } } };
        assert.deepStrictEqual(exchange.resolve('daemon', show), []);
        assert.strictEqual(show.object!.geometry!.bolt, bolt);
        assert.strictEqual(show.object!.geometry!.nut, nut);

        // Shown, it is the window's: any connection's next offer finds it.
        assert.deepStrictEqual(exchange.offer('terminal', ['bolt', 'washer']), ['washer']);
    });

    test('a show naming what is not held is not shown, and says what is missing', () => {
        const exchange = new GeometryExchange<string>(new GeometryStore(1000));
        const bolt = glb(10);
        exchange.stage('daemon', { type: MSG_GEOMETRY, geometry: { bolt } });

        const show: ViewerMessage = { type: MSG_SHOW, object: { geometry: { bolt: null, nut: null } } };
        assert.deepStrictEqual(exchange.resolve('daemon', show), ['nut']);
        // What was sent ahead is still there for the show that follows.
        exchange.stage('daemon', { type: MSG_GEOMETRY, geometry: { nut: glb(5) } });
        const again: ViewerMessage = { type: MSG_SHOW, object: { geometry: { bolt: null, nut: null } } };
        assert.deepStrictEqual(exchange.resolve('daemon', again), []);
        assert.strictEqual(again.object!.geometry!.bolt, bolt);
    });

    test('a show sent whole is kept for the next offer, and text is left for the viewer to decode', () => {
        const exchange = new GeometryExchange<string>(new GeometryStore(1000));
        const show: ViewerMessage = {
            type: MSG_SHOW,
            object: { geometry: { bolt: glb(10), old: 'eJwDAAAAAAE=' } },
        };
        assert.deepStrictEqual(exchange.resolve('daemon', show), []);
        assert.deepStrictEqual(exchange.offer('daemon', ['bolt', 'old']), ['old']);
        assert.strictEqual(show.object!.geometry!.old, 'eJwDAAAAAAE=');
    });

    test('a connection that goes leaves nothing staged behind', () => {
        const exchange = new GeometryExchange<string>(new GeometryStore(1000));
        exchange.stage('daemon', { type: MSG_GEOMETRY, geometry: { bolt: glb(10) } });
        exchange.forget('daemon');
        assert.deepStrictEqual(exchange.offer('daemon', ['bolt']), ['bolt']);
    });

    test('the store keeps the show on screen however large, and lets the rest go past its budget', () => {
        const store = new GeometryStore(100);
        store.keepShown(
            new Map([
                ['a', glb(60)],
                ['b', glb(60)],
            ]),
        );
        assert.deepStrictEqual(store.keys().sort(), ['a', 'b']);
        store.keepShown(new Map([['c', glb(60)]]));
        assert.deepStrictEqual(store.keys(), ['c']);
    });
});

/** A show message as the webview receives one. */
function show(geometry: Record<string, { gltf?: ArrayBuffer; size: number }>, evict: string[] = []) {
    return { object: { geometry }, evict };
}

suite("The webview's cache of parsed geometry", () => {
    test('a shape is parsed once, however many shows draw it', async () => {
        const cache = new GeometryCache<string>();
        let parses = 0;
        const parse = async (buffer: ArrayBuffer) => `parsed ${buffer.byteLength} #${++parses}`;

        cache.receive(show({ bolt: { gltf: glb(10), size: 10 } }));
        assert.strictEqual(await cache.parsed('bolt', parse), 'parsed 10 #1');
        // The next show names it without its buffer.
        cache.receive(show({ bolt: { size: 10 } }));
        assert.strictEqual(await cache.parsed('bolt', parse), 'parsed 10 #1');
        assert.strictEqual(parses, 1);
        // Two shows asking while it parses wait for the one parse.
        cache.receive(show({ nut: { gltf: glb(5), size: 5 } }));
        const both = await Promise.all([cache.parsed('nut', parse), cache.parsed('nut', parse)]);
        assert.deepStrictEqual(both, ['parsed 5 #2', 'parsed 5 #2']);
    });

    test('what it is not sent and does not hold is not there', async () => {
        const cache = new GeometryCache<string>();
        cache.receive(show({ bolt: { size: 10 } }));
        assert.strictEqual(await cache.parsed('bolt', async () => 'never'), undefined);
        assert.ok(!cache.has('bolt'));
    });

    test('what the host says to let go of is freed once no show on the stage draws it', async () => {
        const released: string[] = [];
        const cache = new GeometryCache<string>();
        cache.onRelease((parsed) => released.push(parsed));
        const parse = async () => 'bolt group';

        cache.receive(show({ bolt: { gltf: glb(10), size: 10 } }));
        const bolt = await cache.parsed('bolt', parse);
        cache.use([bolt!]);

        // The next show lets it go, but the stage still draws it until that show is on it.
        cache.receive(show({ nut: { gltf: glb(5), size: 5 } }, ['bolt']));
        assert.ok(!cache.has('bolt'));
        assert.deepStrictEqual(released, []);
        cache.use([bolt!]);
        assert.deepStrictEqual(released, []);
        cache.use([]);
        assert.deepStrictEqual(released, ['bolt group']);
    });

    test('a buffer it was sent is kept even when the show that carried it is never drawn', async () => {
        // What the host's account relies on: a show overtaken before it is drawn
        // still leaves its geometry here, and the next show is sent without it.
        const cache = new GeometryCache<string>();
        cache.receive(show({ bolt: { gltf: glb(10), size: 10 } }));
        cache.receive(show({ bolt: { size: 10 } }));
        assert.strictEqual(await cache.parsed('bolt', async () => 'bolt group'), 'bolt group');
    });

    test('one let go of while it is parsed is freed when the stage no longer needs it', async () => {
        const released: string[] = [];
        const cache = new GeometryCache<string>();
        cache.onRelease((parsed) => released.push(parsed));
        let finish: (value: string) => void = () => undefined;
        cache.receive(show({ bolt: { gltf: glb(10), size: 10 } }));
        const parsing = cache.parsed('bolt', () => new Promise<string>((resolve) => (finish = resolve)));

        cache.receive(show({}, ['bolt']));
        finish('bolt group');
        assert.strictEqual(await parsing, 'bolt group');
        cache.use([]);
        assert.deepStrictEqual(released, ['bolt group']);
    });

    test('a shape that will not parse says why every time, until it is sent again', async () => {
        const cache = new GeometryCache<string>();
        let attempts = 0;
        const parse = async () => {
            attempts++;
            throw new Error('not a glTF');
        };
        cache.receive(show({ bad: { gltf: glb(3), size: 3 } }));
        await assert.rejects(cache.parsed('bad', parse), /not a glTF/);
        await assert.rejects(cache.parsed('bad', parse), /not a glTF/);
        assert.strictEqual(attempts, 1);

        cache.receive(show({ bad: { gltf: glb(4), size: 4 } }));
        assert.strictEqual(await cache.parsed('bad', async () => 'fixed'), 'fixed');
    });
});
