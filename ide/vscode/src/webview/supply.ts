//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "Supply" tab: where to buy what is on screen, and for how much.
//
// The line items and their quotes are the daemon's ('supply', which fills a
// 'ProviderCart' exactly as 'pc supply quote' does and asks every supplier of
// each item on its own). Two views over that one answer:
//
//   * an assembly - or a scene, which is a placed arrangement of the same
//     things - is a list of things to order, so it opens on the list, and
//     clicking a line item zooms in on where that one can be bought;
//   * a part is a single thing to order, so there is no list to choose from and
//     it opens on the options themselves.
//

import { el, empty, link, placeholder } from './dom';
import { orderAs } from './bom';
import { SupplyData, SupplyItem, SupplyOption } from './messages';

export class SupplyView {
    private data: SupplyData | undefined;
    private listed = false;

    constructor(private readonly root: HTMLElement) {}

    /**
     * Show the supply information of the object now on screen.
     *
     * 'kind' is what the viewer was told it is showing: an assembly - or a
     * scene, which is an assembly of placed things - is a list of things to
     * order, anything else is one thing.
     */
    public render(data: SupplyData, kind: string | null): void {
        this.root.classList.add('sheet');
        this.data = data;
        this.listed = kind === 'assembly' || kind === 'scene';
        if (this.listed) {
            this.showList();
        } else {
            this.showItem(data.items[0]);
        }
    }

    private showList(): void {
        const data = this.data;
        if (data === undefined) {
            return;
        }
        empty(this.root);

        this.root.appendChild(el('h1', undefined, 'Supply'));
        this.root.appendChild(el('p', 'subtitle', data.object));

        if (data.items.length === 0) {
            this.root.appendChild(placeholder('There is nothing here to order.'));
            return;
        }

        const table = el('table', 'grid selectable');
        const head = el('tr');
        for (const [column, className] of [
            ['Item', ''],
            ['Count', 'numeric'],
            ['Order as', ''],
            ['Buy from', ''],
            ['Price', 'numeric'],
        ] as [string, string][]) {
            head.appendChild(el('th', className, column));
        }
        table.appendChild(el('thead')).appendChild(head);

        const body = el('tbody');
        for (const item of data.items) {
            body.appendChild(this.renderRow(item));
        }
        table.appendChild(body);
        this.root.appendChild(table);

        this.root.appendChild(this.renderTotals(data));
    }

    private renderRow(item: SupplyItem): HTMLElement {
        const best: SupplyOption | undefined = item.suppliers[0];
        const row = el('tr');
        // A row is a way in to the options for that item, so it behaves like the
        // button it is - for a pointer and for the keyboard alike.
        row.tabIndex = 0;
        row.setAttribute('role', 'button');
        row.title = 'Show where this can be bought';
        row.addEventListener('click', () => this.showItem(item));
        row.addEventListener('keydown', (event: KeyboardEvent) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                this.showItem(item);
            }
        });

        const name = el('td');
        name.appendChild(el('span', 'name', item.name));
        if (item.kind) {
            name.appendChild(el('span', 'badge', item.kind));
        }
        row.appendChild(name);

        row.appendChild(el('td', 'numeric', String(item.count)));
        row.appendChild(el('td', undefined, orderAs(item)));
        row.appendChild(el('td', undefined, best ? best.name : 'No supplier found'));
        row.appendChild(el('td', 'numeric', best ? formatPrice(best.price, best.currency) : ''));
        return row;
    }

    private renderTotals(data: SupplyData): HTMLElement {
        if (data.totals.length === 0) {
            return el('p', 'placeholder', 'No supplier quoted a price for any of these.');
        }
        // One line per currency: two suppliers quoting in different ones cannot
        // be added up, and PartCAD has no exchange rate to do it with.
        const totals = data.totals.map((total) => formatPrice(total.price, total.currency)).join(' + ');
        return el('p', 'total', `Cheapest of each: ${totals}`);
    }

    private showItem(item: SupplyItem | undefined): void {
        empty(this.root);
        if (item === undefined) {
            this.root.appendChild(placeholder('There is nothing here to order.'));
            return;
        }

        if (this.listed) {
            const back = el('button', 'back', '‹ All items');
            back.addEventListener('click', () => this.showList());
            this.root.appendChild(back);
        }

        this.root.appendChild(el('h1', undefined, item.name));
        if (item.desc) {
            this.root.appendChild(el('p', 'subtitle', item.desc));
        }

        const properties = el('dl', 'properties');
        addProperty(properties, 'Needed', String(item.count));
        if (item.kind) {
            addProperty(properties, 'Kind', item.kind);
        }
        if (item.vendor && item.sku) {
            addProperty(properties, 'Order as', orderAs(item));
        }
        if (item.count_per_sku && item.count_per_sku > 1) {
            addProperty(properties, 'Per package', String(item.count_per_sku));
        }
        this.root.appendChild(properties);

        this.root.appendChild(el('h2', undefined, 'Where to buy'));
        if (item.suppliers.length === 0) {
            this.root.appendChild(
                placeholder(
                    'No supplier of this package has it. Declare one under "suppliers:" in ' +
                        'partcad.yaml to see prices here.',
                ),
            );
            return;
        }
        for (const option of item.suppliers) {
            this.root.appendChild(renderOption(option, item));
        }
    }
}

/** One supplier's offer, as the card the "zoomed in" view lists. */
function renderOption(option: SupplyOption, item: SupplyItem): HTMLElement {
    const card = el('div', 'option');

    const header = el('div', 'option-header');
    header.appendChild(link(option.name, option.url, 'name'));
    if (option.price !== null && option.price !== undefined) {
        header.appendChild(el('span', 'price', formatPrice(option.price, option.currency)));
    }
    card.appendChild(header);

    if (option.desc) {
        card.appendChild(el('p', 'subtitle', option.desc));
    }

    if (option.error !== undefined) {
        // A supplier that has the item but would not quote for it. Worth showing
        // rather than hiding: the others still have prices, and the reason is
        // usually the answer (out of stock, below a minimum order).
        card.appendChild(el('p', 'placeholder', `No quote: ${option.error}`));
        return card;
    }

    const properties = el('dl', 'properties');
    addProperty(properties, 'For', `${item.count} × ${item.name}`);
    const eta = formatEta(option.etaMin, option.etaMax);
    if (eta) {
        addProperty(properties, 'Delivery', eta);
    }
    if (option.qos) {
        addProperty(properties, 'Service', option.qos);
    }
    if (option.cartId) {
        // What 'pc supply order' is given: the quote is what makes the price
        // real, and the cart id is the only handle on it.
        addProperty(properties, 'Cart', option.cartId);
    }
    const expires = formatTime(option.expire);
    if (expires) {
        addProperty(properties, 'Quote expires', expires);
    }
    if (properties.childElementCount > 0) {
        card.appendChild(properties);
    }
    return card;
}

function addProperty(list: HTMLElement, label: string, value: string): void {
    list.append(el('dt', undefined, label), el('dd', undefined, value));
}

/**
 * A price with its unit.
 *
 * A quote carries the price as a bare number; the currency comes from the
 * provider's configuration, and a provider that does not declare one leaves the
 * number to speak for itself rather than being labelled with a guess.
 */
export function formatPrice(price: number | null | undefined, currency: string | null | undefined): string {
    if (price === null || price === undefined) {
        return '';
    }
    if (currency && /^[A-Za-z]{3}$/.test(currency)) {
        try {
            return new Intl.NumberFormat(undefined, {
                style: 'currency',
                currency: currency.toUpperCase(),
            }).format(price);
        } catch {
            // Three letters that are not a currency code after all.
        }
    }
    return currency ? `${price.toFixed(2)} ${currency}` : price.toFixed(2);
}

/** A POSIX timestamp as a local date and time, or '' when there is none. */
export function formatTime(timestamp: number | null | undefined): string {
    if (typeof timestamp !== 'number' || !Number.isFinite(timestamp)) {
        return '';
    }
    // Seconds since the epoch: what a provider's quote carries (see
    // 'examples/provider_store'), where JavaScript counts milliseconds.
    return new Date(timestamp * 1000).toLocaleString();
}

function formatEta(min: number | null | undefined, max: number | null | undefined): string {
    const from = formatTime(min);
    const to = formatTime(max);
    if (from && to) {
        return from === to ? from : `${from} – ${to}`;
    }
    return from || to;
}
