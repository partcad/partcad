#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from .test import Test
from .. import logging as pc_logging
from ..part import Part
from ..part_config import PartConfiguration
from ..assembly import Assembly
from ..assembly_config import AssemblyConfiguration


class CamTest(Test):
    def __init__(self) -> None:
        super().__init__("cam")

    async def test(self, ctx, shape):
        if isinstance(shape, Part):
            await self.test_part(ctx, shape)
        elif isinstance(shape, Assembly):
            await self.test_assembly(ctx, shape)

    async def test_part(self, ctx, part: Part):
        if not part.is_manufacturable:
            pc_logging.debug("This part is not supposed to be manufacturable")
            return

        pc_logging.debug("Testing for manufacturability: %s:%s" % (part.project_name, part.name))

        # Test if it can be purchased at a store
        can_be_purchased = False
        store_data = part.get_store_data()
        if store_data.vendor and store_data.sku:
            pc_logging.debug("%s:%s can be purchased" % (part.project_name, part.name))
            # TODO(clairbee): Verify that at least one provider is available
            # TODO(clairbee): Verify that at least one provider is available where it is in stock
            can_be_purchased = True

        # Test if it can be manufactured
        can_be_manufactured = False
        manufacturing_data = PartConfiguration.get_manufacturing_data(part)
        if manufacturing_data.method:
            pc_logging.debug("%s:%s can be manufactured" % (part.project_name, part.name))
            # TODO(clairbee): Verify that at least one provider is available
            can_be_manufactured = True

        if not can_be_purchased and not can_be_manufactured:
            pc_logging.error("%s:%s cannot be purchased or manufactured" % (part.project_name, part.name))
            return

        pc_logging.debug("Passed test: %s: %s:%s" % (self.name, part.project_name, part.name))

    async def test_assembly(self, ctx, assembly: Assembly):
        if not assembly.is_manufacturable:
            pc_logging.debug("This assembly is not supposed to be manufacturable")
            return

        pc_logging.debug("Testing for manufacturability: %s:%s" % (assembly.project_name, assembly.name))

        # Test if it can be purchased at a store
        can_be_purchased = False
        store_data = assembly.get_store_data()
        if store_data.vendor and store_data.sku:
            pc_logging.debug("%s:%s can be purchased" % (assembly.project_name, assembly.name))
            # TODO(clairbee): Verify that at least one provider is available
            # TODO(clairbee): Verify that at least one provider is available where it is in stock
            can_be_purchased = True

        if not can_be_purchased:
            # Test if it can be manufactured
            manufacturing_data = AssemblyConfiguration.get_manufacturing_data(assembly)
            if not manufacturing_data.method:
                pc_logging.error("%s:%s can't be assembled" % (assembly.project_name, assembly.name))
                # TODO(clairbee): Verify that at least one provider is available
                return

            # Now test if all of the parts for assembly are manufacturable by themselves
            bom = await assembly.get_bom()
            for part_name in bom:
                part = ctx.get_part(part_name)
                if part is None:
                    pc_logging.error(
                        f"Missing part '{part_name}' required for assembly '{assembly.project_name}:{assembly.name}'"
                    )
                    continue
                await self.test(ctx, part)

        pc_logging.debug(f"Passed test: {assembly.project_name}:{assembly.name}")
