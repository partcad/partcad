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

    def __init__(self, config={}):
        super().__init__(config)

        if "location" in config:
            self.location = config["location"]
        else:
            self.location = None
        self.shape = None
        self.kind = "assemblies"

        # self.children contains all child parts and assemblies before they turn into 'self.shape'
        self.children = []

        # TODO(clairbee): add reference counter to assemblies
        self.count = 0

    async def do_instantiate(self):
        async with self.locked():
            if len(self.children) == 0:
                self.shape = None  # Invalidate if any
                await pc_thread.run(self.instantiate, self)
                if len(self.children) == 0:
                    pc_logging.warning(
                        "The assembly %s:%s is empty"
                        % (self.project_name, self.name)
                    )

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

        self.shape = None  # Invalidate if any

    def ref_inc(self):
        for child in self.children:
            child.item.ref_inc()

    async def get_shape(self):
        await self.do_instantiate()
        async with self.locked():
            if hasattr(self, "project_name"):
                # This is the top level assembly
                with pc_logging.Action(
                    "Assembly", self.project_name, self.name
                ):
                    return await self._get_shape_real()
            else:
                return await self._get_shape_real()

    async def _get_shape_real(self):
        if self.shape is None:
            child_shapes = []
            tasks = []

            async def per_child(child):
                item = copy.copy(await child.item.get_build123d())
                if not child.name is None:
                    item.label = child.name
                if not child.location is None:
                    item.locate(child.location)
                return item

            if len(self.children) == 0:
                pc_logging.warning(
                    "The assembly %s:%s is empty"
                    % (self.project_name, self.name)
                )
            for child in self.children:
                tasks.append(per_child(child))

            # TODO(clairbee): revisit whether non-determinism here is acceptable
            for f in asyncio.as_completed(tasks):
                item = await f
                child_shapes.append(item)

            compound = b3d.Compound(children=child_shapes)
            if not self.name is None:
                compound.label = self.name
            if not self.location is None:
                compound.locate(self.location)
            self.shape = compound.wrapped
        if self.shape is None:
            pc_logging.warning("The shape is None")
        return self.shape
        # return copy.copy(
        #     self.shape
        # )  # TODO(clairbee): fix this for the case when the parts are made with cadquery

    async def get_bom(self):
        await self.do_instantiate()
        async with self.locked():
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
        await self.do_instantiate()
        for child in self.children:
            child._render_txt_real(file)

    async def _render_markdown_real(self, file):
        await self.do_instantiate()
        for child in self.children:
            child._render_markdown_real(file)
