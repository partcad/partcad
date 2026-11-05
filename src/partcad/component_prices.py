#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What each component of an object costs: its share of what the object costs to buy.

A package declares no prices. What something costs is what a supplier answers
when asked, and PartCAD asks in one place: the quote the IDE's Buy tab shows
and 'pc supply quote' fills its cart for, one line item per thing to order,
each with every supplier that quoted it (see 'supply_quote' in the JSON-RPC
service). The callouts the IDE's 3D and 2D tabs and 'pc render
--with-component-prices' put on every component are that same answer, shared
out - so they add up to the Buy tab's total rather than to some other number.

* A line item's price is what its cheapest supplier quoted for the lot, and one
  of it is that divided by how many the lot is of. A box of a hundred bolts for
  an assembly of eight is a box: each bolt costs an eighth of it here, which is
  what the eight cost this assembly, whatever a bolt costs on its own.
* A line item that is one kind of item of a set sold under one SKU - a shaft and
  the clip it comes with - shares the set's price with the other kinds: each
  kind was quoted the price of the whole set (see 'skus_to_order'), and a shaft
  and its clip priced at a set each would cost the assembly two sets.
* A part is priced as what it is procured as ('partcad.procurement'): itself
  when it is bought, one piece of its stock when it is made from stock - so a
  bracket cut from a sheet costs a sheet's worth of the quote for sheets - and
  nothing when it is made from nothing anybody sells, which is not "free" but
  "no price", and is left without one.
* An assembly sold assembled is a line item of its own, and is priced as one.

A component nobody quoted - no supplier sells it, none answered, the package
names none - has no price, rather than a price of nought.

The quote goes out to the market, so this is only ever worked out when somebody
asks to see the prices; nothing else waits for it.
"""

from . import procurement


def _cheapest(item):
    """The cheapest option a supplier priced for one line item, or None."""
    priced = [option for option in item.get("suppliers") or [] if option.get("price") is not None]
    if not priced:
        return None
    return min(priced, key=lambda option: option["price"])


def unit_prices(items) -> dict:
    """What one of each line item of a quote costs, by its name.

    'items' are the line items 'supply_quote' answers with. Each comes back as
    '{"price": <number>, "currency": <code or None>}'; a line item no supplier
    priced is left out.
    """
    kinds = {}
    for item in items:
        if item.get("item_in_sku") and item.get("vendor") and item.get("sku"):
            kinds.setdefault((item["vendor"], item["sku"]), set()).add(item.get("name"))

    prices = {}
    for item in items:
        best = _cheapest(item)
        if best is None:
            continue
        share = float(best["price"]) / max(int(item.get("count") or 1), 1)
        if item.get("item_in_sku") and item.get("vendor") and item.get("sku"):
            share /= max(len(kinds.get((item["vendor"], item["sku"]), ())), 1)
        prices[item["name"]] = {"price": share, "currency": best.get("currency") or None}
    return prices


async def prices_async(ctx, names, items) -> dict:
    """What one of each of 'names' costs, by name, for those that have a price.

    'names' are the full names ('<package>:<name>') of the objects to price -
    the parts an object is made of, and anything else its tree holds - and
    'items' the line items of the quote for that object. A name that is a line
    item is priced as one; a part that is not is priced as what it is procured
    as, where every piece of that has a price in the same currency.
    """
    units = unit_prices(items)
    prices = {}
    for name in names:
        if name in units:
            prices[name] = units[name]
            continue
        part = await procurement.get_part_async(ctx, name)
        if part is None:
            continue
        procured = await procurement.procured_as(ctx, part)
        if not procured or any(one not in units for one in procured):
            continue
        currencies = {units[one]["currency"] for one in procured}
        if len(currencies) != 1:
            # Two currencies cannot be added up without a rate, and PartCAD has
            # none (see 'supply_totals').
            continue
        prices[name] = {"price": sum(units[one]["price"] for one in procured), "currency": currencies.pop()}
    # Every line item is a component of the object as well - an assembly sold
    # assembled most of all, which no part name above reaches.
    for name, unit in units.items():
        prices.setdefault(name, unit)
    return prices


async def component_names_async(shape) -> list:
    """The full names of the parts 'shape' is made of: itself when it is a part.

    What an assembly or a scene holds at every depth, as its bill of materials
    lists it - which is what every leaf of the tree it is rendered as is named
    by - and nothing built to find out.
    """
    if hasattr(shape, "get_bom"):
        return list((await shape.get_bom()).keys())
    return ["%s:%s" % (shape.project_name, shape.name)]
