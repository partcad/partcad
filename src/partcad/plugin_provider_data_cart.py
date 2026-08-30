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
from .utils import resolve_resource_path
from . import telemetry


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


def resolve_cart_object(ctx, name: str):
    """Resolve the name of a cart item to the object it refers to.

    A cart item is a part most of the time, but it is an assembly whenever one
    is supplied assembled. The name alone does not say which, and it is all that
    survives a cart item being persisted, so both are looked up here.
    """
    project_name, object_name = resolve_resource_path(ctx.current_project_path, name)
    prj = ctx.get_project(project_name)
    if prj is None:
        pc_logging.error(f"Package '{project_name}' not found")
        return None

    object = prj.get_part(object_name, quiet=True)
    if object is None:
        object = prj.get_assembly(object_name)
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
    # TODO(clairbee): add texture
    # TODO(clairbee): add tolerance

    format: str = None
    binary: bytes = None

    def __init__(self):
        self.name = "none"
        self.count = 0
        self.format = "none"

    def _set_store_data(self, object):
        store_data = object.get_store_data()
        self.vendor = store_data.vendor
        self.sku = store_data.sku
        self.count_per_sku = store_data.count_per_sku

    def set_shape(self, shape, count: int = 1):
        """Populate the item from a shape object the caller already holds.

        'set_spec()' resolves a part by name through the context; this is for the
        callers that have the object at hand, including the assemblies that the
        context's part lookup would never find. Only the store data is filled in:
        an assembly has no material, color or finish of its own.
        """
        self.name = "%s:%s" % (shape.project_name, shape.name)
        self.count = count
        self._set_store_data(shape)

    async def set_spec(self, ctx, spec: str):
        self.name, self.count = resolve_cart_item(spec)

        object = resolve_cart_object(ctx, self.name)
        assert object is not None, f"Part or assembly '{self.name}' not found"
        self._set_store_data(object)

        self.material = await object.get_mcftt("material")
        self.color = await object.get_mcftt("color")
        self.finish = await object.get_mcftt("finish")

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

    def __init__(self, qos: str = None):
        self.parts = {}
        self.qos = qos

    async def add_objects(self, ctx, objects: list[str], recursive: bool = False):
        """Add parts or assemblies"""
        for object in objects:
            await self.add_object(ctx, object, recursive=recursive)

    async def add_object(self, ctx, object: str, recursive: bool = False):
        """Add a part or an assembly.

        An assembly the model declares as supplied assembled (see
        'Assembly.is_declared_purchasable()') is added as a single item, the way
        it is ordered. Any other assembly is broken down into what it is made
        of, and the same question is asked about each sub-assembly in turn.

        Only the declaration decides that: no supplier is queried while the cart
        is filled, so an assembly that is declared orderable but that nobody has
        available still enters the cart as one item. Availability is what the
        providers answer afterwards, when the finished cart is put to them.

        Pass 'recursive=True' to break every assembly down to its parts,
        including the ones that could have been ordered assembled.
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
            pc_logging.debug(f"Adding part '{object_name}' to the cart")
            item = ProviderCartItem()
            await item.set_spec(ctx, name)
            self.add_item(item, count)
        else:
            assembly = prj.get_assembly(object_name)
            if assembly:
                if not recursive and assembly.is_declared_purchasable():
                    pc_logging.debug(f"Adding assembly '{object_name}' to the cart as is")
                    item = ProviderCartItem()
                    await item.set_spec(ctx, name)
                    self.add_item(item, count)
                    return

                pc_logging.debug(f"Adding the contents of assembly '{object_name}' to the cart")
                bom = await (assembly.get_bom() if recursive else assembly.get_supply_bom())
                tasks = []
                for item_name, item_count in bom.items():
                    pc_logging.debug(f"Adding '{item_name}' to the cart")
                    item_spec = item_name + "#" + str(item_count)
                    tasks.append(asyncio.create_task(self.add_item_from_spec(ctx, item_spec, count)))
                await asyncio.gather(*tasks)
            else:
                # TODO(clairbee): turn it into an error() and recover nicely
                raise Exception(f"Part or assembly '{object_name}' not found in project '{project_name}'")

    async def add_item_from_spec(self, ctx, part_spec: str, count=1):
        part_item = ProviderCartItem()
        await part_item.set_spec(ctx, part_spec)
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
            self.parts[item.name].count += item.count
        else:
            self.parts[item.name] = item
        return item

    def compose(self):
        req = {"parts": {}, "qos": self.qos}

        for name, part in self.parts.items():
            req["parts"][name] = part.compose()

        return req

    def __repr__(self):
        return str(self.compose())
