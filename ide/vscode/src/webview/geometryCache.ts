//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The geometry this renderer has been shown, parsed, by digest, for the shows
// after it.
//
// Parsing a glTF and uploading it is where the time of showing a large object
// goes, and most of what a show draws is what the one before it drew: an edit
// re-renders one part of an assembly, a cross-section leaves the parts it misses
// as they were, a reader goes back to the object before. So a show's geometry
// table is looked up here first, and only what is not here is parsed.
//
// **What is kept is the host's decision, not this file's.** The host has to know
// what this renderer holds without asking, to leave those buffers out of the next
// show (see 'WebviewLedger' in 'src/viewer/geometryStore.ts'), so it keeps the
// account and says, with every show, what to let go of ('evict'). This side does
// as it is told, in the order it is told: 'receive' runs on the message as it
// arrives, before anything is awaited, so a buffer the host posted is held from
// that moment - even when the show that carried it is overtaken before it is
// drawn, and the next one is sent without it.
//
// Nothing here imports three.js: what an entry parses into is the caller's type,
// and so is how it is freed.

/** What the cache knows of one digest. */
interface Held<T> {
    /** The binary glTF, until it has been parsed. */
    raw?: ArrayBuffer;
    /** What it parsed into. */
    parsed?: T;
    /** The parse under way, which every show asking meanwhile waits for. */
    parsing?: Promise<T>;
    /** Why it would not parse; the same bytes will not parse next time either. */
    error?: string;
}

/** The parts of a show message the cache reads. */
export interface Received {
    object?: { geometry?: Record<string, { gltf?: ArrayBuffer | string }> } | null;
    evict?: string[];
}

export class GeometryCache<T> {
    private readonly held = new Map<string, Held<T>>();
    /**
     * Parsed geometry let go of while something may still draw it: the stage
     * until the next show is on it, or a show that was parsing it. Freed once a
     * show is on the stage that does not draw it ('use').
     */
    private readonly retired = new Set<T>();
    private release: (parsed: T) => void = () => undefined;

    /** How to free what an entry parsed into, once nothing draws it. */
    public onRelease(release: (parsed: T) => void): void {
        this.release = release;
    }

    /** Take in a show as it arrives: let go of what it says to, and keep the buffers it carries. */
    public receive(message: Received): void {
        for (const digest of message.evict ?? []) {
            const held = this.held.get(digest);
            this.held.delete(digest);
            if (held?.parsed !== undefined) {
                this.retired.add(held.parsed);
            }
            // One still parsing is retired when it finishes; see 'parsed'.
        }
        for (const [digest, entry] of Object.entries(message.object?.geometry ?? {})) {
            if (!(entry.gltf instanceof ArrayBuffer)) {
                continue;
            }
            const held = this.held.get(digest);
            if (held !== undefined && held.error === undefined) {
                // Parsed or parsing already: the same digest is the same bytes.
                continue;
            }
            this.held.set(digest, { raw: entry.gltf });
        }
    }

    /** Whether 'digest' is held, parsed or not. */
    public has(digest: string): boolean {
        return this.held.has(digest);
    }

    /** The digests held. */
    public digests(): string[] {
        return [...this.held.keys()];
    }

    /**
     * What 'digest' parses into, parsed by 'parse' the first time it is asked for
     * and never again; undefined when it is not held. Rejects with why it would
     * not parse, every time it is asked.
     */
    public parsed(digest: string, parse: (glb: ArrayBuffer) => Promise<T>): Promise<T | undefined> {
        const held = this.held.get(digest);
        if (held === undefined) {
            return Promise.resolve(undefined);
        }
        if (held.parsed !== undefined) {
            return Promise.resolve(held.parsed);
        }
        if (held.error !== undefined) {
            return Promise.reject(new Error(held.error));
        }
        if (held.parsing === undefined) {
            const raw = held.raw as ArrayBuffer;
            // The buffer goes as soon as the parse has it: what is drawn is what
            // it parses into, and holding both would be the model twice.
            held.raw = undefined;
            held.parsing = parse(raw).then(
                (parsed) => {
                    held.parsing = undefined;
                    held.parsed = parsed;
                    if (this.held.get(digest) !== held) {
                        // Let go of while it was being parsed.
                        this.retired.add(parsed);
                    }
                    return parsed;
                },
                (error) => {
                    held.parsing = undefined;
                    held.error = String(error);
                    throw error;
                },
            );
        }
        return held.parsing;
    }

    /**
     * The stage now draws these, and nothing else from here: free what was let
     * go of and is not among them.
     */
    public use(drawn: Iterable<T>): void {
        const inUse = new Set(drawn);
        for (const parsed of this.retired) {
            if (!inUse.has(parsed)) {
                this.retired.delete(parsed);
                this.release(parsed);
            }
        }
    }
}

/**
 * The renderer's one cache: filled by 'viewer.ts' as each show arrives - the 3D
 * view may still be loading then - and read, and freed from, by 'scene.ts'.
 */
export const geometryCache = new GeometryCache<unknown>();
