#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-09-30
#
# Licensed under Apache License, Version 2.0.
#

import typing

from . import telemetry
from .assembly import Assembly
from .shape_factory import ShapeFactory


@telemetry.instrument()
class AssemblyFactory(ShapeFactory):
    # TODO(clairbee): Make the next line work for assembly_factory_file only
    path: typing.Optional[str] = None
    assembly: Assembly

    # What this factory produces: the kind a package registers it under, the
    # class that holds it, and the pair of context counters it is tallied in.
    #
    # A scene is built exactly the way an assembly is - the same ASSY files,
    # the same tree of placed shapes - and differs only in what a package calls
    # it and in what its source file is allowed to say. So every scene factory
    # is the matching assembly factory with these three changed and nothing
    # else (see scene_factory.py), which is what keeps the two from drifting
    # apart the way two copies of the ASSY reader would.
    #
    # 'self.assembly' keeps its name whatever the kind is: a Scene *is* an
    # Assembly, and renaming the attribute would touch every factory here for
    # no gain.
    OBJECT_KIND = "assembly"
    OBJECT_CLASS = Assembly
    STATS_DECLARED = "stats_assemblies"
    STATS_INSTANTIATED = "stats_assemblies_instantiated"

    def __init__(self, ctx, source_project, target_project, config, extension=""):
        super().__init__(ctx, source_project, config)
        self.target_project = target_project
        self.name = config["name"]
        self.orig_name = config["orig_name"]

    def _create(self, config) -> None:
        self.assembly = self.OBJECT_CLASS(self.target_project.name, config)
        self.assembly.instantiate = lambda assembly_self: self.instantiate(assembly_self)
        self.assembly._prepare = lambda shape_self: self.prepare_async(shape_self)
        self.assembly._subassemblies = lambda assembly_self: self.subassemblies_async(assembly_self)
        self.assembly.info = lambda: self.info(self.assembly)
        self.assembly.with_ports = self.with_ports
        self.target_project.register_object(self.OBJECT_KIND, self.name, self.assembly)

        self.apply_environment_cache_key(self.assembly)
        self.post_create()

        self.count_declared()

    def count_declared(self) -> None:
        setattr(self.ctx, self.STATS_DECLARED, getattr(self.ctx, self.STATS_DECLARED) + 1)

    def count_instantiated(self) -> None:
        setattr(self.ctx, self.STATS_INSTANTIATED, getattr(self.ctx, self.STATS_INSTANTIATED) + 1)

    def get_source_object(self, name, params=None):
        """The object of this kind that 'name' refers to, from any package.

        The indirection an alias and an enrich resolve their source through, so
        that a scene alias points at a scene and an assembly alias at an
        assembly rather than both reaching for assemblies.
        """
        return self.ctx._get_assembly(name, params)

    async def subassemblies_async(self, assembly) -> list:
        """The assemblies this one places directly, resolved but not built.

        None by default, and that is the answer for most formats: a STEP file,
        a URDF or a mesh holds geometry rather than references to other PartCAD
        objects, so there is nothing to build before it. The formats that do
        reference them override this - an ASSY file's links, and the object an
        alias or an enrich stands for.

        Called through 'Assembly.get_subassemblies_async()', which prepares the
        assembly first: that is what has resolved the references by the time
        this reads them.
        """
        return []

    def post_create(self) -> None:
        # This is a base class catch-all method
        pass
