import os

from .part_factory_file import PartFactoryFile
from . import logging as pc_logging
from . import wrapper
from . import shape_envelope
from .exception import PartFactoryError


class PartFactoryObj(PartFactoryFile):
    PYTHON_RUNTIME_VERSION = "3.10"

    def __init__(self, ctx, source_project, target_project, config):
        """
        Initialize the OBJ part factory.
        """
        with pc_logging.Action("InitOBJ", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".obj", can_create=False)
            self._create(config)
            self.runtime = None  # Lazy initialization for the sandbox runtime

    async def instantiate(self, part):
        """
        Instantiate an OBJ part by reading it in a sandbox wrapper.

        Turning an OBJ mesh into OCCT faces needs OCCT, so it happens in a
        sandboxed runtime - the core process never touches a CAD library. The
        factory just forwards the resulting BREP envelope (a compound of faces).
        """
        await super().instantiate(part)

        with pc_logging.Action("OBJ", part.project_name, part.name):
            if self.runtime is None:
                self.runtime = self.ctx.get_python_runtime(self.PYTHON_RUNTIME_VERSION)

            wrapper_path = wrapper.get("obj.py")
            request = {
                "build_parameters": {},
                "name": "%s:%s" % (part.project_name, part.name),
                "label": part.name,
            }
            request_serialized = shape_envelope.serialize(request)

            command = [
                wrapper_path,
                os.path.abspath(self.path),
                os.path.abspath(self.project.config_dir),
            ]
            exitcode, response_serialized, errors = await self.runtime.run_async(
                command,
                request_serialized,
            )
            if exitcode != 0 and not errors:
                errors = "Failed to execute command '%s' with exit code %s" % (" ".join(command), exitcode)
            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

            response = shape_envelope.deserialize(response_serialized)
            if not response.get("success", False):
                pc_logging.error(response["exception"])
                raise PartFactoryError(response["exception"])

            self.ctx.stats_parts_instantiated += 1
            return response["shape"]
