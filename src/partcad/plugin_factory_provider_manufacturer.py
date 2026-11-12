#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import os
import tempfile

from . import logging as pc_logging
from . import telemetry
from .plugin_factory_provider import PluginFactoryProvider
from .plugin_provider import with_currency
from .plugin_provider_data_cart import *
from .plugin_provider_data_cart import resolve_cart_object
from .plugin_request_provider_caps import ProviderRequestCaps
from .plugin_request_provider_order import ProviderRequestOrder
from .plugin_request_provider_quote import ProviderRequestQuote


async def _sent_geometry(ctx, object):
    """What a manufacturer is sent the geometry of: a printed part's design, else the object itself.

    A printed part's own geometry is the print -- or, until PartCAD works the
    print out, whatever stands in for it, an as-printed mesh included -- and a
    mesh is nothing anybody would hand to a slicer; what is printed is its
    design, and that is what a print service slices (see
    'part_config_manufacturing.ADDITIVE_REQUIRED'). A design that cannot be
    found is reported by 'pc qual test', and the part's own geometry is sent
    meanwhile rather than nothing.
    """
    from .part import Part
    from .part_config import PartConfiguration
    from .part_config_manufacturing import METHOD_ADDITIVE
    from .qual.basic.manufacturability_reference import resolve_reference

    if not isinstance(object, Part):
        return object
    try:
        data = PartConfiguration.get_manufacturing_data(object)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("No design for %s: %s" % (object.name, e))
        return object
    # Only a print: a molding's 'source:' is the cavity, which a mold that
    # shrinks the part makes bigger than the part, and the part is what a
    # molder quotes and makes. Its own geometry is that part.
    design = data.design if data is not None and data.method == METHOD_ADDITIVE else None
    if not design:
        return object
    found = await resolve_reference(ctx, object, design, "part")
    return found if found is not None else object


@telemetry.instrument()
class PluginFactoryProviderManufacturer(PluginFactoryProvider):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitManuf", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
            )
            # Complement the config object here if necessary

            self._create(config)

    def _create(self, config):
        super()._create(config)
        self.plugin.is_part_available = self.is_part_available
        self.plugin.load = self.load
        self.plugin.query_caps = self.query_caps
        self.plugin.query_quote = self.query_quote
        self.plugin.query_order = self.query_order

    async def is_part_available(self, cart_item: ProviderCartItem):
        # TODO(clairbee): add vendor/SKU-based availability check
        caps = await self.plugin.get_caps()
        if cart_item.material:
            if cart_item.material not in caps["materials"]:
                return False
            if cart_item.color:
                # TODO(clairbee): implement color mapping as a function in
                #                 the corresponding module
                #                 (resolve cart_item.color as a color object)
                if cart_item.color not in list(
                    map(
                        lambda c: c["name"],
                        caps["materials"][cart_item.material]["colors"],
                    )
                ):
                    return False
            if cart_item.finish:
                # TODO(clairbee): implement finish mapping as a function in
                #                 the corresponding module
                #                 (resolve cart_item.finish as a finish object)
                if cart_item.finish not in list(
                    map(
                        lambda f: f["name"],
                        caps["materials"][cart_item.material]["finishes"],
                    )
                ):
                    pc_logging.debug("Provider %s does not support finish %s" % (self.name, cart_item.finish))
                    pc_logging.debug("Supported finishes: %s" % caps["materials"][cart_item.material]["finishes"])
                    return False
        return True

    async def load(self, cart_item: ProviderCartItem):
        """Load the CAD binary into the cart item based on the provider capabilities."""
        caps = await self.plugin.get_caps()
        # TODO(clairbee): Make the below more generic
        if "formats" in caps and "step" in caps["formats"]:
            # A cart item is a part most of the time, but it is an assembly
            # whenever one is ordered assembled
            object = resolve_cart_object(self.ctx, cart_item.name)
            if object is None:
                pc_logging.error(f"Part or assembly '{cart_item.name}' not found")
                return
            object = await _sent_geometry(self.ctx, object)
            with tempfile.TemporaryDirectory() as tmp_dir:
                filepath = os.path.join(tmp_dir, "cart_item.step")
                await object.render_async(self.ctx, format_name="step", filepath=filepath)
                with open(filepath, "rb") as f:
                    step = f.read()
            cart_item.add_binary("step", step)
        else:
            # TODO(clairbee): add support for other formats
            pc_logging.error(f"Provider {self.plugin.name} does not support STEP format.")

    async def query_caps(self, request: ProviderRequestCaps):
        # TODO(clairbee): does it make sense to run this in a separate thread?
        # return await pc_thread.run_async(
        #   self.query_script, self.plugin, "caps", request.compose()
        # )
        return await self.query_script(self.plugin, "caps", request.compose())

    async def query_quote(self, request: ProviderRequestQuote):
        # TODO(clairbee): does it make sense to run this in a separate thread?
        # return await pc_thread.run_async(
        #   self.query_script, self.plugin, "quote", request.compose(),
        # )
        quote = await self.query_script(self.plugin, "quote", request.compose())
        # Never a price without its currency (see 'plugin_provider.with_currency').
        return with_currency(self.plugin.name, self.config, quote)

    async def query_order(self, request: ProviderRequestOrder):
        # TODO(clairbee): does it make sense to run this in a separate thread?
        # return await pc_thread.run_async(
        #   self.query_script, self.plugin, "order", request.compose(),
        # )
        return await self.query_script(self.plugin, "order", request.compose())
