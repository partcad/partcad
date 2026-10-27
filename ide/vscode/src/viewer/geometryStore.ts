//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What the Digital Thread keeps of the geometry it has been shown, so that the
// next show need not be sent it again.
//
// Two records of it, one for each hop a show takes, because what is worth
// keeping differs:
//
//   * the host's own copy of each binary glTF it was sent, by digest
//     ('GeometryStore', kept by 'PartcadViewerServer'). That is what an offer is
//     answered from (see MSG_OFFER in 'src/partcad_ide_client/protocol.py'): a
//     PartCAD showing an assembly again after one of its parts was edited is told
//     the IDE lacks that part and nothing else, and sends only it. And it is what
//     a webview that has to be filled from nothing - the panel closed and opened,
//     the page reloaded - is filled from, without PartCAD;
//
//   * what the webview holds, parsed into three.js geometry ('WebviewLedger',
//     kept by 'PartcadViewer'). The host decides what the webview keeps and what
//     it lets go of, and says so with every show (its 'evict'), so that it always
//     knows, without asking, which buffers it need not post: the webview has no
//     say, and nothing to report back but the mistake ('geometryMissing').
//
// Both are least-recently-used by bytes, and both always keep the show on screen
// whatever its size: a show larger than the budget is still shown, and only what
// is not in it is let go of. The budgets are for what lingers.
//
// Nothing here imports 'vscode', so the suite runs it as it is.

import { ViewerMessage } from './protocol';

/** How much binary glTF the host keeps beyond what is on screen. */
export const STORE_BUDGET = 256 * 1024 * 1024;

/** How much the webview keeps parsed beyond what is on screen, counted as the glTF it was parsed from. */
export const WEBVIEW_BUDGET = 256 * 1024 * 1024;

/**
 * Entries by digest, least recently used first, the oldest let go of past a
 * budget of bytes - except the pinned ones, which are what is on screen.
 */
export class ByteLru<V> {
    /** In order of use: a Map iterates in insertion order, and a use re-inserts. */
    private readonly entries = new Map<string, { value: V; size: number }>();
    private pinned: ReadonlySet<string> = new Set();
    private total = 0;

    constructor(public readonly budget: number) {}

    /** How many bytes are held. */
    public get bytes(): number {
        return this.total;
    }

    public has(key: string): boolean {
        return this.entries.has(key);
    }

    /** The value under 'key', which is then the most recently used. */
    public get(key: string): V | undefined {
        const entry = this.entries.get(key);
        if (entry === undefined) {
            return undefined;
        }
        this.entries.delete(key);
        this.entries.set(key, entry);
        return entry.value;
    }

    /** Hold 'value' under 'key', as the most recently used; returns what was let go of to make room. */
    public set(key: string, value: V, size: number): string[] {
        this.delete(key);
        this.entries.set(key, { value, size });
        this.total += size;
        return this.trim();
    }

    public delete(key: string): boolean {
        const entry = this.entries.get(key);
        if (entry === undefined) {
            return false;
        }
        this.entries.delete(key);
        this.total -= entry.size;
        return true;
    }

    /** Keep these whatever the budget, instead of the ones pinned before; returns what was then let go of. */
    public pin(keys: Iterable<string>): string[] {
        this.pinned = new Set(keys);
        return this.trim();
    }

    public clear(): void {
        this.entries.clear();
        this.total = 0;
    }

    public keys(): string[] {
        return [...this.entries.keys()];
    }

    private trim(): string[] {
        const dropped: string[] = [];
        if (this.total <= this.budget) {
            return dropped;
        }
        for (const [key, entry] of this.entries) {
            if (this.total <= this.budget) {
                break;
            }
            if (this.pinned.has(key)) {
                continue;
            }
            this.entries.delete(key);
            this.total -= entry.size;
            dropped.push(key);
        }
        return dropped;
    }
}

/** The host's copy of the binary glTF it was sent, by digest. */
export class GeometryStore extends ByteLru<ArrayBuffer> {
    constructor(budget: number = STORE_BUDGET) {
        super(budget);
    }

    /** Of 'digests', the ones neither held here nor in 'staged'. */
    public lacking(digests: readonly string[], staged?: ReadonlyMap<string, ArrayBuffer>): string[] {
        return digests.filter((digest) => !staged?.has(digest) && !this.has(digest));
    }

    /** Hold a show's geometry, and keep it whatever the budget until the next show. */
    public keepShown(geometry: ReadonlyMap<string, ArrayBuffer>): void {
        // Pinned first, so that holding one of them cannot let go of another.
        this.pin(geometry.keys());
        for (const [digest, glb] of geometry) {
            this.set(digest, glb, glb.byteLength);
        }
    }
}

/** What the webview holds, by digest, with the size of the glTF each was parsed from. */
export class WebviewLedger extends ByteLru<true> {
    constructor(budget: number = WEBVIEW_BUDGET) {
        super(budget);
    }

    /**
     * What to post with a show of this geometry, and what the webview is to let go of.
     *
     * 'send' is what the webview does not hold, whose buffers go with the show;
     * the rest it already has parsed. 'evict' is what it holds and is to drop to
     * stay within the budget, never any of this show's. From then on the ledger
     * says the webview holds all of 'geometry' - which it does as soon as it has
     * read the message, since it keeps a buffer it is sent before it does
     * anything else with the show (see 'webview/geometryCache.ts').
     */
    public plan(geometry: ReadonlyMap<string, number>): { send: Set<string>; evict: string[] } {
        const send = new Set<string>();
        for (const digest of geometry.keys()) {
            if (!this.has(digest)) {
                send.add(digest);
            }
        }
        const evict = this.pin(geometry.keys());
        for (const [digest, size] of geometry) {
            evict.push(...this.set(digest, true, size));
        }
        return { send, evict };
    }
}

/**
 * The host's half of an offered show (see MSG_OFFER in the Python module), for
 * every connection: what is lacking, what was sent ahead, and the show that names
 * it all filled in.
 *
 * Generic in what tells connections apart, which is a socket to the server and
 * anything at all to the suite.
 */
export class GeometryExchange<Connection> {
    /**
     * What each connection sent ahead of its show (MSG_GEOMETRY), until a show
     * over it names it. Apart from the store, so that nothing another connection
     * shows in between can let go of it.
     */
    private readonly staged = new Map<Connection, Map<string, ArrayBuffer>>();

    /**
     * 'store' is shared by every connection, since what one PartCAD process sent
     * another may show: the daemon and a 'pc' in a terminal show the same parts.
     */
    constructor(public readonly store: GeometryStore = new GeometryStore()) {}

    /** Of the digests offered, the ones this side lacks. */
    public offer(connection: Connection, digests: unknown): string[] {
        const offered = Array.isArray(digests) ? digests.filter((digest) => typeof digest === 'string') : [];
        return this.store.lacking(offered, this.staged.get(connection));
    }

    /** Keep what a 'geometry' message carries for the show that will follow it over 'connection'. */
    public stage(connection: Connection, message: ViewerMessage): void {
        let staged = this.staged.get(connection);
        if (staged === undefined) {
            staged = new Map();
            this.staged.set(connection, staged);
        }
        for (const [digest, glb] of Object.entries(message.geometry ?? {})) {
            if (glb instanceof ArrayBuffer) {
                staged.set(digest, glb);
            }
        }
    }

    /**
     * Fill in the entries of a show's geometry table that name what this side
     * holds (null), and keep the show's geometry for the next one; returns what
     * it names and is not held, in which case the show is not to be shown.
     *
     * Only the blobs are kept: an entry that came as text is from a PartCAD that
     * does not offer, which has nothing to ask the store. It is decoded where it
     * always was, by the viewer.
     */
    public resolve(connection: Connection, message: ViewerMessage): string[] {
        const table = message.object?.geometry;
        if (table === undefined || table === null) {
            return [];
        }
        const staged = this.staged.get(connection);
        const missing: string[] = [];
        const shown = new Map<string, ArrayBuffer>();
        for (const [digest, payload] of Object.entries(table)) {
            let glb = payload;
            if (glb === null) {
                glb = staged?.get(digest) ?? this.store.get(digest) ?? null;
                if (glb === null) {
                    missing.push(digest);
                    continue;
                }
                table[digest] = glb;
            }
            if (glb instanceof ArrayBuffer) {
                shown.set(digest, glb);
            }
        }
        if (missing.length > 0) {
            return missing;
        }
        this.store.keepShown(shown);
        this.staged.delete(connection);
        return [];
    }

    /** The connection is gone, and with it whatever it sent ahead of a show it never sent. */
    public forget(connection: Connection): void {
        this.staged.delete(connection);
    }
}
