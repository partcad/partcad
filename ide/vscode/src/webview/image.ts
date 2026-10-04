//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// A picture, shown the way a browser shows one and moved the way an image
// viewer moves one: the result plot of a 2D analysis (the FEA and CFD tabs), and
// an object rendered to a file (the 2D and Draft tabs).
//

import { el } from './dom';

/** The still-image formats a browser shows by itself, by file extension. */
export const IMAGE_TYPES: Record<string, string> = {
    png: 'image/png',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    gif: 'image/gif',
    webp: 'image/webp',
    // Shown through an <img>, which cannot run script in it whatever the file
    // says. Never inlined into the DOM: the panel's CSP would not stop an
    // inlined <svg> from carrying an <a> or a <foreignObject>.
    svg: 'image/svg+xml',
};

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 20;

export function decodeBase64(content: string): Uint8Array {
    const binary = atob(content);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
}

/**
 * A still image that pans and zooms.
 *
 * A 2D analysis plot, a projection or a drawing is a picture with numbers
 * written on it, and the numbers are small: the whole point of it being 2D is
 * that it is read closely. So the wheel zooms about the pointer and a drag moves
 * the image, which is what every other image viewer does and therefore what
 * nobody has to be told. A double-click puts it back.
 */
export class ImageView {
    private readonly image = el('img', 'image-view');
    private readonly listeners = new AbortController();
    private scale = 1;
    private x = 0;
    private y = 0;
    private dragging: { x: number; y: number } | undefined;

    constructor(private readonly host: HTMLElement) {
        host.classList.add('image-host');
        host.appendChild(this.image);
        this.image.draggable = false;

        // Every listener under one signal, so that 'dispose()' is one call and
        // cannot forget one: they are added to the *host*, which outlives this
        // view, so emptying the pane does not take them with it.
        const on = { signal: this.listeners.signal };

        host.addEventListener(
            'wheel',
            (event: WheelEvent) => {
                event.preventDefault();
                const rect = host.getBoundingClientRect();
                // Zoom about the pointer rather than the centre: the thing being
                // looked at should stay under the cursor.
                const px = event.clientX - rect.left;
                const py = event.clientY - rect.top;
                const factor = Math.exp(-event.deltaY / 400);
                const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, this.scale * factor));
                const applied = next / this.scale;
                this.x = px - (px - this.x) * applied;
                this.y = py - (py - this.y) * applied;
                this.scale = next;
                this.apply();
            },
            on,
        );
        host.addEventListener(
            'pointerdown',
            (event: PointerEvent) => {
                this.dragging = { x: event.clientX - this.x, y: event.clientY - this.y };
                host.setPointerCapture(event.pointerId);
            },
            on,
        );
        host.addEventListener(
            'pointermove',
            (event: PointerEvent) => {
                if (this.dragging === undefined) {
                    return;
                }
                this.x = event.clientX - this.dragging.x;
                this.y = event.clientY - this.dragging.y;
                this.apply();
            },
            on,
        );
        const release = (event: PointerEvent) => {
            this.dragging = undefined;
            if (host.hasPointerCapture(event.pointerId)) {
                host.releasePointerCapture(event.pointerId);
            }
        };
        host.addEventListener('pointerup', release, on);
        host.addEventListener('pointercancel', release, on);
        host.addEventListener('dblclick', () => this.reset(), on);
    }

    public show(source: string, alt: string): void {
        this.image.src = source;
        this.image.alt = alt;
        this.reset();
    }

    /** Let go of the host: the listeners, the classes, and the <img> itself. */
    public dispose(): void {
        this.listeners.abort();
        this.image.remove();
        this.host.classList.remove('image-host');
    }

    private reset(): void {
        this.scale = 1;
        this.x = 0;
        this.y = 0;
        this.apply();
    }

    private apply(): void {
        this.image.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.scale})`;
    }
}
