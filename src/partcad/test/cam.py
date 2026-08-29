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
import hashlib

from .test import Test
from ..part import Part
from ..part_config import PartConfiguration
from ..assembly import Assembly
from ..assembly_config import AssemblyConfiguration
from ..plugin_provider_data_cart import ProviderCartItem, resolve_cart_object
from ..file_factory import declared_hash, unreproducible_reason
from ..shape_config import final_config as _final_config
from .. import software as pc_software


class CamTest(Test):
    def __init__(self) -> None:
        super().__init__("cam")

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not shape.is_manufacturable and "force_manufacturing" not in test_ctx:
            self.debug(shape, "Not supposed to be manufacturable")
            return self.TEST_PASSED

        # Asked of every shape, before anything specific to one kind of them,
        # because it is not specific to one: it is about the file the object is
        # read from. A sketch is not manufactured itself, but a part extruded
        # from one is no more repeatable than the drawing it was extruded from,
        # and the sketch is where that is worth reporting.
        failure = self.reproducibility_failure(shape)
        if failure:
            return self.failed(shape, failure)

        if isinstance(shape, Part):
            return await self.test_part(tests_to_run, ctx, shape, test_ctx)
        if isinstance(shape, Assembly):
            return await self.test_assembly(tests_to_run, ctx, shape, test_ctx)

        # A sketch is the only other thing that reaches here, and reproducibility
        # is all of this test that applies to it: nothing manufactures a drawing.
        self.debug(shape, "Not applicable")
        return self.TEST_PASSED

    def reproducibility_failure(self, shape) -> str | None:
        """Why this object cannot be made again, or None if it can.

        Manufacturing is repetition: the run after this one has to produce the
        same thing. An object read from a file the package fetches rather than
        carries cannot promise that unless it says which bytes it expects -
        'fileHash' next to 'fileUrl' - because the URL is free to serve
        something else tomorrow, and then the part is quietly a different part.
        So the rule is not "the file is available", which it may well be, but
        "the file is identified".

        A part or an assembly has another way out: a 'vendor' and an 'sku' say
        what to order, and ordering the same SKU again is what "the same again"
        means for a bought thing - the file it also carries is a drawing of what
        arrives rather than the identity of it. A sketch and a piece of software
        cannot say that (the schema gives 'vendor'/'sku' to parts and assemblies
        alone), so for them it is the file or nothing.

        'fileHash' stays optional in the declaration (see
        'file_factory.unreproducible_reason', which is this rule whole and is
        shared with the 'Software' lint check). This is the one place it is
        insisted on, and only of what is actually going to be made: a package
        may pull a vendor's model from a URL and never claim it is
        manufacturable.

        Read from the *final* configuration, so an alias or an enrich is judged
        on the declaration it resolves to rather than on its own, which says
        nothing about where any file comes from.
        """
        failure = unreproducible_reason(_final_config(shape))
        if failure is None:
            return None
        return "It is not reproducible: %s" % failure

    def cache_key_suffix(self, ctx, shape) -> str:
        """What this test reads beyond the shape itself, folded into the cache key.

        A shape's cache key covers what the shape is built from, and the
        software it ships with is not that: a part's key does not move when its
        'software:' does. Without this, correcting a mistyped 'fileHash' - or
        pointing the part at a different image altogether - would be answered
        with the cached failure of the declaration that was replaced, which is
        the one thing a test must never do.

        The object's own 'fileHash' is in here for the same reason, and so is
        where its file comes from: 'reproducibility_failure()' reads both, and
        neither moves the shape's cache key either.

        Note what is being folded in: the *declared* text a package wrote down,
        which is what those two methods read. Not the content of the files, and
        not any hash PartCAD computed - re-hashing every image to decide whether
        a cached answer may be used would cost exactly what the cache exists to
        save.
        """
        config = _final_config(shape)
        declared = []
        if config.get("fileFrom") is not None or declared_hash(config) is not None:
            declared.append("file:%s@%s" % (config.get("fileFrom"), declared_hash(config)))
        for ref in pc_software.resolved_software_refs(shape.project_name, config):
            _project, software = pc_software.lookup(ctx, ref, quiet=True)
            declared.append("%s@%s" % (ref, "" if software is None else software.declared_hash()))
        if not declared:
            # Nothing beyond the shape itself was read, so nothing is added:
            # an object that declares neither keys exactly as it always has,
            # and the cache entries it already has stay valid.
            return ""
        return ".declared=" + hashlib.sha256(";".join(declared).encode()).hexdigest()[:16]

    async def software_failure(self, ctx, shape) -> str | None:
        """Why the software this object ships with is unusable, or None.

        A board nobody can flash is not a board anybody can make, so the
        software an object declares has to hold up before the object is called
        manufacturable: every reference has to resolve, and every file it
        resolves to has to be obtainable and be the one that was meant (see
        'Software.verify_async()').

        Checked for a purchased object as well as a manufactured one. Buying the
        board does not answer the question of which image goes on it, and the
        bill of materials lists that image either way.

        Every failure is reported, not just the first: a package that got two
        hashes wrong should learn both in one run.
        """
        failures = []
        for ref in pc_software.resolved_software_refs(shape.project_name, _final_config(shape)):
            _project, software = pc_software.lookup(ctx, ref)
            if software is None:
                failures.append("the software '%s' is not found" % ref)
                continue
            failure = await software.verify_async()
            if failure is not None:
                failures.append("the software '%s' cannot be relied on: %s" % (ref, failure))
        if not failures:
            return None
        return "; ".join(failures)

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

    def tolerance_failure(self, part: Part) -> str | None:
        """Why this part's manufacturing tolerance is unusable, or None if it is fine.

        A part that is going to be made has to say how precisely. 'tolerance' is
        an object-type parameter of the homogeneous part types, and it reads back
        as 0.0 when nothing declared one - a demand for perfect precision, which
        is what "nobody said" amounts to and is not something a manufacturer can
        be asked for. Read through 'get_object_type_parameter()' rather than
        'get_mcftt()' because the default lives on the part's type, and that is
        the reader that knows it.

        Checked here, in the part path of the CAM test, rather than in a sibling
        test class: the siblings ('cam-additive', 'cam-subtractive',
        'cam-forming') each check the geometry for one manufacturing method,
        while this applies to a part however it is made, and it needs exactly the
        purchased-or-manufactured determination this method has just made.
        Assemblies reach it for free - 'test_assembly()' runs every test in
        'tests_to_run' over its supply BoM, and this test is one of them.
        """
        tolerance = part.get_object_type_parameter("tolerance")
        if tolerance is None:
            return "No manufacturing tolerance: the part type '%s' does not accept one" % part.config.get("type")
        if tolerance == 0.0:
            return "No manufacturing tolerance is specified"
        return None

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

        if not can_be_purchased:
            # Only what is actually made needs a manufacturing tolerance. A part
            # that is bought comes as it comes, which is the same reason the
            # MCFTT parameters are documented as having no effect on a part with
            # a vendor and an SKU.
            failure = self.tolerance_failure(part)
            if failure:
                return self.failed(part, failure)

        # Whatever this part ships with has to hold up too: the bill of
        # materials of every assembly it ends up in lists that software beside
        # the part, and a line item nobody can obtain is not a bill of materials
        # anybody can work from.
        failure = await self.software_failure(ctx, part)
        if failure:
            return self.failed(part, failure)

        failure = await self.supply_failure(ctx, part)
        if failure:
            return self.failed(part, failure)

        return self.passed(part)

    async def test_assembly(self, tests_to_run: list[Test], ctx, assembly: Assembly, test_ctx: dict = {}) -> bool:
        self.debug(assembly, "Testing for manufacturability")

        # The same rule as for a part, and for the same reason: an assembly that
        # ships a host-side tool of its own lists it in its own bill of
        # materials, so it has to be obtainable. Its parts' software is checked
        # by their own run of this test, over the supply BoM below.
        failure = await self.software_failure(ctx, assembly)
        if failure:
            return self.failed(assembly, failure)

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
