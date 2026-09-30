#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a part is procured as: itself, bought, or the stock it is made from.

One rule, used by everything that asks "what do I have to get hold of to have
this part": the supply bill of materials, the cart `pc supply` fills, the
grouped and detailed bills of materials the documents are written from, and the
manufacturability test.

* A part with a `vendor` and an `sku` is **bought**, as itself.
* A part with manufacturing instructions and nothing to buy it by is **made**.
  Whoever builds the assembly is taken at their word that they can make it --
  PartCAD has the instructions and, until it learns otherwise, assumes the
  capabilities to follow them -- so what has to be procured for it is not the
  part but what it is made *from*: the `source:` of its `manufacturing:`
  section, which is procured by this same rule in turn (a blank cut from a
  sheet is procured as the sheet). A part made from nothing it names -- printed,
  formed -- needs nothing procured at all.
* A part that says neither is procured as itself, so that whatever is asked of
  it afterwards fails where it can be seen rather than being dropped here.

A part that can be both bought and made is procured as bought. Whether anybody
actually has it is the market's question, which the manufacturability test asks
and falls back from; a bill of materials is answered offline.

One piece of stock is counted per part made from it. Cutting several parts out
of one board is a question of layout, which PartCAD does not answer yet, so the
count is what buying for each part separately would take -- an upper bound, and
never short.
"""

from . import logging as pc_logging
from .part_config import PartConfiguration
from .utils import resolve_resource_path

# How many stock references are followed before giving up on a cycle -- a part
# whose stock is, eventually, itself.
MAX_STOCK_DEPTH = 16


def is_bought(part) -> bool:
    """Whether the part declares what to order it by."""
    return part.get_store_data().is_purchasable


def is_made(part) -> bool:
    """Whether the part carries manufacturing instructions."""
    return bool(PartConfiguration.get_manufacturing_data(part).method)


def stock_name(part) -> str | None:
    """The fully qualified name of what the part is made from, or None.

    Resolved against the package the part is declared in, like every other
    reference a part makes (see 'test.manufacturability_reference').
    """
    data = PartConfiguration.get_manufacturing_data(part)
    if not data.method or not data.source:
        return None
    project_name, object_name = resolve_resource_path(part.project_name, data.source)
    return "%s:%s" % (project_name, object_name)


async def get_part_async(ctx, name: str):
    """The part a fully qualified name refers to, or None, quietly."""
    project_name, _, object_name = name.partition(":")
    project = ctx.get_project(project_name)
    if project is None:
        return None
    return await project.get_part_async(object_name, quiet=True)


async def procured_as(ctx, part) -> list:
    """The fully qualified names one instance of 'part' is procured as.

    Usually one name, and never more than one per level: [the part] when it is
    bought or is neither bought nor made, [the stock, followed] when it is made
    from stock, and [] when it is made from nothing it names. A stock reference
    that resolves to nothing is kept as the name it was written as, so that the
    cart and the test say it is missing rather than the part being dropped.
    """
    name = "%s:%s" % (part.project_name, part.name)
    for _ in range(MAX_STOCK_DEPTH):
        if is_bought(part) or not is_made(part):
            return [name]
        stock = stock_name(part)
        if stock is None:
            return []
        resolved = await get_part_async(ctx, stock)
        if resolved is None:
            return [stock]
        part, name = resolved, "%s:%s" % (resolved.project_name, resolved.name)
    # A cycle. Reported and procured as the last name reached, so that the
    # bill of materials is short by nothing and the cart names what it could
    # not resolve.
    pc_logging.error("'%s' is made from stock that is, eventually, itself" % name)
    return [name]
