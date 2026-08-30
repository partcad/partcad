//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The element helpers the panel's panes are built with.
//
// Every pane builds its DOM node by node rather than assigning 'innerHTML'.
// What it displays is text out of a package's configuration - a description, a
// part name, a supplier's answer - and none of it is escaped anywhere on the way
// here; 'textContent' cannot be talked into being markup, and no amount of
// review keeps a template literal from being.
//

/** A new element, with an optional class and text content. */
export function el<K extends keyof HTMLElementTagNameMap>(
    tag: K,
    className?: string,
    text?: string,
): HTMLElementTagNameMap[K] {
    const node = document.createElement(tag);
    if (className) {
        node.className = className;
    }
    if (text !== undefined) {
        node.textContent = text;
    }
    return node;
}

/** Empty an element, dropping everything under it. */
export function empty(node: HTMLElement): void {
    node.replaceChildren();
}

/**
 * A link, or plain text when the target is not one a webview can follow.
 *
 * VS Code opens 'http(s)' and 'mailto' links from a webview in the user's
 * browser. Everything else - the relative paths a generated document uses to
 * point at a file of the package tree - resolves against the webview's own
 * origin, where nothing exists, so it is shown as the text it is instead of as a
 * link that goes nowhere.
 */
export function link(text: string, url: string | null | undefined, className?: string): HTMLElement {
    if (!url || !/^(https?|mailto):/i.test(url)) {
        return el('span', className, text);
    }
    const anchor = el('a', className, text);
    anchor.href = url;
    return anchor;
}

/** A "nothing here" line, in the muted style the panes share. */
export function placeholder(text: string): HTMLElement {
    return el('p', 'placeholder', text);
}
