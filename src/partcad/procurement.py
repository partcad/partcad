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
* So is a part that says neither but that an alias says them for: an `alias` of
  the part, loaded in any package, that names a `vendor` and an `sku` of its own
  is a way to order it (see `offers`). One part sold in several pack sizes - a
  resistor on cut tape and on a reel of 5000 - is written that way, one alias
  per SKU with its own `count_per_sku`, and a catalogue that serves the part
  once and its packagings as aliases of it makes the part buyable without
  restating any of them on the part itself.
* A part with manufacturing instructions and nothing to buy it by is **made**.
  Whoever builds the assembly is taken at their word that they can make it --
  PartCAD has the instructions and, until it learns otherwise, assumes the
  capabilities to follow them -- so what has to be procured for it is not the
  part but what it is made *from*: the `source:` of its `manufacturing:`
  section, which is procured by this same rule in turn (a blank cut from a
  sheet is procured as the sheet). A part made from nothing it names -- printed,
  formed -- needs nothing procured at all. A printed part may name a `source:`
  too, and it is not stock: it is the *design* the print is a print of, and
  nothing of it goes into the printer but the material (see
  'part_config_manufacturing.ADDITIVE_REQUIRED').
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

import threading

from . import logging as pc_logging
from .part_config import PartConfiguration
from .part_config_manufacturing import METHOD_ADDITIVE
from .shape_config_store import STORE_PROPERTIES, ShapeConfigStore
from .utils import resolve_resource_path

# How many stock references are followed before giving up on a cycle -- a part
# whose stock is, eventually, itself.
MAX_STOCK_DEPTH = 16
# How far a chain of aliases is followed back to the part it ends at: an alias
# of an alias of a part is a way to order the part as much as an alias of it.
MAX_ALIAS_DEPTH = 16


def is_bought(part, ctx=None) -> bool:
    """Whether the part says what to order it by, or an alias of it does (see 'offers').

    Without a context only the part's own record is asked: the aliases are
    found among the packages a context has loaded.
    """
    return bool(offers(part, ctx))


def offers(part, ctx=None) -> list:
    """The ways to order one 'part', as '(name, ShapeConfigStore)' pairs, fewest items per SKU first.

    The part's own record when it has one, and nothing else: what a part says
    it is bought as is what it is bought as. Otherwise every alias of it that
    is loaded and names a vendor and an SKU of its own (see 'alias_offers'),
    each with its own pack size; [] when there is none, and the part is not
    bought.
    """
    name = "%s:%s" % (part.project_name, part.name)
    own = part.get_store_data()
    if own.is_purchasable:
        return [(name, own)]
    if ctx is None or not hasattr(ctx, "projects"):
        return []
    return alias_offers(ctx, name)


def alternatives(part, ctx=None) -> list:
    """Every way to order 'part' a supplier may take: its own record, if it has one, then each loaded alias of it.

    What 'offers' answers is what the part is bought as when nobody has been
    asked yet, and a part that names its own SKU is bought by it. A supplier
    may not sell that SKU, though: a part Home Depot's package declares is
    still a part Lowe's sells, under an alias of it with Lowe's SKU. So which
    of these a supplier is handed is the supplier's question, asked of each in
    turn (see 'Context.find_part_suppliers'). The aliases come fewest spare
    items first for one of the part; a cart orders them again for its count.
    """
    name = "%s:%s" % (part.project_name, part.name)
    own = part.get_store_data()
    found = [(name, own)] if own.is_purchasable else []
    if ctx is not None and hasattr(ctx, "projects"):
        found += [offer for offer in alias_offers(ctx, name) if offer[0] != name]
    return found


def by_count(offers_: list, count=1) -> list:
    """'offers_' in the order 'choose' prefers them for 'count' of the part: fewest spare items, then fewest SKUs."""
    count = max(int(count or 1), 1)

    def cost(offer):
        per = max(int(offer[1].count_per_sku or 1), 1)
        skus = -(-count // per)
        return (skus * per - count, skus, offer[0])

    return sorted(offers_, key=cost)


def load_suppliers(ctx, suppliers) -> None:
    """Load the packages of 'suppliers', '{provider: extra}' as 'Project.get_suppliers' gives them.

    A store's package is where the aliases are that say what it sells, and an
    alias counts once its package is loaded (see 'alias_offers'). So the stores
    a package names as its suppliers are loaded before what it is made of is
    procured: a desk that lists Home Depot and Lowe's is bought from either, by
    the aliases each of them publishes of the lumber it is cut from.
    """
    for supplier in suppliers or ():
        package_name, _ = resolve_resource_path(getattr(ctx, "current_project_path", "//"), supplier)
        if package_name and package_name not in ctx.projects:
            try:
                ctx.get_project(package_name)
            except Exception as e:  # pylint: disable=broad-except
                pc_logging.debug("The supplier package '%s' did not load: %s" % (package_name, e))


def choose(offers_: list, count=1):
    """Which of 'offers_' to order 'count' of the part by, or None when there are none.

    The one that buys the fewest items beyond 'count', and of those the one
    that takes the fewest SKUs: ten resistors are bought off cut tape, five
    thousand as the reel, and 120 screws as five bags of 25 rather than two of
    100. Offline, like the rest of a bill of materials - which pack is cheaper
    is the store's answer, and a quote asks it of whatever this chose.
    """
    if not offers_:
        return None
    return by_count(offers_, count)[0]


def store_record(part, ctx=None, count=1) -> ShapeConfigStore:
    """What 'count' of 'part' are ordered by: the record of the offer 'choose' picks, or the part's own."""
    chosen = choose(offers(part, ctx), count)
    return chosen[1] if chosen is not None else part.get_store_data()


def alias_offers(ctx, target: str) -> list:
    """The aliases of 'target' loaded so far that name a vendor and an SKU, as 'offers' lists them.

    "Loaded": declared in a package the context has loaded, or served by a
    repository plugin and asked for already (see
    'Project.known_object_configs'). Nothing is fetched to answer - listing a
    catalogue of a hundred thousand parts to find out whether one of them
    points here is not something a bill of materials can afford - so a
    catalogue's alias counts once something has asked for it: a search, a
    listing, an assembly that uses it.

    Followed through chains of aliases: an alias of an alias of 'target' orders
    the geometry of 'target' as much as an alias of it does.
    """
    return list(_alias_index(ctx).get(target, ()))


_INDEX_LOCK = threading.Lock()


def _alias_index(ctx) -> dict:
    """'{target: offers}' over every alias the context has loaded, rebuilt when that changes.

    Kept on the context with the count it was built from, one per package (see
    'Project.known_object_count'), which is what loading another package or
    another declaration changes: asked once per line of a bill of materials, a
    scan of every declaration in every package would otherwise be repeated for
    each of them.
    """
    projects = list(ctx.projects.values())
    signature = tuple((id(project), project.known_object_count("part")) for project in projects)
    with _INDEX_LOCK:
        cached = getattr(ctx, "_purchase_alias_index", None)
        if cached is not None and cached[0] == signature:
            return cached[1]
    sources = {}
    records = {}
    for project in projects:
        for name, config in project.known_object_configs("part"):
            if not isinstance(config, dict) or config.get("type") != "alias":
                continue
            source = _alias_source(ctx, project, name, config)
            if source is None:
                continue
            qualified = "%s:%s" % (project.name, name)
            sources[qualified] = source
            if config.get("vendor") and config.get("sku"):
                records[qualified] = ShapeConfigStore(
                    {key: config[key] for key in STORE_PROPERTIES if config.get(key) is not None}
                )
    index = {}
    for qualified, record in records.items():
        target, seen = sources[qualified], {qualified}
        for _ in range(MAX_ALIAS_DEPTH):
            if target is None or target in seen:
                break
            index.setdefault(target, []).append((qualified, record))
            seen.add(target)
            target = sources.get(target)
    for found in index.values():
        found.sort(key=lambda offer: (max(int(offer[1].count_per_sku or 1), 1), offer[0]))
    with _INDEX_LOCK:
        ctx._purchase_alias_index = (signature, index)
    return index


def _alias_source(ctx, project, name: str, config: dict):
    """The '<package>:<part>' an alias declaration points at, as its factory resolves it; or None."""
    resolved = config.get("source_resolved")
    if resolved:
        return resolved
    from . import cmf, reference
    from .utils import format_parameterized_name

    try:
        declaration = config if "name" in config else dict(config, name=name)
        source = reference.source_of(project, project.name, declaration, "part")
        if config.get("with"):
            package_name, object_name = reference.split(source)
            parameters = cmf.canonical_parameters(ctx, config["with"], project.name)
            source = package_name + ":" + format_parameterized_name(object_name, parameters)
    except Exception as e:
        pc_logging.debug("Not following the alias '%s:%s': %s" % (project.name, name, e))
        return None
    return source


def is_made(part) -> bool:
    """Whether the part carries manufacturing instructions."""
    return bool(PartConfiguration.get_manufacturing_data(part).method)


def stock_name(part) -> str | None:
    """The fully qualified name of what the part is made from, or None.

    Resolved against the package the part is declared in, like every other
    reference a part makes (see 'test.manufacturability_reference').

    None for a printed part whatever it names: its `source:` is its design, and
    a design is not something anybody orders to print it.
    """
    data = PartConfiguration.get_manufacturing_data(part)
    if not data.method or not data.source or data.method == METHOD_ADDITIVE:
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
        if is_bought(part, ctx) or not is_made(part):
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
