from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape

from .part_factory_file import PartFactoryFile
from . import logging as pc_logging


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
            try:
                shape = TopoDS_Shape()
                builder = BRep_Builder()
                brep_tools = BRepTools()

                if not brep_tools.Read_s(shape, self.path, builder):
                    raise ValueError("BRep file could not be loaded")
            except Exception as e:
                pc_logging.error(f"Error loading BRep file: {e}")
                raise

            self.ctx.stats_parts_instantiated += 1

            return shape
