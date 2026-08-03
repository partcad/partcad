#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import os
import subprocess
import tempfile

from . import logging as pc_logging
from . import telemetry, wrapper
from .healthcheck.openscad import find_executable as find_openscad_executable
from .part_factory_file import PartFactoryFile
from . import sandbox_versions

from . import shape_envelope


def _scad_literal(value):
    """Render a Python value as an OpenSCAD literal.

    Shared by the '-D name=value' overrides and the arguments of an injected
    module call, so numbers, booleans, strings and vectors all reach OpenSCAD
    with the right syntax.
    """
    if isinstance(value, bool):
        # bool is a subclass of int, so it has to be handled first
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return '"%s"' % escaped
    if isinstance(value, (list, tuple)):
        return "[%s]" % ", ".join(_scad_literal(item) for item in value)
    if value is None:
        return "undef"
    raise ValueError("Unsupported OpenSCAD parameter value: %r" % (value,))


def _parameter_values(config):
    """Collect the declared parameters as a {name: value} mapping.

    A parameter is either a bare value or an object carrying a 'default' (see
    the 'shape-parameter' schema), matching how the CadQuery and build123d
    factories read 'parameters'. Reading 'default' also picks up values
    overridden at runtime (e.g. 'pc inspect -p name=value').
    """
    values = {}
    for name, param in (config.get("parameters") or {}).items():
        values[name] = param.get("default") if isinstance(param, dict) else param
    return values


def _build_define_args(values):
    """Turn parameters into OpenSCAD '-D name=value' command-line args."""
    args = []
    for name, value in values.items():
        args += ["-D", "%s=%s" % (name, _scad_literal(value))]
    return args


def _build_method_call(method, values):
    """Build a call to 'method' passing the parameters as named args."""
    call_args = ", ".join("%s=%s" % (name, _scad_literal(value)) for name, value in values.items())
    return "%s(%s);" % (method, call_args)


def _write_render_script(source_path, call_line):
    """Copy the script to a throwaway file with 'call_line' appended.

    The source is never modified: a library-style SCAD file that only defines a
    module renders nothing on its own, so a call to that module is appended to a
    temporary copy that is rendered and then deleted.

    The copy is created in the source's own directory so that any relative
    'include'/'use'/'import' paths in the script still resolve -- OpenSCAD
    resolves those relative to the file that contains them, so a copy placed in
    the system temp directory would break them.
    """
    with open(source_path, "r") as f:
        source = f.read()
    fd, tmp_path = tempfile.mkstemp(suffix=".scad", dir=os.path.dirname(source_path) or None)
    with os.fdopen(fd, "w") as f:
        f.write(source)
        if source and not source.endswith("\n"):
            f.write("\n")
        f.write(call_line + "\n")
    return tmp_path


def _build_render_args(scad_executable, stl_path, source_path, config):
    """Assemble the OpenSCAD command line for a part.

    Returns ``(args, tmp_scad_path)``. When the config names a ``method``, the
    parameters become a call appended to a throwaway copy of the source, whose
    path is returned so the caller can delete it after the render. Otherwise the
    parameters become ``-D name=value`` variable overrides and the source is
    rendered directly. ``tmp_scad_path`` is ``None`` when no copy was made.
    """
    values = _parameter_values(config)
    method = config.get("method")

    tmp_scad_path = None
    define_args = []
    if method:
        tmp_scad_path = _write_render_script(source_path, _build_method_call(method, values))
        render_path = tmp_scad_path
    else:
        render_path = source_path
        if values:
            define_args = _build_define_args(values)

    args = [
        scad_executable,
        "--export-format",
        "binstl",
        "-o",
        stl_path,
        *define_args,
        render_path,
    ]
    return args, tmp_scad_path


@telemetry.instrument()
class PartFactoryScad(PartFactoryFile):
    # The sandboxed runtime used to keep build123d out of the main process
    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action("InitOpenSCAD", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension=".scad",
                can_create=can_create,
            )
            # Complement the config object here if necessary
            self._create(config)

            for dep in self.config.get("dependencies", []):
                self.part.cache_dependencies.append(os.path.join(self.project.config_dir, dep))

            self.project_dir = source_project.config_dir

            self.runtime = None  # Lazy initialization for subprocess runtime

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("OpenSCAD", part.project_name, part.name):
            if not os.path.exists(part.path) or os.path.getsize(part.path) == 0:
                pc_logging.error("OpenSCAD script is empty or does not exist: %s" % part.path)
                return None

            # The bundled OpenSCAD first, the host's second -- unless the user
            # opted out of the bundled one. See `partcad.healthcheck.openscad`.
            scad_path = find_openscad_executable(ignore_bundled=self.ctx.user_config.ignore_bundled_openscad)
            if scad_path is None:
                raise Exception("OpenSCAD executable is not found. Please, install OpenSCAD first.")

            fd, stl_path = tempfile.mkstemp(suffix=".stl")
            os.close(fd)  # OpenSCAD writes to the path itself via '-o'
            try:
                with telemetry.start_as_current_span(
                    "PartFactoryScad.instantiate.*{asyncio.create_subprocess_exec}"
                ) as span:
                    # Parameters either override the script's top-level variables
                    # ('-D name=value') or, when a module is named via 'method', are
                    # passed to a call to that module appended to a throwaway copy of
                    # the script (the source file is never modified).
                    args, tmp_scad_path = _build_render_args(scad_path, stl_path, part.path, self.config)
                    span.set_attribute("cmd", " ".join(args))
                    try:
                        p = await asyncio.create_subprocess_exec(
                            *args,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            shell=False,
                        )
                        _, errors = await p.communicate()
                    finally:
                        if tmp_scad_path is not None and os.path.exists(tmp_scad_path):
                            os.unlink(tmp_scad_path)

                errors = errors.decode()
                if p.returncode != 0 and len(errors) == 0:
                    errors = "%s: %s: Failed to instantiate" % (part.project_name, part.name)
                    pc_logging.debug(
                        "%s: %s: Failed to execute command: '%s' with exitcode %s"
                        % (part.project_name, part.name, " ".join(args), p.returncode)
                    )

                if len(errors) > 0:
                    error_lines = errors.split("\n")
                    for error_line in error_lines:
                        pc_logging.debug("%s: %s" % (part.name, error_line))

                if not os.path.exists(stl_path) or os.path.getsize(stl_path) == 0:
                    part.error("OpenSCAD failed to generate the STL file. Please, check the script.")
                    return None

                # The mesh is imported by a wrapper script executed in a sandboxed
                # python runtime, so that build123d is not needed in this process.
                # The wrapper falls back onto 'import_stl' if 'Mesher' fails,
                # to work around the known problem in Mesher.
                if self.runtime is None:
                    self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)

                wrapper_path = wrapper.get("import_mesh.py")

                request = {"fallback_import_stl": True}
                request["name"] = "%s:%s" % (part.project_name, part.name)
                request["label"] = part.name
                request_serialized = shape_envelope.serialize(request)

                await self.runtime.ensure_async(sandbox_versions.OCP_TESSELLATE)
                await self.runtime.ensure_async(sandbox_versions.TYPING_EXTENSIONS)
                await self.runtime.ensure_async(sandbox_versions.OCPSVG)
                await self.runtime.ensure_async(sandbox_versions.BUILD123D)
                # Last: re-asserts the VTK-enabled OCP that build123d's
                # 'cadquery-ocp-novtk' dependency has just replaced.
                await self.runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

                command = [
                    wrapper_path,
                    os.path.abspath(stl_path),
                    os.path.abspath(self.project.config_dir),
                ]
                with telemetry.start_as_current_span("*PartFactoryScad.instantiate.{runtime.run_async}"):
                    exitcode, response_serialized, errors = await self.runtime.run_async(
                        command,
                        request_serialized,
                    )
                if exitcode != 0 and len(errors) == 0:
                    errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"

                if errors:
                    part.error("%s: %s" % (part.name, errors))
                    return None

                try:
                    result = shape_envelope.deserialize(response_serialized)
                except Exception as e:
                    part.error("%s: %s" % (part.name, e))
                    return None

                if not result["success"]:
                    part.error("%s: %s" % (part.name, result["exception"]))
                    return None

                shape = result["shape"]

                self.ctx.stats_parts_instantiated += 1

                return shape
            finally:
                if os.path.exists(stl_path):
                    os.unlink(stl_path)
