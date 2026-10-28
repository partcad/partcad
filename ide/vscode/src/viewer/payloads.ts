//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The files in the answers the Digital Thread's tabs are filled from, as the
// bytes the panel is handed.
//
// A daemon sends each one as raw bytes after the message carrying it (see
// 'common/framing.ts'), and a daemon from before that as base64 under the same
// key. The panel is posted bytes either way -- a Uint8Array, which a webview is
// handed as it is rather than as text -- so that it has one way to show each, a
// Blob URL, and no base64 to decode with 'atob' a character at a time.
//
// Kept apart from 'PartcadViewer.ts', which needs 'vscode', so that the suite
// can drive it without an editor.
//

import { bytesOf } from '../common/framing';

type Fields = Record<string, unknown>;

function isRecord(value: unknown): value is Fields {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function records(value: unknown): Fields[] {
    return Array.isArray(value) ? value.filter(isRecord) : [];
}

/** Make `record[key]` the bytes it carries, or null; leave a key that is not there alone. */
function inBytes(record: Fields, key: string): void {
    if (key in record) {
        record[key] = bytesOf(record[key]) ?? null;
    }
}

/** A generated document's pictures, where they are carried as bytes rather than as a data URI. */
export function documentBytes(data: unknown): void {
    const document = isRecord(data) ? data.document : undefined;
    if (!isRecord(document)) {
        return;
    }
    for (const page of records(document.pages)) {
        for (const block of records(page.blocks)) {
            for (const image of records(block.images)) {
                inBytes(image, 'content');
            }
        }
    }
}

/** The thumbnails of a 'manufacturing.details' answer. */
export function detailsBytes(items: unknown): void {
    for (const item of records(items)) {
        inBytes(item, 'thumbnail');
    }
}

/**
 * Every file in what fills one tab, made bytes in place. Returns `data`.
 *
 * The render tabs carry the file, an analysis carries the model of each
 * scenario (and of the only one, where a client from before scenarios reads
 * it), a run of a simulation its pictures and its video, and the Assembly and
 * Build tabs the pictures of their pages. The Assembly tab's file is not here:
 * it stays in the extension host, where Save copies it from, and is written
 * down with `bytesOf` there.
 */
export function filesAsBytes(tab: string, data: unknown): unknown {
    if (!isRecord(data)) {
        return data;
    }
    switch (tab) {
        case '2d':
        case 'draft':
            inBytes(data, 'content');
            break;
        case 'fea':
        case 'dynamic':
        case 'thermal':
        case 'cfd':
            inBytes(data, 'content');
            for (const entry of records(data.analyses)) {
                inBytes(entry, 'content');
            }
            break;
        case 'simulation':
            for (const run of records(data.simulations)) {
                for (const image of Object.values(isRecord(run.images) ? run.images : {})) {
                    if (isRecord(image)) {
                        inBytes(image, 'content');
                    }
                }
                if (isRecord(run.recording)) {
                    inBytes(run.recording, 'content');
                }
            }
            break;
        case 'assembly':
        case 'build':
            documentBytes(data);
            break;
    }
    return data;
}
