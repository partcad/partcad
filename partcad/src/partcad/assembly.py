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

from .shape import Shape
from .shape_ai import ShapeWithAi
from . import sync_threads as pc_thread
from . import logging as pc_logging


class AssemblyChild:
    def __init__(self, item, name=None, location=None):
        self.item = item
        self.name = name
        self.location = location


class Assembly(ShapeWithAi):
    path: typing.Optional[str] = None

    def __init__(self, project_name: str, config={}):
        super().__init__(project_name, config)

        if "location" in config:
            self.location = config["location"]
        else:
            self.location = None
        self.kind = "assembly"

        # self.children contains all child parts and assemblies before they turn into 'self.shape'
        self.children = []

        # TODO(clairbee): add reference counter to assemblies
        self.count = 0

    async def do_instantiate(self):
        if len(self.children) == 0:
            self._wrapped = None  # Invalidate if any
            await pc_thread.run(self.instantiate, self)
            if len(self.children) == 0:
                pc_logging.warning("The assembly %s:%s is empty" % (self.project_name, self.name))

    # add is a non-thread-safe method for end users to create custom Assemblies
    def add(
        self,
        child_item: Shape,  # pc.Part or pc.Assembly
        name=None,
        loc=b3d.Location((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.0),
    ):
        self.children.append(AssemblyChild(child_item, name, loc))

        # Keep part reference counter for bill-of-materials purposes
        child_item.ref_inc()

        self._wrapped = None  # Invalidate if any

    def ref_inc(self):
        for child in self.children:
            child.item.ref_inc()

    async def get_shape(self, ctx):
        await self.do_instantiate()
        if not "child" in self.config:
            # This is the top level assembly
            with pc_logging.Action("Assembly", self.project_name, self.name):
                return await self._get_shape_real(ctx)
        else:
            return await self._get_shape_real(ctx)

    async def _get_shape_real(self, ctx):
        child_shapes = []

        async def per_child(child):
            # TODO(clairbee): use topods objects here
            item = await child.item.get_build123d(ctx)
            if not child.name is None:
                item.label = child.name
            if not child.location is None:
                item.locate(child.location)
            return item

        if len(self.children) == 0:
            pc_logging.warning("The assembly %s:%s is empty" % (self.project_name, self.name))

        tasks = [asyncio.create_task(per_child(child)) for child in self.children]

        # TODO(clairbee): revisit whether non-determinism here is acceptable
        for f in asyncio.as_completed(tasks):
            item = await f
            child_shapes.append(item)

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

    async def _render_txt_real(self, file):
        with self.lock:
            async with self.get_async_lock():
                await self.do_instantiate()
        for child in self.children:
            child._render_txt_real(file)

    async def _render_markdown_real(self, file):
        with self.lock:
            async with self.get_async_lock():
                await self.do_instantiate()
        for child in self.children:
            child._render_markdown_real(file)
