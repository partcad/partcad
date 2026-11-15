#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Build a shape from a package-defined type: a 'partType' or a 'sketchType'.

An object whose 'type' carries a package path ('<package>:<name>', after any
':' short form has been expanded, see factory.instantiate) is not built by a
built-in factory. Instead the referenced type is looked up in its package and
used to construct the object. Only the default kind, 'wrapper', is implemented:
it runs a package-supplied Python script inside the sandbox, which produces the
shape(s) (see wrappers/wrapper_part_type.py, which runs the scripts of both).

Parts ('partTypes:', 'PartFactoryWrapper') and sketches ('sketchTypes:',
'SketchFactoryWrapper') are built the same way, and this is the one copy of
how: resolving the type, the file an object of a file-backed type is read from,
the image and the sandbox its script runs in, what the object is keyed on, and
running the script. A factory says which section its types are declared in and
what it makes of the script's answer, and nothing else; so a feature added to
one (where its script runs, what it is keyed on) is added to both.

A type that declares an ``extension`` reads a *file*: each object built with it
is one file of that format, declared exactly as a STEP part or a DXF sketch is
-- ``path`` relative to the object's own package, ``<name>.<extension>`` when
left out, ``fileFrom`` to fetch it. The file is resolved against the package
that declares the object rather than the one that declares the type, is what
the object's cache entry depends on, and reaches the script as
``request["path"]``. The other files it is read from - the layers a USD stage
composes - are its ``dependencies``, which the cache entry depends on too: those
its package lists, and, for a type that says ``reportsDependencies``, the ones
its script reports reading as it builds the object (see
'partcad.discovered_dependencies'). That is what makes a format a package can
teach PartCAD to read: 'fcstd' in '//builtin/import', and the ones a plugin
package supplies.
"""

import base64
import os

from . import code_version, discovered_dependencies
from . import logging as pc_logging
from . import output, request_paths, sandbox_versions, shape_envelope, wrapper
from .cache_hash import CacheHash
from .process_crash import describe_exit_code
from .runtime_python import environment_requirements
from .utils import resolve_resource_path

# The wrapper that runs a type's script, for parts and sketches alike: what it
# hands back differs by 'request["kind"]', how the script is run does not.
# 'run_type_async' spells it out, as every 'wrapper.get()' is spelled, so that
# 'tests/partcad/unit/test_code_version.py' sees which wrapper runs.
TYPE_WRAPPER = "part_type.py"


class TypeWrapperFactory:
    """What a factory building an object from a package-defined type shares.

    Mixed into a 'PartFactory' or a 'SketchFactory', ahead of it. A subclass
    sets the class attributes below and implements '_type_config',
    '_builtin_type_package' and 'shape_object', calls 'init_type()' from its
    constructor before '_create()', and builds the object in 'instantiate' from
    what 'run_type_async()' answers.
    """

    # The kind of declaration a type is ('partType', 'sketchType'): the object
    # kind its package lists it under, and what a message calls it.
    TYPE_KIND: str = ""
    # The kind of object built from it, as the type's script is told in
    # 'request["kind"]' and as the wrapper shapes its answer.
    OBJECT_KIND: str = ""

    # ------------------------------------------------------------------ #
    # What a subclass says                                               #
    # ------------------------------------------------------------------ #

    def _type_config(self, project, name):
        """The declaration of the type 'name' in 'project', or None."""
        raise NotImplementedError

    def _builtin_type_package(self, ctx, name):
        """The package declaring a type PartCAD ships called 'name', or None."""
        return None

    def shape_object(self):
        """The object this factory builds: its part, or its sketch."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Construction                                                       #
    # ------------------------------------------------------------------ #

    def init_type(self, ctx, source_project, target_project, config) -> None:
        """Resolve the type the object names, and what is decided by it before anything is built."""
        # 'type' is '<package>:<name>' by the time we get here, or the bare
        # name of a type PartCAD ships (see 'factory.instantiate').
        self.type_ref = config["type"]
        builtin_package = self._builtin_type_package(ctx, self.type_ref)
        if builtin_package is not None:
            self.type_package, self.type_name = builtin_package, self.type_ref
        else:
            self.type_package, self.type_name = resolve_resource_path(target_project.name, self.type_ref)

        # The type is resolved here when it can be, because two things are
        # decided by it before anything is built: whether the object is a
        # file, and which image its sandbox is built from. From the package
        # declaring the object, which is still loading (see
        # 'Context.get_project_from'). A package that cannot be reached yet is
        # resolved again when the object is built, which is where its absence
        # is reported.
        if self.type_package == target_project.name:
            # The package's own type (':name'): the package in hand, which is
            # not registered under its name until it has loaded.
            type_project = target_project
        else:
            try:
                type_project = ctx.get_project_from(target_project, self.type_package)
            except Exception as e:
                pc_logging.debug("%s: %s package %s: %s" % (config["name"], self.TYPE_KIND, self.type_package, e))
                type_project = None
        type_config = self._type_config(type_project, self.type_name) if type_project is not None else None
        type_config = type_config if isinstance(type_config, dict) else {}

        # The file this object is read from, for a type that reads one, spelled
        # the way this platform spells it: 'path:' is written with forward
        # slashes, and the script gets it as it is.
        extension = type_config.get("extension")
        self.path = None
        if extension:
            self.path = os.path.normpath(
                os.path.join(
                    source_project.config_dir,
                    config.get("path") or "%s.%s" % (self.orig_name, str(extension).lstrip(".")),
                )
            )

        # The other files the object is read from, which its script cannot be
        # asked about before it runs - the layers a USD stage composes, the
        # textures it names: each is part of the object's cache key, as the
        # files an OpenSCAD part includes are, so that changing one builds it
        # again rather than serving the shape built before.
        self.dependencies = [
            os.path.normpath(os.path.join(source_project.config_dir, str(dependency)))
            for dependency in config.get("dependencies") or []
        ]
        # The object's key without the files its script reported reading the
        # last time it was built, for a type that reports them: what that list
        # is kept under, and what the key with them continues (see
        # 'partcad.discovered_dependencies'). Set as the object is prepared.
        self._declared_key = None

        # The image is the implementing package's, as it is for an output
        # implementation (see 'Implementation.docker_image'): which environment
        # a script needs is known to whoever wrote it. The object's own package
        # is the last resort, for types that name none.
        self.docker_image = (
            type_config.get("dockerImage")
            or (type_project.docker_image_declared if type_project is not None else None)
            or self.project.docker_image_declared
        )

        python_version = self.project.python_version or sandbox_versions.DEFAULT_PYTHON_VERSION
        self.runtime = self.ctx.get_python_runtime(python_version, image=self.docker_image)
        self.session = self.runtime.get_session(source_project.name)

    def post_create_type(self) -> None:
        """Key the object on the files it is read from (called from 'post_create')."""
        shape = self.shape_object()
        if self.path:
            shape.path = self.path
            shape.cache_dependencies.append(self.path)
        shape.cache_dependencies.extend(self.dependencies)

    async def download_file_async(self, shape) -> None:
        """Fetch what 'fileFrom' points at, for a type that reads a file."""
        if self.path and self.fileFactory is not None and not os.path.exists(self.path):
            with pc_logging.Action("File", self.target_project.name, shape.name):
                await self.fileFactory.download(self.path)

    def environment_cache_key(self) -> str | None:
        """The interpreter and the dependency versions this object renders with.

        Deliberately partial: the type's own 'pythonRequirements' come from a
        package that is only resolved when the object is instantiated, so they
        cannot be read here. The interpreter and the pinned stack can be, and
        they are what a stack upgrade moves, so keying on them is worth having
        even though a type changing its own requirements does not move the key
        - no more than a type changing its wrapper script does today.
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

    # ------------------------------------------------------------------ #
    # Keying                                                             #
    # ------------------------------------------------------------------ #

    async def prepare_type_async(self, shape) -> None:
        """Key the object on its file, its type's code and what its script reported reading.

        'code_versions' has the wrappers this factory runs and the plugin that
        serves the object, but the type's own script is only known once its
        package is: the package that declares it may not be this one, and
        resolving it loads it. Its version is the plugin's when a plugin serves
        the type - the script is one of the plugin's files - and otherwise the
        one the script states, as every wrapper does (see 'code_version').

        Called by a subclass's 'prepare_async', which keys on anything of its
        own (a part's 'requireSolid') before '_key_on_reported_async', last.
        """
        # The file has to be on disk before the cache key means anything: the
        # key hashes its content (see 'PartFactoryFile.prepare_async').
        await self.download_file_async(shape)
        versions = self._type_versions()
        if versions is not None:
            shape.add_code_versions(versions)

    async def _key_on_reported_async(self, shape) -> None:
        """Key 'shape' on the files its script reported reading, for a type that reports them.

        Last, because it is keyed on everything before it.
        """
        reports = self._type_flag(output.REPORTS_DEPENDENCIES_KEY)
        if reports is None:
            shape.cacheable = False
        elif reports and shape.get_cacheable():
            # Keyed on the type reporting them as well: an entry built before
            # it did has no list kept beside it, and served from under the
            # same key it would never come to have one.
            shape.hash.add_string(output.REPORTS_DEPENDENCIES_KEY)
            await self._key_on_discovered(shape)

    def _type_flag(self, key):
        """The type's flag 'key': False where it is not declared, None where it is not a flag."""
        type_project = self.ctx.get_project(self.type_package)
        type_config = self._type_config(type_project, self.type_name) if type_project is not None else None
        if type_config is None:
            return False  # 'instantiate()' says so, where it can fail the object
        try:
            return output.as_flag(type_config.get(key), key)
        except ValueError:
            return None

    def _discovered_base_dir(self) -> str:
        """What the files a script reports are relative to: the directory of the object's file, or its package's."""
        return os.path.dirname(os.path.abspath(self.path)) if self.path else self.project.config_dir

    async def _key_on_discovered(self, shape) -> None:
        """Key 'shape' on the files its script reported reading the last time it was built, if it was.

        The list is kept under the object's declared key - everything it is
        keyed on before this - which is what is looked up here; the object is
        then keyed on that and on the content of every file in the list (see
        'partcad.discovered_dependencies').
        """
        self._declared_key = shape.hash.snapshot()
        if self._declared_key.get() is None:
            return
        found = await self.ctx.cache_shapes.read_data_async(self._declared_key, [discovered_dependencies.KEY])
        listed = discovered_dependencies.parse(found.get(discovered_dependencies.KEY))
        if listed:
            shape.hash = discovered_dependencies.keyed_on(self._declared_key, listed, self._discovered_base_dir())

    async def _record_discovered(self, shape, reported) -> None:
        """Keep the files a build of 'shape' reported reading, and key it on them from now on.

        Kept under the declared key, where the next lookup finds them, and the
        object is keyed on them at once, so that the entry this build writes is
        the one that lookup asks for.
        """
        base_dir = self._discovered_base_dir()
        listed = discovered_dependencies.normalized(reported, base_dir, own=self.path)
        await self.ctx.cache_shapes.write_data_async(
            self._declared_key, {discovered_dependencies.KEY: discovered_dependencies.serialize(listed)}
        )
        shape.hash = discovered_dependencies.keyed_on(self._declared_key, listed, base_dir)

    def _type_versions(self):
        type_project = self.ctx.get_project(self.type_package)
        if type_project is None:
            return None  # 'instantiate()' says so, where it can fail the object
        plugin_version = getattr(type_project, "plugin_cache_version", 0)
        if plugin_version:
            # Already in the key when the object is served by the same plugin -
            # an LDraw part and the partType that builds it are.
            if getattr(self.project, "plugin_ref", None) == type_project.plugin_ref:
                return None
            return code_version.key([(type_project.plugin_ref, plugin_version)])
        type_config = self._type_config(type_project, self.type_name)
        if type_config is None:
            return None
        script = os.path.join(type_project.config_dir, type_config.get("path", self.type_name + ".py"))
        return code_version.key([(self.type_ref, code_version.declared(script))])

    # ------------------------------------------------------------------ #
    # Running the script                                                 #
    # ------------------------------------------------------------------ #

    async def _materialize_wrapper_script(self, type_project, script_rel):
        """Return the on-disk path of the type's script.

        For a local package the script is a file in the package. For a
        plugin-backed package it is fetched from the plugin (like a file-backed
        object) and written into the package's cache directory.
        """
        script_abs = os.path.join(type_project.config_dir, script_rel)
        if os.path.exists(script_abs):
            return script_abs

        get_data_async = getattr(type_project, "get_data_async", None)
        if get_data_async is None:
            raise Exception("%s wrapper script not found: %s" % (self.TYPE_KIND, script_abs))

        data = await get_data_async("files/" + script_rel)
        if data is None:
            raise Exception("The repository did not provide the %s wrapper: %s" % (self.TYPE_KIND, script_rel))
        content = base64.b64decode(data) if isinstance(data, str) else bytes(data)

        dirs = os.path.dirname(script_abs)
        if dirs and not os.path.exists(dirs):
            os.makedirs(dirs, exist_ok=True)
        with open(script_abs, "wb") as f:
            f.write(content)
        return script_abs

    def resolve_type(self, shape):
        """'(type_project, type_config)' of the type 'shape' names, or None once 'shape.error()' says why not."""
        type_project = self.ctx.get_project(self.type_package)
        if type_project is None:
            shape.error("%s package not found: %s" % (self.TYPE_KIND, self.type_package))
            return None

        type_config = self._type_config(type_project, self.type_name)
        if type_config is None:
            shape.error("%s '%s' not found in '%s'" % (self.TYPE_KIND, self.type_name, self.type_package))
            return None

        kind = type_config.get("kind", "wrapper")
        if kind != "wrapper":
            shape.error("Unsupported %s kind '%s' (only 'wrapper' is implemented)" % (self.TYPE_KIND, kind))
            return None
        return type_project, type_config

    def type_request(self, shape, type_project) -> dict:
        """The request handed to the type's script; a subclass adds what is its own."""
        request = {
            "kind": self.OBJECT_KIND,
            "name": "%s:%s" % (shape.project_name, shape.name),
            "label": shape.name,
            "orig_name": self.orig_name,
            "config": self.config,
            "parameters": {},
            # Where the type's package keeps what it fetches for itself.
            "cache_dir": output.package_cache_dir(self.ctx, type_project),
        }
        if self.path:
            request["path"] = os.path.abspath(self.path)
        for param_name, param in (self.config.get("parameters") or {}).items():
            request["parameters"][param_name] = param.get("default") if isinstance(param, dict) else param
        return request

    async def run_type_async(self, shape, type_project, type_config):
        """Run the type's script for 'shape' and return the wrapper's answer.

        None once 'shape.error()' has said why there is none: a file that is
        not there, a script that is not, a script that failed. The answer is
        the wrapper's, with 'success' true: what it holds depends on the kind
        of object (see wrappers/wrapper_part_type.py).
        """
        if self.path:
            try:
                await self.download_file_async(shape)
            except Exception as e:
                shape.error("Failed to fetch %s: %s" % (self.path, e))
                return None
            if not os.path.isfile(self.path):
                shape.error("The %s's file is not found: %s" % (self.OBJECT_KIND, self.path))
                return None

        # The script: 'path' or, by default, '<name>.py'.
        script_rel = type_config.get("path", self.type_name + ".py")
        try:
            script_abs = await self._materialize_wrapper_script(type_project, script_rel)
        except Exception as e:
            shape.error(str(e))
            return None

        # Prepare the sandbox: the type's package dependencies, then whatever
        # the type itself declares, then the geometry stack.
        await self.runtime.prepare_for_package(type_project, session=self.session)
        await self.runtime.prepare_for_shape(self.config, session=self.session)
        for req in type_config.get("pythonRequirements", []) or []:
            await self.runtime.ensure_async(req, session=self.session)

        # The geometry stack the sandbox needs so a wrapper can build and
        # serialize shapes. The versions come from sandbox_versions: a session
        # v-env is shared by every object of a package, so a factory that pins
        # its own version corrupts it for all the others. The core itself never
        # imports OCP - shapes cross the boundary as BREP envelopes (see
        # shape_envelope).
        await self.runtime.ensure_async(sandbox_versions.OCP_TESSELLATE, session=self.session)
        await self.runtime.ensure_async(sandbox_versions.TYPING_EXTENSIONS, session=self.session)
        await self.runtime.ensure_async(sandbox_versions.OCPSVG, session=self.session)
        await self.runtime.ensure_async(sandbox_versions.BUILD123D, session=self.session)
        # The OCP build build123d depends on, which is the one the sandbox's own
        # environment holds. A type that imports CadQuery says so in its
        # 'pythonRequirements', and runs in a layer that carries CadQuery's own
        # build.
        await self.runtime.ensure_async(sandbox_versions.OCP, session=self.session)

        request = self.type_request(shape, type_project)
        # The file goes on the command line as well as in the request, which is
        # what a sandbox that is sent files rather than sharing them sends and
        # rewrites (see 'request_paths').
        command = request_paths.carry(
            [wrapper.get("part_type.py"), os.path.abspath(script_abs), os.path.abspath(type_project.config_dir)],
            request,
            ("path",),
        )
        request_serialized = shape_envelope.serialize(request)

        exitcode, response_serialized, errors = await self.runtime.run_async(
            command,
            request_serialized,
            session=self.session,
        )
        if exitcode != 0 and not errors:
            errors = "%s: %s: %s wrapper failed (%s)" % (
                shape.project_name,
                shape.name,
                self.TYPE_KIND,
                describe_exit_code(exitcode),
            )
        if errors:
            for line in errors.split("\n"):
                line = line.strip()
                if line:
                    pc_logging.debug("%s: %s" % (shape.name, line))

        try:
            response = shape_envelope.deserialize(response_serialized)
        except Exception as e:
            shape.error("Deserialization error: %s" % e)
            return None

        if not response.get("success"):
            shape.error(str(response.get("exception")))
            return None
        return response

    async def record_reported_async(self, shape, response) -> None:
        """Keep what a successful build's script reported reading, for a type keyed on it."""
        if self._declared_key is None:
            return
        if "dependencies" in response and response["dependencies"] is None:
            # The script could not tell what it read: an object kept under a
            # key that leaves those files out would be served after one of them
            # changed. Not cached, then, and so built again.
            pc_logging.warning("%s: what it is read from could not be told, so it is not cached" % shape.name)
            shape.hash = CacheHash(shape.hash.name)
        else:
            await self._record_discovered(shape, response.get("dependencies") or [])
