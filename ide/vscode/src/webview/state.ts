//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// What `pc ide state` learns from the panel: a picture of the sub-tab on screen,
// and the value of every control in a pane.
//
// The picture is taken of the DOM, because most of the panel is DOM: a bill of
// materials is a table, Build vs Buy is switches, a 2D render is an <img>. The
// pane is cloned with every computed style written onto it, put into an SVG
// <foreignObject> and drawn onto a canvas, which is how a page draws itself in a
// browser that has no screenshot API -- Chromium lets such a canvas be read
// back, which is the property all of this rests on. Two things do not survive
// the clone and are put back by hand: a canvas (the 3D view, an analysis result)
// clones blank, so each is replaced by an <img> of what it shows; and a form
// control's value is a property, not an attribute, so it is written as one.
//

/** A canvas's picture as a data URL, or undefined for one this should leave out. */
export type CanvasCapture = (canvas: HTMLCanvasElement) => string | undefined;

/**
 * The element as a PNG, base64 without the 'data:' prefix.
 *
 * Rejects with a sentence when it cannot: an element with no size (a tab that is
 * not laid out), or a browser that refuses to read the canvas back.
 */
export async function snapshot(element: HTMLElement, capture: CanvasCapture): Promise<string> {
    const box = element.getBoundingClientRect();
    const width = Math.ceil(box.width);
    const height = Math.ceil(box.height);
    if (width === 0 || height === 0) {
        throw new Error('the sub-tab on screen has no size -- the PartCAD Viewer is probably hidden');
    }
    const clone = cloneWithStyles(element, capture);
    clone.style.margin = '0';
    const xhtml = new XMLSerializer().serializeToString(clone);
    const svg =
        `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">` +
        `<foreignObject x="0" y="0" width="100%" height="100%">${xhtml}</foreignObject></svg>`;
    const image = await load(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);

    const ratio = window.devicePixelRatio || 1;
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(width * ratio);
    canvas.height = Math.ceil(height * ratio);
    const context = canvas.getContext('2d');
    if (context === null) {
        throw new Error('no 2D canvas to draw the screenshot on');
    }
    context.scale(ratio, ratio);
    // The theme's background: the pane itself is transparent over it.
    context.fillStyle = getComputedStyle(document.body).backgroundColor || '#ffffff';
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);
    return canvas.toDataURL('image/png').replace(/^data:image\/png;base64,/, '');
}

function load(source: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error('the pane could not be drawn as an image'));
        image.src = source;
    });
}

/** A deep clone that looks like the original without the stylesheet it came with. */
function cloneWithStyles(element: HTMLElement, capture: CanvasCapture): HTMLElement {
    const clone = element.cloneNode(true) as HTMLElement;
    const originals = [element, ...Array.from(element.querySelectorAll<HTMLElement>('*'))];
    const copies = [clone, ...Array.from(clone.querySelectorAll<HTMLElement>('*'))];
    originals.forEach((original, index) => {
        const copy = copies[index];
        const computed = getComputedStyle(original);
        copy.setAttribute('style', computed.cssText || styleText(computed));
        if (original instanceof HTMLInputElement) {
            if (original.type === 'checkbox' || original.type === 'radio') {
                if (original.checked) {
                    copy.setAttribute('checked', '');
                } else {
                    copy.removeAttribute('checked');
                }
            } else {
                copy.setAttribute('value', original.value);
            }
        } else if (original instanceof HTMLSelectElement) {
            Array.from((copy as HTMLSelectElement).options).forEach((option, i) => {
                if (i === original.selectedIndex) {
                    option.setAttribute('selected', '');
                } else {
                    option.removeAttribute('selected');
                }
            });
        } else if (original instanceof HTMLTextAreaElement) {
            copy.textContent = original.value;
        } else if (original instanceof HTMLCanvasElement) {
            const picture = capture(original);
            const image = document.createElement('img');
            image.setAttribute('style', copy.getAttribute('style') ?? '');
            image.setAttribute('width', String(original.clientWidth));
            image.setAttribute('height', String(original.clientHeight));
            if (picture !== undefined) {
                image.setAttribute('src', picture);
            }
            copy.replaceWith(image);
        }
    });
    return clone;
}

/** 'cssText' of a computed style is empty in some engines; spelled out property by property then. */
function styleText(style: CSSStyleDeclaration): string {
    let text = '';
    for (let i = 0; i < style.length; i++) {
        const name = style.item(i);
        text += `${name}:${style.getPropertyValue(name)};`;
    }
    return text;
}

/**
 * Every control in a pane that says something about what is shown, by what it is called.
 *
 * Not a tree's own boxes, which are reported as the tree (see 'Tree.rows'); not
 * buttons, which hold no state. A control is named by its label, its
 * 'aria-label', its title, its name or its id, the first of them it has -- the
 * name somebody reading the panel would use.
 */
export function controlValues(pane: HTMLElement): Record<string, string | boolean> {
    const values: Record<string, string | boolean> = {};
    const fields = pane.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
        'input, select, textarea',
    );
    for (const field of Array.from(fields)) {
        if (field.closest('[role="tree"]') !== null || field.closest('.tree') !== null) {
            continue;
        }
        if (field instanceof HTMLInputElement && ['button', 'submit', 'reset', 'hidden'].includes(field.type)) {
            continue;
        }
        const name = controlName(field);
        if (name === undefined) {
            continue;
        }
        const value =
            field instanceof HTMLInputElement && (field.type === 'checkbox' || field.type === 'radio')
                ? field.checked
                : field.value;
        // Two controls of one name: the second is told apart rather than lost.
        let key = name;
        for (let n = 2; key in values; n++) {
            key = `${name} (${n})`;
        }
        values[key] = value;
    }
    return values;
}

function controlName(field: HTMLElement): string | undefined {
    const labelled = field.id ? field.ownerDocument.querySelector(`label[for="${CSS.escape(field.id)}"]`) : null;
    const label = labelled ?? field.closest('label');
    let text: string | undefined;
    if (label !== null) {
        // The label's own words: a control inside its label would otherwise add
        // its text to its name -- a <select> its every option.
        const words = label.cloneNode(true) as HTMLElement;
        words.querySelectorAll('input, select, textarea').forEach((inner) => inner.remove());
        text = words.textContent?.trim();
    }
    return (
        text || field.getAttribute('aria-label') || field.title || field.getAttribute('name') || field.id || undefined
    );
}
