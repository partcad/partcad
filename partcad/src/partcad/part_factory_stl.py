#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import os

import build123d as b3d

from .part_factory_file import PartFactoryFile
from . import logging as pc_logging


class PartFactoryStl(PartFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSTL", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".stl",
            )
            # Complement the config object here if necessary
            self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("STL", part.project_name, part.name):
            try:
                shape = b3d.Mesher().read(self.path)[0].wrapped
            except:
                # First, make sure it's not a problem in Mesher
                # TODO(clairbee): ascii stl files end up here too, but probably don't need to

                from OCP.RWStl import RWStl
                from OCP.BRep import BRep_Builder
                from OCP.TopoDS import TopoDS_Face, TopoDS_Shell, TopoDS_Solid
                from OCP.TopAbs import TopAbs_FACE
                from OCP.BRepCheck import BRepCheck_Shell, BRepCheck_Solid, BRepCheck_Status
                from OCP.BRepGProp import BRepGProp
                from OCP.GProp import GProp_GProps

                builder = BRep_Builder()
                reader = RWStl.ReadFile_s(os.fsdecode(self.path))

                if not reader:
                    raise RuntimeError("Failed to read the STL file")

                # Build and check the faces
                face = TopoDS_Face()
                builder.MakeFace(face, reader)
                if face.IsNull():
                    raise RuntimeError("Failed to read the STL file: Null")
                if face.ShapeType() != TopAbs_FACE:
                    raise RuntimeError("Failed to read the STL file: Wrong shape type")
                if face.Infinite():
                    raise RuntimeError("Failed to read the STL file: Infinite")

                # Build and check the shell
                shell = TopoDS_Shell()
                builder.MakeShell(shell)
                builder.Add(shell, face)
                shell_check = BRepCheck_Shell(shell)
                shell_check_result = shell_check.Closed()
                if shell_check_result != BRepCheck_Status.BRepCheck_NoError:
                    if shell_check_result == BRepCheck_Status.BRepCheck_NotClosed:
                        raise RuntimeError("Failed to read the STL file: Shell is not closed")
                    else:
                        raise RuntimeError("Failed to read the STL file: Shell check failed")

                # Build and check the solid
                solid = TopoDS_Solid()
                builder.MakeSolid(solid)
                builder.Add(solid, shell)
                if solid.IsNull():
                    raise RuntimeError("Failed to read the STL file: Null solid")
                if solid.Infinite():
                    raise RuntimeError("Failed to read STL file: Infinite solid")
                solid_check = BRepCheck_Solid(solid)
                solid_check.Minimum()
                statuses = solid_check.Status()
                if statuses.Size() > 0 and statuses.First() != BRepCheck_Status.BRepCheck_NoError:
                    raise RuntimeError("Failed to read the STL file: Solid check failed: %s" % statuses.First())
                gprops = GProp_GProps()
                BRepGProp.VolumeProperties_s(solid, gprops)
                if gprops.Mass() <= 0:
                    raise RuntimeError("Failed to read the STL file: Zero or negative volume")

                shape = solid

            self.ctx.stats_parts_instantiated += 1

            return shape
