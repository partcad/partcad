#
# PartCAD, 2025
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
from ..plugin_provider_data_cart import ProviderCartItem, resolve_cart_object


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

    async def supply_failure(self, ctx, shape) -> str | None:
        """Why this object cannot be supplied, or None if it can.

        This is the question 'pc supply find' answers, asked about the very same
        object: a part, or an assembly that is ordered assembled.
        """
        spec = f"{shape.project_name}:{shape.name}"
        item = ProviderCartItem()
        await item.set_spec(ctx, spec)

        suppliers = await ctx.find_part_suppliers(item)
        if not suppliers:
            return "No suppliers found"

        for provider_name in suppliers:
            provider = ctx.get_provider(provider_name)
            if await provider.is_part_available(item):
                return None

        return f"No suppliers provide the {shape.kind}"

    async def test_part(self, tests_to_run: list[Test], ctx, part: Part, test_ctx: dict = {}) -> bool:
        self.debug(part, "Testing for manufacturability")

        # Test if it can be purchased at a store
        can_be_purchased = False
        store_data = part.get_store_data()
        if store_data.is_purchasable:
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

        failure = await self.supply_failure(ctx, part)
        if failure:
            return self.failed(part, failure)

        return self.passed(part)

    async def test_assembly(self, tests_to_run: list[Test], ctx, assembly: Assembly, test_ctx: dict = {}) -> bool:
        self.debug(assembly, "Testing for manufacturability")

        # Test if it can be purchased at a store
        can_be_purchased = False
        store_data = assembly.get_store_data()
        if store_data.is_purchasable:
            self.debug(assembly, "Can be purchased")
            # TODO(clairbee): Verify that at least one provider is available
            # TODO(clairbee): Verify that at least one provider is available where it is in stock
            can_be_purchased = True

        failed = False
        if can_be_purchased:
            # It is ordered as a whole, so a supplier has to carry the assembly
            # itself. What is inside it is then somebody else's problem, exactly
            # as it is for 'pc supply'.
            failure = await self.supply_failure(ctx, assembly)
            if failure:
                return self.failed(assembly, failure)
        else:
            # Test if it can be manufactured
            manufacturing_data = AssemblyConfiguration.get_manufacturing_data(assembly)
            if not manufacturing_data.method:
                self.failed(assembly, "Can't be assembled")
                # TODO(clairbee): Verify that at least one provider is available
                failed = True

            # When testing the contents of a manufacturable assembly, ignore their
            # manufacturability preference
            test_ctx = copy.deepcopy(test_ctx)
            test_ctx["force_manufacturing"] = True
            test_ctx["action_prefix"] = f"{assembly.project_name}:{assembly.name}"

            # Now test everything this assembly is procured from: its parts, and
            # the sub-assemblies that are ordered assembled instead of being taken
            # apart. This is the walk 'pc supply' makes, so the two agree on which
            # objects have to be obtainable.
            bom = await assembly.get_supply_bom()
            for object_name in bom:
                # Check if the object exists
                object = resolve_cart_object(ctx, object_name)
                if object is None:
                    # Do not stop here: test the other objects right away
                    self.failed(assembly, f"Missing part or assembly '{object_name}' is referenced")
                    failed = True
                    continue

                # Test the object for everything that we need to test the assembly for
                if "log_wrapper" in test_ctx:
                    tasks = [t.test_log_wrapper(tests_to_run, ctx, object, test_ctx) for t in tests_to_run]
                else:
                    tasks = [t.test(tests_to_run, ctx, object, test_ctx) for t in tests_to_run]
                results = await asyncio.gather(*tasks)
                if self.TEST_FAILED in results:
                    # Do not stop here: test the other objects right away
                    self.failed(assembly, f"Non-manufacturable {object.kind} '{object_name}' is referenced")
                    failed = True

        if failed:
            return self.TEST_FAILED

        return self.passed(assembly)
