#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part read from a glTF file: '.gltf' with its buffers, or a single '.glb'.

glTF is how meshes travel between renderers, game engines and the web, and what
`pc export -t gltf` writes. It is read as every mesh is (see
'wrappers/wrapper_import_gltf.py'): the triangles of every node, placed by the
node tree and stated in millimetres, meshed into the faces of a solid.
"""

import os

from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, telemetry, wrapper
from .part_factory_file import PartFactoryFile
from .part_factory_homogen import PartFactoryHomogen
from .process_crash import command_failure


@telemetry.instrument()
class PartFactoryGltf(PartFactoryHomogen, PartFactoryFile):
    WRAPPERS = ("import_gltf.py",)

    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitGLTF", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".gltf")
            self._create(config)
            self.runtime = None  # Lazy initialization for the sandbox runtime

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("GLTF", part.project_name, part.name):
            if self.runtime is None:
                self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)

            request = {"name": "%s:%s" % (part.project_name, part.name), "label": part.name}
            request_serialized = shape_envelope.serialize(request)

            await self.runtime.ensure_async(sandbox_versions.OCP_TESSELLATE)
            await self.runtime.ensure_async(sandbox_versions.TYPING_EXTENSIONS)
            await self.runtime.ensure_async(sandbox_versions.OCPSVG)
            await self.runtime.ensure_async(sandbox_versions.BUILD123D)
            # Last: re-asserts the VTK-enabled OCP that build123d's
            # 'cadquery-ocp-novtk' dependency has just replaced.
            await self.runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

            command = [wrapper.get("import_gltf.py"), os.path.abspath(self.path)]
            with telemetry.start_as_current_span("*PartFactoryGltf.instantiate.{runtime.run_async}"):
                exitcode, response_serialized, errors = await self.runtime.run_async(command, request_serialized)
            if exitcode != 0 and len(errors) == 0:
                errors = command_failure(command, exitcode)
            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

            result = shape_envelope.deserialize(response_serialized)
            if not result["success"]:
                pc_logging.error(result["exception"])
                raise Exception(result["exception"])

            self.ctx.stats_parts_instantiated += 1
            return result["shape"]
