import os

from .part_factory_python import PartFactoryPython
from . import logging as pc_logging
from . import sandbox_versions
from . import wrapper
from . import transform
from . import shape_envelope


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

            # Build the request, mirroring the other Python part factories. The
            # SDF script runs inside the sandbox, which is the security boundary;
            # the factory does not attempt to sanitize parameter or patch values.
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

            # Serialize the request into the wrapper wire format
            request["name"] = "%s:%s" % (part.project_name, part.name)
            request["label"] = part.name
            request_serialized = shape_envelope.serialize(request)

            # The versions come from sandbox_versions, like every other factory's.
            # They used to be pinned here to a generation of their own
            # (cadquery-ocp 7.7.2, ocp-tessellate 3.0.9, build123d 0.8.0), which
            # downgraded the CAD stack for every other part sharing this
            # package's v-env - a CadQuery part rendered after an SDF one then
            # died on OCP 7.7 with "type object 'OCP.TopoDS.TopoDS' has no
            # attribute 'Vertex'". wrapper_sdf.py itself needs only sdf, numpy,
            # OCP and ocp-tessellate; build123d was never imported by it.
            await self.runtime.ensure_async(
                "sdf-fork",
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.NUMPY,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.OCP_TESSELLATE,
                session=self.session,
            )
            # Last, by the convention every install list here follows: it undoes
            # any novtk OCP a build123d install elsewhere in this v-env left
            # behind (see sandbox_versions.GUARD_INVALIDATED_BY).
            await self.runtime.ensure_async(
                sandbox_versions.CADQUERY_OCP,
                session=self.session,
            )

            exitcode, response_serialized, errors = await self.runtime.run_async(
                [wrapper_path, os.path.abspath(part.path)],
                request_serialized,
                session=self.session,
            )
            if exitcode != 0 and not errors:
                errors = "%s: %s: Failed to instantiate (exit code %s)" % (part.project_name, part.name, exitcode)

            if errors:
                for line in errors.split("\n"):
                    line = line.strip()
                    if line:
                        part.error(line)

            try:
                response = shape_envelope.deserialize(response_serialized)
            except Exception as e:
                part.error(f"Deserialization error: {e}")
                pc_logging.exception(e)
                return None

            if not response["success"]:
                part.error(response["exception"])
                return None

            shapes = response.get("shapes", [])
            if not shapes:
                return None
            if len(shapes) == 1:
                return shapes[0]

            # Compounding now runs in a sandbox (transform.compound spawns a
            # runtime and raises on any failure), so it can fail where the old
            # in-process TopoDS_Compound could not. Keep this method's contract:
            # report via part.error() and return None instead of raising.
            try:
                return await transform.compound(self.ctx, shapes)
            except Exception as e:
                part.error("Failed to compound SDF shapes: %s" % e)
                return None
