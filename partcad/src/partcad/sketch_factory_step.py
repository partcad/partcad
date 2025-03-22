from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader

from . import logging as pc_logging
from .sketch_factory_file import SketchFactoryFile


class SketchFactoryStep(SketchFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSTEP", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".step",
            )
            self._create(config)

    async def instantiate(self, sketch):
        await super().instantiate(sketch)

        with pc_logging.Action("STEP", sketch.project_name, sketch.name):
            shape = None
            try:
                reader = STEPControl_Reader()
                status = reader.ReadFile(self.path)

                if status != IFSelect_RetDone:
                    raise ValueError(f"Failed to read STEP file: {self.path}")

                reader.TransferRoots()
                shape = reader.OneShape()

            except Exception as e:
                pc_logging.exception(f"Failed to import the STEP file: {self.path}: {e}")
                shape = None

            self.ctx.stats_sketches_instantiated += 1
            return shape
