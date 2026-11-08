#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A qualification check that a package supplies: the 'qual' plugin type.

A package declares the checks it supplies in a 'qual:' section of its own
'partcad.yaml', one entry per check, exactly as a simulation plugin is declared
in 'simulation:' (see 'partcad.output'):

    qual:
      lockwire:
        desc: Lockwire's power, mass, bus and torque budgets, from a lockfile
        path: lockwire_qual.py         # the script ('wrappers/wrapper_qual.py')
        subtype: other                 # basic | topology | other
        kinds: [assembly, part]        # what it can be asked of (all, if absent)
        pythonRequirements: [lockwire]
        lockfile: lockwire.yaml        # a parameter, with its default

and an object asks for it by naming it, under the subtype it declares:

    assemblies:
      rover:
        qual:
          other:
            budgets:
              path: //pub/qual/lockwire:lockwire
              lockfile: rover.lockwire.yaml

A check a plugin supplies is not built in, so it is never applied to an object
that does not declare it -- unlike the built-in checks, which are always applied.
What the object declares is its parameters, over the plugin's defaults. The
check runs in a sandbox with what the plugin says it needs, is handed the object
-- by name, with its package's directory, and as a file in the plugin's
'format:' when it declares one -- and answers a verdict and what it found (see
'wrappers/wrapper_qual.py'), which is reported the way its subtype's checks are:
a 'topology' one's geometry is left behind to be looked at ('partcad.qual.
highlight'), an 'other' one's report is handed on as it wrote it.

Its verdict is remembered, as a built-in check's is, only when its declaration
says 'cache: true': a plugin reads what it likes -- a lockfile beside the
package, a server -- and only it can say that its answer is a property of the
object and its parameters alone.
"""

import asyncio
import hashlib
import json
import os
import shutil
import typing

from .. import logging as pc_logging
from .. import output, shape_envelope, wrapper
from ..process_crash import describe_exit_code
from ..utils import resolve_resource_path
from . import config as qual_config
from . import highlight
from .qualification import Qualification

# How long a run may take, in seconds, when the plugin's declaration does not say.
DEFAULT_TIMEOUT = 600.0


class QualPluginError(Exception):
    """What an object declares cannot be found or does not fit: wrong wherever the package is opened."""


def resolve_plugin(ctx, package_name: str, spec: str) -> output.Implementation:
    """The 'output.Implementation' of the qualification plugin 'spec' names, from 'package_name'."""
    if not spec or not isinstance(spec, str):
        raise QualPluginError("names no plugin: 'path:' is the plugin, as '<package>:<name>'")
    plugin_package, plugin_name = resolve_resource_path(package_name, spec)
    project = ctx.get_project(plugin_package)
    if project is None:
        raise QualPluginError(
            "the package of the plugin '%s' is not found: %s. Add it to this package's 'dependencies:'"
            % (spec, plugin_package)
        )
    if getattr(project, "broken", False):
        raise QualPluginError(
            "the package of the plugin '%s' did not load: %s. The reason is reported above" % (spec, project.name)
        )
    section = project.config_obj.get(output.QUAL) or {}
    if not isinstance(section, dict) or not isinstance(section.get(plugin_name), dict):
        names = sorted(section) if isinstance(section, dict) else []
        raise QualPluginError(
            "the package '%s' declares no qualification plugin '%s' in its '%s:' section. It declares: %s"
            % (plugin_package, plugin_name, output.QUAL, ", ".join(names) or "none")
        )
    config = output.stamp(output.normalize(section[plugin_name]), plugin_package)
    return output.Implementation(output.QUAL, plugin_name, config, project)


def _kind_of(shape) -> str:
    from ..assembly import Assembly
    from ..scene import Scene
    from ..sketch import Sketch

    if isinstance(shape, Scene):
        return "scene"
    if isinstance(shape, Assembly):
        return "assembly"
    if isinstance(shape, Sketch):
        return "sketch"
    return "part"


def run_directory(ctx, shape, name: str) -> str:
    """Where one run of a plugin's check on 'shape' may write: emptied before every run."""
    digest = hashlib.sha256(("%s:%s/%s" % (shape.project_name, shape.name, name)).encode()).hexdigest()[:16]
    return os.path.join(ctx.user_config.internal_state_dir, "qual-runs", digest)


class PluginQualification(Qualification):
    """One check a plugin supplies, as one object declares it."""

    WRAPPERS = ("qual.py",)

    def __init__(self, declaration: qual_config.Declaration):
        super().__init__(declaration.name)
        self.declaration = declaration
        # Of the subtype it is declared under: an instance's, not the class's.
        self.SUBTYPE = declaration.subtype
        self.owner = None

    def params(self, shape) -> dict:
        return dict(self.declaration.params)

    def doc(self) -> typing.Optional[dict]:
        desc = self.declaration.desc or "A check supplied by the plugin '%s'." % self.declaration.path
        return {
            "title": desc.split(".")[0][:120] if self.declaration.desc else "Supplied by %s" % self.declaration.path,
            "applies": "the object that declares it, under 'qual: %s: %s:'" % (self.SUBTYPE, self.name),
            "blocks": [
                {"type": "paragraph", "text": desc},
                {
                    "type": "paragraph",
                    "text": "Run by the plugin `%s`, with the parameters the object declares beside its `path:`."
                    % self.declaration.path,
                },
            ],
        }

    def _plugin(self, ctx, shape) -> output.Implementation:
        impl = resolve_plugin(ctx, shape.project_name, self.declaration.path)
        subtype = impl.config.get("subtype") or qual_config.OTHER
        if subtype != self.SUBTYPE:
            raise QualPluginError(
                "the plugin '%s' supplies a check of the '%s' subtype, and is declared under 'qual: %s:'; declare it "
                "under 'qual: %s:'" % (self.declaration.path, subtype, self.SUBTYPE, subtype)
            )
        return impl

    def inapplicable(self, shape):
        from ..shape import Shape

        if not isinstance(shape, Shape):
            return "a plugin's check is asked of the object that declares it"
        if self.owner is not None and shape is not self.owner:
            return "it is declared by '%s', and asked of nothing else" % self.owner.name
        return None

    async def cache_key_suffix(self, ctx, shape) -> str:
        try:
            impl = self._plugin(ctx, shape)
            script = await output.materialize_script(ctx, impl)
            with open(script, "rb") as stream:
                content = hashlib.sha256(stream.read()).hexdigest()
            plugin = json.dumps(impl.config, sort_keys=True, default=str)
        except Exception:  # pylint: disable=broad-except
            # A verdict reached on a plugin that does not resolve is not
            # remembered ('test()'), and a key nothing can match again keeps a
            # stale one from being found.
            content, plugin = os.urandom(8).hex(), ""
        declared = json.dumps(self.declaration.config, sort_keys=True, default=str)
        digest = hashlib.sha256(("%s|%s|%s" % (declared, plugin, content)).encode()).hexdigest()[:32]
        return ".plugin=%s" % digest

    async def test(self, tests_to_run: list, ctx, shape, test_ctx: dict = None) -> bool:
        if test_ctx is None:
            test_ctx = {}
        if self.owner is None:
            self.owner = shape
        reason = self.inapplicable(shape)
        if reason is not None:
            return self.not_applicable(shape, reason)

        try:
            impl = self._plugin(ctx, shape)
        except QualPluginError as e:
            test_ctx[self.NOT_CACHEABLE] = True
            return self.failed(shape, "the check '%s' could not be run: %s", self.name, e)

        kinds = impl.config.get("kinds")
        kind = _kind_of(shape)
        if isinstance(kinds, list) and kinds and kind not in kinds:
            test_ctx[self.NOT_CACHEABLE] = True
            return self.failed(
                shape,
                "the plugin '%s' checks %s, and this is a %s",
                self.declaration.path,
                " and ".join("%ss" % one for one in kinds),
                kind,
            )

        if not impl.config.get("cache"):
            test_ctx[self.NOT_CACHEABLE] = True
        try:
            answer = await self._run_async(ctx, shape, impl, kind)
        except Exception as e:  # pylint: disable=broad-except
            test_ctx[self.NOT_CACHEABLE] = True
            return self.failed(shape, "the plugin '%s' did not answer: %s", self.declaration.path, e)

        for finding in answer.get("findings") or []:
            level, text = finding.get("level"), finding.get("text")
            if level == "warning":
                self.warned(shape, "%s", text)
            elif level == "info" or answer.get("passed") is not False:
                self.info(shape, "%s", text)
        if isinstance(answer.get("report"), dict):
            self.report(shape, answer["report"])
        if answer.get("highlights"):
            await self._highlight_async(ctx, shape, answer)

        passed = answer.get("passed")
        if passed is None:
            test_ctx[self.NOT_CACHEABLE] = True
            return self.skipped(shape, "%s", answer.get("skipped") or "the plugin could not answer here")
        if passed:
            return self.passed(shape)
        errors = [f.get("text") for f in answer.get("findings") or [] if f.get("level") == "error"]
        if not errors:
            return self.failed(shape, "the plugin '%s' says it does not pass", self.declaration.path)
        verdict = self.TEST_FAILED
        for text in errors:
            verdict = self.failed(shape, "%s", text)
        return verdict

    async def restore_artifact_async(self, ctx, shape, artifact: dict) -> bool:
        return await highlight.restore_async(ctx, artifact)

    async def _highlight_async(self, ctx, shape, answer: dict) -> None:
        geometry = []
        for item in answer.get("highlights") or []:
            try:
                with open(item["file"], "rb") as stream:
                    data = stream.read()
            except OSError as e:
                pc_logging.debug("%s: %s: the geometry '%s' could not be read: %s" % (shape.name, self.name, item, e))
                continue
            geometry.append({"name": item.get("name"), "kind": item.get("kind"), "brep": data})
        if not geometry:
            return
        errors = [f.get("text") for f in answer.get("findings") or [] if f.get("level") == "error"]
        artifact = await highlight.make_async(
            ctx,
            shape,
            self.name,
            errors[0] if errors else "What '%s' found" % self.name,
            "'%s', with what the check '%s' found drawn in the colour of a finding" % (shape.name, self.name),
            geometry,
        )
        if artifact is not None:
            self.artifact(shape, artifact)

    async def _export_async(self, ctx, shape, impl, directory: str) -> typing.Optional[str]:
        """The object as a file in the plugin's 'format:', or None when it declares none."""
        format_name = impl.config.get("format")
        if not format_name:
            return None
        project = ctx.get_project(shape.project_name)
        export_impl, _ = shape.output_getopts(
            ctx, format_name, project=project, options_project=impl.project, output_dir=directory
        )
        path = os.path.join(directory, "subject." + export_impl.extension(format_name))
        await shape.render_async(
            ctx,
            format_name,
            project=project,
            options_project=impl.project,
            filepath=path,
            **(impl.config.get("formatOptions") or {}),
        )
        if not os.path.isfile(path):
            raise Exception("the object was not written as '%s'" % format_name)
        return path

    async def _run_async(self, ctx, shape, impl, kind: str) -> dict:
        directory = run_directory(ctx, shape, self.name)
        shutil.rmtree(directory, ignore_errors=True)
        os.makedirs(directory, exist_ok=True)

        params = dict(impl.parameters)
        params.update(self.declaration.params)
        request = dict(params)
        package = ctx.get_project(shape.project_name)
        request.update(
            {
                "qualification": self.name,
                "subtype": self.SUBTYPE,
                "subject": "%s:%s" % (shape.project_name, shape.name),
                "subject_kind": kind,
                "package_dir": os.path.abspath(package.config_dir) if package is not None else None,
                "params": params,
            }
        )
        subject_file = await self._export_async(ctx, shape, impl, directory)
        if subject_file is not None:
            request["subject_file"] = os.path.abspath(subject_file)
            request["subject_format"] = impl.config.get("format")

        script = await output.materialize_script(ctx, impl)
        runtime = ctx.get_python_runtime(version=impl.python_version(), image=impl.docker_image)
        session = runtime.get_session("%s:%s" % (impl.section, impl.format_name))
        await runtime.prepare_for_package(impl.project, session=session)
        for dep in impl.python_requirements:
            await runtime.ensure_async(dep, session=session)

        timeout = impl.config.get("timeout")
        timeout = float(timeout) if isinstance(timeout, (int, float)) and timeout > 0 else DEFAULT_TIMEOUT
        command = [
            wrapper.get("qual.py"),
            os.path.abspath(directory),
            os.path.abspath(impl.project.config_dir),
            os.path.abspath(script),
        ]
        extra = {"output_dirs": [os.path.abspath(directory)]} if getattr(runtime, "EXCHANGES_FILES", False) else {}
        try:
            exitcode, response_serialized, errors = await runtime.run_async(
                command, shape_envelope.serialize(request), session=session, timeout=timeout, **extra
            )
        except (asyncio.TimeoutError, TimeoutError):
            raise Exception("it did not finish within %g seconds ('timeout:' in its declaration)" % timeout)
        if exitcode != 0:
            raise Exception("%s%s" % (describe_exit_code(exitcode), (": " + errors.strip()[-2000:]) if errors else ""))
        result = shape_envelope.deserialize(response_serialized)
        if not isinstance(result, dict):
            raise Exception("it answered with something that is not a result")
        if not result.get("success", False):
            raise Exception(result.get("exception") or "it failed without saying why")
        return result
