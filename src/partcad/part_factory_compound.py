#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from . import part_factory as pf
from . import logging as pc_logging
from .utils import resolve_resource_path, get_child_project_path
from . import telemetry


@telemetry.instrument()
class PartFactoryCompound(pf.PartFactory):
    """A part that is the TopoDS_Compound of a referenced assembly.

    An assembly preserves its hierarchy; a 'compound' part flattens a referenced
    assembly into a single part. If - and only if - the part declares
    'parameters', those are passed verbatim to the assembly to produce the shape
    that is compounded.
    """

    source_assembly_name: str
    source_project_name: str
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitCompound", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            self._create(config)

            if "source" in config:
                self.source_assembly_name = config["source"]
            else:
                self.source_assembly_name = config["name"]
                if "project" not in config and "package" not in config:
                    raise Exception("Compound needs either the source assembly name or the source project name")

            if "project" in config or "package" in config:
                self.source_project_name = config["project"] if "project" in config else config["package"]
                if self.source_project_name == "this" or self.source_project_name == "":
                    self.source_project_name = source_project.name
                elif not self.source_project_name.startswith("//"):
                    self.source_project_name = get_child_project_path(target_project.name, self.source_project_name)
            elif ":" in self.source_assembly_name:
                self.source_project_name, self.source_assembly_name = resolve_resource_path(
                    source_project.name,
                    self.source_assembly_name,
                )
            else:
                self.source_project_name = source_project.name

            self.source = self.source_project_name + ":" + self.source_assembly_name
            config["source_resolved"] = self.source

            # Passed verbatim to the assembly, but only when declared.
            self.parameters = config.get("parameters", None)

            self.part.desc = "Compound of %s" % self.source

    async def prepare_async(self, part) -> None:
        """Resolve the referenced assembly, then prepare it.

        The assembly may live in another package, so resolving it loads - and
        so downloads - that package, and preparing it reaches everything the
        assembly links to in turn.
        """
        params = self.parameters if self.parameters else None
        assembly = self.ctx._get_assembly(self.source, params)
        if assembly is None:
            raise Exception("compound source assembly not found: %s" % self.source)
        await assembly.prepare_async()

    async def instantiate(self, part):
        with pc_logging.Action("Compound", part.project_name, part.name):
            params = self.parameters if self.parameters else None
            assembly = self.ctx._get_assembly(self.source, params)
            if assembly is None:
                part.error("%s: compound source assembly not found: %s" % (part.name, self.source))
                return None

            shape = await assembly.get_wrapped(self.ctx)
            if shape is None:
                part.error("%s: compound source assembly produced no shape: %s" % (part.name, self.source))
                return None

            self.ctx.stats_parts_instantiated += 1
            return shape
