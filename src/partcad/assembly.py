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
from .plugin_provider_data_cart import ProviderCartItem
from .shape import Shape
from .sync_threads import threadpool_manager
from . import logging as pc_logging

# This module needs no CAD library at all: an assembly is built as a nested
# BREP-envelope object with child placements carried as plain data, and the
# geometry is only realized (with OCP) later, inside a sandbox wrapper.


class AssemblyChild:
    """One item placed into an assembly.

    'connection' is set when the item was placed by connecting it to another
    child rather than at an absolute location: it records which child it was
    connected to and where the two ports met, so that an assembly instruction
    book can show that step (see assembly_guide.py). It stays 'None' for items
    placed with 'location:', and for assemblies built through 'add()'.
    """

    def __init__(self, item, name=None, location=None, comment=None, how=None, connection=None):
        self.item = item
        self.name = name
        self.location = location
        # The non-geometric half of the 'connect'/'connectPorts' section that
        # placed this child: free-form context ('comment') and the assembly
        # instructions ('how'). Both are None unless the child was connected.
        self.comment = comment
        self.how = how
        self.connection = connection

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
            # Detached, not constrained: an assembly does not compute anything
            # itself, it waits for the parts it is made of - and each of those
            # takes a thread out of the constrained pool. Assemblies waiting in
            # that same pool is how a render of enough of them at once runs it
            # out of threads, with every one of them waiting for a part that
            # has nowhere left to run. Now that a recursive render admits
            # several packages at a time, that is no longer hypothetical.
            await threadpool_manager.run_detached(self.instantiate, self)
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

        envelope = dict(self.get_cache_metadata())
        envelope[shape_envelope.KEY_ASSEMBLY] = children
        return envelope

    def get_cache_metadata(self):
        """The outer layer to wrap around this assembly's cached children.

        It has to be exactly what '_get_shape_real()' stamps on the tree it
        builds, so that an assembly materialized from the cache is
        indistinguishable from one just built. Besides the name and the label
        that every shape carries, an assembly carries its own placement: two
        assemblies of the same children in different places share the cached
        children but must not inherit each other's location. It carries what it
        reports about itself for the same reason.
        """
        name = ("%s:%s" % (self.project_name, self.name)) if self.name else self.project_name
        metadata = {"name": name, "label": self.name}
        properties = self._shape_properties()
        if properties:
            metadata[shape_envelope.KEY_PROPERTIES] = properties
        root = self._root_location()
        if root is not None:
            metadata[shape_envelope.KEY_LOCATION] = root.as_packed()
        return metadata

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

    async def get_connect_problems(self):
        """What makes this assembly's connection instructions invalid, if anything.

        Each entry is '(child name, problem)'. The instructions are repaired in
        place as they are resolved - an assembly still builds - so this is what
        'pc test' looks at to tell a repaired one from a sound one.
        """
        await self.do_instantiate()
        problems = []
        for child in self.connected_children():
            if child.how is None:
                continue
            problems.extend([(child.name, problem) for problem in child.how.problems])
        return problems

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

    def is_declared_purchasable(self) -> bool:
        """Whether the model declares this assembly as ordered whole, assembled.

        This is a property of the *model*, not of the market: it reads what the
        package says about the assembly and asks no supplier anything, so it is
        answerable offline and costs nothing. That is what a BoM walk needs in
        order to decide whether to descend into a sub-assembly.

        An assembly embedded in its parent's source file (the nested 'links:' of
        an ASSY file) is not an object of any package, so there is no name to
        order it by no matter what it declares: its contents are procured
        instead.

        Whether anybody actually sells it is the other, market-side question,
        answered by '_is_available_to_buy()'. The two are easy to conflate and
        are not interchangeable: this one says what the model intends, that one
        says what can be bought today.
        """
        if self.config.get("child", False):
            return False
        return self.get_store_data().is_purchasable

    async def get_supply_bom(self):
        """The bill of materials to procure this assembly from.

        Same shape of result as 'get_bom()', but the walk stops at every
        sub-assembly the model declares as supplied assembled (see
        'is_declared_purchasable()'): such a sub-assembly is listed itself,
        instead of its contents. An assembly the model does not declare that
        way is procured as the parts it is made of instead. Whether anybody
        actually has one available is a question for the suppliers and is not
        asked here.
        """
        with self.lock:
            async with self.get_async_lock():
                await self.do_instantiate()
                if hasattr(self, "project_name"):
                    # This is the top level assembly
                    with pc_logging.Action("SupplyBoM", self.project_name, self.name):
                        return await self._get_supply_bom_real()
                else:
                    return await self._get_supply_bom_real()

    async def _get_supply_bom_real(self):
        bom = {}

        def account_for(name, count):
            if name in bom:
                bom[name] += count
            else:
                bom[name] = count

        for child in self.children:
            item = child.item
            if isinstance(item, Assembly) and not item.is_declared_purchasable():
                # Nobody sells it assembled: procure whatever it is made of
                for child_name, child_count in (await item.get_supply_bom()).items():
                    account_for(child_name, child_count)
            else:
                account_for(item.project_name + ":" + item.name, 1)

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

    async def get_bom_detailed_async(self, ctx=None, stop_at_purchasable: bool = False):
        """The flattened BoM of this assembly, one entry per line item.

        Like 'get_bom()', the tree is flattened into a map keyed by the object's
        full name, counting how many times each occurs. Unlike it, every entry
        also carries what a bill of materials is read for: whether the item is a
        part or an assembly, its description, and the store data that says what
        to order.

            {"//package:name": {"kind": "part", "count": 2, "desc": "...",
                                "vendor": None, "sku": None, "count_per_sku": 1}}

        With 'stop_at_purchasable', a sub-assembly that can be bought whole -- it
        declares a vendor and an SKU, and a supplier of its package has it
        available -- becomes a line item of its own instead of being expanded
        into its contents. It is then one thing to order rather than a list of
        parts to source and assemble, and nothing below it appears in the BoM.
        Querying the suppliers needs 'ctx'; without one, nothing is purchasable.
        """
        with pc_logging.Action("BoMDetailed", self.project_name, self.name):
            return await self._get_bom_detailed_locked(ctx, stop_at_purchasable, {})

    def get_bom_detailed(self, ctx=None, stop_at_purchasable: bool = False):
        return asyncio.run(self.get_bom_detailed_async(ctx, stop_at_purchasable))

    async def _get_bom_detailed_locked(self, ctx, stop_at_purchasable, purchasable: dict):
        with self.lock:
            async with self.get_async_lock():
                await self.do_instantiate()
                return await self._get_bom_detailed_real(ctx, stop_at_purchasable, purchasable)

    async def _get_bom_detailed_real(self, ctx, stop_at_purchasable, purchasable: dict):
        bom = {}
        for child in self.children:
            item = child.item
            if isinstance(item, Assembly):
                # An assembly embedded in the parent's source file belongs to no
                # package, so there is no name to order it by; it can only ever be
                # expanded, exactly as the grouped BoM treats it. That rule is
                # part of the declaration half of '_is_available_to_buy()'.
                if stop_at_purchasable and await _is_available_to_buy(ctx, item, purchasable):
                    _bom_detailed_add(bom, item, "assembly")
                    continue
                child_bom = await item._get_bom_detailed_locked(ctx, stop_at_purchasable, purchasable)
                _bom_detailed_merge(bom, child_bom)
            else:
                _bom_detailed_add(bom, item, "part")
        return bom


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


def _bom_detailed_add(bom: dict, item, kind: str):
    """Account for one more instance of 'item' in a detailed BoM."""
    name = "%s:%s" % (item.project_name, item.name)
    entry = bom.get(name)
    if entry is None:
        store_data = item.get_store_data()
        entry = bom[name] = {
            "kind": kind,
            "count": 0,
            "desc": getattr(item, "desc", None),
            "vendor": store_data.vendor,
            "sku": store_data.sku,
            "count_per_sku": store_data.count_per_sku,
        }
    entry["count"] += 1


def _bom_detailed_merge(bom: dict, other: dict):
    """Add the counts of another detailed BoM into 'bom'."""
    for name, entry in other.items():
        if name in bom:
            bom[name]["count"] += entry["count"]
        else:
            bom[name] = dict(entry)


async def _is_available_to_buy(ctx, assembly, cache: dict) -> bool:
    """Whether 'assembly' can be bought whole today instead of being assembled.

    Where 'Assembly.is_declared_purchasable()' answers a question about the
    model, this answers one about the *market*, and so it has to query the
    suppliers. Both halves are required: what the model declares as orderable,
    and a supplier of the assembly's own package that has it available. Either
    half on its own is not something a buyer can act on, which is why a
    procurement answer cannot be given offline the way a BoM walk can.

    The declaration half is delegated to 'is_declared_purchasable()' rather than
    re-derived here, so that the two never drift apart -- an assembly embedded
    in its parent's source file, for one, is never orderable by name.

    The answer is cached per assembly, so a sub-assembly used many times costs
    one supplier query rather than one per instance.
    """
    if ctx is None:
        return False

    name = "%s:%s" % (assembly.project_name, assembly.name)
    if name in cache:
        return cache[name]

    def answer(value: bool) -> bool:
        cache[name] = value
        return value

    if not assembly.is_declared_purchasable():
        return answer(False)

    # Whether the package declares any supplier at all is asked here rather than
    # left to 'find_part_suppliers()': that reports the absence as an error, and
    # a package that simply does not sell anything is not one.
    project = ctx.get_project(assembly.project_name)
    if project is None or not project.get_suppliers():
        return answer(False)

    item = ProviderCartItem()
    item.set_shape(assembly)
    # 'find_part_suppliers()' keeps only the providers that report the item as
    # available, so a non-empty result is the availability answer.
    return answer(bool(await ctx.find_part_suppliers(item)))
