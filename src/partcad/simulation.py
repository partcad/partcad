#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Simulating a part or an assembly: what ``simulate:`` declares and how it runs.

A part says what it *is*. ``simulate:`` is where it says what it is supposed to
*do* -- or, more often, what it is supposed not to do: not fall over, not slide
off, not come apart. That is a claim about the part in a world, so a simulation
is never of a part alone:

    scene       the world it is placed in, by full path. The subject's own full
                path is assigned to that scene's ``subject`` parameter,
                unconditionally and whatever else the declaration says, which is
                what makes one scene serve every object that names it. Nothing
                is declared for it: a scene is an ordinary object, and this is
                an ordinary parameter of it.
    offset      where in that scene the subject goes, in the scene's frame. It
                is stated here rather than in the scene because it is a fact
                about *this* object -- where its origin sits relative to the
                floor it is meant to stand on -- and the scene is shared.
    simulation  which simulation plugin runs it, by full path. A plugin is
                declared exactly as an export or a render implementation is
                (see 'partcad.output'), in a ``simulation:`` section: a scene
                goes in as a file, JSON carrying ``before`` and ``after`` comes
                out. See 'wrappers/wrapper_simulate.py'. It is always somebody
                else's package -- PartCAD ships no simulator.
    validation  a Python expression over ``before`` and ``after`` that says
                whether what happened is what was supposed to happen. It is the
                only thing PartCAD reads out of a plugin's result: what is
                *inside* ``before`` and ``after`` is the plugin's vocabulary,
                and the expression is written by whoever knows both the part and
                the plugin.

``scene`` does not have to be named -- the default is the built-in empty world
holding the subject, which is what "does this part stand up on its own" means
and is most of what anybody asks. ``simulation`` does: PartCAD implements no
simulator (see 'output.SIMULATE'), so a package imports one and says which.

What is deliberately *not* here: PartCAD does not know what a simulation
result means. It exports the scene, starts the plugin, hands the two objects the
plugin produced to the expression the package wrote, and reports what the
expression said. Every judgement in that sentence belongs to the package.
"""

from __future__ import annotations

import copy
import hashlib
import os
import shutil
import typing

from . import cache_artifacts
from . import logging as pc_logging
from . import output, shape_envelope, wrapper
from .process_crash import describe_exit_code
from .utils import resolve_resource_path

# The section of 'partcad.yaml' a part or an assembly declares its simulations in.
SECTION = "simulate"

# The scene a declaration that names none is run in. There is no counterpart
# for the plugin: PartCAD implements no simulator (see 'output.SIMULATE'), so
# 'simulation:' has to be named and there is nothing sensible to default it to.
DEFAULT_SCENE = output.BUILTIN_SCENE_PACKAGE + ":subject"

# The package that implements the one PartCAD knows about, named in the message
# a declaration that forgot 'simulation:' gets. Not a default and not a
# dependency -- a string in an error, so that "you have to name one" also
# answers "name what?".
KNOWN_SIMULATION = "partcad/partcad-sim-mujoco"

# The parameter every scene used as a simulation scene is handed the subject's
# full path in. Required of the scene: a scene that does not declare it cannot
# place the subject, and running it would silently simulate an empty world.
SUBJECT_PARAMETER = "subject"
# The two a scene may declare beside it, filled in when it does. Optional
# because a scene that hard-codes where and what its subject is (a fixture built
# around one part) is a perfectly good scene.
SUBJECT_KIND_PARAMETER = "subject_kind"
SUBJECT_OFFSET_PARAMETER = "subject_offset"

# The identity, as the string a scene parameter carries it in. A location
# reaches an ASSY template as text that is substituted into the YAML, so it is
# written the way the YAML would have been written by hand.
IDENTITY_OFFSET = [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 0.0]

# What a 'validation:' expression may call. Everything else - '__import__',
# 'open', 'eval' - is absent, and so is every module: the expression is a
# question about two dictionaries, and the answer never needs the filesystem.
#
# This is not a security boundary and is not meant to be one. A package that
# can declare a 'validation:' can also declare a CadQuery part, which is
# arbitrary code by design; what this is for is that a validation expression
# stays a validation expression, so that a reader of it can see what it asserts
# without having to wonder what else it does.
VALIDATION_BUILTINS = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in (
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "divmod",
        "enumerate",
        "filter",
        "float",
        "int",
        "len",
        "list",
        "map",
        "max",
        "min",
        "pow",
        "range",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    )
}


class SimulationConfigError(Exception):
    """What a declaration names cannot be found, so nothing could be run.

    No plugin named, a plugin no package declares, a scene that is not there or
    cannot hold a subject, a plugin that names no format to hand the scene over
    in. Each of those is wrong on every machine the package is opened on, and no
    install mends it -- which is the whole of why it is a type of its own:
    `partcad.test.sim` fails it whatever the machine, while a run that resolved
    and then did not deliver may be the machine's fault (see
    `ImplementationTest._verdict`). The same split `CaeConfigError` and
    `CamConfigError` make for the analyses and the routes.
    """


class SimulationDeclaration:
    """One entry of an object's ``simulate:`` section, normalized."""

    def __init__(self, name: str, config: dict):
        self.name = name
        if config and not isinstance(config, dict):
            # A declaration that is not a mapping - most often a section written
            # as one unnamed simulation, which is not a form PartCAD has. Read
            # as empty and reported, so that it fails saying what is wrong with
            # it rather than on an attribute of a string.
            pc_logging.error(
                "The simulation '%s' is not a mapping of settings: '%s' is a section of named simulations"
                % (name, SECTION)
            )
            config = {}
        self.config = config or {}
        self.desc = self.config.get("desc")
        self.scene = self.config.get("scene") or DEFAULT_SCENE
        # No default: see 'KNOWN_SIMULATION'. 'run_async' is what reports it,
        # so that a package listing an object with a broken 'simulate:' still
        # lists it.
        self.simulation = self.config.get("simulation") or None
        self.validation = self.config.get("validation")
        self.offset = normalize_offset(self.config.get("offset"), name)
        # Parameter overrides handed to the plugin, on top of what its own
        # declaration says. A 'simulate:' that wants a longer run says
        # 'params: {duration: 30}' rather than needing a plugin of its own.
        self.params = self.config.get("params") or {}

    def __repr__(self) -> str:
        return "<simulate %s: %s in %s>" % (self.name, self.simulation, self.scene)


class SimulationResult:
    """What one run produced, and what the validation made of it."""

    def __init__(self, declaration: SimulationDeclaration, object_name: str):
        self.declaration = declaration
        self.object_name = object_name
        # None when nothing was validated - either the declaration states no
        # expression, or the run never got far enough to evaluate one.
        self.passed: typing.Optional[bool] = None
        self.result: dict = {}
        self.error: typing.Optional[str] = None

        # The three below are for a caller that has to say *why*, and are kept
        # out of 'to_dict()' -- which is what 'pc sim --json' prints, and which
        # is unchanged by them.
        #
        # What the run raised, beside 'error', which is only its text: whether
        # it was the declaration's fault ('SimulationConfigError') or the
        # machine's ('runtime.SandboxUnavailable') is a question of its type.
        self.exception: typing.Optional[BaseException] = None
        # The plugin, once it resolved. None means the run never got as far as
        # knowing who would have run it.
        self.plugin: typing.Optional[output.Implementation] = None
        # Why the 'validation:' could not be evaluated, when that is why it
        # failed: a syntax error, or an expression that raised. None when it was
        # evaluated -- including to False, which is a verdict and not a problem.
        self.problem: typing.Optional[str] = None

    @property
    def name(self) -> str:
        return self.declaration.name

    @property
    def failed(self) -> bool:
        """Whether this run is a failure the command should exit non-zero on."""
        return self.error is not None or self.passed is False

    @property
    def misconfigured(self) -> bool:
        """Whether this run failed on what the declaration names, before anything ran."""
        return isinstance(self.exception, SimulationConfigError)

    @property
    def plugin_name(self) -> str:
        """The plugin as a full path, or as the declaration wrote it if it never resolved."""
        if self.plugin is not None and self.plugin.project is not None:
            return "%s:%s" % (self.plugin.project.name, self.plugin.format_name)
        return str(self.declaration.simulation)

    def to_dict(self) -> dict:
        return {
            "object": self.object_name,
            "simulation": self.name,
            "scene": self.declaration.scene,
            "plugin": self.declaration.simulation,
            "validation": self.declaration.validation,
            "passed": self.passed,
            "error": self.error,
            "result": self.result,
        }


def normalize_offset(offset, name: str) -> list:
    """A declared ``offset:`` as PartCAD's packed location, or the identity.

    Reported and defaulted rather than raised on: an offset that is written
    wrongly puts the subject in the wrong place, which is a thing the person
    who wrote it can see and correct, while refusing to run tells them less.
    """
    if offset is None:
        return copy.deepcopy(IDENTITY_OFFSET)
    try:
        translation, axis, angle = offset
        packed = [
            [float(v) for v in translation],
            [float(v) for v in axis],
            float(angle),
        ]
        if len(packed[0]) != 3 or len(packed[1]) != 3:
            raise ValueError("a location needs three numbers of translation and three of axis")
        return packed
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.error("The 'offset' of the simulation '%s' is not a location: %s" % (name, e))
        return copy.deepcopy(IDENTITY_OFFSET)


def declared(config: dict) -> list:
    """The simulations an object declares, in the order they are declared.

    A mapping of names to declarations, which is what every other named section
    of 'partcad.yaml' is - 'export:', 'render:', 'simulation:'. There is
    deliberately no unnamed single-declaration short form: telling one from the
    other means guessing from which keys are present, and the name is not
    ceremony - it is what '-f' selects, what the report prints beside the
    verdict, and what names the directory a run's scene is written to.
    """
    section = (config or {}).get(SECTION)
    if not section:
        return []
    if not isinstance(section, dict):
        pc_logging.error("The '%s' section must be a mapping of simulation names" % SECTION)
        return []
    return [SimulationDeclaration(name, value or {}) for name, value in section.items()]


def of_shape(shape) -> list:
    """The simulations a shape declares, through whatever it resolves to.

    'get_final_config()' rather than 'config', so that an alias and an enrich
    answer for what they point at - the same reading 'shape_config.final_config'
    does, and for the same reason.
    """
    from .shape_config import final_config

    return declared(final_config(shape))


# ---------------------------------------------------------------------------
# Resolving what a declaration names
# ---------------------------------------------------------------------------


def resolve_plugin(ctx, package_name: str, spec: str):
    """The 'output.Implementation' of the simulation plugin 'spec' names.

    A plugin is addressed by full path (``<package>:<name>``) rather than by
    name alone, which is what separates it from an export or a render format:
    those are file *types*, and a package configuring one is configuring the way
    that type is written for itself. A simulation is not a type of anything -
    "mujoco" is a program - so the declaration says whose it is.
    """
    plugin_package, plugin_name = resolve_resource_path(package_name, spec)
    project = ctx.get_project(plugin_package)
    if project is None:
        raise SimulationConfigError(
            "The package implementing the simulation '%s' is not found: %s. "
            "Add it to this package's 'dependencies:', or name another one." % (spec, plugin_package)
        )
    if getattr(project, "broken", False):
        # A package that failed to load answers every question about itself
        # with nothing, so without this the sentence below would say it declares
        # no simulations at all -- sending the reader to a file that was never
        # read. The reason is already in the log; what is worth saying here is
        # that this is why the simulation is not running. The same note
        # 'Shape._analysis_implementation' makes for a solver.
        raise SimulationConfigError(
            "The package implementing the simulation '%s' did not load: %s. "
            "The reason is reported above; a dependency that could not be fetched is the usual one."
            % (spec, project.name)
        )

    section = project.config_obj.get(output.SIMULATE) or {}
    config = section.get(plugin_name)
    if config is None:
        raise SimulationConfigError(
            "The package '%s' declares no simulation '%s'. It declares: %s"
            % (plugin_package, plugin_name, ", ".join(sorted(section)) or "none")
        )

    config = output.stamp(output.normalize(config), plugin_package)
    return output.Implementation(output.SIMULATE, plugin_name, config, project)


def scene_parameters(
    ctx, scene_package: str, scene_name: str, declaration: SimulationDeclaration, subject: str, kind: str
) -> dict:
    """The parameter values the simulation scene is asked for.

    ``subject`` always, because that is what a simulation scene is for and a
    scene that cannot take it is not one. The other two only when the scene
    declares them: a scene written around one particular fixture may well say
    where the subject goes itself, and handing it a parameter it never declared
    is an error rather than an override.
    """
    project = ctx.get_project(scene_package)
    if project is None:
        raise SimulationConfigError("The package holding the simulation scene is not found: %s" % scene_package)
    config = project.get_scene_config(scene_name)
    if config is None:
        raise SimulationConfigError("The simulation scene is not found: %s:%s" % (scene_package, scene_name))

    parameters = config.get("parameters") or {} if isinstance(config, dict) else {}
    if SUBJECT_PARAMETER not in parameters:
        raise SimulationConfigError(
            "The scene '%s:%s' declares no '%s' parameter, so it cannot hold the object being simulated"
            % (scene_package, scene_name, SUBJECT_PARAMETER)
        )

    params = {SUBJECT_PARAMETER: subject}
    if SUBJECT_KIND_PARAMETER in parameters:
        params[SUBJECT_KIND_PARAMETER] = kind
    if SUBJECT_OFFSET_PARAMETER in parameters:
        params[SUBJECT_OFFSET_PARAMETER] = format_offset(declaration.offset)
    elif declaration.config.get("offset") is not None:
        pc_logging.warning(
            "The scene '%s:%s' declares no '%s' parameter, so the 'offset' of the simulation '%s' is ignored"
            % (scene_package, scene_name, SUBJECT_OFFSET_PARAMETER, declaration.name)
        )
    return params


def format_offset(offset) -> str:
    """A packed location as the seven numbers a scene parameter carries.

    Not as the bracketed, comma-separated form a location is written in
    everywhere else, and the reason is a rule of PartCAD's own: a parameter
    value has to be spellable in an instance name ("scene;subject_offset=..."),
    where ',', ';' and '=' are the separators -- which is why the configuration
    schema refuses a string default carrying one (see 'parameter-default').
    Seven whitespace-separated numbers say exactly the same thing and carry
    none of them; the scene's template puts the brackets back.
    """
    translation, axis, angle = offset
    return " ".join("%g" % float(value) for value in list(translation) + list(axis) + [angle])


def run_directory(ctx, object_name: str, simulation_name: str) -> str:
    """Where one run's scene file, its meshes and whatever the plugin writes go.

    Under PartCAD's own state directory, for the reason every other generated
    file is: a simulation is derived data and running one must not drop files
    into the user's source tree. Stable per (object, simulation), so a rerun
    replaces the previous one instead of accumulating (see 'run_async', which
    empties it first).
    """
    digest = hashlib.sha256(("%s\0%s" % (object_name, simulation_name)).encode("utf-8")).hexdigest()[:16]
    directory = os.path.join(ctx.user_config.internal_state_dir, "simulate", digest)
    os.makedirs(directory, exist_ok=True)
    return directory


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def subject_kind(shape) -> typing.Optional[str]:
    """What a shape is as the subject of a simulation, or None if it cannot be one.

    A part or an assembly: those are what declare ``simulate:``. Asked of the
    shape's own ``kind`` rather than of its class, because a scene *is* an
    assembly in the class hierarchy and is not a subject -- it is the world a
    subject is placed in.
    """
    kind = getattr(shape, "kind", None)
    return kind if kind in ("part", "assembly") else None


async def run_declared_async(
    ctx, shape, kind: str, name: typing.Optional[str] = None, report: bool = True
) -> typing.List[SimulationResult]:
    """Run the simulations a shape declares, or the one called ``name``.

    One after another, deliberately: a simulation plugin is a whole simulator
    running a physics model, so the machine is what limits how many fit at once,
    and two competing for it make both slower and neither more informative. This
    is the loop ``pc sim`` runs for each object it was asked about and the one
    ``pc test``'s ``sim`` check runs for the object it is checking -- one loop,
    so the two cannot come to run different simulations of the same object.

    ``report`` is handed to 'run_async' for each.
    """
    results = []
    for declaration in of_shape(shape):
        if name and declaration.name != name:
            continue
        results.append(await run_async(ctx, shape, kind, declaration, report=report))
    return results


async def run_async(ctx, shape, kind: str, declaration: SimulationDeclaration, report: bool = True) -> SimulationResult:
    """Run one declared simulation of one object and validate what came back.

    Never raises: whatever went wrong is on the result, as text in ``error``
    and as the exception itself in ``exception``.

    ``report`` is whether this says what came of the run, at the level the
    outcome deserves -- ``ERROR`` for a run that failed or did not validate.
    ``pc sim`` asks it to, because those lines are its verdict. ``pc test`` does
    not, because its verdict is the check's to write: a check that decides a
    failed run was the machine's fault and *skips* it cannot have had an
    ``ERROR`` logged in its name already, since any ``ERROR`` is what makes
    ``pc`` exit non-zero. Unreported, the same lines go to ``DEBUG``.
    """
    object_name = "%s:%s" % (shape.project_name, shape.name)
    result = SimulationResult(declaration, object_name)
    say_error = pc_logging.error if report else pc_logging.debug
    say_info = pc_logging.info if report else pc_logging.debug

    with pc_logging.Action("Simulate", shape.project_name, "%s/%s" % (shape.name, declaration.name)):
        try:
            if not declaration.simulation:
                raise SimulationConfigError(
                    "the simulation '%s' names no 'simulation:' plugin to run it. PartCAD implements no "
                    "simulator itself; import one and name it, e.g. '%s' for MuJoCo"
                    % (declaration.name, KNOWN_SIMULATION)
                )
            # Both names resolve against the package the object is in, never
            # against the current one: 'sim-mujoco:mujoco' means the
            # 'sim-mujoco' *that* package imported. Which is what keeps
            # 'pc test -P //...' -- run with the root of a tree current while
            # every object in it sits one or more packages down -- resolving
            # each declaration the way 'pc sim' in its own package would.
            impl = resolve_plugin(ctx, shape.project_name, declaration.simulation)
            result.plugin = impl
            scene_package, scene_name = resolve_resource_path(shape.project_name, declaration.scene)
            params = scene_parameters(ctx, scene_package, scene_name, declaration, object_name, kind)

            scene = ctx.get_scene("%s:%s" % (scene_package, scene_name), params)
            if scene is None:
                raise SimulationConfigError(
                    "The simulation scene could not be built: %s:%s" % (scene_package, scene_name)
                )

            directory = run_directory(ctx, object_name, declaration.name)
            # What the directory holds is this run's and nothing else's: the
            # whole of it is what the cache stores, and an artifact an earlier
            # run left there would be stored as this one's - or, worse, read by
            # whoever opens the directory as what this run produced.
            _empty(directory)

            # The same question asked again is a read: the directory is put
            # back as the run that answered it left it, scene and all, and the
            # result comes with it. The validation is not part of the question
            # and is evaluated below either way, so editing it re-judges the
            # run rather than repeating it.
            cache = getattr(ctx, "cache_artifacts", None)
            artifact = await _artifact_hash(ctx, scene, impl, declaration, object_name, kind)
            result.result = await cache_artifacts.restore_async(cache, artifact, directory=directory)
            if result.result is None:
                # Whatever a failed restore managed to write is not this run's.
                _empty(directory)
                scene_file = await _export_scene_async(ctx, scene, impl, directory)
                result.result = await _run_plugin_async(
                    ctx, impl, directory, scene_file, declaration, object_name, kind
                )
                # Only an answer is remembered: a run that failed raised above.
                await cache_artifacts.store_async(cache, artifact, result.result, directory=directory)
        except Exception as e:  # pylint: disable=broad-except
            result.error = str(e)
            result.exception = e
            say_error("%s: the simulation '%s' failed: %s" % (object_name, declaration.name, e))
            return result

        result.passed, result.problem = _evaluate(declaration, result.result, object_name)
        if result.problem:
            say_error(result.problem)
        if result.passed is False:
            say_error("%s: the simulation '%s' did not validate" % (object_name, declaration.name))
        elif result.passed is True:
            say_info("%s: the simulation '%s' validated" % (object_name, declaration.name))
        return result


def _empty(directory: str) -> None:
    """Leave 'directory' there and empty."""
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory, exist_ok=True)


def _scene_export(ctx, scene, impl, directory: str):
    """Who writes the scene for the plugin: the format, its implementation, the package."""
    format_name = impl.config.get("format")
    if not format_name:
        raise SimulationConfigError(
            "The simulation '%s' declares no 'format' to hand the scene over in" % impl.format_name
        )

    scene_project = ctx.get_project(scene.project_name)
    # The plugin's own package is read for the file type as well, underneath the
    # scene's. ``format:`` is the plugin saying which file type it reads, and an
    # engine's own scene format is one the plugin itself implements -- MJCF is
    # MuJoCo's, SDFormat is Gazebo's, and '//builtin/export' writes neither -- so
    # the plugin's package is the only place the exporter can be found. It goes
    # in below the scene's own package rather than above it so that a package
    # re-tuning the export for its own scenes still wins.
    export_impl, _ = scene.output_getopts(
        ctx, format_name, project=scene_project, options_project=impl.project, output_dir=directory
    )
    return format_name, export_impl, scene_project


async def _artifact_hash(ctx, scene, impl, declaration, subject: str, kind: str):
    """The cache key of one simulation's answer, or None when it has none.

    The scene's own key - which covers the subject, since the subject is a
    parameter of the scene and the scene is keyed on what it links to - and
    everything the run adds to it: the plugin, its resolved options and its
    sandbox, what the declaration hands it, how the scene is written for it,
    and the content of both scripts and of the wrappers that run them.

    Never raises. A key that cannot be worked out is a run that is not cached,
    and the run itself is what reports why.
    """
    try:
        subject_key = await scene.get_cache_key_async()
        if not subject_key:
            return None
        format_name, export_impl, _ = _scene_export(ctx, scene, impl, os.curdir)
        # First: resolving a script is also what tells an implementation which
        # package it lives in, and its interpreter is that package's to say.
        files = [
            await output.materialize_script(ctx, impl),
            await output.materialize_script(ctx, export_impl),
            wrapper.get("simulate.py"),
            wrapper.get("export.py"),
        ]
        question = {
            "kind": "simulation",
            "plugin": "%s:%s" % (impl.project.name, impl.format_name),
            "options": impl.config,
            "params": declaration.params,
            "subject": subject,
            "subject_kind": kind,
            # Declared, never observed: see 'Implementation.environment_cache_key'.
            "environment": impl.environment_cache_key(),
            "format": format_name,
            "export": export_impl.config,
            "export_environment": export_impl.environment_cache_key(),
        }
        return cache_artifacts.question_hash("%s#%s" % (subject, declaration.name), subject_key, question, files)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s: the simulation '%s' will not be cached: %s" % (subject, declaration.name, e))
        return None


async def _export_scene_async(ctx, scene, impl, directory: str) -> str:
    """Write the scene out in the format the plugin reads, and return the file.

    The plugin's own declaration decides both halves: ``format:`` says which
    file type, and ``formatOptions:`` says how it is to be written -- which for
    a physics simulation means "every body free to move", the opposite of what a
    scene means on its own. A plugin is the only thing that knows that, which is
    why it says so rather than PartCAD assuming it.
    """
    format_name, export_impl, scene_project = _scene_export(ctx, scene, impl, directory)
    path = os.path.join(directory, "scene." + export_impl.extension(format_name))

    options = impl.config.get("formatOptions") or {}
    await scene.render_async(
        ctx,
        format_name,
        project=scene_project,
        options_project=impl.project,
        filepath=path,
        **options,
    )
    if not os.path.isfile(path):
        raise Exception("The scene was not written to %s as '%s'" % (path, format_name))
    return path


async def _run_plugin_async(ctx, impl, directory: str, scene_file: str, declaration, subject: str, kind: str) -> dict:
    """Start the plugin in its sandbox and return the JSON it produced."""
    script = await output.materialize_script(ctx, impl)

    request = dict(impl.parameters)
    request.update(declaration.params)
    request.update(
        {
            "scene_file": os.path.abspath(scene_file),
            "scene_format": impl.config.get("format"),
            "scene_name": os.path.splitext(os.path.basename(scene_file))[0],
            "subject": subject,
            "subject_kind": kind,
            "simulation": declaration.name,
        }
    )
    # The same key the export wrapper reads its script path under; one
    # definition of it, in 'output', so the two wrappers cannot disagree.
    request[output.SCRIPT_KEY] = os.path.abspath(script)

    runtime = ctx.get_python_runtime(version=impl.python_version())
    await runtime.prepare_for_package(impl.project)
    # One at a time rather than with asyncio.gather(), for the reason
    # 'Shape._render_one_async' installs them that way: the order a package
    # declares its requirements in is part of what it declared.
    for dep in impl.python_requirements:
        await runtime.ensure_async(dep)

    command = [
        wrapper.get("simulate.py"),
        # The wrapper's first positional argument is the directory a plugin may
        # write artifacts into; the second is where it runs, as for every other
        # wrapper.
        os.path.abspath(directory),
        os.path.abspath(impl.project.config_dir),
    ]
    exitcode, response_serialized, errors = await runtime.run_async(command, shape_envelope.serialize(request))
    # Only on a non-zero exit. 'RuntimePython' clears stderr for a run it
    # considers successful, but it decides that on the raw 'returncode' -
    # *before* normalizing the two Windows fault codes it deliberately forgives
    # (see 'run_async_onced_locked'). So a forgiven crash arrives here as
    # exitcode 0 with stderr still set, and raising on stderr alone would fail a
    # run the runtime just decided to let through. A wrapper that really failed
    # says so in its result, which the 'success' check below reads.
    if exitcode != 0:
        raise Exception(errors or "the simulation failed: %s" % describe_exit_code(exitcode))

    if not response_serialized.strip():
        raise Exception("the simulation produced no result")
    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "the simulation failed")
    for warning in result.get("warnings") or []:
        pc_logging.warning("%s: %s" % (declaration.name, warning))
    return result


def validate(declaration: SimulationDeclaration, result: dict, object_name: str):
    """Evaluate a declaration's ``validation:``, or None when it states none.

    The expression is handed ``before``, ``after`` and, beside them, ``result``
    -- the whole of what the plugin returned, for a validation that needs
    something the plugin states outside the two. What is inside any of them is
    the plugin's business; this only carries them across.

    An expression that raises is a failure of the validation and not of the
    simulation: the run happened, and what did not work is the claim made about
    it. Reported with the exception, because "TypeError" on its own tells
    whoever wrote it nothing.
    """
    verdict, problem = _evaluate(declaration, result, object_name)
    if problem:
        pc_logging.error(problem)
    return verdict


def _evaluate(declaration: SimulationDeclaration, result: dict, object_name: str):
    """'validate' without the logging: the verdict, and why it could not be reached.

    The second is None unless the expression would not compile or raised, and
    is then the sentence 'validate' logs. Returned rather than logged so that
    'run_async' can leave the saying of it to its caller (see its ``report``),
    and so that 'pc test' can put it in the one line its verdict is.
    """
    if not declaration.validation:
        return None, None
    # In the globals rather than in a separate locals mapping, and that is not a
    # detail: a generator expression compiles to a function of its own, and a
    # function body sees the enclosing globals but never a caller's locals. The
    # natural way to write one of these expressions is
    # "max(f(after[k]) for k in before)", and with the values in locals that
    # fails with "name 'after' is not defined" - only the outermost iterable is
    # evaluated in the enclosing scope.
    scope = {
        "__builtins__": VALIDATION_BUILTINS,
        "before": result.get("before"),
        "after": result.get("after"),
        "result": result,
    }
    try:
        verdict = eval(  # pylint: disable=eval-used
            compile(declaration.validation.strip(), "<validation:%s>" % declaration.name, "eval"),
            scope,
        )
    except SyntaxError as e:
        return False, (
            "%s: the 'validation' of the simulation '%s' is not a Python expression: %s"
            % (object_name, declaration.name, e)
        )
    except Exception as e:  # pylint: disable=broad-except
        return False, (
            "%s: the 'validation' of the simulation '%s' could not be evaluated: %s: %s"
            % (object_name, declaration.name, type(e).__name__, e)
        )
    return bool(verdict), None


# ---------------------------------------------------------------------------
# Saying what came of it
# ---------------------------------------------------------------------------


def dysfunction_report(
    object_name: str, simulation_name: str, plugin: str, error, remedy: typing.Optional[str] = None
) -> str:
    """Why a simulation produced no answer, as the failure a user has to act on.

    The report 'partcad.cae.dysfunction_report()' writes for an analysis and
    'partcad.cam.dysfunction_report()' for a route, and for the same reason:
    what the plugin said is relayed verbatim, because only it knows what went
    wrong, and what PartCAD adds is the two things the sentence usually omits
    and the reader always needs -- which plugin was asked, and which machine it
    did not work on. "No module named 'mujoco'" is a puzzle; the same sentence
    under '//...:mujoco' on Windows-AMD64 is an answer.
    """
    import platform

    lines = [
        "%s: the simulation '%s' could not be run by %s" % (object_name, simulation_name, plugin),
        "\t%s" % str(error).replace("\n", "\n\t"),
        "\tplatform: %s-%s, Python %s" % (platform.system(), platform.machine(), platform.python_version()),
    ]
    if remedy:
        lines.append("\t%s" % remedy)
    return "\n".join(lines)


def validation_report(result: SimulationResult) -> str:
    """Why a run that happened is not what the declaration said would happen.

    The expression is quoted, because it is the claim that failed and the reader
    has to see which one -- an object can declare several, and the package may
    have been edited since anybody last read it. What the plugin reported is
    not: it is the plugin's own vocabulary and often long, and ``pc sim --json``
    prints the whole of it for the one run somebody wants to look into.
    """
    declaration = result.declaration
    if result.problem:
        # The expression never reached a verdict, which says more about it than
        # "does not hold" would.
        head = result.problem
    else:
        head = "%s: the simulation '%s' ran, and its 'validation' does not hold" % (
            result.object_name,
            declaration.name,
        )
    expression = str(declaration.validation or "").strip().replace("\n", "\n\t\t")
    return "%s\n\tvalidation:\n\t\t%s\n\t'pc sim --json' prints what %s reported" % (
        head,
        expression,
        result.plugin_name,
    )
