//
// PartCAD, 2026
//
// Licensed under Apache License, Version 2.0.
//
// The "Bill of Materials" tab.
//
// The line items are the daemon's, not this file's: 'bom' answers with exactly
// what 'pc bom' prints, which is 'Assembly.get_bom_detailed_async()' - the whole
// tree flattened and counted, with the store data that says what to order. The
// columns are the ones '_bom_output()' prints for the same reason it prints
// them: buying an item needs the vendor and the SKU, not the name PartCAD knows
// it by.
//

import { el, empty, placeholder } from './dom';
import { BomData, BomItem } from './messages';

/** Draw a bill of materials into 'root'. */
export function renderBom(root: HTMLElement, data: BomData): void {
    empty(root);
    root.classList.add('sheet');

    root.appendChild(el('h1', undefined, 'Bill of Materials'));
    root.appendChild(el('p', 'subtitle', data.assembly));

    if (data.items.length === 0) {
        root.appendChild(placeholder('This assembly has nothing in it.'));
        return;
    }

    const table = el('table', 'grid');
    const head = el('tr');
    for (const [column, className] of [
        ['Item', ''],
        ['Count', 'numeric'],
        ['Order as', ''],
        ['Description', ''],
    ] as [string, string][]) {
        head.appendChild(el('th', className, column));
    }
    table.appendChild(el('thead')).appendChild(head);

    const body = el('tbody');
    for (const item of data.items) {
        body.appendChild(renderRow(item));
    }
    table.appendChild(body);
    root.appendChild(table);

    root.appendChild(el('p', 'total', `Total: ${data.total}`));
}

function renderRow(item: BomItem): HTMLElement {
    const row = el('tr');

    const name = el('td');
    name.appendChild(el('span', 'name', item.name));
    if (item.kind) {
        name.appendChild(el('span', 'badge', item.kind));
    }
    row.appendChild(name);

    row.appendChild(el('td', 'numeric', String(item.count)));
    row.appendChild(el('td', undefined, orderAs(item)));
    row.appendChild(el('td', undefined, item.desc ?? ''));
    return row;
}

/** What to order, for the items that say: the vendor and the SKU, together. */
export function orderAs(item: { vendor?: string | null; sku?: string | null }): string {
    return item.vendor && item.sku ? `${item.vendor} ${item.sku}` : '';
}
