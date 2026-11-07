//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A frame the WebGPU renderer drew off the screen, put onto a 2D canvas
// ('readback.ts'): what a window that cannot present a WebGPU canvas is shown.
// The drawing needs a GPU and is checked in a browser ('tests/ide'); the copy is
// arithmetic, and is checked here.
//

import * as assert from 'assert';

import { copyPixels } from '../../webview/readback';

/** A frame of 'width' by 'height', each row 'stride' bytes, pixel (x, y) being [x, y, 7, alpha]. */
function frame(width: number, height: number, stride: number, alpha = 255): Uint8Array {
    const pixels = new Uint8Array((height - 1) * stride + width * 4).fill(99);
    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            pixels.set([x, y, 7, alpha], y * stride + x * 4);
        }
    }
    return pixels;
}

function pixel(image: Uint8ClampedArray, width: number, x: number, y: number): number[] {
    return Array.from(image.slice((y * width + x) * 4, (y * width + x) * 4 + 4));
}

suite('A frame drawn off the screen, on the screen', () => {
    test('rows padded to 256 bytes, as three r185 reads them back, lose the padding', () => {
        const pixels = frame(3, 2, 256);
        const image = new Uint8ClampedArray(3 * 2 * 4);
        copyPixels(pixels, 3, 2, image);
        assert.deepStrictEqual(pixel(image, 3, 0, 0), [0, 0, 7, 255]);
        assert.deepStrictEqual(pixel(image, 3, 2, 1), [2, 1, 7, 255]);
        assert.ok(!image.includes(99), 'nothing of the padding is in the image');
    });

    test('rows that are not padded, as three r187 reads them back, are taken as they are', () => {
        const pixels = frame(3, 2, 12);
        assert.strictEqual(pixels.length, 3 * 2 * 4);
        const image = new Uint8ClampedArray(3 * 2 * 4);
        copyPixels(pixels, 3, 2, image);
        assert.deepStrictEqual(pixel(image, 3, 1, 1), [1, 1, 7, 255]);
        // A width whose rows need no padding is the same either way.
        const aligned = frame(64, 2, 256);
        const into = new Uint8ClampedArray(64 * 2 * 4);
        copyPixels(aligned, 64, 2, into);
        assert.deepStrictEqual(pixel(into, 64, 63, 1), [63, 1, 7, 255]);
    });

    test('what was blended over nothing is divided by its alpha, and nothing stays nothing', () => {
        // A colour half on top of nothing, as the renderer leaves it: premultiplied.
        const half = new Uint8Array([100, 50, 0, 128]);
        const image = new Uint8ClampedArray(4);
        copyPixels(half, 1, 1, image);
        assert.deepStrictEqual(Array.from(image), [199, 100, 0, 128]);
        const clear = new Uint8Array([0, 0, 0, 0]);
        copyPixels(clear, 1, 1, image);
        assert.deepStrictEqual(Array.from(image), [0, 0, 0, 0]);
    });
});
