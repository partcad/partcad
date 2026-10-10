#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

import asyncio
import os
import tempfile
import typing

from partcad_utils import assy_filter, timeouts

from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, shape_ports
from . import software as pc_software
from . import telemetry, wrapper
from .geom import Location
from .process_crash import command_failure
from .revision import package_revision
from .shape import Shape
from .shape_config import final_config as _final_config
from .sync_threads import threadpool_manager

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

    'composition' is how a connected child's location was worked out: the
    placement kept as the ordered steps it is the product of (see
    'partcad.joint'), so that 'composition.location()' is 'location' bit for
    bit. 'joint' is set when any of those steps stayed free - the child moves
    against its target - and stays None for a rigid attachment: PartCAD has no
    fixed joints. A reader that knows its joints some other way (a URDF does)
    may fill 'joint' in directly. 'joint_problems' is what resolving the joint
    found wrong with the declarations it read, which 'pc test' reports.
    """

    def __init__(
        self,
        item,
        name=None,
        location=None,
        comment=None,
        how=None,
        connection=None,
        description=None,
        located=False,
        composition=None,
        joint=None,
        joint_problems=None,
    ):
        self.item = item
        self.name = name
        self.location = location
        # Whether the ASSY file placed this item with 'location:'. Not the same
        # as 'location is not None', which every item has once it is placed,
        # connected or not.
        self.located = located
        # The non-geometric half of the 'connect'/'connectPorts' section that
        # placed this child: free-form context ('comment') and the assembly
        # instructions ('how'). Both are None unless the child was connected.
        self.comment = comment
        self.how = how
        self.connection = connection
        # What the ASSY node that placed this child says the child is, in words
        # (its 'description'). Unlike 'comment' it belongs to the node rather
        # than to a connection, so an item placed by 'location:' carries one
        # too. Like 'comment', nothing in PartCAD interprets it: it is what the
        # assembly's generated documents say about this step (assembly_guide.py).
        self.description = description
        self.composition = composition
        self.joint = joint
        self.joint_problems = list(joint_problems or [])

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
async def _recorded_box(ctx, item):
    """An item's box: the one it recorded when it was built, or else what it says when asked."""
    get_measurements = getattr(item, "get_measurements_async", None)
    if get_measurements is not None and not isinstance(item, Assembly):
        measurements = await get_measurements(ctx) or {}
        box = measurements.get(shape_envelope.METADATA_BBOX)
        if box is not None and len(box) == 6:
            return tuple(box)
    get_box = getattr(item, "get_bounding_box_async", None)
    return None if get_box is None else await get_box(ctx)


class Assembly(Shape):
    path: typing.Optional[str] = None

    def __init__(self, project_name: str, config: dict = {}):
        super().__init__(project_name, config)

        self.location = config.get("location")
        self.kind = "assembly"

        # self.children contains all child parts and assemblies before they turn into 'self.shape'
        self.children = []

        # Set by the factory (see AssemblyFactory._create): which assemblies
        # this one is built out of, without building any of them. None for an
        # assembly nobody declared - one put together in Python with 'add()' -
        # which has no declaration to read them out of.
        self._subassemblies = None

    @property
    def timeout(self) -> typing.Optional[float]:
        """The seconds this assembly declares building it may take ('timeout:'), or None.

        Announced to a waiting client while anything is done to the assembly
        (see 'Shape.locked'), and what '--fast-only' leaves it out for. See
        'partcad_utils.timeouts'.
        """
        return timeouts.declared(self.config)

    def link_name(self, index: int) -> str:
        """What this assembly addresses the child at ``index`` by.

        The one definition of it, because four things ask: a ``connect:``
        resolving its target, a ``map:`` naming a node, a filter selecting what
        to keep ('partcad.assembly_filter'), and the label this assembly stamps
        on the child's node for a reader of the tree ('_child_name_label').

        It is the child's own name where it has one -- an ASSY file's ``name:``,
        or the part or assembly the link places, which is what the factory falls
        back to -- and otherwise its position in this assembly, one-based. The
        positional form is `partcad_utils.assy_filter.synthetic_link_name`,
        shared with the half of the feature that reads the *file* rather than the
        built assembly, so ``pc filter`` and a filtered render name one link one
        way.

        An ASSY link never reaches the positional form: the factory resolves it
        as the file is read, so that a ``connect:`` can name it too (see
        'AssemblyFactoryAssy.handle_node_list'). What does reach it is a child
        that nothing named -- a STEP or URDF element whose reader gave no name,
        and an 'add()' with none -- which is exactly the case that used to be
        shown as "<assembly>:None" and could not be addressed at all.
        """
        child = self.children[index]
        return child.name if child.name is not None else assy_filter.synthetic_link_name(index)

    def link_names(self) -> list:
        """What this assembly addresses each of its children by, in order."""
        return [self.link_name(index) for index in range(len(self.children))]

    async def get_subassemblies_async(self) -> list["Assembly"]:
        """The assemblies this one places, resolved but not built.

        What a declaration points at, read from the declaration: an ASSY file's
        'assembly:' links, the object an alias or an enrich stands for. Not the
        parts, and not the sub-assemblies of the sub-assemblies - each of those
        answers the same question about itself, which is what makes an assembly
        tree walkable one level at a time.

        Prepared first, because that is what resolves the references: a link
        may name a package nothing has loaded yet, and an enrich does not know
        which instance it points at until the parameter values have reached it.
        """
        await self.prepare_async()
        if self._subassemblies is None:
            return []
        return await self._subassemblies(self)

    async def get_uncached_subassemblies_async(self, ctx) -> list["Assembly"]:
        """The distinct assemblies this one places that would have to be built.

        The first phase of building an assembly in two: what is already cached
        (or already in memory) costs nothing to use, so what is left is the
        work this assembly is really about to do, one entry per assembly however
        many times it is placed.

        An assembly that links to itself is left out of its own list - the
        recursion is reported where it is built, not here.
        """
        found = {}
        for sub in await self.get_subassemblies_async():
            # The kind is part of what identifies one: a package may declare an
            # assembly and a scene of one name, and they are two objects.
            key = (sub.kind, sub.project_name, sub.name)
            if sub is self or key in found:
                continue
            if await sub.is_cached_async(ctx):
                continue
            found[key] = sub
        return list(found.values())

    def get_async_instantiate_lock(self) -> asyncio.Lock:
        """The task lock 'do_instantiate' serializes on, one per thread.

        Not 'get_async_lock()': 'Shape.get_wrapped()' holds that one on its way
        to 'get_shape()' and so to here, and an 'asyncio.Lock' is not
        re-entrant. Thread-local, and keyed on the loop as well, exactly as
        that one is and for its reason: a worker thread runs one 'asyncio.run()'
        per instantiation, so a thread handed a second one gets a second loop,
        and an 'asyncio.Lock' awaited under the first refuses to be awaited
        under the second.
        """
        if not hasattr(self.tls, "async_instantiate_locks"):
            self.tls.async_instantiate_locks = {}
        self_id = id(self)
        loop_id = id(asyncio.get_event_loop())
        if self_id not in self.tls.async_instantiate_locks or self.tls.async_instantiate_locks[self_id][1] != loop_id:
            self.tls.async_instantiate_locks[self_id] = (asyncio.Lock(), loop_id)
        return self.tls.async_instantiate_locks[self_id][0]

    async def do_instantiate(self):
        # Both locks, the way 'Shape.get_wrapped()' takes them, and for the same
        # reason: a factory appends to 'children' rather than replacing them, so
        # whoever finds it empty a second time puts the whole tree in twice.
        #
        # The thread lock keeps two threads out of here - one rendering the
        # assembly, one resolving a part it produces
        # ('Project._materialize_derived_part'). It does not keep two tasks of
        # one loop out: an RLock is re-entrant per *thread*, and tasks of a loop
        # share one, so every one of them passes it. Hence the task lock inside
        # it, which is only ever contended within a single thread because the
        # thread lock is what excludes the others.
        with self.lock:
            async with self.get_async_instantiate_lock():
                if len(self.children) != 0:
                    return
                self._wrapped = None  # Invalidate if any
                # Detached, not constrained: an assembly does not compute
                # anything itself, it waits for the parts it is made of - and
                # each of those takes a thread out of the constrained pool.
                # Assemblies waiting in that same pool is how a render of enough
                # of them at once runs it out of threads, with every one of them
                # waiting for a part that has nowhere left to run. Now that a
                # recursive render admits several packages at a time, that is no
                # longer hypothetical.
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

    async def filtered_view_async(self, mask):
        """This assembly with only the links ``mask`` keeps, as an assembly.

        What 'Shape.filtered_view_async' is a hook for: an assembly is the one
        kind of shape that has links to select from. 'partcad.assembly_filter'
        is the whole of it, and is imported here rather than at the top because
        it imports this module.
        """
        from . import assembly_filter

        return await assembly_filter.filtered_async(self, mask)

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

        @telemetry.instrument_function_async("Assembly._get_shape_real.per_child")
        async def per_child(index, child):
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
            name, label = self._child_name_label(child, index)
            return self._place(envelope, child.location, name, label, child.joint)

        if len(self.children) == 0:
            pc_logging.warning("The assembly %s:%s is empty" % (self.project_name, self.name))

        # Children are built concurrently but collected in declaration order, so
        # the resulting tree - and every artifact derived from it - is stable
        # across runs regardless of which child's wrapper happens to finish first.
        tasks = [asyncio.create_task(per_child(index, child)) for index, child in enumerate(self.children)]
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
        reports about itself, and what it says about connections, for the same
        reason - an assembly's own ports are the ones its 'map:' externalizes,
        and two assemblies of identical geometry need not externalize the same
        ones.
        """
        name = ("%s:%s" % (self.project_name, self.name)) if self.name else self.project_name
        metadata = {"name": name, "label": self.name}
        properties = self._shape_properties()
        if properties:
            metadata[shape_envelope.KEY_PROPERTIES] = properties
        root = self._root_location()
        if root is not None:
            metadata[shape_envelope.KEY_LOCATION] = root.as_packed()
        metadata.update(shape_ports.connection_metadata(self))
        return metadata

    def _root_location(self):
        """The assembly's own location as a geom.Location, or None."""
        if isinstance(self.location, Location):
            return self.location
        if isinstance(self.location, (list, tuple)):
            return Location(self.location)
        return None

    def _child_name_label(self, child, index: int):
        """The two things a child's node says about itself, and they differ.

        'name' is the **object**: '<package>:<object>', what the child *is*. An
        assembly that places the same bolt a hundred times stamps one name on a
        hundred nodes, which is the point -- it is the identity the geometry
        table is keyed by and the name 'pc ide view' resolves.

        'label' is the **link**: what *this* assembly addresses the child by, and
        so what a 'connect:', a 'map:' and a filter name (see 'link_name'). It
        is what tells those hundred nodes apart, and it is the one a request
        coming back from a reader of the tree has to carry -- which is why it is
        never a fallback to something else: a child nothing named is labelled by
        its position rather than by the object it holds.
        """
        item = child.item
        project = getattr(item, "project_name", None)
        item_name = getattr(item, "name", None)
        name = ("%s:%s" % (project, item_name)) if project and item_name else item_name
        return name, self.link_name(index)

    def _place(self, child_env, placement, name, label, joint=None):
        """The child's node re-stamped for this assembly.

        'shape_envelope.placed()' is the composition, and is shared with
        everything else that puts a node inside a node: the name and the label
        are this assembly's account of the child, and the placement is composed
        onto whatever the child already carried.

        A child that moves against its target carries its joint on the node as
        well (KEY_JOINT), beside the properties its object reports, so that an
        exporter walking the tree ('decode: false') finds the mechanism where it
        finds the parts. It is this assembly's account of the child, like the
        label, so it is stamped here rather than by the child: one part may be
        placed rigidly once and on a hinge twice.
        """
        node = shape_envelope.placed(child_env, placement, name=name, label=label)
        if joint is not None:
            node[shape_envelope.KEY_JOINT] = joint.to_envelope()
        return node

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

    def joints(self, prefix: str = ""):
        """Every joint this assembly declares, in link order, as '(path prefix, joint)'.

        The prefix is the path of the container the two links it joins are in
        ('' at the top, 'gearbox/' inside a container named 'gearbox'), which is
        what makes 'prefix + joint.child' the path the rest of PartCAD names the
        link by. A sub-assembly the file *places* has joints of its own; they
        are its, not this one's, exactly as its connections are.
        """
        for index, child in enumerate(self.children):
            if child.joint is not None:
                yield prefix, child.joint
            item = child.item
            if isinstance(item, Assembly) and item.config.get("child", False):
                yield from item.joints(prefix + self.link_name(index) + "/")

    async def get_connect_problems(self):
        """What makes this assembly's connection instructions invalid, if anything.

        Each entry is '(child name, problem)'. The instructions are repaired in
        place as they are resolved - an assembly still builds - so this is what
        'pc test' looks at to tell a repaired one from a sound one. The joints
        are resolved the same lenient way, and what that found is here too: a
        'motion:' that contradicts itself, a 'dof' naming no parameter, two
        interfaces disagreeing about the physics of the joint they make, two
        joints of one name, and a connection that would close a loop.
        """
        await self.do_instantiate()
        problems = []
        for child in self.connected_children():
            if child.how is not None:
                problems.extend([(child.name, problem) for problem in child.how.problems])
            problems.extend([(child.name, problem) for problem in child.joint_problems])
        return problems

    async def get_bounding_box_async(self, ctx):
        """The box around everything in this assembly, built from its children's boxes.

        An assembly - one a package declares, or a 'links:' list inside an ASSY
        file, named or not - is its children where it puts them, so its box is
        theirs where it puts them: each child's box with its eight corners
        placed, the box around those, and the assembly's own placement on top.
        Nothing is built that is not built already. A part's box is the one it
        recorded when it was built; a sub-assembly's is this same composition,
        one level down.

        Where a child is turned, the box around its turned box is larger than
        the box around the turned child - never smaller. That is what a box is
        for here: deciding quickly what cannot touch what, which a box that is
        too large never gets wrong.
        """
        if self._bounding_box is not None:
            return self._bounding_box
        await self.do_instantiate()

        async def placed_corners(child):
            box = await _recorded_box(ctx, child.item)
            if box is None:
                return []
            corners = [(x, y, z) for x in (box[0], box[3]) for y in (box[1], box[4]) for z in (box[2], box[5])]
            location = child.location
            if location is None:
                return corners
            if not isinstance(location, Location):
                location = Location(location)
            return [location.transform_point(corner) for corner in corners]

        points = [point for corners in await asyncio.gather(*map(placed_corners, self.children)) for point in corners]
        if not points:
            return None
        root = self._root_location()
        if root is not None:
            points = [root.transform_point(point) for point in points]
        self._bounding_box = tuple(
            [min(point[axis] for point in points) for axis in range(3)]
            + [max(point[axis] for point in points) for axis in range(3)]
        )
        return self._bounding_box

    async def get_interference_async(self, ctx, min_volume=0.05, min_fraction=0.0, expected=(), opaque=()):
        """The pairs of parts in this assembly whose solids share space.

        Returned as {"overlaps": [{"a", "b", "volume"}, ...], "unchecked": [...],
        "parts": n}, or None when the assembly could not be realized. Measured
        in a sandbox, like every other operation on geometry: the core has no
        CAD library.

        'unchecked' names the parts a boolean could not be asked about because
        they are not valid solids. It is reported rather than hidden: a shape
        that is inside out intersects things it is nowhere near, so leaving it
        out is the only way the rest of the answer means anything - and a caller
        that was told nothing would take "no interference" for "checked".

        'min_volume' is a floor under the arithmetic: two surfaces that merely
        touch bound nothing, and a boolean over tessellated faces answers with a
        sliver rather than with zero. It is not a place to hide an overlap that
        is meant to be there.

        'expected' is that place: the pairs whose joint says they share space,
        as (a, b) name patterns. They are not measured at all, since nothing
        would be done with the answer, and a seated pin is the slowest boolean
        an assembly has. Neither is reported, then, nor counted as indeterminate.
        Each is a pair of subtrees: a part, or everything under an assembly.

        'opaque' names the declared sub-assemblies under this one whose inside
        has a verdict of its own already. Only what crosses the boundary of one
        is examined; what lies wholly inside it is that sub-assembly's business.
        """
        obj = await self.get_wrapped(ctx)
        if obj is None:
            return None

        with pc_logging.Action("Interference", self.project_name, self.name):
            # The tree travels as a JSON string rather than as itself. Anything
            # recognisable as a shape or an assembly is turned into OCCT
            # geometry on arrival (see ocp_serialize.decode), and a compound is
            # exactly what this must not be given: the names go with it, and a
            # report that two parts overlap has to be able to say which two.
            # A string is left alone, so the wrapper decodes the tree itself,
            # leaf by leaf, keeping each name attached to its solid.
            request_serialized = shape_envelope.serialize(
                {
                    # shape_envelope.dumps, not json.dumps: the envelope carries
                    # its BREP payloads as bytes, which stock JSON cannot encode
                    # at all. Getting this wrong raised a TypeError that the
                    # test caught and reported as a pass, so the check answered
                    # "no interference" for every assembly without ever looking
                    # at one.
                    "assembly_json": shape_envelope.dumps(obj),
                    "min_volume": min_volume,
                    "min_fraction": min_fraction,
                    "expected": [list(pair) for pair in expected],
                    "opaque": list(opaque),
                }
            )

            runtime = ctx.get_python_runtime(version="3.11")
            await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

            # The wrapper writes nothing, but every wrapper is invoked with an
            # output path; give it one inside a directory of our own.
            with tempfile.TemporaryDirectory(prefix="partcad-interference-") as unused_dir:
                command = [wrapper.get("interference.py"), os.path.join(unused_dir, "unused.txt")]
                exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized)
            if exitcode != 0 and len(errors) == 0:
                errors = command_failure(command, exitcode)
            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

            response_lines = response_serialized.strip().splitlines()
            if not response_lines:
                pc_logging.error("Empty response from wrapper: %s" % command[0])
                return None
            result = shape_envelope.deserialize(response_lines[-1].strip())

            if not result.get("success", False):
                pc_logging.error(
                    "Interference failed for %s:%s: %s"
                    % (self.project_name, self.name, result.get("exception", "Unknown error"))
                )
                return None
            return {
                "overlaps": result.get("overlaps", []),
                "unchecked": result.get("unchecked", []),
                "indeterminate": result.get("indeterminate", []),
                "parts": result.get("parts", 0),
            }

    async def get_step_problems(self, include_located: bool = True):
        """What keeps the steps of this assembly from being followed by hand.

        Each entry is '(child name, problem)'. Somebody putting the assembly
        together needs every item after the first to say what it is joined to
        - a 'connect' or 'connectPorts' section - and how it goes on: pushed,
        snapped or screwed in, said by that section's 'how' or by the mating or
        the interfaces it connects through (see 'ConnectHow.motion_declared()').
        The first item of each list of links is what the rest is added to, and
        is joined to nothing.

        'include_located' also reports items placed by 'location:', the first
        included: a coordinate says where a thing ends up and not what holds it
        there. The 'connectivity' test already fails a manufacturable assembly
        for that, so the 'manufacturability' test leaves it out rather than
        failing the same item twice.

        Read from the declarations as they are instantiated; nothing is built.
        """
        await self.do_instantiate()
        problems = []

        def walk(assembly):
            for index, child in enumerate(assembly.children):
                name = child.name or getattr(child.item, "name", None) or "item %d" % (index + 1)
                if child.located:
                    if include_located:
                        problems.append((name, "it is placed by 'location:', which does not say what it is joined to"))
                elif index > 0 and child.connection is None:
                    problems.append((name, "it is not connected to anything: it has no 'connect' section"))
                elif index > 0 and (child.how is None or not child.how.motion_declared()):
                    problems.append(
                        (
                            name,
                            "nothing says how it is put in place: its 'connect' section has no 'how', and "
                            "neither the mating nor the interfaces it connects through say whether it is "
                            "pushed, snapped or screwed in",
                        )
                    )
                item = child.item
                if isinstance(item, Assembly) and item.config.get("child", False):
                    walk(item)

        walk(self)
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
        which the supply quote asks. The two are easy to conflate and are not
        interchangeable: this one says what the model intends, that one says
        what can be bought today.
        """
        if self.config.get("child", False):
            return False
        return self.get_store_data().is_purchasable

    async def get_supply_bom(self, ctx=None):
        """The bill of materials to procure this assembly from.

        Same shape of result as 'get_bom()', but the walk stops at every
        sub-assembly the model declares as supplied assembled (see
        'is_declared_purchasable()'): such a sub-assembly is listed itself,
        instead of its contents. An assembly the model does not declare that
        way is procured as the parts it is made of instead. Whether anybody
        actually has one available is a question for the suppliers and is not
        asked here.

        Given 'ctx', a part is listed as what it is *procured* as (see
        'partcad.procurement'): a part that is made is replaced by the stock it
        is made from, one piece per part, so this is what has to be bought.
        Without one, every part is listed as itself -- which is the list of
        what has to be *had*, bought or made, and is what the manufacturability
        test walks, because a made part is something it has to test too.
        """
        with self.lock:
            async with self.get_async_lock():
                await self.do_instantiate()
                if hasattr(self, "project_name"):
                    # This is the top level assembly
                    with pc_logging.Action("SupplyBoM", self.project_name, self.name):
                        return await self._get_supply_bom_real(ctx)
                else:
                    return await self._get_supply_bom_real(ctx)

    async def _get_supply_bom_real(self, ctx=None):
        from . import procurement

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
                for child_name, child_count in (await item.get_supply_bom(ctx)).items():
                    account_for(child_name, child_count)
            elif ctx is not None and not isinstance(item, Assembly):
                for name in await procurement.procured_as(ctx, item):
                    account_for(name, 1)
            else:
                account_for(item.project_name + ":" + item.name, 1)

        return bom

    async def get_bom_grouped_async(self, ctx=None):
        """The recursive contents of this assembly, grouped by package.

        Unlike 'get_bom()', which flattens the whole tree into a map of part
        names, this keeps parts, sub-assemblies and software apart and groups
        each of them by the package they come from:

            {
                "parts": {"//package": {"name": {"count": 2, "desc": "..."}}},
                "assemblies": {...},
                "software": {"//package": {"name": {"count": 1, "desc": "...",
                                                    "revision": "<commit id>"}}},
            }

        Assemblies embedded in the parent's source file (the nested 'links:' of
        an ASSY file) are not objects of any package, so they are not listed:
        their contents are attributed to the assembly that embeds them.

        Software is what the parts, the sub-assemblies and this assembly itself
        declare they ship with (see 'software' in 'partcad.yaml'). Resolving a
        reference needs 'ctx', because the software may well come from another
        package; without one the software section comes back empty rather than
        half-filled with names nothing was read from.
        """
        with pc_logging.Action("BoMGrouped", self.project_name, self.name):
            return await self._get_bom_grouped_locked(ctx)

    def get_bom_grouped(self, ctx=None):
        return asyncio.run(self.get_bom_grouped_async(ctx))

    async def _get_bom_grouped_locked(self, ctx=None):
        with self.lock:
            async with self.get_async_lock():
                await self.do_instantiate()
                return await self._get_bom_grouped_real(ctx)

    async def _get_bom_grouped_real(self, ctx):
        grouped = {"parts": {}, "assemblies": {}, "software": {}, "stock": {}, "manufactured": {}}
        # This assembly's own software first: an assembly that ships a firmware
        # image ships it whether or not any of its parts say so.
        _bom_grouped_add_software(grouped["software"], ctx, self)
        for child in self.children:
            item = child.item
            if isinstance(item, Assembly):
                if not item.config.get("child", False):
                    _bom_grouped_add(grouped["assemblies"], item)
                _bom_grouped_merge(grouped, await item._get_bom_grouped_locked(ctx))
            else:
                _bom_grouped_add(grouped["parts"], item)
                _bom_grouped_add_software(grouped["software"], ctx, item)
                await _bom_grouped_add_manufactured(grouped, ctx, item)
        return grouped

    async def get_bom_detailed_async(self, ctx=None, stop_at_purchasable: bool = False):
        """The flattened BoM of this assembly, one entry per line item.

        Like 'get_bom()', the tree is flattened into a map keyed by the object's
        full name, counting how many times each occurs. Unlike it, every entry
        also carries what a bill of materials is read for: whether the item is a
        part, an assembly or stock, its description, and the store data that
        says what to order.

            {"//package:name": {"kind": "part", "count": 2, "desc": "...",
                                "vendor": None, "sku": None, "count_per_sku": 1,
                                "item_in_sku": None}}

        It lists what has to be procured, by the rule 'get_supply_bom()' and
        the cart follow, so that the three agree:

        * a sub-assembly that declares a vendor and an SKU is one line item, of
          kind "assembly" -- ordered whole, and nothing inside it is listed (see
          'is_declared_purchasable()');
        * any other sub-assembly is expanded into its own bill of materials;
        * a part is what it is procured as (see 'partcad.procurement'): itself
          when it declares a vendor and an SKU, or says neither how it is
          bought nor how it is made; the stock it is made from when it is made,
          followed while that stock is made in turn, as a line item of kind
          "stock"; and nothing when it is made from nothing it names.

        Which sub-assembly is ordered whole is decided by the declaration alone,
        offline: whether anybody has one today is the supply quote's question.
        Without 'ctx' no stock can be looked up, and every part is listed as
        itself.

        Software the objects ship with is listed too, as entries of kind
        "software" (see 'get_bom_grouped_async'). A software line item is the
        file itself, so instead of a vendor and an SKU it carries what
        identifies that file: the package it comes from, the revision of that
        package, and the version and hash the declaration pins it to. Its
        'count' is how many times something in this assembly needs it - three
        boards running one firmware image is a count of three, the same way
        three of anything else is. A part listed as its stock still ships its
        software; an assembly ordered whole comes with its own already on it.

        'stop_at_purchasable' is accepted and changes nothing. It used to be
        what made a sub-assembly with a vendor and an SKU a line item, and then
        only one a supplier reported in stock; every sub-assembly that declares
        both is one now.
        """
        with pc_logging.Action("BoMDetailed", self.project_name, self.name):
            return await self._get_bom_detailed_locked(ctx)

    def get_bom_detailed(self, ctx=None, stop_at_purchasable: bool = False):
        return asyncio.run(self.get_bom_detailed_async(ctx, stop_at_purchasable))

    async def _get_bom_detailed_locked(self, ctx):
        with self.lock:
            async with self.get_async_lock():
                await self.do_instantiate()
                return await self._get_bom_detailed_real(ctx)

    async def _get_bom_detailed_real(self, ctx):
        bom = {}
        _bom_detailed_add_software(bom, ctx, self)
        for child in self.children:
            item = child.item
            if isinstance(item, Assembly):
                # An assembly embedded in the parent's source file belongs to no
                # package, so there is no name to order it by; it is always
                # expanded, exactly as the grouped BoM treats it. That rule is
                # part of 'is_declared_purchasable()'.
                if item.is_declared_purchasable():
                    # Bought whole, and so is whatever is inside it - the
                    # firmware its boards run comes flashed, and is no more a
                    # line item here than its screws are.
                    _bom_detailed_add(bom, item, "assembly")
                    continue
                _bom_detailed_merge(bom, await item._get_bom_detailed_locked(ctx))
            else:
                await _bom_detailed_add_part(bom, ctx, item)
                _bom_detailed_add_software(bom, ctx, item)
        return bom


def _bom_grouped_add(section: dict, item):
    """Account for one more instance of 'item' in a grouped BoM section."""
    entries = section.setdefault(item.project_name, {})
    entry = entries.setdefault(item.name, {"count": 0, "desc": getattr(item, "desc", None)})
    entry["count"] += 1


async def _bom_grouped_add_manufactured(grouped: dict, ctx, item):
    """Account for a part that is made rather than bought, and for its stock.

    Two sections. 'manufactured' lists the parts to be made, each with the
    stock it is made from, which is what the instruction book opens with.
    'stock' lists what has to be procured to make them, followed to the end of
    the chain (see 'partcad.procurement'), one piece per part -- and which parts
    each piece is for, because "4 of these" is not a cut list.
    """
    from . import procurement

    if ctx is None or procurement.is_bought(item) or not procurement.is_made(item):
        return
    stock = procurement.stock_name(item)
    entries = grouped["manufactured"].setdefault(item.project_name, {})
    entry = entries.setdefault(item.name, {"count": 0, "desc": getattr(item, "desc", None), "stock": stock})
    entry["count"] += 1

    for name in await procurement.procured_as(ctx, item):
        package_name, _, object_name = name.partition(":")
        stock_entries = grouped["stock"].setdefault(package_name, {})
        stock_entry = stock_entries.get(object_name)
        if stock_entry is None:
            resolved = await procurement.get_part_async(ctx, name)
            stock_entry = stock_entries[object_name] = {
                "count": 0,
                "desc": getattr(resolved, "desc", None),
                "for": [],
            }
        stock_entry["count"] += 1
        made = "%s:%s" % (item.project_name, item.name)
        if made not in stock_entry["for"]:
            stock_entry["for"].append(made)


def _software_of(ctx, item):
    """The (reference, package, software) triples an object ships with.

    A reference that resolves to nothing is dropped here, after 'lookup' has
    reported it: a bill of materials that silently invented a line item for a
    name nothing was read from would be worse than one that is short by it.
    """
    if ctx is None:
        return []
    found = []
    for ref in pc_software.resolved_software_refs(item.project_name, _final_config(item)):
        project, software = pc_software.lookup(ctx, ref)
        if software is None:
            continue
        found.append((ref, project, software))
    return found


def _bom_grouped_add_software(section: dict, ctx, item):
    """Account for the software 'item' ships with in a grouped BoM section."""
    for _ref, project, software in _software_of(ctx, item):
        entries = section.setdefault(software.project_name, {})
        entry = entries.setdefault(
            software.name,
            {
                "count": 0,
                "desc": software.desc or None,
                # The commit the package was read at. Without it the line names
                # a file that changes whenever the package publishes again,
                # which for software is the whole of what identifies it.
                "revision": package_revision(project),
                "version": software.config.get("version"),
                "fileHash": software.declared_hash(),
            },
        )
        entry["count"] += 1


def _bom_grouped_merge(grouped: dict, other: dict):
    """Add the counts of another grouped BoM into 'grouped'."""
    for kind, packages in other.items():
        for package_name, entries in packages.items():
            target = grouped[kind].setdefault(package_name, {})
            for name, entry in entries.items():
                if name in target:
                    target[name]["count"] += entry["count"]
                    for made in entry.get("for") or []:
                        if made not in target[name].setdefault("for", []):
                            target[name]["for"].append(made)
                else:
                    target[name] = dict(entry)
                    if "for" in entry:
                        target[name]["for"] = list(entry["for"])


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
            "item_in_sku": store_data.item_in_sku,
        }
    entry["count"] += 1


async def _bom_detailed_add_part(bom: dict, ctx, part):
    """Account for one more instance of a part: what it is procured as.

    Itself when it is bought, or says neither how it is bought nor how it is
    made; the stock it is made from when it is made, followed while that is made
    in turn; nothing when it is made from nothing it names (see
    'partcad.procurement'). Without a context nothing can be looked up, and the
    part is listed as itself.
    """
    from . import procurement

    if ctx is None:
        _bom_detailed_add(bom, part, "part")
        return
    own = "%s:%s" % (part.project_name, part.name)
    for name in await procurement.procured_as(ctx, part):
        if name == own:
            _bom_detailed_add(bom, part, "part")
        else:
            await _bom_detailed_add_stock_piece(bom, ctx, name)


async def _bom_detailed_add_stock_piece(bom: dict, ctx, name: str):
    """Account for one more piece of stock, by its fully qualified name.

    A name that resolves to nothing is still a line item -- the cart and the
    test say it is missing -- just one with nothing to order it by.
    """
    from . import procurement

    entry = bom.get(name)
    if entry is None:
        resolved = await procurement.get_part_async(ctx, name)
        store_data = resolved.get_store_data() if resolved is not None else None
        entry = bom[name] = {
            "kind": "stock",
            "count": 0,
            "desc": getattr(resolved, "desc", None),
            "vendor": store_data.vendor if store_data else None,
            "sku": store_data.sku if store_data else None,
            "count_per_sku": store_data.count_per_sku if store_data else 1,
            "item_in_sku": store_data.item_in_sku if store_data else None,
        }
    entry["count"] += 1


async def part_bom_detailed_async(ctx, part) -> dict:
    """The detailed BoM of one part: what one of it is procured as.

    The same rule an assembly's BoM applies to each of its parts, and the same
    shape of line item ('Assembly.get_bom_detailed_async()'), with the part as
    the whole of the tree (see 'partcad.procurement'):

    * a part that is bought, or that says neither how it is bought nor how it is
      made, is its own bill of materials: one of itself;
    * a part that is made is the stock it is made from -- followed while that is
      made in turn, so a blank cut from a sheet cut from a roll is one roll;
    * a part made from nothing it names, printed or formed, needs nothing
      procured, and its bill of materials is empty.

    The software it ships with is listed as well, as an assembly lists that of
    each of its parts.
    """
    bom = {}
    with pc_logging.Action("BoMDetailed", part.project_name, part.name):
        await _bom_detailed_add_part(bom, ctx, part)
        _bom_detailed_add_software(bom, ctx, part)
    return bom


def _bom_detailed_add_software(bom: dict, ctx, item):
    """Account for the software 'item' ships with in a detailed BoM."""
    for ref, project, software in _software_of(ctx, item):
        entry = bom.get(ref)
        if entry is None:
            entry = bom[ref] = {
                "kind": "software",
                "count": 0,
                "desc": software.desc or None,
                # Kept so that every line item of a BoM has the same shape,
                # whatever it is: a reader that asks for the vendor of a line
                # should get an answer rather than a KeyError.
                "vendor": None,
                "sku": None,
                "count_per_sku": 1,
                "item_in_sku": None,
                "package": software.project_name,
                "revision": package_revision(project),
                "type": software.type,
                "version": software.config.get("version"),
                "fileHash": software.declared_hash(),
            }
        entry["count"] += 1


def _bom_detailed_merge(bom: dict, other: dict):
    """Add the counts of another detailed BoM into 'bom'."""
    for name, entry in other.items():
        if name in bom:
            bom[name]["count"] += entry["count"]
        else:
            bom[name] = dict(entry)
