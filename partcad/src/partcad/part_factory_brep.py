from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape

from .part_factory_file import PartFactoryFile
from . import logging as pc_logging
from .exception import PartFactoryBrepError


class PartFactoryBrep(PartFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitBREP", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".brep",
            )
            self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("BREP", part.project_name, part.name):
            shape = TopoDS_Shape()
            builder = BRep_Builder()

            if not BRepTools().Read_s(shape, self.path, builder):
                raise PartFactoryBrepError(f"Failed to load BREP file: {self.path}")

            self.ctx.stats_parts_instantiated += 1
            return shape
