#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'step' assembly type: a STEP assembly used directly as a PartCAD assembly.

A STEP file that carries an assembly structure already says what a PartCAD
assembly says: a tree of named components, each placed by a transform. Read it
and the result is the very same in-memory representation an ASSY file produces -
a tree of 'Assembly'/'AssemblyChild' objects wrapping 'Part's - so everything
downstream (rendering, export, BoM, inspection, caching) treats a STEP assembly
and an ASSY assembly identically.

Every component becomes one part, registered into the package as
``<assembly name>/<component name>``. Those parts are ordinary parts: they can
be inspected, rendered and exported on their own. They are not declared in
``partcad.yaml`` - the STEP file is what declares them - so a package resolves
such a name by building the assembly that owns it first (see
``Project._derived_part_owner``).

The reading is done by wrapper_import_assy inside a python sandbox, through
assembly_step_reader: STEP-CAF is OCCT, which the core process never loads. What
comes back here is plain data plus one STEP file per distinct shape, written
under PartCAD's own state directory.

This is the standing half of reading a STEP assembly. 'pc import assembly' is
the one-shot half: it runs the same reader but writes the parts and an '.assy'
file into the package, after which the package owns them and the STEP file is no
longer consulted. Declare 'type: step' when the STEP file is to stay the source
of truth (a vendor's file, one that is regenerated, one pulled from a URL); run
'pc import assembly' when the structure is to be taken over and edited.
"""

import asyncio
import hashlib
import os

from . import assembly_step_reader
from . import logging as pc_logging
from . import telemetry
from .assembly import Assembly, AssemblyChild
from .assembly_factory_file import AssemblyFactoryFile
from .geom import Location
from .part_config import PartConfiguration


@telemetry.instrument()
class AssemblyFactoryStep(AssemblyFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSTEP", source_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".step")
            self._create(config)
            # Which parts a STEP file resolves to is only known once it has been
            # read, so the dependency set cannot be hashed up front - the same
            # reason the ASSY factory marks itself this way.
            self.assembly.cache_dependencies_broken = True
            for dep in self.config.get("dependencies", []):
                self.assembly.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
            # Generated STEP file -> the Part registered for it. Keyed by the
            # file and not by the node: the reader deduplicates by geometry, so
            # the same shape placed twice is one part in two places.
            self._parts = {}

    def instantiate(self, assembly):
        asyncio.run(self.instantiate_async(assembly))

    async def instantiate_async(self, assembly):
        await super().instantiate(assembly)

        with pc_logging.Action("STEP", assembly.project_name, assembly.name):
            root = await self._read_async()

            # This assembly *is* the STEP file's root, so what it holds are the
            # root's own components rather than the root wrapped in one more
            # level. A file whose root is a single shape becomes an assembly of
            # that one part - which is what 'pc import assembly' writes too.
            if root["type"] == "assembly":
                await self.handle_node_list(assembly, root.get("links") or [])
            else:
                child = await self.handle_node(assembly, root)
                if child is not None:
                    assembly.children.append(child)

            if not assembly.children:
                pc_logging.warning("Assembly is empty")

            self.ctx.stats_assemblies_instantiated += 1

    async def _read_async(self):
        """Run the STEP reader in a sandbox and return its data tree."""
        return await assembly_step_reader.read_assembly_tree(
            self.ctx,
            self.path,
            self._generated_dir(),
            precision=self.config.get("precision", 5),
        )

    def _generated_dir(self):
        """Where the STEP file written for each distinct shape goes.

        Under PartCAD's own state directory rather than inside the package: the
        parts a STEP assembly is made of are derived data, and using an assembly
        should not drop files into the user's source tree. 'pc import assembly'
        is the command that deliberately materializes them into the package.
        """
        digest = hashlib.sha256(os.path.abspath(self.path).encode()).hexdigest()[:16]
        return os.path.join(self.ctx.user_config.internal_state_dir, "step", digest)

    async def handle_node_list(self, assembly, nodes):
        for node in nodes:
            child = await self.handle_node(assembly, node)
            if child is not None:
                assembly.children.append(child)

    async def handle_node(self, assembly, node):
        """Turn one node of the reader's tree into an AssemblyChild."""
        name = node.get("name")
        # Only a part node carries a placement: the reader folds each parent's
        # transform into the shapes below it, so a sub-assembly sits at the
        # origin and the placements it contains are already absolute.
        location = Location(node["location"]) if node.get("location") else Location()

        if node["type"] == "assembly":
            config = {
                "name": "%s:%s" % (self.name, name),
                "child": True,
                "cache": self.ctx.user_config.cache,
                "cache_dependencies_ignore": self.ctx.user_config.cache_dependencies_ignore,
            }
            item = Assembly(assembly.project_name, config)
            # Keep it uncacheable before the parts info is in the hashing context
            item.cacheable = False
            item.instantiate = lambda _self: True
            await self.handle_node_list(item, node.get("links") or [])
            if not item.children:
                return None
        else:
            item = self.part_for(node)
            if item is None:
                return None

        return AssemblyChild(item, name, location)

    def part_name(self, part_file):
        """The package-wide name of the part one shape of the STEP file becomes.

        ``<assembly>/<component name>``, taken from the file the reader wrote
        rather than from the node itself: STEP labels repeat freely across
        different geometry, and the reader has already made the file names
        unique (a second, different 'Plate' lands in 'Plate_1.step'). It is also
        exactly the name 'pc import assembly' gives the very same part.
        """
        return "%s/%s" % (self.name, os.path.splitext(os.path.basename(part_file))[0])

    def part_for(self, node):
        """The Part for one shape of the STEP file, registering it on first use.

        The parts are registered in memory only - the STEP file is what declares
        them, not ``partcad.yaml`` - which is why 'Project.get_part' builds the
        owning assembly when it is handed one of these names.
        """
        part_file = os.path.abspath(node["part_file"])
        if part_file in self._parts:
            return self._parts[part_file]

        part_name = self.part_name(part_file)
        config = {
            "type": "step",
            "name": part_name,
            "orig_name": part_name,
            "path": part_file,
            "desc": "Component '%s' of the STEP assembly '%s'" % (node.get("name") or part_name, self.name),
        }

        full_name = "%s:%s" % (self.project.name, part_name)
        config = PartConfiguration.normalize(part_name, config, full_name)
        try:
            part = self.project.materialize_part_by_config(config)
        except Exception as e:
            pc_logging.error("%s: failed to add the part '%s': %s" % (self.name, part_name, e))
            return None

        if part is None:
            pc_logging.error("%s: the part '%s' failed to instantiate" % (self.name, part_name))
            return None
        self.assembly.cache_dependencies.append(part_file)
        self._parts[part_file] = part
        return part
