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
STORE_PROPERTIES = frozenset({"vendor", "sku", "count_per_sku"})


class ShapeConfigStore:
    vendor: str | None
    sku: str | None
    count_per_sku: int

    def __init__(self, final_config):
        self.vendor = final_config.get("vendor", None)
        self.sku = final_config.get("sku", None)
        self.count_per_sku = final_config.get("count_per_sku", 1)

    @property
    def is_purchasable(self) -> bool:
        """Whether the object can be bought off the shelf.

        Both the vendor and the SKU are needed to order anything: the SKU alone
        does not say from whom, and the vendor alone does not say what.
        """
        return bool(self.vendor and self.sku)

    def __str__(self) -> str:
        return f"ShapeConfigStore(vendor={self.vendor}, sku={self.sku}, count_per_sku={self.count_per_sku})"


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
