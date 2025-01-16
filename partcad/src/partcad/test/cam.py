#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import copy

from .test import Test
from ..part import Part
from ..part_config import PartConfiguration
from ..assembly import Assembly
from ..assembly_config import AssemblyConfiguration
from ..provider_data_cart import ProviderCartItem


class CamTest(Test):
    def __init__(self) -> None:
        super().__init__("cam")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        is_part = isinstance(shape, Part)
        is_assembly = isinstance(shape, Assembly)
        if not is_part and not is_assembly:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        if not shape.is_manufacturable and "force_manufacturing" not in test_ctx:
            self.debug(shape, "Not supposed to be manufacturable")
            return self.TEST_PASSED

        if is_part:
            return await self.test_part(tests_to_run, ctx, shape, test_ctx)
        else:
            return await self.test_assembly(tests_to_run, ctx, shape, test_ctx)

    async def test_part(self, tests_to_run: list[Test], ctx, part: Part, test_ctx: dict = {}) -> bool:
        self.debug(part, "Testing for manufacturability")

        # Test if it can be purchased at a store
        can_be_purchased = False
        store_data = part.get_store_data()
        if store_data.vendor and store_data.sku:
            self.debug(part, "Can be purchased")
            # TODO(clairbee): Verify that at least one provider is available
            # TODO(clairbee): Verify that at least one provider is available where it is in stock
            can_be_purchased = True

        # Test if it can be manufactured
        can_be_manufactured = False
        manufacturing_data = PartConfiguration.get_manufacturing_data(part)
        if manufacturing_data.method:
            self.debug(part, "Can be manufactured")
            # TODO(clairbee): Verify that at least one provider is available
            can_be_manufactured = True

        if not can_be_purchased and not can_be_manufactured:
            return self.failed(part, "Cannot be purchased or manufactured")

        part_spec = f"{part.project_name}:{part.name}"
        part_item = ProviderCartItem()
        await part_item.set_spec(ctx, part_spec)
        suppliers = await ctx.find_part_suppliers(part_item)
        if not suppliers:
            return self.failed(part, "No suppliers found")

        supplier_found = False
        for provider_name in suppliers:
            provider = ctx.get_provider(provider_name)
            if await provider.is_part_available(part_item):
                supplier_found = True
                break
        if not supplier_found:
            return self.failed(part, "No suppliers provide the part")

        return self.passed(part)

    async def test_assembly(self, tests_to_run: list[Test], ctx, assembly: Assembly, test_ctx: dict = {}) -> bool:
        self.debug(assembly, "Testing for manufacturability")

        # Test if it can be purchased at a store
        can_be_purchased = False
        store_data = assembly.get_store_data()
        if store_data.vendor and store_data.sku:
            self.debug(assembly, "Can be purchased")
            # TODO(clairbee): Verify that at least one provider is available
            # TODO(clairbee): Verify that at least one provider is available where it is in stock
            can_be_purchased = True

        failed = False
        if not can_be_purchased:
            # Test if it can be manufactured
            manufacturing_data = AssemblyConfiguration.get_manufacturing_data(assembly)
            if not manufacturing_data.method:
                self.failed(assembly, "Can't be assembled")
                # TODO(clairbee): Verify that at least one provider is available
                failed = True

            # When testing parts in a manufacturable assembly, ignore their manufacturability preference
            test_ctx = copy.copy(test_ctx)
            test_ctx["force_manufacturing"] = True
            test_ctx["action_prefix"] = f"{assembly.project_name}:{assembly.name}"

            # Now test if all of the parts for assembly are manufacturable by themselves
            bom = await assembly.get_bom()
            for part_name in bom:
                # Check if the part exists
                part = ctx.get_part(part_name)
                if part is None:
                    # Do not stop here: test other parts right away
                    self.failed(assembly, f"Missing part '{part_name}' is referenced")
                    failed = True
                    continue

                # Test the part for everything that we need to test the assembly for
                if "log_wrapper" in test_ctx:
                    tasks = [t.test_log_wrapper(tests_to_run, ctx, part, test_ctx) for t in tests_to_run]
                else:
                    tasks = [t.test(tests_to_run, ctx, part, test_ctx) for t in tests_to_run]
                results = await asyncio.gather(*tasks)
                if self.TEST_FAILED in results:
                    # Do not stop here: test other parts right away
                    self.failed(assembly, f"Non-manufacturable part '{part_name}' is referenced")
                    failed = True

        if failed:
            return self.TEST_FAILED

        return self.passed(assembly)
