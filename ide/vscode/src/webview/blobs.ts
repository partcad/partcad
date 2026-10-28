//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// Pictures the host posted as bytes, shown through Blob URLs.
//
// Every file the panel shows arrives as a Uint8Array (see 'viewer/payloads.ts'
// on the host's side), which postMessage hands over as it is. A data URI would
// be that file as base64 text again, a third bigger and parsed by the <img>; a
// Blob URL names the bytes where they are. The panel's CSP allows 'blob:' for
// images, and the URL is the panel's own.
//
// A Blob URL holds its bytes until it is revoked, however long the page lives
// -- and this panel is kept alive while hidden. So whoever shows one owns it,
// and lets go of it when what it showed goes.
//

/**
 * The Blob URLs one view has made, one per file, revoked together.
 *
 * One per file rather than one per <img>: a view drawn again (a table filled
 * in row by row, a page flipped back to) asks for the same file again, and an
 * instruction book shows one illustration on several pages -- which the host
 * sends once, so its pages are views of one buffer.
 */
export class ObjectUrls {
    private readonly made = new Map<object, string>();

    /** A URL for these bytes, made the first time they are asked for. */
    public of(bytes: Uint8Array, type: string): string {
        const key = bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength ? bytes.buffer : bytes;
        let url = this.made.get(key);
        if (url === undefined) {
            url = URL.createObjectURL(new Blob([bytes as Uint8Array<ArrayBuffer>], { type }));
            this.made.set(key, url);
        }
        return url;
    }

    /** Let go of every URL made so far; whatever showed them shows nothing now. */
    public revoke(): void {
        for (const url of this.made.values()) {
            URL.revokeObjectURL(url);
        }
        this.made.clear();
    }
}
