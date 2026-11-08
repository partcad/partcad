//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A frame of the WebGPU renderer read back from the texture it was drawn into,
// for a window that cannot present a WebGPU canvas (see 'offscreenSurface' in
// 'surface.ts'). Nothing is imported, so the extension host's tests can import
// it (see 'viewerReadback.test.ts').
//

/**
 * A frame read back from a texture, as a 2D canvas takes it: colours that were
 * blended over nothing - premultiplied by their alpha - divided by it again.
 *
 * A row of a texture copied to a buffer is padded to 256 bytes, which three
 * r185 handed back as they were and r187 takes out; so the rows are as long as
 * what arrived says they are, whichever it is.
 */
export function copyPixels(pixels: Uint8Array, width: number, height: number, into: Uint8ClampedArray): void {
    const stride = pixels.length === width * height * 4 ? width * 4 : Math.ceil((width * 4) / 256) * 256;
    for (let y = 0; y < height; y++) {
        let from = y * stride;
        let to = y * width * 4;
        for (let x = 0; x < width; x++, from += 4, to += 4) {
            const alpha = pixels[from + 3];
            if (alpha === 255 || alpha === 0) {
                into[to] = pixels[from];
                into[to + 1] = pixels[from + 1];
                into[to + 2] = pixels[from + 2];
            } else {
                const scale = 255 / alpha;
                into[to] = pixels[from] * scale;
                into[to + 1] = pixels[from + 1] * scale;
                into[to + 2] = pixels[from + 2] * scale;
            }
            into[to + 3] = alpha;
        }
    }
}
