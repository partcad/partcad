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
                out. See 'wrappers/wrapper_simulate.py'.
    validation  a Python expression over ``before`` and ``after`` that says
                whether what happened is what was supposed to happen. It is the
                only thing PartCAD reads out of a plugin's result: what is
                *inside* ``before`` and ``after`` is the plugin's vocabulary,
                and the expression is written by whoever knows both the part and
                the plugin.

Neither ``scene`` nor ``simulation`` has to be named. The defaults are the two
built-in packages -- an empty world holding the subject, run in MuJoCo -- which
is what "does this part stand up on its own" means and is most of what anybody
asks.

What is deliberately *not* here: PartCAD does not know what a simulation
result means. It exports the scene, starts the plugin, hands the two objects the
plugin produced to the expression the package wrote, and reports what the
expression said. Every judgement in that sentence belongs to the package.
"""

from __future__ import annotations

import copy
import hashlib
import os
import typing

from . import logging as pc_logging
from . import output, shape_envelope, wrapper
from .utils import resolve_resource_path

# The section of 'partcad.yaml' a part or an assembly declares its simulations in.
SECTION = "simulate"

# The scene a declaration that names none is run in, and the plugin a
# declaration that names none is run by.
DEFAULT_SCENE = output.BUILTIN_SCENE_PACKAGE + ":subject"
DEFAULT_SIMULATION = output.BUILTIN_PACKAGES[output.SIMULATE] + ":mujoco"

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


class SimulationDeclaration:
    """One entry of an object's ``simulate:`` section, normalized."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config or {}
        self.desc = self.config.get("desc")
        self.scene = self.config.get("scene") or DEFAULT_SCENE
        self.simulation = self.config.get("simulation") or DEFAULT_SIMULATION
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

    @property
    def name(self) -> str:
        return self.declaration.name

    @property
    def failed(self) -> bool:
        """Whether this run is a failure the command should exit non-zero on."""
        return self.error is not None or self.passed is False

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

    Accepts the two shapes a section like this is written in: a mapping of names
    to declarations, which is what every other named section of 'partcad.yaml'
    is, and a single unnamed declaration, which is what one simulation looks
    like when there is no reason to name it. The latter is given the name
    "default" so that everything downstream - the report, '-f', the JSON - has
    one to print.
    """
    section = (config or {}).get(SECTION)
    if not section:
        return []
    if not isinstance(section, dict):
        pc_logging.error("The '%s' section must be a mapping of simulation names" % SECTION)
        return []
    if any(key in section for key in ("scene", "simulation", "validation", "offset", "params")):
        return [SimulationDeclaration("default", section)]
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
        raise Exception("The package implementing the simulation '%s' is not found: %s" % (spec, plugin_package))

    section = project.config_obj.get(output.SIMULATE) or {}
    config = section.get(plugin_name)
    if config is None:
        raise Exception(
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
        raise Exception("The package holding the simulation scene is not found: %s" % scene_package)
    config = project.get_scene_config(scene_name)
    if config is None:
        raise Exception("The simulation scene is not found: %s:%s" % (scene_package, scene_name))

    parameters = config.get("parameters") or {} if isinstance(config, dict) else {}
    if SUBJECT_PARAMETER not in parameters:
        raise Exception(
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
    overwrites the previous one instead of accumulating.
    """
    digest = hashlib.sha256(("%s\0%s" % (object_name, simulation_name)).encode("utf-8")).hexdigest()[:16]
    directory = os.path.join(ctx.user_config.internal_state_dir, "simulate", digest)
    os.makedirs(directory, exist_ok=True)
    return directory


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


async def run_async(ctx, shape, kind: str, declaration: SimulationDeclaration) -> SimulationResult:
    """Run one declared simulation of one object and validate what came back."""
    object_name = "%s:%s" % (shape.project_name, shape.name)
    result = SimulationResult(declaration, object_name)

    with pc_logging.Action("Simulate", shape.project_name, "%s/%s" % (shape.name, declaration.name)):
        try:
            impl = resolve_plugin(ctx, shape.project_name, declaration.simulation)
            scene_package, scene_name = resolve_resource_path(shape.project_name, declaration.scene)
            params = scene_parameters(ctx, scene_package, scene_name, declaration, object_name, kind)

            scene = ctx.get_scene("%s:%s" % (scene_package, scene_name), params)
            if scene is None:
                raise Exception("The simulation scene could not be built: %s:%s" % (scene_package, scene_name))

            directory = run_directory(ctx, object_name, declaration.name)
            scene_file = await _export_scene_async(ctx, scene, impl, directory)
            result.result = await _run_plugin_async(ctx, impl, directory, scene_file, declaration, object_name, kind)
        except Exception as e:  # pylint: disable=broad-except
            result.error = str(e)
            pc_logging.error("%s: the simulation '%s' failed: %s" % (object_name, declaration.name, e))
            return result

        result.passed = validate(declaration, result.result, object_name)
        if result.passed is False:
            pc_logging.error("%s: the simulation '%s' did not validate" % (object_name, declaration.name))
        elif result.passed is True:
            pc_logging.info("%s: the simulation '%s' validated" % (object_name, declaration.name))
        return result


async def _export_scene_async(ctx, scene, impl, directory: str) -> str:
    """Write the scene out in the format the plugin reads, and return the file.

    The plugin's own declaration decides both halves: ``format:`` says which
    file type, and ``formatOptions:`` says how it is to be written -- which for
    a physics simulation means "every body free to move", the opposite of what a
    scene means on its own. A plugin is the only thing that knows that, which is
    why it says so rather than PartCAD assuming it.
    """
    format_name = impl.config.get("format")
    if not format_name:
        raise Exception("The simulation '%s' declares no 'format' to hand the scene over in" % impl.format_name)

    scene_project = ctx.get_project(scene.project_name)
    export_impl, _ = scene.output_getopts(ctx, format_name, project=scene_project, output_dir=directory)
    path = os.path.join(directory, "scene." + export_impl.extension(format_name))

    options = impl.config.get("formatOptions") or {}
    await scene.render_async(ctx, format_name, project=scene_project, filepath=path, **options)
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
    if exitcode != 0 and not errors:
        errors = "the simulation failed with exit code %s" % exitcode
    if errors:
        raise Exception(errors)

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
    if not declaration.validation:
        return None
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
        pc_logging.error(
            "%s: the 'validation' of the simulation '%s' is not a Python expression: %s"
            % (object_name, declaration.name, e)
        )
        return False
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.error(
            "%s: the 'validation' of the simulation '%s' could not be evaluated: %s: %s"
            % (object_name, declaration.name, type(e).__name__, e)
        )
        return False
    return bool(verdict)
