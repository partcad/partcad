#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Construct a part from a package-defined 'partType'.

A part whose 'type' carries a package path ('<package>:<name>', after any ':'
short form has been expanded, see factory.instantiate) is not built by a
built-in factory. Instead the referenced partType is looked up in its package
and used to construct the part. Only the default partType kind, 'wrapper', is
implemented: it runs a package-supplied Python script inside the sandbox, which
produces the shape(s) (see wrappers/wrapper_part_type.py).

A partType that declares an ``extension`` reads a *file*: each part built with
it is one file of that format, declared exactly as a STEP or an STL part is --
``path`` relative to the part's own package, ``<name>.<extension>`` when left
out, ``fileFrom`` to fetch it. The file is resolved against the package that
declares the part rather than the one that declares the type, is what the
part's cache entry depends on, and reaches the script as ``request["path"]``.
That is what makes a format a package can teach PartCAD to read: 'fcstd' in
'//builtin/import', and the ones a plugin package supplies.
"""

import base64
import os

from . import code_version
from . import logging as pc_logging
from . import output, sandbox_versions, shape_envelope, telemetry, transform, wrapper
from .part_factory import PartFactory
from .process_crash import describe_exit_code
from .runtime_python import environment_requirements
from .utils import resolve_resource_path


@telemetry.instrument()
class PartFactoryWrapper(PartFactory):
    WRAPPERS = ("part_type.py", "transform.py")

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitWrapper", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)

            # 'type' is '<package>:<partType>' by the time we get here, or the
            # bare name of a partType PartCAD ships (see 'factory.instantiate').
            self.part_type_ref = config["type"]
            builtin_package = output.builtin_part_type(ctx, self.part_type_ref)
            if builtin_package is not None:
                self.part_type_package, self.part_type_name = builtin_package, self.part_type_ref
            else:
                self.part_type_package, self.part_type_name = resolve_resource_path(
                    target_project.name, self.part_type_ref
                )

            # The partType is resolved here when it can be, because two things
            # are decided by it before anything is built: whether the part is a
            # file, and which image its sandbox is built from. From the package
            # declaring the part, which is still loading (see
            # 'Context.get_project_from'). A package that cannot be reached yet
            # is resolved again when the part is built, which is where its
            # absence is reported.
            if self.part_type_package == target_project.name:
                # The package's own partType (':name'): the package in hand,
                # which is not registered under its name until it has loaded.
                pt_project = target_project
            else:
                try:
                    pt_project = ctx.get_project_from(target_project, self.part_type_package)
                except Exception as e:
                    pc_logging.debug("%s: partType package %s: %s" % (config["name"], self.part_type_package, e))
                    pt_project = None
            pt_config = pt_project.get_part_type_config(self.part_type_name) if pt_project is not None else None
            pt_config = pt_config if isinstance(pt_config, dict) else {}

            # The file this part is read from, for a partType that reads one,
            # spelled the way this platform spells it: 'path:' is written with
            # forward slashes, and the script gets it as it is.
            extension = pt_config.get("extension")
            self.path = None
            if extension:
                self.path = os.path.normpath(
                    os.path.join(
                        source_project.config_dir,
                        config.get("path") or "%s.%s" % (self.orig_name, str(extension).lstrip(".")),
                    )
                )

            # The image is the implementing package's, as it is for an output
            # implementation (see 'Implementation.docker_image'): which
            # environment a script needs is known to whoever wrote it. The part's
            # own package is the last resort, for partTypes that name none.
            self.docker_image = (
                pt_config.get("dockerImage")
                or (pt_project.docker_image_declared if pt_project is not None else None)
                or self.project.docker_image_declared
            )

            python_version = self.project.python_version or sandbox_versions.DEFAULT_PYTHON_VERSION
            self.runtime = self.ctx.get_python_runtime(python_version, image=self.docker_image)
            self.session = self.runtime.get_session(source_project.name)

            self._create(config)

    def post_create(self) -> None:
        if self.path:
            self.part.path = self.path
            self.part.cache_dependencies.append(self.path)
        super().post_create()

    async def download_file_async(self, part) -> None:
        """Fetch what 'fileFrom' points at, for a partType that reads a file."""
        if self.path and self.fileFactory is not None and not os.path.exists(self.path):
            with pc_logging.Action("File", self.target_project.name, part.name):
                await self.fileFactory.download(self.path)

    def environment_cache_key(self) -> str | None:
        """The interpreter and the dependency versions this part renders with.

        Deliberately partial: the partType's own 'pythonRequirements' come from
        a package that is only resolved when the part is instantiated, so they
        cannot be read here. The interpreter and the pinned stack can be, and
        they are what a stack upgrade moves, so keying on them is worth having
        even though a partType changing its own requirements does not move the
        key - no more than a partType changing its wrapper script does today.
        """
        return sandbox_versions.environment_cache_key(
            "python",
            self.runtime.version,
            environment_requirements(self.project, self.config),
            # What the package declared, never what this machine's sandbox was
            # built in: every sandbox type is expected to produce the same shape,
            # so a key that named the image a 'docker' or 'remote' sandbox ran
            # in - or the PartCAD release tagged on it - would key the one shape
            # differently on conda, and switching sandboxes would orphan every
            # entry (see 'sandbox_versions.environment_cache_key').
            image=self.docker_image,
        )

    async def prepare_async(self, part) -> None:
        """Key the part on the version its partType's code reports, too.

        'code_versions' has the wrappers this factory runs and the plugin that
        serves the part, but the partType's own script is only known once its
        package is: the package that declares it may not be this one, and
        resolving it loads it. Its version is the plugin's when a plugin serves
        the partType - the script is one of the plugin's files - and otherwise
        the one the script states, as every wrapper does (see 'code_version').
        """
        await super().prepare_async(part)
        # The file has to be on disk before the cache key means anything: the
        # key hashes its content (see 'PartFactoryFile.prepare_async').
        await self.download_file_async(part)
        versions = self._part_type_versions()
        if versions is not None:
            part.add_code_versions(versions)

    def _part_type_versions(self):
        pt_project = self.ctx.get_project(self.part_type_package)
        if pt_project is None:
            return None  # 'instantiate()' says so, where it can fail the part
        plugin_version = getattr(pt_project, "plugin_cache_version", 0)
        if plugin_version:
            # Already in the key when the part is served by the same plugin -
            # an LDraw part and the partType that builds it are.
            if getattr(self.project, "plugin_ref", None) == pt_project.plugin_ref:
                return None
            return code_version.key([(pt_project.plugin_ref, plugin_version)])
        pt_config = pt_project.get_part_type_config(self.part_type_name)
        if pt_config is None:
            return None
        script = os.path.join(pt_project.config_dir, pt_config.get("path", self.part_type_name + ".py"))
        return code_version.key([(self.part_type_ref, code_version.declared(script))])

    async def _materialize_wrapper_script(self, pt_project, script_rel):
        """Return the on-disk path of the partType's wrapper script.

        For a local package the script is a file in the package. For a
        plugin-backed package it is fetched from the plugin (like a file-backed
        object) and written into the package's cache directory.
        """
        script_abs = os.path.join(pt_project.config_dir, script_rel)
        if os.path.exists(script_abs):
            return script_abs

        get_data_async = getattr(pt_project, "get_data_async", None)
        if get_data_async is None:
            raise Exception("partType wrapper script not found: %s" % script_abs)

        data = await get_data_async("files/" + script_rel)
        if data is None:
            raise Exception("The repository did not provide the partType wrapper: %s" % script_rel)
        content = base64.b64decode(data) if isinstance(data, str) else bytes(data)

        dirs = os.path.dirname(script_abs)
        if dirs and not os.path.exists(dirs):
            os.makedirs(dirs, exist_ok=True)
        with open(script_abs, "wb") as f:
            f.write(content)
        return script_abs

    async def instantiate(self, part):
        with pc_logging.Action("Wrapper", part.project_name, part.name):
            pt_project = self.ctx.get_project(self.part_type_package)
            if pt_project is None:
                part.error("partType package not found: %s" % self.part_type_package)
                return None

            pt_config = pt_project.get_part_type_config(self.part_type_name)
            if pt_config is None:
                part.error("partType '%s' not found in '%s'" % (self.part_type_name, self.part_type_package))
                return None

            kind = pt_config.get("kind", "wrapper")
            if kind != "wrapper":
                part.error("Unsupported partType kind '%s' (only 'wrapper' is implemented)" % kind)
                return None

            if self.path:
                try:
                    await self.download_file_async(part)
                except Exception as e:
                    part.error("Failed to fetch %s: %s" % (self.path, e))
                    return None
                if not os.path.isfile(self.path):
                    part.error("The part's file is not found: %s" % self.path)
                    return None

            # The wrapper script: 'path' or, by default, '<name>.py'.
            script_rel = pt_config.get("path", self.part_type_name + ".py")
            try:
                script_abs = await self._materialize_wrapper_script(pt_project, script_rel)
            except Exception as e:
                part.error(str(e))
                return None

            # Prepare the sandbox: the partType's package dependencies, then
            # whatever the partType itself declares, then the geometry stack.
            await self.runtime.prepare_for_package(pt_project, session=self.session)
            await self.runtime.prepare_for_shape(self.config, session=self.session)
            for req in pt_config.get("pythonRequirements", []) or []:
                await self.runtime.ensure_async(req, session=self.session)

            # The geometry stack the sandbox needs so a wrapper can build and
            # serialize shapes. The versions come from sandbox_versions: a
            # session v-env is shared by every part of a package, so a factory
            # that pins its own version corrupts it for all the others. The
            # core itself never imports OCP - shapes cross the boundary as
            # BREP envelopes (see shape_envelope).
            await self.runtime.ensure_async(sandbox_versions.OCP_TESSELLATE, session=self.session)
            await self.runtime.ensure_async(sandbox_versions.TYPING_EXTENSIONS, session=self.session)
            await self.runtime.ensure_async(sandbox_versions.OCPSVG, session=self.session)
            await self.runtime.ensure_async(sandbox_versions.BUILD123D, session=self.session)
            # Last: re-asserts the VTK-enabled OCP that build123d's
            # 'cadquery-ocp-novtk' dependency has just replaced.
            await self.runtime.ensure_async(sandbox_versions.CADQUERY_OCP, session=self.session)

            # The request handed to the wrapper script.
            request = {
                "name": "%s:%s" % (part.project_name, part.name),
                "label": part.name,
                "orig_name": self.orig_name,
                "config": self.config,
                "parameters": {},
                # Where the partType's package keeps what it fetches for itself.
                "cache_dir": output.package_cache_dir(self.ctx, pt_project),
            }
            if self.path:
                request["path"] = os.path.abspath(self.path)
            for param_name, param in (self.config.get("parameters") or {}).items():
                request["parameters"][param_name] = param.get("default") if isinstance(param, dict) else param
            request_serialized = shape_envelope.serialize(request)

            meta_wrapper = wrapper.get("part_type.py")
            exitcode, response_serialized, errors = await self.runtime.run_async(
                [meta_wrapper, os.path.abspath(script_abs), os.path.abspath(pt_project.config_dir)],
                request_serialized,
                session=self.session,
            )
            if exitcode != 0 and not errors:
                errors = "%s: %s: partType wrapper failed (%s)" % (
                    part.project_name,
                    part.name,
                    describe_exit_code(exitcode),
                )
            if errors:
                for line in errors.split("\n"):
                    line = line.strip()
                    if line:
                        pc_logging.debug("%s: %s" % (part.name, line))

            try:
                response = shape_envelope.deserialize(response_serialized)
            except Exception as e:
                part.error("Deserialization error: %s" % e)
                return None

            if not response.get("success"):
                part.error(str(response.get("exception")))
                return None

            shapes = response.get("shapes", [])
            if not shapes:
                part.error("The partType wrapper produced no shape")
                return None
            self.ctx.stats_parts_instantiated += 1
            if len(shapes) == 1:
                return shapes[0]

            # Compounding runs in the sandbox (transform.compound), so the core
            # never touches OCP. Keep the contract: report via part.error() and
            # return None instead of raising.
            try:
                return await transform.compound(self.ctx, shapes)
            except Exception as e:
                part.error("Failed to compound wrapper shapes: %s" % e)
                return None
