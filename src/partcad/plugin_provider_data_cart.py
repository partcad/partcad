#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import copy

from . import logging as pc_logging
from . import telemetry
from .utils import resolve_resource_path


def resolve_cart_item(item_spec: str):
    if "#" in item_spec:
        components = item_spec.split("#")
        name = components[0]
        assert len(components) == 2
        assert components[1].isdigit()
        count = int(components[1])
        assert count > 0
    else:
        # Without the count or parameters
        name = item_spec
        count = 1

    return name, count


def _declared_parameter(object, name: str):
    """The default of the parameter 'name' the object declares, or None: what 'get_mcft' reads of a bought part."""
    parameters = (getattr(object, "config", None) or {}).get("parameters") or {}
    parameter = parameters.get(name)
    return parameter.get("default") if isinstance(parameter, dict) else None


def resolve_cart_object(ctx, name: str):
    """Resolve the name of a cart item to the object it refers to.

    A cart item is a part most of the time, but it is an assembly whenever one
    is supplied assembled. The name alone does not say which, and it is all that
    survives a cart item being persisted, so every kind that can be one is
    looked up here. A scene is among them because what it holds is procured
    like anything else: a scene is never itself something to order -- nobody
    sells an arrangement -- so it only ever appears as the objects in it, but
    the cart is filled from its name.
    """
    project_name, object_name = resolve_resource_path(ctx.current_project_path, name)
    prj = ctx.get_project(project_name)
    if prj is None:
        pc_logging.error(f"Package '{project_name}' not found")
        return None

    object = prj.get_part(object_name, quiet=True)
    if object is None:
        object = prj.get_assembly(object_name, quiet=True)
    if object is None:
        object = prj.get_scene(object_name)
    return object


class ProviderCartItem:
    """
    Describes a single object in a cart: a part, or an assembly that is
    supplied assembled.
    It must be serializable for persistence.
    It must be deterministic: it must not be possible
    to imply a different CAD model after deserialization,
    even if the part definition has changed since it was serialized.
    """

    name: str
    count: int
    material: str = None
    color: str = None
    finish: str = None
    # TODO(clairbee): add tolerance

    format: str = None
    binary: bytes = None

    vendor: str = None
    sku: str = None
    count_per_sku: int = 1
    item_in_sku: str = None

    # The suppliers named by the package of the assembly this item is procured
    # for, as '{provider: extra config}' the way 'Project.get_suppliers()'
    # returns them. Empty for an object put in the cart on its own. They are
    # asked ahead of the ones the item's own package names (see
    # 'Context.find_part_suppliers()'): whoever built the assembly chose where
    # its parts are bought, and the package the parts come from may never have
    # heard of that store. Not part of what a provider is handed.
    suppliers: dict

    # Whether a quote may go without this item when nobody supplies it: what a
    # scene holds always may - a scene is an arrangement, and its walls, its
    # floor and whatever else nobody sells are no reason to price none of the
    # rest - and what anything else holds may when the cart was made with
    # 'ignore_missing'. Not part of what a provider is handed.
    optional: bool = False

    # Every way the item can be ordered, as 'procurement.alternatives' lists
    # them: its own record, if it has one, then each loaded alias of it that
    # names a vendor and an SKU. The vendor, the SKU and the pack size above
    # are the one of these the item is ordered by: its own, or for a part that
    # has none the alias that suits its count ('settle'), or whichever one the
    # supplier it goes to sells ('use_offer'). Not part of what a provider is
    # handed.
    offers: list
    # Whether the first of 'offers' is the item's own record.
    has_own: bool = False
    # The alias the item is ordered as, whose package's suppliers are asked for
    # it too (see 'Context.find_part_suppliers'); None when it is its own.
    via: str = None
    # Which offer each supplier that has the item has it as, by provider name
    # (see 'Context.find_part_suppliers'), and what it asked for it where it was
    # priced to choose ('--cheapest').
    offer_by_provider: dict
    price_by_provider: dict
    # Set once a supplier's offer is chosen ('use_offer'): a count that changes
    # afterwards does not choose again.
    pinned: bool = False

    def __init__(self):
        self.name = "none"
        self.count = 0
        self.format = "none"
        self.suppliers = {}
        self.optional = False
        self.offers = []
        self.offer_by_provider = {}
        self.price_by_provider = {}

    def _set_store_data(self, object, ctx=None):
        store_data = object.get_store_data()
        self.has_own = bool(getattr(store_data, "is_purchasable", False))
        self._set_record(store_data)
        self.refresh_offers(ctx, object)
        self.settle()

    def refresh_offers(self, ctx, object=None):
        """Ask again what the item can be ordered as: a store's package loaded since adds its aliases.

        Only a part can have aliases that sell it, and only a context knows
        which are loaded; anything else keeps its own record alone.
        """
        if ctx is None:
            return
        from . import procurement

        if object is None:
            object = resolve_cart_object(ctx, self.name)
        if object is None or not hasattr(object, "project_name"):
            return
        try:
            self.offers = procurement.alternatives(object, ctx)
        except AttributeError:
            # A stand-in for a shape, with a record and nothing else to ask.
            self.offers = []

    def _set_record(self, store_data):
        self.vendor = store_data.vendor
        self.sku = store_data.sku
        self.count_per_sku = store_data.count_per_sku
        self.item_in_sku = getattr(store_data, "item_in_sku", None)

    def settle(self):
        """Order this item by the offer that suits its count, where it is bought through an alias.

        One part on cut tape and on a reel is two aliases of it, one SKU each
        (see 'procurement.choose'): which of them a cart orders is a question
        of how many it holds, so it is asked again each time that changes. A
        part with a record of its own is ordered by it, and an item a supplier
        has chosen the offer of stays with that offer.
        """
        offers = getattr(self, "offers", None)
        if not offers or getattr(self, "has_own", False) or getattr(self, "pinned", False):
            return
        from . import procurement

        chosen = procurement.choose(offers, self.count)
        if chosen is not None:
            self._set_record(chosen[1])
            self.via = chosen[0]

    def candidates(self) -> list:
        """The offers to put to a supplier, in the order it is asked about them.

        The item's own record first, where it has one, and then its aliases, the
        one that suits the count best first; a manufacturer, which makes the
        part rather than selling a SKU, is asked about the item as it is.
        """
        from . import procurement

        offers = list(getattr(self, "offers", None) or [])
        if getattr(self, "has_own", False) and offers:
            return offers[:1] + procurement.by_count(offers[1:], self.count)
        return procurement.by_count(offers, self.count)

    def use_offer(self, name: str) -> bool:
        """Order the item by the offer called 'name', and keep to it; False when it has none of that name."""
        for offer_name, record in getattr(self, "offers", None) or []:
            if offer_name == name:
                self._set_record(record)
                self.via = None if offer_name == self.name else offer_name
                self.pinned = True
                return True
        return False

    def use_offer_of(self, provider_name: str) -> None:
        """Order the item by what 'provider_name' was found to have it as, if it was asked."""
        chosen = (getattr(self, "offer_by_provider", None) or {}).get(provider_name)
        if chosen:
            self.use_offer(chosen)

    def set_shape(self, shape, count: int = 1, ctx=None):
        """Populate the item from a shape object the caller already holds.

        'set_spec()' resolves a part by name through the context; this is for the
        callers that have the object at hand, including the assemblies that the
        context's part lookup would never find. Only the store data is filled in:
        an assembly has no material, color or finish of its own.
        """
        self.name = "%s:%s" % (shape.project_name, shape.name)
        self.count = count
        self._set_store_data(shape, ctx)

    async def set_spec(self, ctx, spec: str):
        self.name, self.count = resolve_cart_item(spec)

        object = resolve_cart_object(ctx, self.name)
        if object is None:
            # Raised rather than asserted: a stock reference that resolves to
            # nothing reaches here from a bill of materials, and an assertion
            # is neither a message for a user nor there at all under '-O'.
            raise ValueError(f"Part or assembly '{self.name}' not found")
        self._set_store_data(object, ctx)

        if self.offers and not self.has_own:
            # Bought, as a store's SKU, through an alias of it: what it is made
            # of is the store's to say, as it is for a part that names its own
            # SKU, so only what it declares is passed on and nothing is warned
            # about (see 'ShapeConfiguration.get_mcft').
            self.material = _declared_parameter(object, "material")
            self.color = _declared_parameter(object, "color")
            self.finish = _declared_parameter(object, "finish")
            return
        self.material = await object.get_mcft("material")
        self.color = await object.get_mcft("color")
        self.finish = await object.get_mcft("finish")

    def compose(self):
        result = {
            "name": self.name,
            "count": self.count,
            "material": self.material,
            "color": self.color,
            "finish": self.finish,
            "format": self.format,
        }
        if self.binary:
            result["binary"] = self.binary
        if self.vendor and self.sku:
            result["vendor"] = self.vendor
            result["sku"] = self.sku
            result["count_per_sku"] = self.count_per_sku
            if getattr(self, "item_in_sku", None):
                result["item_in_sku"] = self.item_in_sku
        return result

    def add_binary(self, format: str, binary: bytes):
        self.format = format
        self.binary = binary

    def __repr__(self):
        result = self.name + "#"
        result += str(self.count)
        return result


@telemetry.instrument(exclude=["__repr__"])
class ProviderCart:
    """Describes a cart of parts and of assemblies supplied assembled"""

    # TODO(clairbee): add a lock

    parts: dict[str, ProviderCartItem]
    qos: str = None
    # Whether an item nobody supplies is left out of a quote rather than failing
    # it, for what is not in a scene too: '--ignore-missing'. See
    # 'ProviderCartItem.optional'.
    ignore_missing: bool = False
    # Whether an item that can be ordered more than one way - its own SKU and
    # the packs or stores its aliases name - is priced each way at each
    # supplier and ordered the cheapest, rather than the first way a supplier
    # has it: '--cheapest'. See 'Context.find_part_suppliers'.
    cheapest: bool = False

    def __init__(self, qos: str = None, ignore_missing: bool = False, cheapest: bool = False):
        self.parts = {}
        self.qos = qos
        self.ignore_missing = bool(ignore_missing)
        self.cheapest = bool(cheapest)

    async def add_objects(self, ctx, objects: list[str], recursive: bool = False):
        """Add parts or assemblies"""
        for object in objects:
            await self.add_object(ctx, object, recursive=recursive)

    async def add_object(self, ctx, object: str, recursive: bool = False):
        """Add a part, an assembly or a scene.

        An assembly the model declares as supplied assembled (see
        'Assembly.is_declared_purchasable()') is added as a single item, the way
        it is ordered. Any other assembly is broken down into what it is made
        of, and the same question is asked about each sub-assembly in turn.

        Only the declaration decides that: no supplier is queried while the cart
        is filled, so an assembly that is declared orderable but that nobody has
        available still enters the cart as one item. Availability is what the
        providers answer afterwards, when the finished cart is put to them.

        A scene is broken down the same way an assembly is, and always: it is
        an arrangement of objects rather than a thing to order, so there is
        never an item to add for the scene itself. What is in it is procured
        exactly as an assembly's contents are.

        Every item an assembly or a scene is broken down into carries the
        suppliers of the package it is declared in (see
        'ProviderCartItem.suppliers'), however deep in it the item was: the
        package that is asked to be procured is the one whose choice of store
        applies to all of it.

        Pass 'recursive=True' to break every assembly down to its parts,
        including the ones that could have been ordered assembled.

        What a scene holds is optional (see 'ProviderCartItem.optional'): a
        quote goes without what nobody supplies. What anything else holds is
        optional only in a cart made with 'ignore_missing'.
        """
        name, count = resolve_cart_item(object)
        project_name, object_name = resolve_resource_path(
            ctx.current_project_path,
            name,
        )
        name = project_name + ":" + object_name
        prj = ctx.get_project(project_name)

        part = await prj.get_part_async(object_name, quiet=True)
        if part:
            # A part that is made is procured as what it is made from, and one
            # made from nothing it names needs nothing procured at all (see
            # 'partcad.procurement'). A bought part is procured as itself.
            from . import procurement

            for procured in await procurement.procured_as(ctx, part):
                if procured != name and resolve_cart_object(ctx, procured) is None:
                    # What 'procured_as' keeps a missing stock as, so that it
                    # is said here, against the part that names it.
                    raise ValueError(f"'{procured}', which '{name}' is made from, is not found")
                pc_logging.debug(f"Adding '{procured}' to the cart for part '{object_name}'")
                item = ProviderCartItem()
                await item.set_spec(ctx, procured)
                item.optional = self.ignore_missing
                self.add_item(item, count)
        else:
            # Quietly, both of them: a name that is one is not the other, and
            # the failure worth reporting is the one at the end.
            assembly = prj.get_assembly(object_name, quiet=True)
            scene = prj.get_scene(object_name, quiet=True) if assembly is None else None
            holder = assembly or scene
            if holder:
                # The shortcut is an assembly's alone. 'Scene' inherits
                # 'is_declared_purchasable()', which answers from 'vendor' and
                # 'sku' in the configuration -- but nobody sells an
                # arrangement, so a scene is expanded whatever it carries.
                if assembly is not None and not recursive and assembly.is_declared_purchasable():
                    pc_logging.debug(f"Adding assembly '{object_name}' to the cart as is")
                    item = ProviderCartItem()
                    await item.set_spec(ctx, name)
                    item.optional = self.ignore_missing
                    self.add_item(item, count)
                    return

                pc_logging.debug(f"Adding the contents of assembly '{object_name}' to the cart")
                # The stores this package buys from publish what they sell as
                # aliases, which count once their packages are loaded - before
                # the bill of materials, since being bought through one decides
                # whether a part is procured as itself or as its stock.
                from . import procurement

                suppliers = await prj.get_suppliers_async()
                procurement.load_suppliers(ctx, suppliers)
                if recursive:
                    bom = await _procured(ctx, await holder.get_bom())
                else:
                    bom = await holder.get_supply_bom(ctx)
                optional = scene is not None or self.ignore_missing
                tasks = []
                for item_name, item_count in bom.items():
                    pc_logging.debug(f"Adding '{item_name}' to the cart")
                    item_spec = item_name + "#" + str(item_count)
                    tasks.append(
                        asyncio.create_task(self.add_item_from_spec(ctx, item_spec, count, suppliers, optional))
                    )
                await asyncio.gather(*tasks)
            else:
                # TODO(clairbee): turn it into an error() and recover nicely
                raise Exception(f"Part, assembly or scene '{object_name}' not found in project '{project_name}'")

    async def add_item_from_spec(self, ctx, part_spec: str, count=1, suppliers: dict = None, optional=False):
        part_item = ProviderCartItem()
        await part_item.set_spec(ctx, part_spec)
        part_item.suppliers = dict(suppliers or {})
        part_item.optional = bool(optional)
        self.add_item(part_item, count)

    async def add_part_specs(self, ctx, part_specs: list[str]):
        """Add parts"""
        for part_spec in part_specs:
            await self.add_part_spec(ctx, part_spec)

    async def add_part_spec(self, ctx, part_spec: str):
        """Add a part"""
        item = ProviderCartItem()
        await item.set_spec(ctx, part_spec)
        return self._add_item(item)

    def add_item(self, item: ProviderCartItem, count=1):
        """Copy the cart item into this cart in a way that the original cart is not affected"""
        new_item = copy.deepcopy(item)
        self._add_item(new_item, count)
        return new_item

    def _add_item(self, item: ProviderCartItem, count=1):
        """Add item without 'copy.deepcopy()'"""
        assert item.count > 0
        item.count *= count
        if item.name in self.parts:
            existing = self.parts[item.name]
            existing.count += item.count
            existing.settle()
            # Optional only while everything that asked for it may go without
            # it: the same chair in a scene and in an assembly is the
            # assembly's to fail over.
            existing.optional = bool(getattr(existing, "optional", False) and getattr(item, "optional", False))
            # The same part reached through assemblies of two packages can be
            # bought where either of them says; the first to name a store keeps
            # its place, and what it said about it.
            for supplier, extra in item.suppliers.items():
                existing.suppliers.setdefault(supplier, extra)
        else:
            item.settle()
            self.parts[item.name] = item
        return item

    def compose(self):
        """The cart, as a provider is handed it.

        'parts' is one entry per object. 'skus' is what to order: a list with
        one entry per (vendor, SKU), with the number of that SKU to buy (see
        'skus_to_order()'). A list rather than a mapping, because a vendor and
        a SKU are free text and no key made of the two is safe from colliding
        with another pair. The two differ where one SKU is a set of several
        kinds of objects, and a store should order from 'skus' -- ordering
        each of 'parts' on its own buys a set once for every kind in it.
        """
        from .shape_config_store import skus_to_order

        req = {"parts": {}, "qos": self.qos}

        for name, part in self.parts.items():
            req["parts"][name] = part.compose()

        skus = skus_to_order(
            (
                getattr(part, "vendor", None),
                getattr(part, "sku", None),
                getattr(part, "item_in_sku", None),
                getattr(part, "count_per_sku", 1),
                part.count,
            )
            for part in self.parts.values()
        )
        req["skus"] = []
        for (vendor, sku), order in sorted(skus.items()):
            req["skus"].append(
                {
                    "vendor": vendor,
                    "sku": sku,
                    "count": order["count"],
                    "parts": sorted(
                        name
                        for name, part in self.parts.items()
                        if getattr(part, "vendor", None) == vendor and getattr(part, "sku", None) == sku
                    ),
                }
            )

        return req

    def __repr__(self):
        return str(self.compose())


async def _procured(ctx, bom: dict) -> dict:
    """A bill of materials of parts, as what each of them is procured as.

    A module function rather than a method: '@telemetry.instrument()' wraps
    the callables a class holds, and a static one comes back expecting 'self'.
    """
    from . import procurement

    procured = {}
    for name, count in bom.items():
        part = await procurement.get_part_async(ctx, name)
        names = [name] if part is None else await procurement.procured_as(ctx, part)
        for one in names:
            procured[one] = procured.get(one, 0) + count
    return procured
