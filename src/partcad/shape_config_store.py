#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#

# What a declaration says about buying the object off the shelf, rather than
# about what it is or how it is made. Named as a set because a reference has to
# be able to restate the lot of them in one go (see 'resolve_store_properties').
STORE_PROPERTIES = frozenset({"vendor", "sku", "count_per_sku", "item_in_sku"})


class ShapeConfigStore:
    vendor: str | None
    sku: str | None
    count_per_sku: int
    # Which kind of item within the SKU this is, where the SKU is a set of
    # several kinds of things, or None where it is one kind (see 'sku_key').
    item_in_sku: str | None

    def __init__(self, final_config):
        self.vendor = final_config.get("vendor", None)
        self.sku = final_config.get("sku", None)
        self.count_per_sku = final_config.get("count_per_sku", 1)
        self.item_in_sku = final_config.get("item_in_sku", None)

    @property
    def is_purchasable(self) -> bool:
        """Whether the object can be bought off the shelf.

        Both the vendor and the SKU are needed to order anything: the SKU alone
        does not say from whom, and the vendor alone does not say what.
        """
        return bool(self.vendor and self.sku)

    def __str__(self) -> str:
        return (
            f"ShapeConfigStore(vendor={self.vendor}, sku={self.sku}, count_per_sku={self.count_per_sku}, "
            f"item_in_sku={self.item_in_sku})"
        )


def skus_to_order(items) -> dict:
    """How many of each SKU to order to get every one of 'items'.

    'items' are (vendor, sku, item_in_sku, count_per_sku, count) tuples, one per
    line of a cart. What comes back is keyed by (vendor, sku), with the number
    of that SKU to order and the kinds of items that number was worked out for.

    One SKU is one thing to order, but it is not always one kind of thing: a
    shaft is sold with the clip that goes on it, under one SKU, and the two are
    separate objects in a model -- used independently, assembled separately,
    taken apart and put back. Each of them names the SKU and says which item of
    it it is ('item_in_sku'). So the SKU has to be ordered as many times as the
    kind that needs the most of it, and not once for each kind: two shafts and
    two clips are two sets, where adding the lines up would buy four.

    Lines that say nothing of 'item_in_sku' are one kind with each other, which
    is what a SKU of one kind of thing is: two references to the same pack of
    nuts, ordered from two places in a model, add up.
    """
    per_kind = {}
    for vendor, sku, item_in_sku, count_per_sku, count in items:
        if not vendor or not sku:
            continue
        key = (vendor, sku)
        kinds = per_kind.setdefault(key, {})
        kind = kinds.setdefault(item_in_sku, [0, max(int(count_per_sku or 1), 1)])
        kind[0] += count
        # The same kind named twice with two pack sizes is a mistake in the
        # declarations; the smaller pack is the one that cannot be short.
        kind[1] = min(kind[1], max(int(count_per_sku or 1), 1))
    result = {}
    for key, kinds in per_kind.items():
        count = max((needed + per_sku - 1) // per_sku for needed, per_sku in kinds.values())
        result[key] = {"count": count, "items": sorted(kinds, key=lambda kind: (kind is not None, kind or ""))}
    return result


def resolve_store_properties(source_config: dict, declaration) -> dict:
    """'source_config' as a reference declaring 'declaration' reports it.

    A reference - an 'alias' or an 'enrich' - resolves to the declaration of the
    object it points at, and that is what it reports for everything about what
    the object *is*. What it is *bought* as is the one thing it may restate: one
    piece of geometry is sold by several vendors, in several pack sizes, and the
    documentation says to write each of those as an alias of the first (see
    'Procurement' in 'docs/source/configuration.rst'). The schema accepts
    'vendor', 'sku' and 'count_per_sku' on a reference for that reason, and
    until this existed it accepted them and threw them away.

    A reference that names a 'vendor' or an 'sku' names a different thing to
    order, so it replaces the source's record whole rather than half of it: the
    pack size written for the source's SKU says nothing about how this one is
    boxed, and an SKU inherited beside a vendor that does not sell it is a
    (vendor, SKU) pair nobody wrote. An absent 'count_per_sku' therefore reads
    as the default of 1, exactly as it would on a part declared outright.

    A reference that names neither is ordering the same thing, so the record
    stands and a 'count_per_sku' of its own is what it looks like: a correction
    to how many of that same SKU arrive in one.

    The source's own dictionary is handed back untouched where the reference
    states nothing of the three, which is nearly every reference: a copy per
    call would be a copy per 'get_final_config()', and there are a lot of those.
    A key written as nothing ('vendor:' with no value) states nothing either -
    the schema has no such value to offer, and reading one as "unsell what this
    points at" would leave half a record behind rather than no record.
    """
    if not isinstance(declaration, dict):
        return source_config
    declared = {name: declaration[name] for name in STORE_PROPERTIES if declaration.get(name) is not None}
    if not declared:
        return source_config

    if declaration.get("vendor") is not None or declaration.get("sku") is not None:
        resolved = {key: value for key, value in source_config.items() if key not in STORE_PROPERTIES}
    else:
        resolved = dict(source_config)
    resolved.update(declared)
    return resolved
