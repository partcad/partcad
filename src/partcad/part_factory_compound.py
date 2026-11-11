#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from . import assembly_compound
from . import logging as pc_logging
from . import part_factory as pf
from . import reference, sandbox_versions, telemetry


@telemetry.instrument()
class PartFactoryCompound(pf.PartFactory):
    """A part that is the TopoDS_Compound of a referenced assembly.

    An assembly preserves its hierarchy; a 'compound' part flattens a referenced
    assembly into a single part: one shape, every item of the assembly placed
    in it, with the colours and materials each states on its own faces (see
    'partcad.assembly_compound', which is also what 'pc export --compound'
    makes of an assembly). If - and only if - the part declares 'parameters',
    those are passed verbatim to the assembly to produce the shape that is
    compounded.
    """

    # The compound is made in a sandbox, by 'wrapper_transform.flatten'. Until
    # it was, this part was the assembly's tree under the part's name - not a
    # part at all, for anything that asked - and the wrapper's version in its
    # key is what keeps an entry cached in that form from being read back.
    WRAPPERS = assembly_compound.WRAPPERS
    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    source_assembly_name: str
    source_project_name: str
    source: str

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitCompound", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            self._create(config)

            # Where this points, by the rules every reference spells it with
            # (see 'partcad.reference'), and recorded on the declaration so a
            # listing can read its description off it without building it.
            self.source = reference.source_of(source_project, target_project.name, config, "assembly")
            self.source_project_name, self.source_assembly_name = reference.split(self.source)
            config["source_resolved"] = self.source

            # Passed verbatim to the assembly, but only when declared.
            self.parameters = config.get("parameters", None)

            self.part.desc = config.get("desc") or reference.describe(config["type"], target_project.name, self.source)

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

        # The assembly's name is in this part's key already (it is in the
        # configuration); what it is made of is not, and without that an
        # edited part inside it would leave this compound served as it was.
        if not await part.add_cache_key_of(assembly):
            # An assembly with no key - 'cache: false', or made of something
            # that is - has content nothing here can vouch for, so neither has
            # a compound of it.
            part.cacheable = False

    async def instantiate(self, part):
        with pc_logging.Action("Compound", part.project_name, part.name):
            params = self.parameters if self.parameters else None
            assembly = self.ctx._get_assembly(self.source, params)
            if assembly is None:
                part.error("%s: compound source assembly not found: %s" % (part.name, self.source))
                return None

            shape = await assembly_compound.flatten_async(self.ctx, part, assembly)
            if shape is None:
                part.error("%s: compound source assembly produced no shape: %s" % (part.name, self.source))
                return None

            self.ctx.stats_parts_instantiated += 1
            return shape
