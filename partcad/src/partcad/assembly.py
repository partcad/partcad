#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

import asyncio
import os
import sys
import typing

from . import telemetry
from .geom import Location
from .shape import Shape
from .shape_ai import ShapeWithAi
from .sync_threads import threadpool_manager
from . import logging as pc_logging

# This module is on the 'import partcad' path, so it imports neither build123d
# nor OCP at module scope. The assembly compound is composed with OCCT directly
# (via the sandbox codec 'ocp_serialize'), which is imported lazily - only when
# an assembly is actually built or serialized, never at import time.
_WRAPPERS_DIR = os.path.join(os.path.dirname(__file__), "wrappers")


def _ocp_serialize():
    """Import the OCP-backed shape codec lazily (keeps OCP off the import path)."""
    if _WRAPPERS_DIR not in sys.path:
        sys.path.append(_WRAPPERS_DIR)
    import ocp_serialize

    return ocp_serialize


class AssemblyChild:
    def __init__(self, item, name=None, location=None):
        self.item = item
        self.name = name
        self.location = location


@telemetry.instrument()
class Assembly(ShapeWithAi):
    path: typing.Optional[str] = None

    def __init__(self, project_name: str, config: dict = {}):
        super().__init__(project_name, config)

        self.location = config.get("location")
        self.kind = "assembly"

        # self.children contains all child parts and assemblies before they turn into 'self.shape'
        self.children = []

    async def do_instantiate(self):
        if len(self.children) == 0:
            self._wrapped = None  # Invalidate if any
            await threadpool_manager.run(self.instantiate, self)
            if len(self.children) == 0:
                pc_logging.warning(f"The assembly {self.project_name}:{self.name} is empty")

    # add is a non-thread-safe method for end users to create custom Assemblies
    def add(
        self,
        child_item: Shape,  # pc.Part or pc.Assembly
        name=None,
        loc=Location((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.0),
    ):
        self.children.append(AssemblyChild(child_item, name, loc))
        self._wrapped = None  # Invalidate if any

    async def get_shape(self, ctx):
        await self.do_instantiate()
        if "child" not in self.config:
            # This is the top level assembly
            with pc_logging.Action("Assembly", self.project_name, self.name):
                return await self._get_shape_real(ctx)
        else:
            return await self._get_shape_real(ctx)

    async def _get_shape_real(self, ctx):
        ocp_serialize = _ocp_serialize()

        @telemetry.start_as_current_span_async("Assembly._get_shape_real.per_child")
        async def per_child(child):
            # get_wrapped() hands back the child's BREP envelope (or None when the
            # shape could not be built). Decode it to a live TopoDS and compose
            # the compound with OCCT directly - the core no longer routes through
            # build123d to fetch child shapes, so building an assembly needs only
            # cadquery-ocp, not build123d.
            envelope = await child.item.get_wrapped(ctx)
            if envelope is None:
                # A child whose shape is missing, most often because its wrapper
                # process died before producing any output. Report which child
                # failed here, rather than let it surface as an opaque failure
                # deeper in the compound assembly.
                child_name = "%s:%s" % (
                    getattr(child.item, "project_name", "<unknown>"),
                    getattr(child.item, "name", "<unknown>"),
                )
                msg = "%s: %s: failed to get the shape of the child %s" % (
                    self.project_name,
                    self.name,
                    child_name,
                )
                self.error(msg)
                raise Exception(msg)
            shape = ocp_serialize.decode_shape(envelope)
            if child.location is not None:
                # 'child.location.wrapped' is a TopLoc_Location (both pc.Location
                # and build123d's Location expose it); 'Located' places the child
                # at that absolute location. Labels are metadata that the flat
                # compound cannot carry - they survive in the cached tree instead
                # (see get_cache_value/_serialize_children).
                shape = shape.Located(child.location.wrapped)
            return shape

        if len(self.children) == 0:
            pc_logging.warning("The assembly %s:%s is empty" % (self.project_name, self.name))

        tasks = [asyncio.create_task(per_child(child)) for child in self.children]

        # The children are still built concurrently, but they are collected in the
        # order they are declared in, not in the order the workers happen to finish.
        # Completion order varies from run to run (a part loaded from a STEP file
        # finishes long before one built by CadQuery), and it ends up baked into the
        # resulting compound, making rendered artifacts differ between otherwise
        # identical runs.
        child_shapes = list(await asyncio.gather(*tasks))

        compound = ocp_serialize.compound_of(child_shapes)
        root = self._root_location()
        if root is not None:
            compound = compound.Located(root.wrapped)
        return compound

    def _root_location(self):
        """The assembly's own location as a geom.Location, or None."""
        if isinstance(self.location, Location):
            return self.location
        if isinstance(self.location, (list, tuple)):
            return Location(self.location)
        return None

    def _child_name_label(self, child):
        item = child.item
        project = getattr(item, "project_name", None)
        item_name = getattr(item, "name", None)
        name = ("%s:%s" % (project, item_name)) if project and item_name else item_name
        label = child.name if child.name is not None else item_name
        return name, label

    async def _serialize_children(self, ctx, parent_location):
        """The nested shape/assembly objects for this assembly's children.

        Locations accumulate down the tree: a child at 'child.location' inside a
        parent at 'parent_location' sits at 'parent_location * child.location'.
        Leaf parts carry their fully accumulated world location in the BREP, and
        sub-assemblies recurse - so the tree decodes back to the same geometry as
        the flat compound while keeping every name, label and level.
        """
        # Make sure this (sub-)assembly's children are populated - a cache hit on
        # get_wrapped() would otherwise have skipped instantiation.
        await self.do_instantiate()

        ocp_serialize = _ocp_serialize()
        children = []
        for child in self.children:
            if child.location is None:
                loc = parent_location
            elif parent_location is None:
                loc = child.location
            else:
                loc = parent_location * child.location

            name, label = self._child_name_label(child)
            item = child.item

            if isinstance(item, Assembly):
                sub = await item._serialize_children(ctx, loc)
                children.append(ocp_serialize.encode_assembly(sub, name=name, label=label))
            else:
                # get_wrapped() hands back a BREP envelope, not a live shape.
                # Decode it here to bake in the accumulated world location - this
                # is the assembly's own in-process OCP use (Tier 1) - then
                # re-encode the located shape back into the tree.
                envelope = await item.get_wrapped(ctx)
                if envelope is None:
                    continue
                shape = ocp_serialize.decode_shape(envelope)
                if loc is not None:
                    shape = shape.Located(loc.wrapped)
                children.append(ocp_serialize.encode_shape(shape, name=name, label=label))
        return children

    async def get_cache_value(self, ctx, shape):
        """Cache the assembly as its nested tree, not a flat compound.

        The tree preserves the hierarchy - names, labels and sub-assemblies -
        and decodes back (via ocp_serialize.decode_shape) to a TopoDS_Compound
        equal to the geometry returned by get_wrapped().
        """
        children = await self._serialize_children(ctx, self._root_location())
        name = ("%s:%s" % (self.project_name, self.name)) if self.name else self.project_name
        return _ocp_serialize().encode_assembly(children, name=name, label=self.name)

    async def get_bom(self):
        with self.lock:
            async with self.get_async_lock():
                await self.do_instantiate()
                if hasattr(self, "project_name"):
                    # This is the top level assembly
                    with pc_logging.Action("BoM", self.project_name, self.name):
                        return await self._get_bom_real()
                else:
                    return await self._get_bom_real()

    async def _get_bom_real(self):
        bom = {}
        for child in self.children:
            if hasattr(child.item, "get_bom"):
                # This is an assembly
                child_bom = await child.item.get_bom()
                for (
                    child_part_name,
                    child_part_count,
                ) in child_bom.items():
                    if child_part_name in bom:
                        bom[child_part_name] += child_part_count
                    else:
                        bom[child_part_name] = child_part_count
            else:
                part_name = child.item.project_name + ":" + child.item.name
                if part_name in bom:
                    bom[part_name] += 1
                else:
                    bom[part_name] = 1
        return bom
