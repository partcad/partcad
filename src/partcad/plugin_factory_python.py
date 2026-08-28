#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import os
import sys
import typing

from . import shape_envelope

from .plugin import Plugin
from .plugin_factory_file import PluginFactoryFile
from .runtime_python import PythonRuntime

from . import wrapper
from . import logging as pc_logging
from . import sandbox_versions
from . import telemetry


async def query_with_deadline(plugin: Plugin, run, timeout: int, subject: typing.Optional[str] = None):
    """Await ``run()`` on behalf of ``plugin``, for at most ``timeout`` seconds.

    A plugin script is third-party code doing whatever it likes in a sandbox of
    its own, and PartCAD waited for it with nothing bounding the wait. That is
    fine until a script is slow rather than broken: the LDraw repository plugin
    that ``//pub/universe/lego/ldraw`` is served by enumerates a category by
    fetching every part in it from ldraw.org, one HTTP request per part, and the
    library has 104 categories and some twenty thousand parts. A recursive
    listing of the public index asks it for every one of them, so ``pc list -r
    //pub`` stopped printing anything and never came back.

    Returns ``None`` when the deadline passes, which every caller here already
    treats as "this plugin has no answer", and records the reason on the plugin
    so that it is not asked again. The second half matters as much as the first:
    a package tree served by one plugin asks it once per sub-package per object
    kind, so paying the deadline over and over is the same wedge in slower
    motion -- LDraw's 104 categories, three kinds each, at three minutes apiece
    is fifteen hours.

    The deadline is over the *script*, not over the sandbox it runs in.
    Provisioning a Python sandbox means creating a conda environment and
    installing the CAD stack into it, which legitimately takes many minutes on a
    cold machine and is shared by every package that uses it; that is why
    ``run()`` carries the bound down to the interpreter run itself (see
    PythonRuntime.run_async_onced) rather than it being applied out here.
    """
    try:
        return await run()
    except (asyncio.TimeoutError, TimeoutError):
        # The long form is said once, where it happened; what the refused
        # queries after it repeat is the short reason, because there is one of
        # them per package the plugin serves.
        plugin.deadline_exceeded = "skipped: the plugin script exceeded its %d second deadline" % timeout
        plugin.error(
            "%s: the plugin script did not answer within %d seconds "
            "(raise 'plugin.query.timeout' / PC_PLUGIN_QUERY_TIMEOUT to wait longer); "
            "this plugin is not asked again" % (subject or plugin.name, timeout)
        )
        return None


@telemetry.instrument()
class PluginFactoryPython(PluginFactoryFile):
    runtime: PythonRuntime
    cwd: str

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config,
        can_create=False,
        python_version=None,
        extension=".py",
    ):
        super().__init__(
            ctx,
            source_project,
            target_project,
            config,
            extension=extension,
            can_create=can_create,
        )
        self.cwd = config.get("cwd", None)

        if python_version is None:
            # TODO(clairbee): stick to a default constant or configured version
            python_version = self.project.python_version
        if python_version is None:
            # Stay one step ahead of the minimum required Python version
            python_version = sandbox_versions.DEFAULT_PYTHON_VERSION
        # A provider script may use either CadQuery or build123d, so it takes
        # the stricter of the two floors.
        python_version = sandbox_versions.at_least(python_version, sandbox_versions.MIN_PYTHON_VERSION_CADQUERY)

        self.runtime = self.ctx.get_python_runtime(python_version)
        self.session = self.runtime.get_session(source_project.name)

    def info(self, plugin: Plugin):
        return {
            "sandbox_version": self.runtime.version,
            "sandbox_path": self.runtime.path,
        }

    async def prepare_script(self, plugin) -> bool:
        """
        Finish initialization of PythonRuntime
        which was too expensive to do in the constructor
        """

        # Install dependencies of this package
        await self.runtime.prepare_for_package(self.project, session=self.session)
        await self.runtime.prepare_for_shape(self.config, session=self.session)

        return await super().prepare_script(plugin)

    async def query_script(self, plugin: Plugin, script_name: str, request):
        extra = ""
        if script_name == "avail":
            vendor = request.get("vendor", None)
            sku = request.get("sku", None)
            if not vendor and not sku:
                extra = request["name"]
            else:
                if not vendor:
                    vendor = "None"
                if not sku:
                    sku = "None"
                extra = vendor + ":" + sku
        timeout = self.ctx.user_config.plugin_query_timeout
        # What this particular query was for. A repository plugin serves a whole
        # tree of packages, so its name alone would not say which of them the
        # answer (or the refusal below) belongs to; the key does.
        subject = plugin.name
        if isinstance(request, dict) and request.get("key"):
            subject += " '%s'" % request["key"]
        with pc_logging.Action(
            script_name.capitalize(),
            plugin.project_name,
            plugin.name,
            extra,
        ):
            if plugin.deadline_exceeded:
                # Reported on every refused query rather than once. A package
                # that comes out empty has to say why every time it does, or the
                # next command against the same warm daemon would report a
                # complete listing that quietly is not one.
                plugin.error("%s: %s" % (subject, plugin.deadline_exceeded))
                return None

            prepared = await self.prepare_script(plugin)
            if not prepared:
                pc_logging.error("Failed to prepare %s of %s" % (script_name, plugin.name))
                return None

            # Get the path to the wrapper script
            # which needs to be executed
            wrapper_path = wrapper.get("plugin.py")

            # Build the request
            request["partcad_version"] = sys.modules["partcad"].__version__
            request["verbose"] = pc_logging.getLevel() <= pc_logging.DEBUG
            request["api"] = script_name
            request["user"] = self.ctx.user_config.pii_config.to_dict()
            request["parameters"] = {}
            if "parameters" in self.config:
                for param_name, param in self.config["parameters"].items():
                    # Check if this parameter has a value set
                    if "default" in param:
                        request["parameters"][param_name] = param["default"]

            # TODO(clairbee): Add support for patching. Copy files or drop runpy
            # patch = {}
            # if "patch" in self.config:
            #     patch.update(self.config["patch"])
            # request["patch"] = patch

            # Serialize the request
            request_serialized = shape_envelope.serialize(request)

            # TODO-199: Use a requirements.txt or pyproject.toml for version specifications
            # TODO-200: Create a version resolution mechanism that can handle dependency conflicts
            # TODO-201: Implement a version update strategy for security patches
            await self.runtime.ensure_async(
                sandbox_versions.OCP_TESSELLATE,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.NLOPT,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.CADQUERY,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.NUMPY,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.TYPING_EXTENSIONS,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.CADQUERY_OCP,
                session=self.session,
            )
            cwd = self.project.config_dir
            if self.cwd is not None:
                cwd = os.path.join(self.project.config_dir, self.cwd)
            command = [
                wrapper_path,
                os.path.abspath(self.path),
                os.path.abspath(cwd),
            ]
            completed = await query_with_deadline(
                plugin,
                lambda: self.runtime.run_async(
                    command,
                    request_serialized,
                    session=self.session,
                    timeout=timeout,
                ),
                timeout,
                subject,
            )
            if completed is None:
                return None
            exitcode, response_serialized, errors = completed

            if exitcode != 0 and len(errors) == 0:
                errors = "%s: %s: Failed to instantiate" % (self.project.name, plugin.name)
                pc_logging.debug(
                    "%s: %s: Failed to execute command: '%s' with exitcode %s"
                    % (plugin.project_name, plugin.name, " ".join(command), exitcode)
                )

            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    plugin.error("%s: %s" % (plugin.name, error_line))

            try:
                result = shape_envelope.deserialize(response_serialized)
            except Exception as e:
                plugin.error("Exception while deserializing %s: %s" % (plugin.name, e))
                return None

            if "exception" in result:
                plugin.error("%s: %s" % (plugin.name, result["exception"]))
                return None

            self.ctx.stats_plugin_queries += 1

            return result
