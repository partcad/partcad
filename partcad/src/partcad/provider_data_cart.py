#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import copy

from . import logging as pc_logging
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


class ProviderCartItem:
    """
    Describes a single part in a cart.
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

    vendor: str = None
    sku: str = None
    count_per_sku: int = None

    format: str = None
    binary: bytes = None

    def __init__(self):
        self.name = "none"
        self.count = 0
        self.format = "none"

    async def set_spec(self, ctx, spec: str):
        self.name, self.count = resolve_cart_item(spec)

        part = ctx.get_part(self.name)
        assert part is not None
        self.vendor = part.vendor
        self.sku = part.sku
        self.count_per_sku = part.count_per_sku

        self.material = await part.get_mcftt("material")
        self.color = await part.get_mcftt("color")
        self.finish = await part.get_mcftt("finish")

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
            if self.count_per_sku:
                result["count_per_sku"] = self.count_per_sku
            else:
                result["count_per_sku"] = 1
        return result

    def add_binary(self, format: str, binary: bytes):
        self.format = format
        self.binary = binary

    def __repr__(self):
        result = self.name + "#"
        result += str(self.count)
        return result


class ProviderCart:
    """Describes a cart of parts"""

    # TODO(clairbee): add a lock

    parts: dict[str, ProviderCartItem]
    qos: str = None

    def __init__(self, qos: str = None):
        self.parts = {}
        self.qos = qos

    async def add_objects(self, ctx, objects: list[str]):
        """Add parts or assemblies"""
        for object in objects:
            await self.add_object(ctx, object)

    async def add_object(self, ctx, object: str):
        """Add a part or an assembly"""
        # The input object may be an assembly
        # But self.cart must contain parts only
        name, count = resolve_cart_item(object)
        project_name, object_name = resolve_resource_path(
            ctx.current_project_path,
            name,
        )
        prj = ctx.get_project(project_name)

        part = prj.get_part(object_name, quiet=True)
        if part:
            pc_logging.debug(f"Adding part '{object_name}' to the cart")
            item = ProviderCartItem()
            await item.set_spec(ctx, name)
            self.add_item(item, count)
        else:
            assembly = prj.get_assembly(object_name)
            if assembly:
                pc_logging.debug(f"Adding assembly '{object_name}' to the cart")
                bom = await assembly.get_bom()
                tasks = []
                for part_name, part_count in bom.items():
                    pc_logging.debug(f"Adding part '{part_name}' to the cart")
                    part_spec = part_name + "#" + str(part_count)
                    tasks.append(
                        asyncio.create_task(
                            self.add_item_from_spec(ctx, part_spec, count)
                        )
                    )
                await asyncio.gather(*tasks)
            else:
                raise Exception(
                    f"Part or assembly '{object_name}' not found in project '{project_name}'"
                )

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
        new_item = copy.copy(item)
        self._add_item(new_item, count)
        return new_item

    def _add_item(self, item: ProviderCartItem, count=1):
        """Add item without 'copy.copy()'"""
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
