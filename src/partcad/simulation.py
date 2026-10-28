#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Simulating a part, an assembly or a scene: what ``simulate:`` declares and how it runs.

A part says what it *is*. ``simulate:`` is where it says what it is supposed to
*do* -- or, more often, what it is supposed not to do: not fall over, not slide
off, not come apart. That is a claim about the part in a world, so a simulation
is never of a part alone. A scene declares one the same way -- a stack of blocks
is an arrangement, not a product -- and is placed in its world by a ``scene:``
link:

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
    feature     the feature of the object's ``requirements:`` that this
                simulation demonstrates, by name (or a list of them). Optional,
                and read by nothing that runs the simulation: it is what lets a
                reader of the requirements - the IDE's Requirements tab,
                ``/pc:validate`` - see which of them a simulation stands behind
                (see 'partcad.requirements').

``scene`` does not have to be named -- the default is the built-in empty world
holding the subject, which is what "does this part stand up on its own" means
and is most of what anybody asks. ``simulation`` does: PartCAD implements no
simulator (see 'output.SIMULATE'), so a package imports one and says which.

What the world is *like* is the scene's to say, not the declaration's: the
gravity in it and the fluid it is filled with (see 'partcad.scene_world'). The
built-in scene states neither -- Earth's gravity as the engine has it, in a
vacuum -- and a package that wants its part simulated under water writes a scene
that says so, the way it would for a fixture to drop the part onto. The one
override is the plugin's: a ``params: {gravity: ...}`` is handed to the plugin
like any other of its parameters and applied over the scene's for that run, so
the order is that, then the scene, then the engine's own default.

Every run also asks the plugin for two pictures of the scene, one before
anything moved and one when the run is over, taken from where the scene is
looked at when it is rendered -- see 'snapshot_request'. They are what the IDE's
Simulation tab shows side by side, and they are the one thing a reader can check
a verdict against without reading numbers.

Every run has a wall-clock **budget** (see 'run_budget'), and a run that does
not finish within it is stopped -- with everything it started -- and fails as
'SimulationTimeout'. A plugin that dies instead, or answers with something that
is not an answer, fails as 'SimulationCrash', carrying the end of what it wrote
to standard error. Neither is ever a hang, and neither is cached: only a run
that answered is.

What is deliberately *not* here: PartCAD does not know what a simulation
result means. It exports the scene, starts the plugin, hands the two objects the
plugin produced to the expression the package wrote, and reports what the
expression said. Every judgement in that sentence belongs to the package.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import os
import shutil
import typing

from partcad_utils import timeouts

from . import cache_artifacts
from . import logging as pc_logging
from . import output, shape_envelope, source_key, wrapper
from .process_crash import describe_exit_code

# By name rather than as 'from . import render': the package exports a function
# called 'render' too, and which of the two 'partcad.render' is depends on what
# was imported first.
from .render import VIEWS, resolve_viewport
from .utils import resolve_resource_path

# The section of 'partcad.yaml' a part, an assembly or a scene declares its
# simulations in.
SECTION = "simulate"

# The key of a declaration that names the requirement feature it demonstrates.
FEATURE = "feature"

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

# The pictures a run is asked to take of the scene, and the file each is written
# to inside the run directory. Named here rather than by the plugin, so that the
# request says where they go and a plugin has nothing to choose.
SNAPSHOTS = ("before", "after")
SNAPSHOT_FORMAT = "png"
SNAPSHOT_FILES = {moment: "snapshot-%s.%s" % (moment, SNAPSHOT_FORMAT) for moment in SNAPSHOTS}

# Where the scene is looked at from when nothing says otherwise: the corner a
# rendered part is drawn from, which is what makes a 3D arrangement read as 3D.
SNAPSHOT_DEFAULT_VIEW = "iso"

# The size of a snapshot when the scene's rendering configuration does not say,
# which is what '//builtin/render' gives a PNG.
SNAPSHOT_DEFAULT_SIZE = 512

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


# The parameter a run's wall-clock budget is stated and handed over under, in
# seconds -- by a declaration's 'params:', by a plugin's own declaration, and in
# the request the plugin is handed. 'wrappers/wrapper_simulate.TIMEOUT_KEY' is
# its twin, and the wrapper is what holds the run to it.
TIMEOUT_KEY = "timeout"

# The key of a plugin's answer that says its budget was spent, carrying the
# seconds; written by the wrapper, never by a plugin.
# 'wrappers/wrapper_simulate.TIMED_OUT_KEY' is its twin.
TIMED_OUT_KEY = "timed_out"

# The budget of a run nothing states one for: the larger of these two -- five
# minutes, and ten wall-clock seconds for every second of simulated time. Five
# minutes is the bound the Gazebo plugin had always waited for its server,
# which covers starting an engine in a container on a cold machine; ten times
# the duration is what keeps a long run from being cut short by it. An engine
# that runs at its real-time factor -- Gazebo's is about one -- needs about the
# duration itself; MuJoCo needs a fraction of it.
DEFAULT_TIMEOUT = 300.0
TIMEOUT_PER_SIMULATED_SECOND = 10.0

# How much longer than the budget PartCAD itself waits before it kills the
# sandbox, in seconds. The wrapper inside the sandbox stops the run when the
# budget is spent and says so (see 'wrappers/wrapper_simulate.py'); this is for
# the run so wedged that the wrapper cannot act -- an interpreter held in native
# code -- and for the time a sandbox takes to hand an answer back.
TIMEOUT_GRACE = 30.0

# How much of what a plugin wrote to standard error a failure carries: the end
# of it, which is where a traceback ends and a crash says what killed it.
STDERR_TAIL_LINES = 30
STDERR_TAIL_CHARACTERS = 4000


class SimulationTimeout(Exception):
    """A run that did not finish within its budget, and was stopped.

    A failure and not a skip (see `partcad.test.sim`): a run that hangs is a
    defect -- in the plugin, in the model it was handed, or in how long the
    package says the run takes -- and calling it unanswered would report it as
    checked. The message names the plugin, the budget and where the budget came
    from, and how to raise it; the object and the simulation are named by
    whoever reports it.
    """

    def __init__(self, message: str, budget: float, plugin: str):
        super().__init__(message)
        self.budget = budget
        self.plugin = plugin


class SimulationCrash(Exception):
    """A plugin that ended without an answer: an exit status, a signal, or output that is not one.

    Carries the end of what it wrote to standard error, which is what says why.
    """

    def __init__(self, message: str, exitcode=None):
        super().__init__(message)
        self.exitcode = exitcode


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
        self.features = declared_features(self.config.get(FEATURE))

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
        # The pictures the plugin took, as absolute paths keyed by the moment
        # each is of ('before', 'after'). Empty when it took none -- a plugin
        # that predates them, or one that could not draw on this machine.
        self.snapshots: typing.Dict[str, str] = {}

        # The four below are for a caller that has to say *why*, and are kept
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
        # The key the run's answer was looked up and stored under in the
        # artifact cache, or None when it had none. A caller that remembers
        # something derived from the run -- 'pc test''s verdict -- may only do
        # so when there was one (see 'question_key_async').
        self.artifact_key: typing.Optional[str] = None

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
            "snapshots": dict(self.snapshots),
        }


def declared_features(value) -> list:
    """The feature names a declaration's ``feature:`` gives, as a list.

    One name or several; anything else names none. Whether each is a feature
    the object's requirements declare is 'partcad.requirements' to say, since
    that is where the features are.
    """
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and item]
    return []


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
# The pictures of a run
# ---------------------------------------------------------------------------


def snapshot_request(ctx, scene) -> dict:
    """What the plugin is asked to draw of the scene, and from where.

    The camera is the one the scene is *rendered* from: ``viewport_origin`` and
    ``viewport_up`` of its ``render: png:`` configuration, read exactly as
    ``pc render -t png`` reads them -- the scene's own over its package's (see
    'Shape.output_getopts') -- so that a package that has said how its world is
    best looked at has said it once, for both. Nothing said anywhere is the
    corner a rendered part is drawn from (``render.VIEWS["iso"]``), and the size
    is the PNG's.

    ``viewport_origin`` names a direction, as it does for a render: the picture
    looks from there towards the middle of the scene, and is scaled to fit. A
    plugin that frames both pictures alike -- on everything either of them
    holds -- is one whose "after" can be read against its "before" at a glance.

    ``files`` says where each picture goes, relative to the run directory the
    plugin is handed as ``path``; see 'collect_snapshots' for what is done with
    what the plugin reports.
    """
    options = {}
    try:
        scene_project = ctx.get_project(scene.project_name)
        impl, _ = scene.output_getopts(ctx, SNAPSHOT_FORMAT, project=scene_project)
        options = impl.parameters or {}
    except Exception as e:  # pylint: disable=broad-except
        # A scene that cannot say how it is rendered still simulates: the
        # pictures are taken from the default corner, and the run is what the
        # user asked for.
        pc_logging.debug(
            "The scene %s:%s says nothing usable about how it is rendered: %s" % (scene.project_name, scene.name, e)
        )

    default_origin, default_up = VIEWS[SNAPSHOT_DEFAULT_VIEW]
    try:
        viewport = resolve_viewport(
            viewport_origin=options.get("viewport_origin") or default_origin,
            viewport_up=options.get("viewport_up") or default_up,
        )
    except ValueError as e:
        pc_logging.warning(
            "The scene %s:%s is rendered from a viewpoint that cannot be used for the snapshots of a "
            "simulation (%s); using the '%s' view" % (scene.project_name, scene.name, e, SNAPSHOT_DEFAULT_VIEW)
        )
        viewport = resolve_viewport(view=SNAPSHOT_DEFAULT_VIEW)

    return {
        "format": SNAPSHOT_FORMAT,
        "files": dict(SNAPSHOT_FILES),
        "width": _size(options.get("width")),
        "height": _size(options.get("height")),
        "viewport_origin": viewport["viewport_origin"],
        "viewport_up": viewport["viewport_up"],
    }


def _size(value) -> int:
    """A snapshot's width or height, in pixels."""
    try:
        size = int(value)
    except (TypeError, ValueError):
        return SNAPSHOT_DEFAULT_SIZE
    return size if size > 0 else SNAPSHOT_DEFAULT_SIZE


def collect_snapshots(directory: str, result: dict, object_name: str, simulation_name: str) -> dict:
    """The pictures the plugin says it took, as absolute paths, by moment.

    A plugin reports them under ``snapshots``, each as the name of a file in the
    run directory: ``{"before": "snapshot-before.png", "after": ...}``. Only the
    ones that are there are kept; one that names a file outside the directory or
    a file that does not exist is reported and left out rather than handed to
    somebody who will try to open it. A plugin that reports none has taken none,
    which is not a failure: the verdict does not depend on a picture.
    """
    reported = result.get("snapshots") if isinstance(result, dict) else None
    if not reported:
        return {}
    if not isinstance(reported, dict):
        pc_logging.warning(
            "%s: the simulation '%s' reported 'snapshots' that are not a mapping of moments to files"
            % (object_name, simulation_name)
        )
        return {}

    root = os.path.abspath(directory)
    found = {}
    for moment, name in reported.items():
        if not isinstance(name, str) or not name:
            continue
        path = os.path.abspath(os.path.join(root, name))
        if not path.startswith(root + os.sep):
            pc_logging.warning(
                "%s: the simulation '%s' reported a '%s' snapshot outside its run directory: %s"
                % (object_name, simulation_name, moment, name)
            )
            continue
        if not os.path.isfile(path):
            pc_logging.warning(
                "%s: the simulation '%s' reported a '%s' snapshot it did not write: %s"
                % (object_name, simulation_name, moment, name)
            )
            continue
        found[str(moment)] = path
    return found


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


# What may be simulated: what may declare 'simulate:', and what a simulation
# scene's 'subject_kind' parameter may be told the subject is - which is also
# the key the scene's ASSY link names it with ('part:', 'assembly:', 'scene:').
SUBJECT_KINDS = ("part", "assembly", "scene")


def subject_kind(shape) -> typing.Optional[str]:
    """What a shape is as the subject of a simulation, or None if it cannot be one.

    A part, an assembly or a scene: those are what declare ``simulate:``. A
    scene is a subject like the others -- a stack of blocks is an arrangement
    rather than a product, so it is a scene, and it is still a thing that can
    be claimed to stand -- and it is simulated as the subject *of* a scene, the
    default world or another one, whose link places it with ``scene:`` (see
    docs/design/simulation.md, section 7). Asked of the shape's own ``kind``
    rather than of its class, because a scene *is* an assembly in the class
    hierarchy and what is placed has to be told apart from it.
    """
    kind = getattr(shape, "kind", None)
    return kind if kind in SUBJECT_KINDS else None


async def run_async(
    ctx,
    shape,
    kind: str,
    declaration: SimulationDeclaration,
    report: bool = True,
    plugin: typing.Optional[str] = None,
) -> SimulationResult:
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

    ``plugin`` runs it with another simulation plugin than the one it names
    ('pc sim --plugin', the IDE's "Simulated by"), as '<package>:<name>'
    resolved the way the declaration's own would be: everything else the
    declaration says -- the scene, the offset, the parameters, the validation
    -- is asked of that plugin instead. It is a different question, so it is
    cached as one.
    """
    if plugin:
        declaration = copy.copy(declaration)
        declaration.simulation = plugin
    object_name = "%s:%s" % (shape.project_name, shape.name)
    result = SimulationResult(declaration, object_name)
    say_error = pc_logging.error if report else pc_logging.debug
    say_info = pc_logging.info if report else pc_logging.debug

    with pc_logging.Action("Simulate", shape.project_name, "%s/%s" % (shape.name, declaration.name)):
        try:
            impl = _resolve_plugin_of(ctx, shape, declaration)
            result.plugin = impl
            scene = _resolve_scene_of(ctx, shape, kind, declaration)
            # The gravity the scene states and the fluid it is filled with,
            # worked out before anything is exported: a medium nothing answers
            # to is a mistake in the declaration, and saying so here says it
            # with the scene's name on it instead of as a file that was never
            # written. The same facts are what the exporter is handed, and part
            # of what the answer is cached under -- see '_artifact_hash'.
            await scene.prepare_async()
            world = scene.world_facts(ctx)

            directory = run_directory(ctx, object_name, declaration.name)
            # What the directory holds is this run's and nothing else's: the
            # whole of it is what the cache stores, and an artifact an earlier
            # run left there would be stored as this one's - or, worse, read by
            # whoever opens the directory as what this run produced. That
            # includes last run's pictures, which would otherwise be reported as
            # this run's when the plugin draws none.
            _empty(directory)

            # The pictures to ask for. Part of the question, so that a scene
            # looked at from somewhere else is not answered with the pictures
            # taken from where it used to be looked at.
            snapshot = snapshot_request(ctx, scene)

            # The same question asked again is a read: the directory is put
            # back as the run that answered it left it, scene and all, and the
            # result comes with it. The validation is not part of the question
            # and is evaluated below either way, so editing it re-judges the
            # run rather than repeating it.
            cache = getattr(ctx, "cache_artifacts", None)
            artifact = await _artifact_hash(ctx, scene, impl, declaration, object_name, kind, world, snapshot)
            result.artifact_key = artifact.get() if artifact is not None else None
            result.result = await cache_artifacts.restore_async(cache, artifact, directory=directory)
            if result.result is None:
                # Whatever a failed restore managed to write is not this run's.
                _empty(directory)
                scene_file = await _export_scene_async(ctx, scene, impl, directory)
                result.result = await _run_plugin_async(
                    ctx, impl, directory, scene_file, declaration, object_name, kind, snapshot=snapshot
                )
                # Only an answer is remembered: a run that failed raised above.
                await cache_artifacts.store_async(cache, artifact, result.result, directory=directory)
            # Restored or run, the pictures are files in the directory now.
            result.snapshots = collect_snapshots(directory, result.result, object_name, declaration.name)
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


def _resolve_plugin_of(ctx, shape, declaration: SimulationDeclaration):
    """The plugin a declaration names, resolved from the package the object is in.

    Never against the current package: 'sim-mujoco:mujoco' means the
    'sim-mujoco' *that* package imported. Which is what keeps 'pc test -P //...'
    -- run with the root of a tree current while every object in it sits one or
    more packages down -- resolving each declaration the way 'pc sim' in its
    own package would.
    """
    if not declaration.simulation:
        raise SimulationConfigError(
            "the simulation '%s' names no 'simulation:' plugin to run it. PartCAD implements no "
            "simulator itself; import one and name it, e.g. '%s' for MuJoCo" % (declaration.name, KNOWN_SIMULATION)
        )
    return resolve_plugin(ctx, shape.project_name, declaration.simulation)


def _resolve_scene_of(ctx, shape, kind: str, declaration: SimulationDeclaration):
    """The scene a declaration places the object in, with the object in it, unbuilt."""
    object_name = "%s:%s" % (shape.project_name, shape.name)
    scene_package, scene_name = resolve_resource_path(shape.project_name, declaration.scene)
    params = scene_parameters(ctx, scene_package, scene_name, declaration, object_name, kind)
    scene = ctx.get_scene("%s:%s" % (scene_package, scene_name), params)
    if scene is None:
        raise SimulationConfigError("The simulation scene could not be built: %s:%s" % (scene_package, scene_name))
    return scene


async def question_key_async(ctx, shape, kind: str, declaration: SimulationDeclaration) -> typing.Optional[str]:
    """The key one run's answer is cached under, or None when it has none.

    What 'run_async' asks the artifact cache with, worked out the same way and
    without building or running anything: the scene's key (which covers the
    subject), the plugin and its resolved options, its environment, the
    declaration's 'params', how the scene is exported for it, the pictures it
    is asked to take, and the content of both scripts and of the wrappers. So it
    is the whole of what a run's 'before' and 'after' depend on -- and
    deliberately not the 'validation:', which is judged over them afterwards.
    The pictures are not something a verdict depends on, but they are part of
    what the run is asked, and this key is that question's (a test holds the
    two to be equal): a scene looked at from somewhere else is judged again
    rather than vouched for by a run that drew it from where it used to be.

    For a caller that remembers something *derived* from a run, and has to be
    told when the run it was derived from would be a different one: 'pc test'
    keys its 'sim' verdict on it (see 'SimTest.cache_key_suffix'). None for a
    declaration that does not resolve, and for a subject with no key
    ('cache: false') -- a run that has no key is one nothing may be remembered
    about.
    """
    object_name = "%s:%s" % (shape.project_name, shape.name)
    try:
        impl = _resolve_plugin_of(ctx, shape, declaration)
        scene = _resolve_scene_of(ctx, shape, kind, declaration)
        # The scene's world is part of what 'run_async' keys a run on, so it is
        # part of this key too; a world that cannot be made sense of is a run
        # that will fail, and nothing is remembered about one.
        await scene.prepare_async()
        world = scene.world_facts(ctx)
        snapshot = snapshot_request(ctx, scene)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s: the simulation '%s' has no key: %s" % (object_name, declaration.name, e))
        return None
    artifact = await _artifact_hash(ctx, scene, impl, declaration, object_name, kind, world, snapshot)
    return artifact.get() if artifact is not None else None


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


async def _artifact_hash(ctx, scene, impl, declaration, subject: str, kind: str, world=None, snapshot=None):
    """The cache key of one simulation's answer, or None when it has none.

    The scene's own key - which covers the subject, since the subject is a
    parameter of the scene and the scene is keyed on what it links to - and
    everything the run adds to it: the plugin, its resolved options and its
    sandbox, what the declaration hands it, how the scene is written for it,
    and the content of both scripts and of the wrappers that run them -- and of
    every module those can import from their packages ('source_key'), since a
    plugin release that changes only 'mujoco_common.py' changes the answer --
    and the version each of those scripts reports ('code_version').

    And the scene's world as the facts it resolved to ('world'), not as the
    declaration that names them. The scene's key covers its 'medium:' only as
    the reference it is written as; the density behind that reference lives in
    another package, which can be corrected without this one changing at all.
    A run in water whose density was fixed is a different run.

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
            # Without the budget: it bounds the run and does not change its
            # answer, so giving a run longer is no reason to run it again.
            "options": without_budget(impl.config),
            "params": without_budget(declaration.params),
            "subject": subject,
            "subject_kind": kind,
            # Declared, never observed: see 'Implementation.environment_cache_key'.
            "environment": impl.environment_cache_key(),
            "format": format_name,
            "export": export_impl.config,
            "export_environment": export_impl.environment_cache_key(),
            # What the two scripts import from their packages, and the
            # revision a fetched one is at -- not only the scripts themselves,
            # which 'files' already holds. See 'partcad.source_key'.
            "source": impl.source_cache_key(),
            "export_source": export_impl.source_cache_key(),
            "wrappers": source_key.wrappers_key(),
            # The pictures asked for: where from, how big, and into which files.
            "snapshot": snapshot,
        }
        if world:
            # Only when there is one, so that a scene that states neither keeps
            # the key - and the cached answer - it had before scenes could.
            question["world"] = world
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


def run_budget(ctx, impl, declaration) -> typing.Tuple[float, str]:
    """How long one run may take, in wall-clock seconds, and what said so.

    The first of these that states a positive number of seconds:

    1. ``simulation.timeout`` in the user configuration (``PC_SIMULATION_TIMEOUT``).
       It is about this machine rather than about the run, and it is the one
       knob for somebody who cannot edit the package -- a slow runner, or a CI
       job that would rather fail fast -- so it is over everything else.
    2. ``params: {timeout: ...}`` of the ``simulate:`` declaration: this run is
       known to be slow, or known to be quick.
    3. ``timeout:`` in the plugin's own declaration: this engine is.
    4. The default, which grows with the run: the larger of ``DEFAULT_TIMEOUT``
       and ``TIMEOUT_PER_SIMULATED_SECOND`` for every second of the
       ``duration`` the run is handed.

    Anything else -- nought, a negative number, text -- states nothing and is
    passed over, so the bound can be moved and never switched off: a run with
    no bound is a run that can hang forever, and that is what this is for.

    The budget is the run's, from the moment the sandbox interpreter starts.
    Not the sandbox's provisioning before that -- building an environment and
    installing an engine into it is shared with every other run and takes
    minutes on a cold machine, which is why 'PythonRuntime.run_async_onced'
    bounds the interpreter alone -- and not the export of the scene, which is
    a build like any other.

    The second value is the sentence a timeout carries, so that whoever reads
    it is told what to change.
    """
    configured = timeouts.seconds(getattr(getattr(ctx, "user_config", None), "simulation_timeout", None))
    if configured is not None:
        return configured, "'simulation.timeout' (PC_SIMULATION_TIMEOUT) in this machine's configuration"
    declared = timeouts.seconds((declaration.params or {}).get(TIMEOUT_KEY))
    if declared is not None:
        return declared, "the 'timeout' in the 'params:' of the simulation"
    parameters = dict(impl.parameters or {})
    plugin_declared = timeouts.seconds(parameters.get(TIMEOUT_KEY))
    if plugin_declared is not None:
        return plugin_declared, "the 'timeout' the plugin declares"
    parameters.update(declaration.params or {})
    duration = timeouts.seconds(parameters.get("duration")) or 0.0
    budget = max(DEFAULT_TIMEOUT, TIMEOUT_PER_SIMULATED_SECOND * duration)
    return budget, "the default: the larger of %g s and %g s for each of the %g s simulated" % (
        DEFAULT_TIMEOUT,
        TIMEOUT_PER_SIMULATED_SECOND,
        duration,
    )


def without_budget(mapping) -> dict:
    """'mapping' without the run's budget in it, for a cache key.

    A budget bounds a run and does not change its answer, so it is in no key:
    neither the run's ('_artifact_hash') nor the verdict's
    ('SimTest.cache_key_suffix'). Raising one after a run timed out runs it
    again anyway -- a timeout is never stored -- and raising one after it
    answered has nothing to run again for.
    """
    return {key: value for key, value in (mapping or {}).items() if key != TIMEOUT_KEY}


# What to say about raising the budget, beside every timeout.
RAISE_THE_BUDGET = (
    "If the run is simply slow, give it longer: 'params: {timeout: <seconds>}' on the simulation, or "
    "'simulation.timeout' / PC_SIMULATION_TIMEOUT for every run on this machine"
)


def timeout_report(plugin: str, budget: float, source: str, killed: bool = False) -> str:
    """The sentence a run that used up its budget fails with."""
    if killed:
        how = (
            "did not stop when its budget was spent, so PartCAD killed it, with everything it started, %g s later"
            % TIMEOUT_GRACE
        )
    else:
        how = "was stopped, with everything it started"
    return "timed out after %g s: %s did not finish within its budget of %g s (%s) and %s. %s" % (
        budget,
        plugin,
        budget,
        source,
        how,
        RAISE_THE_BUDGET,
    )


def stderr_tail(errors) -> str:
    """The end of what a plugin wrote to standard error, which is where it says why it stopped."""
    text = (errors or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    tail = "\n".join(lines[-STDERR_TAIL_LINES:])
    if len(tail) > STDERR_TAIL_CHARACTERS:
        tail = tail[-STDERR_TAIL_CHARACTERS:]
    if tail != text:
        tail = "...\n" + tail
    return tail


def crash_report(plugin: str, what: str, errors) -> str:
    """The sentence a plugin that ended without an answer fails with, and the end of its stderr."""
    tail = stderr_tail(errors)
    if not tail:
        return "%s %s, and wrote nothing to standard error" % (plugin, what)
    return "%s %s. The end of what it wrote to standard error:\n%s" % (plugin, what, tail)


def read_answer(response_serialized: str):
    """What a plugin answered, as a dict; None for no answer at all.

    Raises ValueError, with the beginning of what came back, for an answer that
    is not one -- text that is not JSON, or JSON that is not an object.
    """
    if not (response_serialized or "").strip():
        return None
    try:
        answer = shape_envelope.deserialize(response_serialized)
    except Exception as e:  # pylint: disable=broad-except
        raise ValueError("%s, beginning %r" % (e, response_serialized.strip()[:200]))
    if not isinstance(answer, dict):
        raise ValueError(
            "a %s rather than an object, beginning %r" % (type(answer).__name__, response_serialized.strip()[:200])
        )
    return answer


async def _run_plugin_async(
    ctx, impl, directory: str, scene_file: str, declaration, subject: str, kind: str, snapshot=None
) -> dict:
    """Start the plugin in its sandbox and return the JSON it produced.

    Never waits longer than the run's budget (see 'run_budget') and a grace
    period beside it, and never returns anything but an answer: a run that did
    not finish raises 'SimulationTimeout', a plugin that ended without an answer
    'SimulationCrash'.
    """
    script = await output.materialize_script(ctx, impl)
    plugin_name = "%s:%s" % (impl.project.name, impl.format_name) if impl.project is not None else impl.format_name
    budget, budget_source = run_budget(ctx, impl, declaration)

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
            # The run's budget as it was resolved, whatever stated it: the
            # wrapper holds the run to it, and a plugin can see how long it has.
            TIMEOUT_KEY: budget,
        }
    )
    if snapshot:
        # The pictures to take, and from where; see 'snapshot_request'.
        request["snapshot"] = snapshot

    # The image the plugin names, as for an export or a render implementation
    # (see 'Shape._run_implementation_locked'): a simulator that is not a wheel
    # - Gazebo - can only arrive in a sandbox built from an image that carries
    # it.
    runtime = ctx.get_python_runtime(version=impl.python_version(), image=impl.docker_image)
    # In a layer over the sandbox's own environment, as an output
    # implementation's are (see 'Shape._run_implementation_locked').
    session = runtime.get_session("%s:%s" % (impl.section, impl.format_name))
    await runtime.prepare_for_package(impl.project, session=session)
    # One at a time rather than with asyncio.gather(), for the reason
    # 'Shape._run_implementation_locked' installs them that way: the order a
    # package declares its requirements in is part of what it declared.
    for dep in impl.python_requirements:
        await runtime.ensure_async(dep, session=session)

    command = [
        wrapper.get("simulate.py"),
        # The wrapper's first positional argument is the directory a plugin may
        # write artifacts into; the second is where it runs, as for every other
        # wrapper.
        os.path.abspath(directory),
        os.path.abspath(impl.project.config_dir),
        # The script, on the command line rather than in the request: an
        # argument is rewritten to wherever a sandbox that sends files put it,
        # and the request is not (see 'wrapper_simulate.SCRIPT_ARGUMENT').
        os.path.abspath(script),
    ]
    # A sandbox that sends files rather than sharing a directory has to be told
    # what comes back: the pictures are written into the run directory, so the
    # run directory does. The scene goes the other way without being named,
    # because the directory is an argument (see 'input_dirs_for').
    extra = {"output_dirs": [os.path.abspath(directory)]} if getattr(runtime, "EXCHANGES_FILES", False) else {}
    try:
        exitcode, response_serialized, errors = await runtime.run_async(
            command,
            shape_envelope.serialize(request),
            session=session,
            # Longer than the budget: the wrapper stops the run when the budget
            # is spent and says so, which is the better report, and this is for
            # the run it could not stop. 'communicate' kills the process tree.
            timeout=budget + TIMEOUT_GRACE,
            **extra,
        )
    except (asyncio.TimeoutError, TimeoutError):
        raise SimulationTimeout(timeout_report(plugin_name, budget, budget_source, killed=True), budget, plugin_name)

    try:
        result = read_answer(response_serialized)
    except ValueError as e:
        # Read before the exit status: an answer that is not one is the more
        # specific thing to say, and the status of a run that wrote one is
        # usually the wrapper failing over it.
        if exitcode == 0:
            raise SimulationCrash(
                crash_report(plugin_name, "answered with something that is not a result (%s)" % e, errors)
            )
        result = None
    if result is not None and result.get(TIMED_OUT_KEY):
        # The wrapper's own answer for a run whose budget it saw spent; it
        # stopped everything the plugin had started, inside the sandbox.
        raise SimulationTimeout(timeout_report(plugin_name, budget, budget_source), budget, plugin_name)
    # Only on a non-zero exit. 'RuntimePython' clears stderr for a run it
    # considers successful, but it decides that on the raw 'returncode' -
    # *before* normalizing the two Windows fault codes it deliberately forgives
    # (see 'run_async_onced_locked'). So a forgiven crash arrives here as
    # exitcode 0 with stderr still set, and raising on stderr alone would fail a
    # run the runtime just decided to let through. A wrapper that really failed
    # says so in its result, which the 'success' check below reads.
    if exitcode != 0:
        raise SimulationCrash(
            crash_report(plugin_name, "ended without an answer: %s" % describe_exit_code(exitcode), errors),
            exitcode,
        )
    if result is None:
        raise SimulationCrash(crash_report(plugin_name, "exited cleanly and produced no result", errors), exitcode)
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
