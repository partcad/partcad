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
from .shape import Shape
from .shape_ai import ShapeWithAi
from .sync_threads import threadpool_manager
from . import logging as pc_logging


class AssemblyChild:
    def __init__(self, item: Shape, name: str = None, location=None):
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
        self.children: list[AssemblyChild] = []

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
        loc=b3d.Location((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.0),
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
        child_shapes = []

        @telemetry.start_as_current_span_async("Assembly._get_shape_real.per_child")
        async def per_child(child: AssemblyChild):
            # TODO(clairbee): use topods objects here
            item: b3d.Shape = await child.item.get_build123d(ctx)
            if child.name is not None or child.location is not None:
                item = copy.copy(item)
                if child.name is not None:
                    item.label = child.name
                if child.location is not None:
                    item.locate(child.location)
            return item

        if len(self.children) == 0:
            pc_logging.warning("The assembly %s:%s is empty" % (self.project_name, self.name))

        tasks = [asyncio.create_task(per_child(child)) for child in self.children]

        # TODO(clairbee): revisit whether non-determinism here is acceptable
        for f in asyncio.as_completed(tasks):
            item = await f
            child_shapes.append(item)

        if len(child_shapes) == 1:
            return child_shapes[0]

        compound = b3d.Compound(children=child_shapes)
        if not self.name is None:
            compound.label = self.name
        elif self.config.get("name"):
            compound.label = self.config["name"]
        if not self.location is None:
            compound.locate(self.location)
        # TODO(clairbee): the name and location are ignored anyway. Use OCP Compound here instead
        return compound.wrapped

    async def get_components(self, ctx, subloc):
        await self.do_instantiate()
        if len(self.components) == 0:
            if not self.location is None:
                subloc += self.location
            for child in self.children:
                # if hasattr(child.item, "get_components"):
                #     child_components = await child.item.get_components(ctx)
                #     if child_components:
                #         self.components.append(child_components)
                # else:
                if hasattr(child.item, "children"):
                    child_components = await child.item.get_components(ctx, subloc)
                    if child_components:
                        self.components.append(child_components)
                else:
                    # self.components.append(await child.item.get_wrapped(ctx))
                    # self.components.append(await child.item.get_build123d())
                    compound = b3d.Compound(children=[await child.item.get_build123d()])
                    if child.name is not None:
                        compound.label = child.name
                    elif hasattr(child.item, "name"):
                        compound.label = child.item.name
                    compound.locate(subloc)
                    self.components.append(compound)

            if self.with_ports is not None:
                ports_list = await self.with_ports.get_components(ctx, subloc)
                if ports_list:
                    self.components.append(ports_list)

        return self.components

    async def get_names(self, ctx):
        def get_child_name(child):
            if child.name is not None:
                return child.name
            elif hasattr(child.item, "name"):
                return child.item.name
            else:
                # TODO(clairbee): preserve the part/assembly ID to use it here
                return "Object"

        await self.do_instantiate()
        if len(self.names) == 0:
            for child in self.children:
                # if hasattr(child.item, "get_names"):
                #     child_names = await child.item.get_names(ctx)
                #     if child_names:
                #         self.names.append(child_names)
                # else:
                if hasattr(child.item, "children"):
                    child_names = await child.item.get_names(ctx)
                    if child_names:
                        self.names.append(child_names)
                else:
                    self.names.append(get_child_name(child))

            if self.with_ports is not None:
                ports_list = await self.with_ports.get_names(ctx)
                if ports_list:
                    self.names.append(ports_list)

        return self.names

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
