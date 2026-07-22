#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

import asyncio
import copy
import typing

import build123d as b3d

from . import telemetry
from .geom import Location
from .shape import Shape
from .shape_ai import ShapeWithAi
from .sync_threads import threadpool_manager
from . import logging as pc_logging


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
        @telemetry.start_as_current_span_async("Assembly._get_shape_real.per_child")
        async def per_child(child):
            # TODO(clairbee): use topods objects here
            item = await child.item.convert("build123d", ctx)
            if item is None or item.wrapped is None:
                # convert("build123d") hands back a Solid whose 'wrapped' is None
                # when the shape could not be built, most often because the wrapper
                # process died before producing any output. Copying or compounding
                # such an object fails deep inside build123d with an AttributeError
                # that names neither this assembly nor the child that is missing,
                # so report which child failed here instead.
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
            if child.name is not None or child.location is not None:
                item = copy.copy(item)
                if child.name is not None:
                    item.label = child.name
                if child.location is not None:
                    # 'item' is a build123d object while 'child.location' is a pc.Location
                    # (see geom.py). build123d's Shape.locate() only reads '.wrapped', which
                    # both types expose as a TopLoc_Location, so no conversion is needed here.
                    item.locate(child.location)
            return item

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

        compound = b3d.Compound(children=child_shapes)
        if not self.name is None:
            compound.label = self.name
        if not self.location is None:
            compound.locate(self.location)
        return compound.wrapped
        # return copy.copy(
        #     shape
        # )  # TODO(clairbee): fix this for the case when the parts are made with cadquery

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
