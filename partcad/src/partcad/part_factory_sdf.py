import os
import base64
import pickle
from .part_factory_python import PartFactoryPython
from . import logging as pc_logging
from . import wrapper
from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound

class PartFactorySdf(PartFactoryPython):
    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        super().__init__(
            ctx,
            source_project,
            target_project,
            config,
            can_create=can_create,
            python_version="3.11",
            extension=".py",
        )
        self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)
        with pc_logging.Action("SDF", part.project_name, part.name):
            if not os.path.exists(part.path):
                part.error(f"SDF script not found: {part.path}")
                return None

            await self.prepare_python()
            wrapper_path = wrapper.get("sdf.py")

            # Build the request with parameterization similar to the CadQuery example
            request = {"build_parameters": {}}
            if "parameters" in self.config:
                for param_name, param in self.config["parameters"].items():
                    request["build_parameters"][param_name] = param["default"]
            patch = {}
            if "show" in self.config:
                patch["\\Z"] = "\nshow(%s)\n" % self.config["show"]
            if "showObject" in self.config:
                patch["\\Z"] = "\nshow_object(%s)\n" % self.config["showObject"]
            if "patch" in self.config:
                patch.update(self.config["patch"])
            request["patch"] = patch

            # Serialize the request
            data = base64.b64encode(pickle.dumps(request)).decode()
            cwd = os.path.join(self.project.config_dir, self.cwd) if self.cwd else self.project.config_dir

            await self.runtime.ensure_async(
                "git+https://github.com/fogleman/sdf",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "cadquery-ocp==7.7.2",
                session=self.session,
            )

            response_serialized, errors = await self.runtime.run_async(
                [wrapper_path, os.path.abspath(part.path)],
                data,
                session=self.session,
            )

            if errors:
                for line in errors.split("\n"):
                    part.error(line)

            try:
                response = pickle.loads(base64.b64decode(response_serialized))
            except Exception as e:
                part.error(f"Deserialization error: {e}")
                return None

            if not response["success"]:
                part.error(response["exception"])
                return None

            shapes = response.get("shapes", [])
            if not shapes:
                return None
            if len(shapes) == 1:
                return shapes[0]

            builder = TopoDS_Builder()
            compound = TopoDS_Compound()
            builder.MakeCompound(compound)
            for s in shapes:
                builder.Add(compound, s)
            return compound
