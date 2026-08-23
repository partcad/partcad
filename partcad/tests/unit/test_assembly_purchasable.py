#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""What `Assembly.is_declared_purchasable()` answers, and what it does not.

It reads the model and asks no supplier anything, so it is answerable offline -
which is what lets a BoM walk use it. The market-side question, whether anybody
has one available today, belongs to `_is_available_to_buy()` and is not tested
here.
"""

import partcad as pc
from partcad.assembly import Assembly

# The same package the supply-BoM tests use:
#   '//sub:unit'  - a pair of cubes, sold assembled (vendor + sku)
#   '//sub:frame' - a pair of cubes nobody sells assembled
#   '//:top'      - the top level assembly, which nobody sells
SUPPLY_BOM_PACKAGE = "partcad/tests/unit/data/supply_bom/partcad.yaml"


def _assembly(spec: str) -> Assembly:
    return pc.Context(SUPPLY_BOM_PACKAGE)._get_assembly(spec)


def test_an_assembly_with_a_vendor_and_an_sku_is_declared_purchasable():
    assert _assembly("//sub:unit").is_declared_purchasable()


def test_an_assembly_with_neither_is_not():
    assert not _assembly("//sub:frame").is_declared_purchasable()
    assert not _assembly("//:top").is_declared_purchasable()


def test_half_a_declaration_is_not_a_declaration():
    """Ordering needs both: the SKU does not say from whom, the vendor not what."""
    assert not Assembly("//pkg", {"name": "a", "vendor": "acme"}).is_declared_purchasable()
    assert not Assembly("//pkg", {"name": "a", "sku": "U-1"}).is_declared_purchasable()
    assert not Assembly("//pkg", {"name": "a"}).is_declared_purchasable()


def test_an_embedded_assembly_is_never_declared_purchasable():
    """No name to order it by, whatever it declares.

    An assembly written into its parent's ASSY file is not an object of any
    package. `assembly_factory_assy.py` builds its config as a fixed dict that
    carries no 'vendor' and no 'sku', so in practice the store data is empty
    anyway and the 'child' guard never decides the answer on its own. The guard
    is what keeps that true if such a config ever did carry them, which is what
    this pins down - it is the one case where the two clauses disagree.
    """
    embedded = Assembly("//pkg", {"name": "a", "child": True, "vendor": "acme", "sku": "U-1"})
    assert not embedded.is_declared_purchasable()

    # Same declaration, not embedded: this is what the guard is suppressing.
    assert Assembly("//pkg", {"name": "a", "vendor": "acme", "sku": "U-1"}).is_declared_purchasable()
