#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

import asyncio
import typing

from . import telemetry
from . import shape_envelope
from .geom import Location
from .shape import Shape
from .sync_threads import threadpool_manager
from . import logging as pc_logging

# This module needs no CAD library at all: an assembly is built as a nested
# BREP-envelope object with child placements carried as plain data, and the
# geometry is only realized (with OCP) later, inside a sandbox wrapper.


class AssemblyChild:
    def __init__(self, item, name=None, location=None, comment=None, how=None):
        self.item = item
        self.name = name
        self.location = location
        # The non-geometric half of the 'connect'/'connectPorts' section that
        # placed this child: free-form context ('comment') and the assembly
        # instructions ('how'). Both are None unless the child was connected.
        self.comment = comment
        self.how = how

    def connect_info(self):
        """What the ASSY file says about connecting this child, or None.

        Connections that carry neither a comment nor anything but the default
        'how' are left out: they add nothing to what the defaults already say.
        """
        has_how = self.how is not None and not self.how.is_default()
        if self.comment is None and not has_how:
            return None
        info = {"name": self.name}
        if self.comment is not None:
            info["comment"] = self.comment
        if has_how:
            info["how"] = self.how.info()
        return info


@telemetry.instrument()
class Assembly(Shape):
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
        comment=None,
        how=None,
    ):
        self.children.append(AssemblyChild(child_item, name, loc, comment, how))
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
        """Build this assembly as a nested BREP-envelope object.

        Rather than decoding children and compounding them into a flat TopoDS in
        the core process, the assembly is populated incrementally into the same
        {name, label, assembly: [...]} object the wrappers produce: each child
        contributes its own envelope plus its placement, carried as plain data
        (KEY_LOCATION). The geometry-side codec (ocp_serialize.decode_shape)
        applies the placements only when the tree is finally realized in a
        sandbox, so building an assembly needs no CAD library in the core at all.
        This is also what get_wrapped() caches - no separate serialization pass.
        """

        @telemetry.start_as_current_span_async("Assembly._get_shape_real.per_child")
        async def per_child(child):
            envelope = await child.item.get_wrapped(ctx)
            if envelope is None:
                # A child whose shape is missing, most often because its wrapper
                # process died before producing any output. Report which child
                # failed here, rather than let it surface as an opaque failure
                # later on.
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
            name, label = self._child_name_label(child)
            return self._place(envelope, child.location, name, label)

        if len(self.children) == 0:
            pc_logging.warning("The assembly %s:%s is empty" % (self.project_name, self.name))

        # Children are built concurrently but collected in declaration order, so
        # the resulting tree - and every artifact derived from it - is stable
        # across runs regardless of which child's wrapper happens to finish first.
        tasks = [asyncio.create_task(per_child(child)) for child in self.children]
        children = list(await asyncio.gather(*tasks))

        name = ("%s:%s" % (self.project_name, self.name)) if self.name else self.project_name
        envelope = {"name": name, "label": self.name, shape_envelope.KEY_ASSEMBLY: children}
        root = self._root_location()
        if root is not None:
            envelope[shape_envelope.KEY_LOCATION] = root.as_packed()
        return envelope

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

    def _place(self, child_env, placement, name, label):
        """The child's envelope re-stamped for this assembly.

        The child keeps its own geometry and, if it is a sub-assembly, its own
        internal location; this assembly's placement of the child is composed
        onto that (placement first, then the child's own) and carried as data.
        """
        entry = dict(child_env)
        entry["name"] = name
        entry["label"] = label
        if placement is not None:
            placement = placement if isinstance(placement, Location) else Location(placement)
            own = child_env.get(shape_envelope.KEY_LOCATION)
            composed = placement if own is None else (placement * Location(own))
            entry[shape_envelope.KEY_LOCATION] = composed.as_packed()
        return entry

    def connected_children(self):
        """Every child of this assembly, including those of the sub-assemblies it embeds.

        An ASSY file's top level 'links:' becomes a child assembly of the object
        the file defines, and so does every nested 'links:'. Those embedded
        assemblies are not objects of any package - exactly as in the grouped
        BoM, what they hold belongs to the assembly that embeds them - so the
        connections inside them are this assembly's connections.
        """
        for child in self.children:
            yield child
            item = child.item
            if isinstance(item, Assembly) and item.config.get("child", False):
                yield from item.connected_children()

    async def resolve_connect_metadata(self, ctx):
        """Fill in the parts of the connection metadata that need the geometry.

        Only 'how.pushDistance' does, and only when the ASSY file left it to be
        derived from the object being connected. Instantiating an assembly
        deliberately does not build any geometry, so this is a separate step for
        the callers that have a context and want the numbers.
        """
        await self.do_instantiate()
        await asyncio.gather(
            *[child.how.resolve_push_distance(ctx) for child in self.connected_children() if child.how is not None]
        )

    def shape_info(self, ctx):
        info = super().shape_info(ctx)
        # The connection metadata lives on the children, and a cached shape is
        # returned without ever populating them.
        if not self.children:
            asyncio.run(self.do_instantiate())
        try:
            asyncio.run(self.resolve_connect_metadata(ctx))
        except Exception as e:
            pc_logging.debug("Failed to resolve the connection metadata: %s" % e)
        connections = [child.connect_info() for child in self.connected_children()]
        connections = [connection for connection in connections if connection is not None]
        if connections:
            info["Connections"] = connections
        return info

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

    async def get_bom_grouped_async(self):
        """The recursive contents of this assembly, grouped by package.

        Unlike 'get_bom()', which flattens the whole tree into a map of part
        names, this keeps parts and sub-assemblies apart and groups each of them
        by the package they come from:

            {
                "parts": {"//package": {"name": {"count": 2, "desc": "..."}}},
                "assemblies": {...},
            }

        Assemblies embedded in the parent's source file (the nested 'links:' of
        an ASSY file) are not objects of any package, so they are not listed:
        their contents are attributed to the assembly that embeds them.
        """
        with pc_logging.Action("BoMGrouped", self.project_name, self.name):
            return await self._get_bom_grouped_locked()

    def get_bom_grouped(self):
        return asyncio.run(self.get_bom_grouped_async())

    async def _get_bom_grouped_locked(self):
        with self.lock:
            async with self.get_async_lock():
                await self.do_instantiate()
                return await self._get_bom_grouped_real()

    async def _get_bom_grouped_real(self):
        grouped = {"parts": {}, "assemblies": {}}
        for child in self.children:
            item = child.item
            if isinstance(item, Assembly):
                if not item.config.get("child", False):
                    _bom_grouped_add(grouped["assemblies"], item)
                _bom_grouped_merge(grouped, await item._get_bom_grouped_locked())
            else:
                _bom_grouped_add(grouped["parts"], item)
        return grouped


def _bom_grouped_add(section: dict, item):
    """Account for one more instance of 'item' in a grouped BoM section."""
    entries = section.setdefault(item.project_name, {})
    entry = entries.setdefault(item.name, {"count": 0, "desc": getattr(item, "desc", None)})
    entry["count"] += 1


def _bom_grouped_merge(grouped: dict, other: dict):
    """Add the counts of another grouped BoM into 'grouped'."""
    for kind, packages in other.items():
        for package_name, entries in packages.items():
            target = grouped[kind].setdefault(package_name, {})
            for name, entry in entries.items():
                if name in target:
                    target[name]["count"] += entry["count"]
                else:
                    target[name] = dict(entry)
