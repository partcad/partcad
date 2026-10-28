#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import copy
import json
import os
import sys
import tempfile
import threading
import warnings
from typing import TYPE_CHECKING, Optional

from partcad_utils import timeouts

from . import cache_artifacts
from . import cae as pc_cae
from . import cam as pc_cam
from . import code_version
from . import logging as pc_logging
from . import material as pc_material
from . import output
from . import physics as pc_physics
from . import render_overlay
from . import runtime as pc_runtime
from . import sandbox_versions, scene_world, shape_ports, shape_section, source_key, sync_threads, wrapper
from .cache_hash import CacheHash
from .cache_shape import properties_key
from .shape_config import ShapeConfiguration
from .utils import resolve_resource_path, total_size

if TYPE_CHECKING:
    from partcad.context import Context
    from partcad.project import Project

# The core carries shapes as opaque BREP envelopes (see shape_envelope), never
# as live OCP objects. 'wrappers' stays on sys.path so the few code paths that
# legitimately need a live shape - the single normalization choke point in
# get_wrapped(), and convert()/show() which hand a live object to a CAD library
# - can import the OCP codec lazily.
sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from . import shape_envelope, telemetry
from .process_crash import command_failure

PART_EXTENSION_MAPPING = {
    "step": "step",
    "brep": "brep",
    "stl": "stl",
    "3mf": "3mf",
    "threejs": "json",
    "obj": "obj",
    "iges": "iges",
    "gltf": "json",
    "urdf": "urdf",
    "cadquery": "py",
    "build123d": "py",
    "chili3d": "chili",
    "sdf": "py",
    "scad": "scad",
}

SKETCH_EXTENSION_MAPPING = {
    "svg": "svg",
    "dxf": "dxf",
    "cadquery": "py",
    "build123d": "py",
}

# The scene types that are file formats, and the extension each is stored in.
# The counterpart of the two mappings above for the third kind of object a file
# can hold: an arrangement rather than a shape or a drawing. It exists for the
# same reason they do -- to tell from a file name what a conversion should read
# it as.
#
# One entry, and it is the only one there can be: a scene format that belongs to
# a simulation engine is declared by that engine's plugin package (`mjcf` by
# `partcad/partcad-sim-mujoco`, `world` by `partcad/partcad-sim-gazebo`), and
# this table is consulted where there is no package graph to resolve such a name
# in. So it holds what PartCAD itself knows and nothing else -- a plugin format
# is reached by asking the graph, not by looking it up here.
#
# 'assy' is in it and is not convertible ad-hoc (see
# 'partcad.adhoc.adhoc.PACKAGE_ONLY_TYPES'): naming it is what lets the refusal
# say what the file is instead of reporting an unknown extension.
SCENE_EXTENSION_MAPPING = {
    "assy": "assy",
}

# The 2D projections '//builtin/render' implements, and the file extension each
# one writes. Deliberately kept apart from the two mappings above: those also
# enumerate the part types 'Shape.convert()' accepts, and a projection is not one
# of them (it cannot be read back in as a part or a sketch).
#
# Only 'jpeg' has an extension that differs from its name, which is what this is
# consulted first for. The other three are listed anyway so that this is the set
# of built-in projections and not a list of exceptions - 'pc adhoc render' reads
# it in reverse, to tell from an output file name which projection was asked for.
# A file type a package implements itself is not here, and is not inferable: it
# is declared in that package, and an ad-hoc render has no package.
RENDER_EXTENSION_MAPPING = {
    "svg": "svg",
    "png": "png",
    "jpeg": "jpg",
    "dxf": "dxf",
}

# The part types 'Shape.convert()' can hand back as a live in-memory CAD object
# instead of a serialized representation.
LIVE_OBJECT_PART_TYPES = frozenset({"build123d", "cadquery"})

# Part types that are named in the extension mappings above but that no exporter
# in this repository can produce. OpenSCAD is an input format for PartCAD
# (see part_factory_scad.py); nothing writes it back out.
UNEXPORTABLE_PART_TYPES = {
    "scad": "PartCAD can read OpenSCAD but cannot write it",
    "sdf": "PartCAD can read SDF scripts but cannot write them",
    "chili3d": "PartCAD can read Chili3D scripts but cannot write them",
    # URDF is exportable, but not *in memory*: the export is a .urdf file plus
    # the directory of mesh files it references, and convert() hands back a
    # single payload. Returning only the XML would quietly lose the geometry.
    "urdf": (
        "a URDF export is a .urdf file plus the mesh files it references, so it cannot be "
        "returned in memory; export it to a path instead ('pc export -t urdf')"
    ),
}

# Every part type named by the extension mappings that 'Shape.convert()' can
# serialize. Derived from the mappings rather than hand-listed, so a new format
# added to a mapping (and declared by '//builtin/export' or '//builtin/render')
# is picked up here automatically.
SERIALIZED_PART_TYPES = (
    frozenset(set(PART_EXTENSION_MAPPING) | set(SKETCH_EXTENSION_MAPPING))
    - LIVE_OBJECT_PART_TYPES
    - set(UNEXPORTABLE_PART_TYPES)
)

# Serialized part types whose output is text no matter which options are passed.
# 'stl' and 'gltf' are deliberately absent: both switch between a text and a
# binary encoding depending on the options, so both always return bytes.
TEXT_PART_TYPES = frozenset({"step", "iges", "brep", "obj", "threejs", "svg", "dxf"})

SUPPORTED_PART_TYPES = frozenset(LIVE_OBJECT_PART_TYPES | SERIALIZED_PART_TYPES)


# What a shape's configuration says about the shape to a reader, rather than
# what its geometry is made of. Everything else in the configuration is hashed
# into the cache key.
#
# A deny-list rather than an allow-list, on purpose. An allow-list has to know
# every key that can change a shape, and it cannot: a partType of kind
# 'wrapper' is a package-supplied script that reads configuration keys of its
# own invention. The ':ldraw' partType identifies its part with 'dat', which
# the previous allow-list of 'parameters'/'offset'/'scale' did not name, so
# every LDraw part hashed to the same key and whichever was meshed first was
# handed back for all the others - four different parts exported byte-identical
# geometry, and an assembly of bricks rendered as cones.
#
# The two mistakes are not symmetrical: hashing a key that turns out not to
# matter costs a rebuild, while missing one that does matter serves the wrong
# shape and says nothing. So a key this does not know about is hashed.
_NON_GEOMETRIC_CONFIG_KEYS = frozenset(
    {
        "aliases",
        "author",
        "cache",
        "cache_dependencies_ignore",
        "category",
        # How the thing is packaged for sale, not what it is. The third of the
        # (vendor, SKU, pack size) record, and the only one of the three that
        # was missing here - so the same geometry sold in bags of 25 keyed
        # differently from the same geometry sold singly, and declaring a pack
        # size rebuilt a part for a number nothing reads but a bill of
        # materials. Keying on less cannot serve the wrong shape here: nothing
        # builds anything out of it.
        "count_per_sku",
        "desc",
        "docs",
        "example",
        "images",
        "label",
        "license",
        "manufacturable",
        "manufacturing",
        # A shape's own name is not what it is made of: two parts alike but for
        # their names are one shape and share an entry. What a file-backed part
        # is built from reaches the key as the file's content, not as its name.
        "name",
        "orig_name",
        # Outputs, not inputs. A part that gains a material has not become a
        # different shape (see test_shape_properties.py).
        "properties",
        # What the object is supposed to do once it is placed in a world, not
        # what it is. A simulation's own answer is cached under a key of its
        # own that covers what decides it -- the scene, the plugin, its
        # options, its 'params' -- and deliberately not the 'validation:', so
        # that editing the claim re-judges the run rather than repeating it
        # (see 'simulation.run_async'). Hashed here, every such edit rebuilt the
        # object, moved the key of the scene it is placed in and ran the
        # simulator again: the opposite of what that leaves out, and the one
        # edit somebody writing the claim first makes over and over.
        "simulate",
        "sku",
        "summary",
        "supplier",
        "tags",
        # How long building it may take, not what gets built: declaring one, or
        # changing it, must not cost an assembly its cache entry -- least of all
        # the slow ones, which are the only ones that declare it.
        "timeout",
        "title",
        "url",
        "vendor",
    }
)


def sandbox_note(ctx, impl) -> str:
    """Why ``impl`` did not run in the image it named, as a line to append; or nothing.

    An implementation names an image for what pip cannot install, so one run
    anywhere else has very likely failed *because* of that -- and its own
    message cannot say so, since it does not know where it was run. Not for one
    declaring a 'container:', which runs there or not at all.

    A function rather than a method: `Shape` is wrapped by the telemetry
    decorator, which does not keep a `staticmethod` one.
    """
    if getattr(impl, "container", None):
        return ""
    note_for = getattr(ctx, "docker_image_note", None)
    note = note_for(getattr(impl, "docker_image", None)) if note_for else None
    return "\n" + note if note else ""


def _held_by_current_task(shape) -> bool:
    """Whether the task this is called from holds 'shape.locked()' already.

    A function rather than a method, for the reason 'sandbox_note' is one: the
    telemetry decorator would make a span of every call, and this is asked on
    the way into every lock. 'current_task()' is None outside a task; two such
    callers on one loop cannot interleave at an await point anyway, so None is
    never treated as re-entry.
    """
    owners = getattr(shape.tls, "async_shape_lock_owners", None)
    task = asyncio.current_task()
    return task is not None and bool(owners) and owners.get(id(shape)) is task


def _file_identity(path: str):
    """Which file is at 'path' and as of when, to tell afterwards whether a run replaced it; or None.

    The inode as well as the size and the modification time, because an
    implementation that writes a new file and renames it over the old one
    changes the first even when the clock is too coarse to change the last.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _render_action(project_name: str, format_name) -> str:
    """The name of the action that writes one file type, or every one of them.

    The bare file type: a package path in it would make one operation look like
    several, one per package that asked.
    """
    return f"Render{output.split_format(project_name, format_name)[0].upper()}" if format_name else "Render"


class _Output:
    """One file an implementation is to write: who writes it, from what, where, and what is known of it on the way.

    'artifact' is its cache key ('Shape._artifact_hash'), and 'before' which file
    was at 'path' before it was written ('_file_identity').
    """

    __slots__ = ("impl", "script", "request", "path", "artifact", "before")

    def __init__(self, impl, script, request, path, artifact=None):
        self.impl = impl
        self.script = script
        self.request = request
        self.path = path
        self.artifact = artifact
        self.before = None


def _sandbox_of(impl):
    """Which sandbox interpreter an implementation runs in, as far as running several in one goes; or None.

    The interpreter and the image it is built from - what 'ctx.get_python_runtime'
    is asked for - and whose implementation it is. PartCAD's own built-in
    implementations are written to run one after another in one process, each
    setting what it reads of OCCT's process-wide parameters and naming no helper
    module another one names; two packages' implementations are not known to be,
    so each package's run with its own and nobody else's. A container is a
    process of the implementation's own, and so is one whose environment cannot
    be told: None, which runs alone.
    """
    try:
        if impl.container:
            return None
        name = getattr(impl.project, "name", None) or ""
        builtin = name == output.BUILTIN_ROOT_PACKAGE or name.startswith(output.BUILTIN_ROOT_PACKAGE + "/")
        return (impl.python_version(), impl.docker_image, output.BUILTIN_ROOT_PACKAGE if builtin else name)
    except Exception:  # pylint: disable=broad-except
        return None


def _rounds(outputs) -> list:
    """The indices of 'outputs', in rounds none of which writes one path twice.

    Each in the first round after the last one that writes its path, so files
    asked for at one path are written in the order asked for and the last of
    them is the one left there, as when each was written on its own.
    """
    rounds = []
    last = {}
    for index, output_ in enumerate(outputs):
        path = os.path.normcase(os.path.abspath(output_.path))
        position = last.get(path, -1) + 1
        if position == len(rounds):
            rounds.append([])
        rounds[position].append(index)
        last[path] = position
    return rounds


def _together_request(outputs) -> dict:
    """What 'wrapper_export.py' is handed to write several files: every request, and each object once.

    The object a request is of is taken out of it and put in a list of its own,
    once however many requests are of it, and the request names it by its place
    there (see 'output.BATCH_OUTPUTS_KEY'). What makes two requests of one object
    is that they hold the one tree: every file type of a shape is handed the tree
    'get_wrapped' answered, and a filtered view the tree of the view.
    """
    subjects = []
    named = {}
    entries = []
    for output_ in outputs:
        request = dict(output_.request)
        entry = {output.BATCH_REQUEST_KEY: request}
        # The key '_output_request' puts the object under, and the wrapper reads
        # it from ('wrapper_export.WRAPPED_KEY').
        wrapped = request.pop("wrapped", None)
        if wrapped is not None:
            subject = named.get(id(wrapped))
            if subject is None:
                subject = named[id(wrapped)] = len(subjects)
                subjects.append(wrapped)
            entry[output.BATCH_SUBJECT_KEY] = subject
        entries.append(entry)
    return {output.BATCH_OUTPUTS_KEY: entries, output.BATCH_SUBJECTS_KEY: subjects}


def _together_answers(stdout, count: int) -> dict:
    """What a call writing 'count' files said of each of them, by its place in the call.

    One line per file it finished (see 'output.BATCH_OUTPUT_KEY'). A line that
    is not one of those is not an answer; a file with none was not answered.
    """
    answers = {}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            answer = shape_envelope.loads(line)
        except Exception:  # pylint: disable=broad-except
            pc_logging.debug("Not an answer from the export wrapper: %s" % line[:200])
            continue
        if not isinstance(answer, dict):
            continue
        index = answer.get(output.BATCH_OUTPUT_KEY)
        result = answer.get(output.BATCH_RESULT_KEY)
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < count and isinstance(result, dict):
            answers[index] = result
    return answers


class _OutputBatch:
    """The file types of one shape that 'Shape.render_async' was asked for together, written together.

    Each is worked out in a task of its own, exactly as when it is asked for on
    its own - which implementation, which script, which path, what it is handed
    and its cache key - and is then handed in here ('submit') instead of being
    run. Once every one of them has been handed in, or has given up on the way
    (an empty shape, a filter that is not one), the cache is asked for each and
    what it does not hold is written in as few sandbox calls as their
    environments allow ('Shape._outputs_run_async'). Each task then reports its
    own file from its own answer, the way it always has.

    The tasks are worked out one at a time, in the order they get here
    ('member'): they share what one render call works out once and fills in as
    it is asked - where the ports are, the filtered views - and two at once
    would each work it out.

    Never made by a task that holds the shape's lock already: the tasks of the
    batch are other tasks, and would wait for that lock for good.
    """

    def __init__(self, shape, ctx, size):
        self.shape = shape
        self.ctx = ctx
        self.undecided = size
        self.cache = None
        self.turn = asyncio.Lock()
        self.current = None
        self.waiting = []

    @contextlib.asynccontextmanager
    async def member(self):
        """One file type's part in the batch, from working it out to handing it in or giving up."""
        await self.turn.acquire()
        mine = {"decided": False}
        self.current = mine
        try:
            yield
        finally:
            if not mine["decided"]:
                await self._decide(mine)

    async def submit(self, cache, output_):
        """Hand in the file the member working now is to write, and wait for what writing it said."""
        self.cache = cache
        future = asyncio.get_running_loop().create_future()
        self.waiting.append((output_, future))
        await self._decide(self.current)
        return await future

    async def _decide(self, mine):
        mine["decided"] = True
        self.current = None
        self.turn.release()
        self.undecided -= 1
        if self.undecided == 0:
            await self._run()

    async def _run(self):
        """Write what was handed in, and answer every member that handed something in.

        Only what a member is still waiting for: one that stopped - its render
        was cancelled while the last of the batch was being worked out - has
        nobody to write its file for, and the cancellation is not to wait for it.
        """
        waiting, self.waiting = [entry for entry in self.waiting if not entry[1].done()], []
        if not waiting:
            return
        try:
            outcomes = await self.shape._outputs_run_async(self.ctx, [output_ for output_, _ in waiting], self.cache)
        except asyncio.CancelledError:
            for _, future in waiting:
                future.cancel()
            raise
        except Exception as e:  # pylint: disable=broad-except
            outcomes = [e] * len(waiting)
        for (_, future), outcome in zip(waiting, outcomes):
            if future.done():
                continue
            if isinstance(outcome, BaseException):
                future.set_exception(outcome)
            else:
                future.set_result(outcome)


def _in_order(results: dict, formats) -> dict:
    """'results' in the order 'formats' asked for them: file types written together finish in any order."""
    return {format_name: results[format_name] for format_name in formats if format_name in results}


async def _together(batch, each, formats) -> None:
    """'each(format)' for every file type of one render call: all at once for a batch, else one after another.

    A batch's file types are written by whichever of them is handed in last, so
    none of them is left running when this returns: a failure is raised once
    every one has finished - the first in the order asked for - and not as it
    happens, which left the rest writing files, or not, for a caller that had
    already been told the render failed.
    """
    if batch is None:
        for format_name in formats:
            await each(format_name)
        return
    outcomes = await asyncio.gather(*(each(format_name) for format_name in formats), return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            raise outcome


# The part types whose geometry is the file they are read from, and is handed
# over as the file holds it: a closed shell in one is reported, not converted.
FILE_AUTHORITY_TYPES = frozenset({"step", "brep"})

# How often 'Shape.prepare_async(wait=True)' looks again at a preparation that
# somebody else has begun and not finished, in seconds: from the first value,
# doubling to the second. Polled rather than awaited for the reason
# 'sandbox_lock' polls - a shape is prepared from several event loops at once,
# and there is no one loop to put a future on.
_PREPARE_POLL_MIN = 0.002
_PREPARE_POLL_MAX = 0.1

# The longest 'Shape.prepare_async(wait=True)' waits for a preparation begun
# elsewhere before it goes on without the shape's key, in seconds. A backstop,
# not the rule: the waits that can never end - a cycle of preparations, a lock
# the preparer may need - are refused before any waiting (see
# '_refusal_to_wait'). What is left is what nothing here can see, a preparer
# stopped by something it waits for on another thread; giving up on it costs
# one uncached build, where waiting on would cost the run.
_PREPARE_WAIT_MAX = 60.0


class PreparationInFlight(Exception):
    """A shape's preparation, begun elsewhere and not over, that its caller may not wait for.

    Raised by 'Shape.prepare_async(wait=True)' instead of returning, because
    the caller asked to wait in order to read the key, and the key is not the
    shape's key until the preparation is over.
    """


class _Preparation:
    """One chain of preparations: a 'prepare_async()' and every one it leads to, in one task."""

    __slots__ = ()


# Which preparation the running code is part of, if any: set while a shape's
# preparation hook runs, so that every shape it prepares on the way is known to
# be prepared on its behalf. A context variable, so that it follows the task
# and the tasks it starts, and nothing else.
_preparation: contextvars.ContextVar = contextvars.ContextVar("partcad.shape.preparation", default=None)

# What each preparation that is waiting is waiting for: '_Preparation' -> the
# shape. Read to tell a wait that would close a cycle from one that ends. Under
# '_preparations', with every shape's '_preparer', because those are written
# from several threads at once.
_preparations = threading.Lock()
_waiting_for: dict = {}

# How many shapes' thread locks this thread holds (see '_ShapeLock').
_held = threading.local()


class _ShapeLock(sync_threads.PoolAwareRLock):
    """A shape's thread lock: re-entrant, and counted per thread while held.

    Waited for without blocking an event loop, and by a slot of the thread
    pools without keeping the slot from work that the lock's holder may be
    waiting for: see 'sync_threads.PoolAwareRLock'.

    The count is how 'prepare_async(wait=True)' knows this thread holds some
    shape's lock. Such a lock keeps any other thread that asks for the same
    shape waiting until it is released, so a thread holding one must not wait
    for a preparation running on another thread: that thread may be the one
    waiting for the lock.
    """

    def _try(self, timeout=None) -> bool:
        acquired = super()._try(timeout)
        if acquired:
            _held.count = getattr(_held, "count", 0) + 1
        return acquired

    def release(self):
        super().release()
        _held.count -= 1


def _waits_for(preparation, chain) -> bool:
    """Whether 'preparation' is waiting, directly or through others, for 'chain'. Under '_preparations'."""
    seen = set()
    while preparation is not None and id(preparation) not in seen:
        if preparation is chain:
            return True
        seen.add(id(preparation))
        shape = _waiting_for.get(preparation)
        owner = shape._preparer if shape is not None else None
        preparation = owner[0] if owner is not None else None
    return False


@telemetry.instrument(exclude=["locked"])
class Shape(ShapeConfiguration):
    name: str
    desc: str
    kind: str
    requirements: dict | list | str
    svg_path: str
    svg_url: str
    # shape: None | OCP.TopoDS.TopoDS_Solid

    errors: list[str]

    # Made by PartCAD for somebody to look at, rather than declared by the
    # package it is registered in: what a check leaves behind (see
    # 'test/interference_artifact.py'). It is found by name like any other
    # object, and left out of what lists the package's declarations.
    artifact = False

    # Whether 'get_shape()' builds this shape on the constrained thread pool:
    # a part, a sketch. What 'get_wrapped()' does about it is said there. An
    # assembly is not: it builds itself on the loop that asks, so that its
    # children are spread over the pool rather than built one after another on
    # the one thread it would have been given.
    built_on_pool = False

    # What a shape built here rather than read from a declaration is a view of,
    # and what about it: the picture of a step of an assembly instruction book
    # (see 'assembly_guide'), a filtered view (see 'assembly_filter.derive').
    # Neither has a cache key of its own - no declaration states it - but what
    # it draws is that object's and this, so that is what its artifacts are
    # keyed on (see 'get_artifact_key_async'). Class-level, so a shape made
    # without the constructor has them too.
    derived_from: Optional["Shape"] = None
    artifact_identity: Optional[str] = None

    def __init__(self, project_name: str, config: dict) -> None:
        super().__init__(config)
        self.project_name = project_name
        self.errors = []
        # Re-entrant for the thread holding it, safe to wait for from an event
        # loop and from a slot of the thread pools, and counted per thread
        # while held: see '_ShapeLock'.
        self.lock = _ShapeLock()
        self.tls = threading.local()
        self.components = []
        self.compound = None
        self.with_ports = None

        # Leave the svg path empty to get it created on demand
        self.svg_lock = asyncio.Lock()
        self.svg_path = None
        self.svg_url = None

        self.desc = config.get("desc", None)
        self.desc = self.desc.strip() if self.desc is not None else None
        self.requirements = config.get("requirements", None)
        finalized_default = config.get("type", None) != "kicad"
        self.finalized = config.get("finalized", finalized_default)

        # Cache behavior
        self.cacheable = config.get("cache", True)
        # Optional: what the environment this shape is produced in consists
        # of, for the shapes that are produced in one at all (see
        # set_environment_cache_key). None for a shape that is composed rather
        # than rendered, such as an assembly.
        self.environment_cache_key = None
        self.cache_dependencies = []
        self.cache_dependencies_broken = False
        self.cache_dependencies_ignore = self.config.get("cache_dependencies_ignore", True)

        # Memory cache
        self._wrapped = None
        self._bounding_box = None
        # What 'get_solidity_async()' found, kept for the same reason as the box.
        self._solidity = None
        # Everything recorded about this shape's geometry when it was built -
        # its measurements, and whatever its source stated (see
        # 'shape_envelope.KEY_METADATA'). Learnt while building or read back
        # with the geometry, and kept here for the runs that have nowhere to
        # cache it. See 'get_metadata_async()'.
        self._metadata = None

        # Set by the factory (see ShapeFactory.prepare_async): everything that has
        # to happen before this shape's cache key means anything - 'fileFrom'
        # downloads and cross-package references - without building the shape.
        # '_prepared' is raised as the preparation begins, '_prepare_finished'
        # once it is over, and '_preparer' says who is doing it meanwhile: the
        # '_Preparation' and the thread (see 'prepare_async').
        self._prepare = None
        self._prepared = False
        self._prepare_finished = False
        self._preparer = None

        # Filesystem cache
        self.hash = CacheHash(f"{self.project_name}:{self.name}", cache=self.cacheable)
        self.hash.set_dependencies(self.cache_dependencies)

        # Whether this shape's cache entry is this shape's to write. False for
        # a reference that took its key from the object it points at without
        # changing anything about it (see 'take_cache_key_from'): the two share
        # one entry, and the object that owns it is the one that fills it.
        self.owns_cache_entry = True

        if self.cacheable:
            cad_config = {key: value for key, value in self.config.items() if key not in _NON_GEOMETRIC_CONFIG_KEYS}
            self.hash.add_dict(cad_config)

    def set_environment_cache_key(self, environment_cache_key: str) -> None:
        """Record the environment this shape is produced in, and cache by it.

        A shape produced by a sandbox comes from an interpreter of some version
        with dependencies of some versions, and the result belongs to that
        combination: move the package to another interpreter or another CAD
        library and the shape has to be built again rather than read back from
        what the previous one produced.

        Every kind of shape can have one. A part written as a script obviously
        does, but so does a sketch, and so does a part read from a CAD file -
        the importer that turns a STEP file into a BREP is itself a script in a
        sandbox. What does not is a shape that is composed rather than rendered,
        such as an assembly, whose pieces each carry their own.

        None of it is visible to the hash otherwise. Only 'parameters', 'offset'
        and 'scale' are taken from the configuration above, and the environment
        is not spelled out in a shape's configuration anyway - it is resolved
        from the package's settings, the shape's, and the versions PartCAD
        itself supplies.

        Set through ShapeFactory.apply_environment_cache_key() as a shape is
        created, from 'sandbox_versions.environment_cache_key()'. Must happen
        before the hash is used, which creation time guarantees.
        """
        self.environment_cache_key = environment_cache_key
        self.hash.add_string(environment_cache_key)

    def add_code_versions(self, versions: str) -> None:
        """Key this shape on the versions the code producing it reports.

        'versions' is what 'code_version.key()' made of them - the wrappers that
        build it, the plugin that serves it, a partType's script. Raising any of
        those versions is how that code's author has every shape it made built
        again; see 'code_version' and 'ShapeFactory.code_versions'.

        Called as the shape is created, and again from a factory's
        'prepare_async' for the code it only knows by then. Must happen before
        the hash is used, which both of those guarantee.
        """
        self.hash.add_string("code:" + versions)

    def matches(self, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()

        # Check for a match in its configuration
        if keyword in str(self.config).lower() or keyword in self.name.lower():
            return True

        # Check for a match in other files associated with this shape
        if self.path and os.path.exists(self.path):
            with open(self.path, errors="replace") as f:
                if keyword and keyword.lower() in f.read().lower():
                    return True
        return False

    def get_cache_dependencies_broken(self) -> bool:
        if self.cache_dependencies_ignore:
            return False
        return self.cache_dependencies_broken

    def get_cacheable(self) -> bool:
        return self.cacheable and not self.get_cache_dependencies_broken()

    async def get_summary_async(self, project=None):
        # Return a manually configured summary if present, otherwise None.
        if "summary" in self.config and self.config["summary"] is not None:
            return self.config["summary"]
        return None

    def get_summary(self, project=None):
        return asyncio.run(self.get_summary_async(project))

    def get_async_lock(self) -> asyncio.Lock:
        if not hasattr(self.tls, "async_shape_locks"):
            self.tls.async_shape_locks = {}
        self_id = id(self)
        # Keyed on the loop as well as the shape, the way the runtime keys its
        # own (see runtime_python.PythonRuntime). A worker thread runs one
        # 'asyncio.run()' per instantiation, so a thread that is handed a
        # second one gets a second loop, and an asyncio.Lock that was awaited
        # under the first refuses to be awaited under the second.
        loop_id = id(asyncio.get_event_loop())
        if self_id not in self.tls.async_shape_locks or self.tls.async_shape_locks[self_id][1] != loop_id:
            self.tls.async_shape_locks[self_id] = (asyncio.Lock(), loop_id)
        return self.tls.async_shape_locks[self_id][0]

    @contextlib.asynccontextmanager
    async def locked(self):
        """Hold this shape still: nobody else instantiates it or writes its files.

        One lock for both, because they are the same question asked twice. A
        shape's files are not private to whoever asked for them: the path an
        output goes to is derived from the shape and the file type, so two
        concurrent runs over the same shape resolve to the *same* path, and
        without this the second one's work lands in the middle of the first
        one's -- deleting a model between the moment its owner wrote it and the
        moment its owner reads it back, or handing one caller the other's file.
        Instantiation has always been serialized this way; producing files was
        the half that was not.

        **Re-entrant**, and it has to be. The operations nest: 'analyze_async'
        holds this across the whole remove-run-verify sequence, and inside that
        calls 'get_wrapped' and '_run_implementation_async', each of which takes
        it in its own right. 'threading.RLock' already allows that; an
        'asyncio.Lock' does not, and a second acquisition from the task that
        already holds it waits for a release that only it can perform. So the
        owning task is remembered and passes straight through.

        The cost is real and worth stating: two *different* outputs of one shape
        no longer run at the same time, even though they write different paths.
        That is the price of one rule with no exceptions, and PartCAD's
        parallelism is across shapes rather than within one.

        **Waited for without blocking anything else.** The thread lock is taken
        with 'async with', which polls rather than blocks the event loop, and a
        slot of the thread pools that waits for it gives the slot back while
        whoever holds it waits for the pools itself (see
        'sync_threads.PoolAwareRLock'). Keeping the slot while waiting was how a
        shape's lock, held by the loop a command runs on while the shape's build
        sat in the pool's queue, stopped a render for good once every slot was
        taken by something waiting for that lock.
        """
        if not hasattr(self.tls, "async_shape_lock_owners"):
            self.tls.async_shape_lock_owners = {}
        owners = self.tls.async_shape_lock_owners
        self_id = id(self)
        task = asyncio.current_task()
        if _held_by_current_task(self):
            yield
            return

        async with self.lock:
            async with self.get_async_lock():
                owners[self_id] = task
                try:
                    # Whatever is done to a shape is done under this lock -
                    # building it, writing its files, analyzing it - so this is
                    # where the time an object declares it may take is
                    # announced. Nothing for a shape that declares none.
                    with pc_logging.Timeout(self.timeout, self.project_name, self.name):
                        yield
                finally:
                    owners.pop(self_id, None)

    @property
    def timeout(self) -> Optional[float]:
        """How many seconds working on this shape may take, as it declares, or None.

        Only an assembly (or a scene) declares one; see 'Assembly.timeout'.
        """
        return None

    async def get_components(self, ctx):
        if len(self.components) == 0:
            # Maybe it's empty, maybe it's not generated yet
            wrapped = await self.get_wrapped(ctx)

            # If it's a compound, we can get the components
            if len(self.components) == 0:
                self.components = [wrapped]

            await shape_ports.prepare_async(self, ctx)
            if self.with_ports is not None:
                ports_list = list(await self.with_ports.get_components(ctx))
                if len(ports_list) != 0:
                    self.components.append(ports_list)

        return self.components

    async def get_representation(self, ctx, form=shape_envelope.FORM_BREP, section=None):
        """This shape as a tree of nodes, with the geometry at each in 'form'.

        The one way to ask a shape for itself as a whole. Every shape is such a
        tree: an assembly is a node per thing it holds, and a part or a sketch is
        a tree of depth one - itself, its geometry, and what it says about
        connections. Nothing about the hierarchy depends on the form; the form
        decides only what sits at a node that has geometry (see
        'shape_envelope.FORM_BREP' / 'FORM_GLTF').

        BREP is the tree the core builds, composes and caches, so that is what
        this is in the ordinary case and it costs a cache lookup. glTF is that
        same tree tessellated, in one sandbox, for a caller that has to draw it
        rather than compute with it - a browser has no CAD kernel. That is
        cached too, a shape at a time (see 'shape_gltf.convert_async'): it is
        what the IDE asks for every time an object is shown, and starting a
        sandbox to answer it is most of the wait.

        The sketches this object's ports are drawn with come with it, on the root
        node, in the same form (see 'port_sketches'). They are not in what the
        shape cache holds, because what a node records about a port is the
        reference and not the geometry - which is why the tessellation is keyed
        on the geometry it is handed rather than on this shape's key.

        'section' is a cross-section to cut the geometry to first, as a box in
        the frame of the tree's root ('shape_section.normalize'), or None for the
        whole shape. Only the nodes are cut: the port sketches are annotations of
        the object, and a port is where it is whether or not the solid around it
        is drawn.
        """
        from . import port_sketches, shape_gltf

        tree = await port_sketches.attach_async(ctx, await self.get_wrapped(ctx))
        return await shape_gltf.in_form_async(ctx, tree, form, cacheable=self.artifacts_cacheable(), section=section)

    def prepare(self):
        return asyncio.run(self.prepare_async())

    async def prepare_async(self, wait: bool = False):
        """Fetch everything the cache key depends on, without building the shape.

        This is what makes 'pc install' behave like 'npm install': the factory
        hook downloads whatever 'fileFrom' points at and resolves every
        cross-package reference, which loads - and so downloads - the packages
        this shape really depends on. A later build then finds it all on disk.

        Idempotent, and safe against reference cycles between assemblies: the
        flag is raised before the hook runs, so a shape that (indirectly) links
        back to itself stops here instead of recursing.

        That same flag is what everybody else sees while the hook is still
        running, and by default they return on it too: the preparation has
        begun, but what it hashes in - the keys of the objects an assembly links
        to, the file a plugin or a 'fileFrom' fetches - may not be in the hash
        yet. A hash adds its files when it is first read, so a key read then is
        not merely early: the shape keeps it, file left out, for as long as the
        process lives.

        'wait' is for every caller about to read the key - 'get_cache_key_async()',
        'get_wrapped()', 'Test.test_cached()' - and it returns only once the
        preparation is over: one begun elsewhere is waited for, and if it
        failed, the shape is prepared here instead. Where waiting could never
        end, it raises 'PreparationInFlight' rather than wait, and the caller
        goes on without the key (see '_refusal_to_wait()' for when). A caller
        that only needs the preparation started - one that resolves what a
        declaration points at - does not pass it, and nothing about it changed.
        """
        chain = _preparation.get()
        delay, waited = _PREPARE_POLL_MIN, 0.0
        # A slot of the thread pools does not keep its slot while it waits for
        # a preparation in the hands of a thread that may itself be waiting for
        # the pools -- the event loop a command runs on, or a slot that has
        # given its own back -- for the reason a shape's lock is waited for that
        # way (see 'sync_threads.waiting'). A preparation can wait for the
        # pools: a connected assembly's works out the ports of what it links
        # to, which can instantiate a sub-assembly under that one's lock.
        slot_wait = sync_threads.waiting(lambda: (self._preparer or (None, None))[1])
        try:
            while True:
                with _preparations:
                    if not self._prepared:
                        # Ours to do: in the chain this was called from, or in a
                        # chain of its own.
                        self._prepared = True
                        self._prepare_finished = False
                        mine = chain if chain is not None else _Preparation()
                        self._preparer = (mine, threading.get_ident())
                        break
                    if self._prepare_finished or not wait:
                        return
                    refusal = self._refusal_to_wait(chain, waited)
                    if refusal is None and chain is not None:
                        _waiting_for[chain] = self
                if refusal is not None:
                    if waited >= _PREPARE_WAIT_MAX:
                        pc_logging.warning("%s:%s: %s" % (self.project_name, self.name, refusal))
                    raise PreparationInFlight("%s:%s %s" % (self.project_name, self.name, refusal))
                slot_wait.update()
                await asyncio.sleep(delay)
                waited += delay
                delay = min(2 * delay, _PREPARE_POLL_MAX)
        finally:
            slot_wait.__exit__(None, None, None)
            if chain is not None:
                with _preparations:
                    if _waiting_for.get(chain) is self:
                        del _waiting_for[chain]

        token = _preparation.set(mine)
        try:
            if self._prepare is not None:
                await self._prepare(self)
        except BaseException:
            # A preparation that failed has not happened: leaving the flag
            # up would make a warm context skip it forever and then hash a
            # file that was never downloaded.
            with _preparations:
                self._prepared = False
                self._preparer = None
            raise
        finally:
            _preparation.reset(token)
        with _preparations:
            self._prepare_finished = True
            self._preparer = None

    def _refusal_to_wait(self, chain, waited: float):
        """Why a caller may not wait for this shape's preparation, under way elsewhere; None if it may.

        Under '_preparations'. 'chain' is the preparation the caller is part
        of, if any; 'waited' how long it has waited so far.

        A wait that could never end is refused before it starts, and there are
        two of those:

          * **A cycle of preparations.** A link back to a shape from inside its
            own preparation would wait for itself; and two preparations each
            waiting for a shape the other is preparing - X linking Y, while Y
            links X - would wait for each other. Each preparation records what
            it waits for, and a wait that would close a loop is refused. A
            shape in a cycle has no key, which is what keying it on half of
            itself used to amount to anyway.
          * **A shape's lock, held across threads.** A shape's thread lock
            stops every other thread that asks for that shape, its whole event
            loop with it (see 'locked()'). A thread that holds one and waits for
            a preparation running on another thread may be waiting for a thread
            it has stopped. Waiting on the same thread is safe - the waiter
            hands its own loop back while it waits - which is what an
            assembly's children do while the assembly is built under its lock.

        What is left is backstopped by '_PREPARE_WAIT_MAX'.
        """
        owner, thread = self._preparer if self._preparer is not None else (None, None)
        if chain is not None and (owner is chain or _waits_for(owner, chain)):
            return "is being prepared by a preparation that is waiting for this one: a cycle of links"
        if getattr(_held, "count", 0) > 0 and thread != threading.get_ident():
            return "is being prepared on another thread, and this one holds a shape's lock"
        if waited >= _PREPARE_WAIT_MAX:
            return "has been in preparation elsewhere for %ds; going on without its cache key" % waited
        return None

    async def get_cache_key_async(self) -> Optional[str]:
        """Prepare this shape and return its cache key, or None if it has none.

        The key hashes the shape's configuration together with the content of
        the files it is built from, so it is only correct once those files are
        on disk - which is what 'prepare_async()' above guarantees. Shapes that
        are not cached in their own right (an alias or an enrich hashes the
        object it points at, not itself) report no key.

        Every key that reaches a cache, or another shape's key, comes through
        here or waits the same way, so it is never read while a preparation of
        this shape begun elsewhere is still under way: that is waited for, and
        where it may not be (see 'prepare_async()'), there is no key yet - None,
        as for a shape that is not cached, and the hash is left unread so that
        whoever asks once the preparation is over gets the whole of it.
        """
        try:
            await self.prepare_async(wait=True)
        except PreparationInFlight as e:
            pc_logging.debug("No cache key yet: %s" % e)
            return None
        if not self.get_cacheable():
            return None
        return self.hash.get()

    def get_cache_key(self) -> Optional[str]:
        return asyncio.run(self.get_cache_key_async())

    async def get_artifact_key_async(self) -> Optional[str]:
        """What a render, an export or an analysis of this shape is keyed on, or None.

        Its cache key, for every shape that has one. A shape derived from
        another one for a single purpose has none - an instruction book's step,
        made of some of an assembly's items where the assembly put them - and is
        keyed as what it was derived from and what it is of that ('derived_from',
        'artifact_identity'): the assembly's key and the step. None when either
        is missing, which is what keeps `cache: false` on the assembly meaning
        nothing derived from it is cached.
        """
        key = await self.get_cache_key_async()
        if key is not None or self.derived_from is None or not self.artifact_identity:
            return key
        source = await self.derived_from.get_artifact_key_async()
        return "%s#%s" % (source, self.artifact_identity) if source else None

    def artifacts_cacheable(self) -> bool:
        """Whether what is made of this shape may be cached: the `cache: false` rule.

        A derived shape is cacheable when what it was derived from is - its
        own `cache: false` says only that it has no declaration to key it on.
        """
        if self.get_cacheable():
            return True
        return self.derived_from is not None and self.derived_from.artifacts_cacheable()

    async def is_cached_async(self, ctx) -> bool:
        """Whether this shape can be had without building it.

        True when it is already in this process's memory, and otherwise when
        the cache holds the one entry 'get_wrapped()' materializes it from.
        One entry is the whole of it: whatever was recorded about the geometry
        travels inside that entry (see cache_shape.py), so a hit is a hit and
        there is no sibling entry that might be missing. The components beside
        it are not asked after for the same reason 'get_wrapped()' does not
        insist on them - a shape that has none is cached exactly as completely
        as one that has.

        Asked of the tiers rather than read out of them, so that answering it
        for a large assembly costs a stat() rather than the assembly. A shape
        that is not cacheable at all is never "cached" by this: it is either in
        memory or it has to be built.
        """
        if self._wrapped is not None:
            return True
        if not ctx or await self.get_cache_key_async() is None:
            return False
        present = await ctx.cache_shapes.contains_data_async(self.hash, [self.kind])
        return present.get(self.kind, False)

    async def add_cache_key_of(self, source: "Shape") -> bool:
        """Key this shape on the key of a shape it is built from, too.

        For a shape made *out of* others - an extrusion of a sketch, an
        assembly of parts - its own configuration and files say which objects
        it uses but not what they contain, so editing one of them would leave
        this shape's key, and the entry stored under it, as they were. Their
        keys cover their content, so hashing those covers it here as well.

        False when the source has no key - it says 'cache: false', or is made
        of something that does - which leaves this shape's content unaccounted
        for: the caller must not cache it either.
        """
        await source.prepare_async()
        key = await source.get_cache_key_async()
        if key is None:
            return False
        self.hash.add_string(key)
        return True

    async def take_cache_key_from(self, source: "Shape") -> None:
        """Key this shape on the shape it points at, plus what it adds to it.

        A reference - an alias or an enrich - is not geometry of its own: what
        it hands back is what the object it points at hands back, moved or
        scaled if it says so. A key of its own would put that geometry in the
        cache a second time, under a second key, for every copy of the
        reference; the source's key stores it once.

        A reference that adds nothing shares the source's entry outright -
        including the key, so the two are the same entry and not two copies of
        one - and leaves the writing to the source ('owns_cache_entry'). One
        that moves or scales what it points at produces different geometry and
        so keys differently: the source's key, plus what it adds, which is an
        entry of its own to fill.

        Called once the source is resolved and prepared, which is the first
        moment there is a key to take, and still before anything asks this
        shape for its own (see the alias factories' 'prepare_async').
        """
        source_key = await source.get_cache_key_async()
        if source_key is None:
            # Nothing to share: what this points at is not cached either.
            self.cacheable = False
            return

        transform = {key: self.config[key] for key in ("offset", "scale") if key in self.config}
        if not transform:
            self.hash = source.hash
            self.owns_cache_entry = False
            return

        # 'source.hash' carries everything the source is keyed on by now - the
        # call above is what hashed the files it depends on - so continuing it
        # is the source's key with this shape's own contribution after it.
        self.hash = CacheHash(f"{self.project_name}:{self.name}", hasher=source.hash.hasher, cache=True)
        self.hash.add_dict(transform)
        # The move or the scale is done by a wrapper (see 'get_wrapped'), whose
        # version is part of what this entry is.
        versions = code_version.wrappers_key(["transform.py"])
        if versions is not None:
            self.add_code_versions(versions)

    async def get_wrapped(self, ctx):
        if self.built_on_pool:
            # Built already. Never unset again for a shape like this, so the
            # answer needs no lock -- and must not wait for one: whoever holds
            # it may be writing this shape's files for as long as that takes,
            # and an object built from this one has no reason to wait for that.
            if self._wrapped is not None:
                return self._wrapped
            # Not on a slot of the pools yet, which is a command asking for this
            # shape rather than another shape being built out of it: go to the
            # pool *before* taking the lock, and take it there. Then whoever
            # holds a part's lock while it is built is the thread building it,
            # which needs nothing from the pools to finish (see
            # 'sync_threads'), and an object built from it that waits for the
            # lock waits for that thread and nothing else.
            #
            # Taken here instead, the lock is held by the command's event loop
            # for as long as the build sits in the pool's queue -- behind,
            # quite possibly, the very objects waiting for the lock. Each of
            # those has to give its slot back for the build to get one
            # ('sync_threads.PoolAwareRLock'), and the pool starts a thread for
            # whatever is next in its queue, which may be one more object
            # waiting for the same lock: a thread per waiter where none is
            # needed. Before slots were given back, it was a deadlock -- a part
            # and eight aliases of it, asked for at once on four threads,
            # stopped for good even once no object took a second slot for its
            # source.
            #
            # Not when the calling task holds the lock already: 'analyze_async'
            # and the others take it first and ask for the shape inside it,
            # and going elsewhere for the lock would be waiting for itself. Nor
            # from inside a preparation, whose chain is a context variable the
            # hop would leave behind: the far side would not know it for part
            # of that preparation, and could wait for what is waiting for it.
            if sync_threads.current_slot() is None and not _held_by_current_task(self) and _preparation.get() is None:
                return await sync_threads.threadpool_manager.run_async(self._get_wrapped, ctx)
        return await self._get_wrapped(ctx)

    async def _get_wrapped(self, ctx):
        # Prepared before this shape's lock is taken, and waited for where
        # somebody else began it: the key read below means nothing until the
        # preparation is over, and waiting for one under the lock is the one
        # place that must never happen - the lock stops every other thread that
        # asks for this shape, the preparer's among them. A preparation that
        # cannot be waited for leaves this build uncached rather than keyed on
        # part of what it is made of.
        try:
            await self.prepare_async(wait=True)
        except PreparationInFlight as e:
            pc_logging.debug("Building without the cache: %s" % e)
        async with self.locked():
            if self._wrapped is not None:
                return self._wrapped

            # Before the cache key means anything: the files this shape is
            # built from have to be on disk to be hashed, and a reference
            # has to have resolved what it points at to have a key at all
            # (see 'take_cache_key_from'). Costs one flag test once it has
            # happened.
            await self.prepare_async()

            # And before the layer this shape stamps on whatever comes back means
            # anything: that layer carries the shape's ports, and an assembly's
            # 'map:' is what turns a declaration into ports. It is resolved here
            # rather than on the way to 'get_shape()' because the cache hit below
            # stamps the same layer without ever getting there. A no-op - one
            # dictionary lookup - for everything that declares no 'map:', which
            # is every part, every sketch, and most assemblies.
            await shape_ports.prepare_async(self, ctx)

            # Not before the preparation is over (see above).
            is_cacheable = self.get_cacheable() and ctx and self._prepare_finished
            if is_cacheable:
                cache_hash = self.hash
                if cache_hash:
                    cached, to_cache_in_memory = await ctx.cache_shapes.read_async(
                        cache_hash, [self.kind, "cmps"], self.get_cache_metadata()
                    )
                    # Whatever was recorded about the geometry came back inside
                    # the same entry as the geometry (see cache_shape.py), so a
                    # hit is a hit: there is no sibling entry that might be
                    # missing, and nothing to check for completeness.
                    #
                    # Set only on a hit, and to '{}' rather than None when the
                    # entry recorded nothing: None on this attribute means "not
                    # known yet" and is what sends 'get_metadata_async()' off to
                    # build the shape. A miss here has to leave it saying that.
                    if cached.get(self.kind) is not None:
                        self._metadata = shape_envelope.metadata_of(cached[self.kind]) or {}
                    if to_cache_in_memory.get(self.kind, False):
                        self._wrapped = cached[self.kind]
                    if to_cache_in_memory.get("cmps", False):
                        self.components = cached["cmps"]
                    if self.kind in cached and cached[self.kind] is not None:
                        return cached[self.kind]
                else:
                    if self.cache:
                        pc_logging.warning(f"No cache hash for shape: {self.name}")
            else:
                cache_hash = None

            shape = await self.get_shape(ctx)

            # Normalize whatever the factory produced into a BREP envelope so
            # the rest of the core - caching, offset/scale, the return value -
            # only ever handles opaque envelopes, never live OCP objects. A
            # factory that still builds a live shape in-process is encoded
            # here, at the single choke point; factories that delegate to a
            # wrapper already return an envelope and pass straight through.
            shape = self._to_envelope(shape)
            # What the wrapper that built it has done of what comes next - the
            # validation, the 'offset', the 'scale' - while the shape was live
            # there (see 'finish_request'). Taken off first, so that nothing
            # below, and nothing cached, ever sees the claim; what it does not
            # claim is done below, as it always was.
            shape, claim = shape_envelope.take_finished(shape)
            finished = self._finished_by_wrapper(claim)
            # Every part, by the one validation every part goes through,
            # before anything is recorded or cached: see '_validated_part'.
            # Already taken by the wrapper that built it, where it could, on
            # the live shape and with the same two functions: then the part is
            # converted already, and all that is left is to say what is wrong
            # with it, in the same words.
            verdict = finished.get(shape_envelope.FINISHED_VALIDATED)
            if self.kind == "part" and shape_envelope.is_shape_object(shape):
                if verdict is not None:
                    self._not_a_solid(verdict.get("problems") or [])
                elif ctx is not None:
                    shape = await self._validated_part(ctx, shape)
            if self.components:
                self.components = [self._component_to_envelope(c) for c in self.components]

            # What the wrapper that produced this envelope recorded about it -
            # the size it measured, and whatever the source file stated (see
            # 'shape_envelope.KEY_METADATA'). Taken off here and not later
            # because 'offset'/'scale' below may go through a wrapper that
            # decodes the envelope and encodes a fresh one, which cannot carry
            # forward what it was never sent.
            recorded = shape_envelope.metadata_of(shape)

            # TODO(clairbee): apply 'offset' and 'scale' to 'components' too
            # 'offset'/'scale' are applied in a sandbox so the core does not
            # have to run build123d in-process to do it: by the wrapper that
            # built the shape, as it built it, wherever that wrapper could (see
            # 'finish_request'), and otherwise here, by a sandbox of its own
            # (transform.py) - which is the only way left for a shape that was
            # never live in a wrapper of its own: a reference to another part,
            # which moves the source's geometry.
            if shape is not None and ("offset" in self.config or "scale" in self.config):
                from . import transform
                from .geom import Location

                if "offset" in self.config and "offset" not in finished:
                    shape = await transform.offset(ctx, shape, self.config["offset"])
                if "scale" in self.config and "scale" not in finished:
                    shape = await transform.scale(ctx, shape, self.config["scale"])

                # The transform rebuilt the geometry, so the encoder on the far
                # side measured what came out and the numbers on the way back
                # are the new ones - which is the point: a part scaled by two is
                # not the size the file it was read from would suggest. What
                # that wrapper could not know is what the *source* stated, so
                # the sections read at import are laid back under the fresh
                # measurements rather than lost with the envelope they rode in.
                # (Where the wrapper that built the shape moved it, the two are
                # one envelope already, and this changes nothing.)
                #
                # The old measurements are dropped first rather than merged
                # under. They describe a shape that no longer exists, so if the
                # far side could not measure what came out, the honest answer is
                # that this shape's size is unknown - not the size it used to
                # be, which is the one answer nobody could detect as wrong.
                recorded = shape_envelope.merge_metadata(
                    shape_envelope.without_measurements(recorded),
                    shape_envelope.metadata_of(shape),
                )

                # And what the source said about each element goes where the
                # element went, moved the way the geometry was and in the same
                # order - or a bend line's angle would go on being pinned to
                # the place the line was drawn rather than the place it is.
                if "offset" in self.config:
                    offset = Location(self.config["offset"])
                    recorded = shape_envelope.moved_annotations(recorded, offset.transform_point)
                if "scale" in self.config:
                    factor = float(self.config["scale"])
                    recorded = shape_envelope.moved_annotations(
                        recorded, lambda point: [factor * axis for axis in point]
                    )

            # Whatever produced the envelope - a factory, a wrapper, a
            # transform - the outer layer around it is this shape's own. It
            # is stamped here rather than left to whoever built the payload,
            # so that a shape built now and the same shape materialized from
            # the cache later carry exactly the same name and label.
            shape = shape_envelope.apply_metadata(shape, self.get_cache_metadata())

            # Kept on the object as well as cached, because the two answer for
            # different runs. A shape with 'cache: false', one that does not own
            # its entry, and a run with every tier switched off all reach here
            # having built the shape and having nowhere to store what that
            # produced - and 'pc info' should still be able to say how big it is.
            self._metadata = recorded or {}
            if recorded:
                shape = dict(shape)
                shape[shape_envelope.KEY_METADATA] = recorded

            if cache_hash:
                if is_cacheable and self.owns_cache_entry:
                    # The geometry and everything recorded about it go into the
                    # one entry, in the one write, because they were produced
                    # together and are valid together: the hash that keys the
                    # entry covers what produced the geometry, so a shape that
                    # rebuilds measures again and one that does not never needs
                    # to. Separate entries could be separately present.
                    to_cache = {self.kind: await self.get_cache_value(ctx, shape)}
                    if self.components and len(self.components) > 0:
                        to_cache["cmps"] = self.components
                    properties = self._shape_properties()
                    if properties:
                        # The one thing still kept beside the geometry rather
                        # than in it, and the reason is that it is *declared*:
                        # the hash does not cover a 'properties:' section, so
                        # editing one leaves the geometry entry valid and a copy
                        # buried inside it would go on answering with the values
                        # it happened to be written with. See
                        # 'cache_shape.properties_key()'.
                        to_cache[properties_key(self.kind)] = properties
                    to_cache_in_memory = await ctx.cache_shapes.write_async(cache_hash, to_cache)
                    do_cache_in_memory = to_cache_in_memory.get(self.kind, False)
                else:
                    do_cache_in_memory = True
                if do_cache_in_memory:
                    self._wrapped = shape
            else:
                # Let the file cache tell us if we need to cache this in memory
                self._wrapped = shape
            return shape

    def _shape_properties(self):
        """What this shape reports about itself, or None if it reports nothing.

        The 'properties:' section of the configuration - 'material', 'color' and
        'physics'. They are outputs, not inputs: 'parameters:' is what is asked
        of the object type that produces the shape, while these describe the
        shape that came out. Nothing here takes part in the cache hash, which is
        why a cached entry can be shared by objects that state different ones.

        Read as it stands, and nothing is derived here. What a shape turned out
        to be made of is written into 'properties:' by whatever instantiated it
        - a reader that found it in the file, or the part factory promoting the
        'material' its type was asked for (see
        'PartFactory.record_object_type_properties()'). By the time a shape is
        being asked what it reports, that has already happened.
        """
        if not isinstance(self.config, dict):
            return None
        properties = self.config.get(shape_envelope.KEY_PROPERTIES)
        if not isinstance(properties, dict):
            return None
        properties = {key: value for key, value in properties.items() if value not in (None, {}, [], "")}
        return properties or None

    def material_reference(self) -> Optional[str]:
        """What this shape says it is made of, as it was written, or None.

        A *name* - '//pub/std/manufacturing/material/metal:al-5052-h32', or
        ':aluminium' for one catalogued in the shape's own package - and not
        yet a thing anything can be asked of. 'get_material()' below is what
        turns it into one.
        """
        properties = self._shape_properties() or {}
        reference = properties.get("material")
        return reference if isinstance(reference, str) and reference else None

    def get_material(self, ctx, quiet: bool = True):
        """The material this shape is made of, or None if it names none.

        Resolved against the package that owns *this shape*, exactly as
        'physics.physics_by_shape()' resolves it on the far side of an export:
        ':aluminium' means "in my own package", and whose package that is is a
        fact about the shape that wrote the reference rather than about the
        string. Two packages may each catalogue an 'aluminium' of their own and
        each get theirs.

        Quiet by default, because the callers are the ones that report a
        reference nobody answers to in their own way - 'shape_info()' below puts
        it in the answer rather than in the log - and because a shape with no
        material at all is the ordinary case rather than a mistake.
        """
        reference = self.material_reference()
        if reference is None or ctx is None:
            return None
        package, name = resolve_resource_path(self.project_name, reference)
        _project, found = pc_material.lookup(ctx, "%s:%s" % (package, name), quiet=quiet)
        return found

    def world_facts(self, ctx) -> Optional[dict]:
        """What this shape says about the world it is, or None: nothing, unless it is a scene.

        A part or an assembly is a thing placed *in* a world and has no gravity
        or medium of its own to state; 'Scene' overrides this. Asked of every
        shape rather than only of scenes so that '_output_request()' below has
        one question to ask and no kind to test for -- a filtered view of a
        scene is a scene too, and answers the same.
        """
        return None

    async def get_cached_properties_async(self, ctx):
        """What the cache recorded beside this shape's geometry, or None.

        The other half of 'get_wrapped()'. The two entries are filled together,
        as the shape is instantiated, and materialized apart: the properties can
        be had without pulling a BREP out of the cache, and the BREP without
        them. A shape that has never been built, an entry written before
        properties were cached at all, and a shape that reports nothing all mean
        the same thing here - nothing recorded - which is an answer rather than
        a failure, and never a reason to build the geometry again.

        What comes back describes the geometry, which every object hashing to
        the same key shares. What identifies *this* object is its own
        'properties:' section, which is why 'get_cache_metadata()' - and so
        everything stamped onto an envelope - reads the configuration and never
        comes here.
        """
        if not ctx or await self.get_cache_key_async() is None:
            return None
        key = properties_key(self.kind)
        cached, _ = await ctx.cache_shapes.read_async(self.hash, [key])
        properties = cached.get(key)
        return properties if isinstance(properties, dict) and properties else None

    def _shape_metadata(self):
        """The (full_name, label) stamped onto this shape's envelope."""
        name = getattr(self, "name", None)
        project = getattr(self, "project_name", None)
        full_name = ("%s:%s" % (project, name)) if project and name else name
        label = self.config.get("label", name) if isinstance(self.config, dict) else name
        return full_name, label

    def _to_envelope(self, shape, name=None, label=None):
        """Normalize a factory's output into a BREP envelope dict.

        An envelope (or None) passes straight through. A live OCP shape - which
        only the in-process factories still produce - is encoded here, the one
        place in the core that touches a live shape. The OCP codec is imported
        lazily, so a workflow that only uses delegating factories never pulls
        OCP into the core process. The payload is taken as the compressed bytes,
        not the base64 the same codec produces for the pipe: this envelope stays
        in this process, and may go straight into a cache from here.
        """
        if shape is None or shape_envelope.is_shape_envelope(shape):
            return shape
        import ocp_serialize
        import shape_measure

        if name is None and label is None:
            name, label = self._shape_metadata()
        envelope = shape_envelope.make_shape(ocp_serialize.compressed_brep(shape), name=name, label=label)
        # Measured here for the same reason a wrapper's shapes are measured as
        # they are encoded: this is the moment the live object exists, and it is
        # the last one. An in-process factory is the one producer that does not
        # go through the sandbox encoder, so without this its shapes would be
        # the only ones whose size had to be computed all over again later.
        measured = shape_measure.measurements_or_none(shape)
        if measured:
            envelope[shape_envelope.KEY_METADATA] = {shape_envelope.METADATA_MEASUREMENTS: measured}
        return envelope

    def _component_to_envelope(self, component):
        """Normalize a component (or nested list of components) into envelopes."""
        if isinstance(component, list):
            return [self._component_to_envelope(item) for item in component]
        return self._to_envelope(component)

    def take_side_data_from(self, source) -> None:
        """Adopt what the object this one points at recorded about its geometry.

        A reference shares the cache entry of its source (see
        'take_cache_key_from'), so the two have to answer the same - and the
        source is what builds, and so what learns, what the geometry measures
        and what its file stated. Called once the source has been materialized,
        beside the copy of its components that happens for the same reason.
        """
        self._metadata = copy.deepcopy(getattr(source, "_metadata", None))

    async def get_cache_value(self, ctx, shape):
        """The value handed to the shape cache under 'self.kind'.

        A plain shape is a single BREP envelope; an assembly is the nested tree
        it was built as, so that the hierarchy - names, labels and
        sub-assemblies - survives caching, which a flat compound would lose.

        'shape' is already an envelope (get_wrapped normalizes it) and is passed
        on as it is: what identifies this particular shape is not cached with
        the geometry but comes from 'get_cache_metadata()' on the way out.
        """
        return shape

    def get_cache_metadata(self):
        """The outer layer to wrap around this shape's payload read from the cache.

        A cache entry is keyed on the geometry, so several shapes with identical
        geometry share one. Everything that says which shape this is therefore
        lives here rather than in the cache - see ShapeCache. That includes what
        the shape reports about itself: two parts cut from the same solid may
        well be made of different materials, and each has to get its own back.

        And what it says about connections, for the same reason: two parts cut
        from one solid may have their ports in different places, or none at all,
        so where this shape's ports are and which interfaces they form is
        re-stamped here rather than stored inside the entry they share.
        """
        full_name, label = self._shape_metadata()
        metadata = {"name": full_name, "label": label}
        properties = self._shape_properties()
        if properties:
            metadata[shape_envelope.KEY_PROPERTIES] = properties
        metadata.update(shape_ports.connection_metadata(self))
        return metadata

    async def convert(self, part_type: str, ctx=None, **kwargs):
        """Convert this shape to 'part_type' and return the result in memory.

        This is the in-memory counterpart of 'render_async()': it drives the very
        same export machinery, but hands the result back instead of leaving an
        output file behind.

        Args:
            part_type: One of the supported part types (see below).
            ctx: Execution context. Optional for the live-object types, required
                for every serialized format (the exporters run in a managed
                Python runtime that only the context can provide).
            kwargs: Format-specific export options, forwarded to
                'render_async()' - e.g. 'tolerance', 'angularTolerance',
                'ascii' (stl), 'binary' (gltf), 'line_weight' and
                'viewport_origin' (svg/dxf), 'write_pcurves' and
                'precision_mode' (step/iges). 'project' may be passed to pick up
                a project's render options.

        Supported part types:
            Live objects, returned as the CAD library's own object:
                "build123d", "cadquery"
            Serialized formats:
                "3mf", "brep", "dxf", "gltf", "iges", "obj", "step", "stl",
                "svg", "threejs"

        Return type:
            The live-object types return the corresponding object. For the
            serialized formats the rule is: formats that are textual by
            definition return 'str' (UTF-8 decoded), and formats that are or can
            be binary return 'bytes'. Concretely, "step", "iges", "brep", "obj",
            "threejs", "svg" and "dxf" return 'str'; "stl", "3mf" and "gltf"
            return 'bytes', because each of those switches between a text and a
            binary encoding depending on the options. The return type therefore
            depends only on 'part_type' and never on the options passed.

        Raises:
            ValueError: 'part_type' is not supported, or a serialized format was
                requested without a context.
            RuntimeError: the exporter produced no output.
        """
        if not isinstance(part_type, str):
            raise ValueError(f"Invalid part type {part_type!r}: expected a string, got {type(part_type).__name__}")

        normalized = part_type.strip().lower()

        if normalized in LIVE_OBJECT_PART_TYPES:
            return await self._convert_to_live_object(normalized, ctx)

        if normalized in SERIALIZED_PART_TYPES:
            return await self._convert_to_serialized(normalized, ctx, **kwargs)

        supported = ", ".join(sorted(SUPPORTED_PART_TYPES))
        if normalized in UNEXPORTABLE_PART_TYPES:
            raise ValueError(
                f"Cannot convert to '{part_type}': {UNEXPORTABLE_PART_TYPES[normalized]}. "
                f"Supported part types: {supported}"
            )
        raise ValueError(f"Unknown part type '{part_type}'. Supported part types: {supported}")

    async def _convert_to_live_object(self, part_type: str, ctx):
        """Wrap this shape into a live build123d or CadQuery object."""
        if not ctx:
            pc_logging.debug(
                "No context provided to convert('%s'). Consider using Context.convert_part() instead." % part_type
            )

        # The shape may fail to instantiate, in which case 'get_wrapped()'
        # returns None. Keep handing back an object with 'wrapped' set to None
        # rather than raising: callers such as Assembly._get_shape_real() rely on
        # being able to tell that apart and report which shape went missing.
        wrapped = await self.get_wrapped(ctx)

        # 'build123d' and 'cadquery' are NOT dependencies of PartCAD: it builds
        # and exports every shape in sandboxed runtimes. Handing back a *live*
        # object of that flavour is the one thing PartCAD cannot do without the
        # library actually present in the caller's environment - so this path is
        # only for users who already have it, and OCP (which decodes the BREP)
        # comes with it. When it is missing, warn naming the expected library and
        # re-raise, rather than pointing at a PartCAD install extra.
        try:
            # get_wrapped() returns a BREP envelope; a live object is what this
            # API promises, so decode it here. This is one of the few core paths
            # that legitimately holds a live OCP shape, which is why the imports
            # stay lazy.
            live = None
            if wrapped is not None:
                import ocp_serialize

                live = ocp_serialize.decode_shape(wrapped)

            if part_type == "build123d":
                import build123d as b3d

                b3d_solid = b3d.Solid.make_box(1, 1, 1)
                b3d_solid.wrapped = live
                return b3d_solid

            import cadquery as cq

            cq_solid = cq.Solid.makeBox(1, 1, 1)
            cq_solid.wrapped = live
            return cq_solid
        except ImportError as e:
            pc_logging.warning(
                "convert('%s') needs the '%s' library, which is not installed. Install it in "
                "your project to work with PartCAD parts as live '%s' objects." % (part_type, part_type, part_type)
            )
            raise ImportError(
                "convert('%s') needs the '%s' library, which is not installed. "
                "Install '%s' to get a live %s object." % (part_type, part_type, part_type, part_type)
            ) from e

    async def _convert_to_serialized(self, part_type: str, ctx, **kwargs):
        """Export this shape to 'part_type' and return the payload in memory.

        Every exporter PartCAD ships insists on writing to a path, so the export
        goes to a temporary directory that is removed on both the success and the
        error path.
        """
        if ctx is None:
            raise ValueError(
                f"Cannot convert '{self.name}' to '{part_type}' without a context: "
                "the exporters run in a context-managed Python runtime"
            )

        # The extension is not cosmetic: some exporters pick the output format
        # from it (CadQuery's 3MF exporter, for one), so use the same mapping
        # 'render_async()' uses when it has to invent a file name.
        extension = PART_EXTENSION_MAPPING.get(part_type) or SKETCH_EXTENSION_MAPPING.get(part_type, part_type)

        with tempfile.TemporaryDirectory(prefix="partcad-convert-") as temp_dir:
            # A fixed basename keeps shape names with path separators or other
            # awkward characters out of the filesystem.
            filepath = os.path.join(temp_dir, f"shape.{extension}")

            await self.render_async(ctx, part_type, filepath=filepath, **kwargs)

            if not os.path.exists(filepath):
                raise RuntimeError(
                    f"Failed to convert {self.project_name}:{self.name} to '{part_type}': "
                    "the exporter produced no output"
                )

            with open(filepath, "rb") as f:
                data = f.read()

        if part_type in TEXT_PART_TYPES:
            return data.decode("utf-8")
        return data

    async def get_cadquery(self, ctx=None):
        """Deprecated. Use 'convert("cadquery", ctx)' instead."""
        warnings.warn(
            "Shape.get_cadquery() is deprecated, use Shape.convert('cadquery', ctx) instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.convert("cadquery", ctx)

    async def get_build123d(self, ctx=None):
        """Deprecated. Use 'convert("build123d", ctx)' instead."""
        warnings.warn(
            "Shape.get_build123d() is deprecated, use Shape.convert('build123d', ctx) instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.convert("build123d", ctx)

    async def show_async(self, ctx=None, tab=None, scenario=None, section=None):
        """Show this shape in the Digital Thread, on its tab 'tab' if one is named, and that tab's 'scenario'.

        'section' cuts it by a box first ('shape_section'): what the viewer's
        section sliders ask for, by asking for the object to be shown again.
        """
        from . import viewer

        # Refused before anything is built: a section that is not one costs a
        # message, not a tessellation.
        section = shape_section.normalize(section)

        # A caller that cannot pass one gets the process-wide context; one that
        # passes None where there is no global is told so rather than left to
        # discover it from the first thing that needs one. See 'viewer.context'.
        ctx = viewer.context(ctx, self.name)
        if ctx is None:
            return

        with pc_logging.Action("Show", self.project_name, self.name):
            # The whole object, as the tree it is, with every node's geometry
            # tessellated: the viewer is a browser and has no CAD kernel, so the
            # glTF form is what it can draw (see 'shape_gltf'). Nothing about the
            # tree is built for the viewer - it is the same hierarchy, with the
            # same names, placements, ports and interfaces, that this shape
            # answers with for every other purpose.
            tree = None
            # TODO(clairbee): consider removing this exception handler permanently
            # Comment out the below exception handler for easier troubleshooting in CLI
            try:
                tree = await self.get_representation(ctx, shape_envelope.FORM_GLTF, section=section)
            except Exception as e:
                pc_logging.exception(e)

            if tree is not None:
                await viewer.show(
                    ctx,
                    tree,
                    name=self.name,
                    kind=self.kind,
                    package=self.project_name,
                    tab=tab,
                    scenario=scenario,
                    section=section,
                )

    def show(self, ctx=None, tab=None, scenario=None, section=None):
        asyncio.run(self.show_async(ctx, tab=tab, scenario=scenario, section=section))

    def shape_info(self, ctx):
        """What 'pc info' reports of any shape, whatever kind or type it is.

        What it cost to hold, what it measured, what it is keyed and cached
        under, and the ports it carries. A factory adds what is particular to
        its type on top of this (see 'ShapeFactory.info').

        The shape is built first, and has to be: a measurement is of geometry,
        and the hash of a shape means nothing until the files it is built from
        are on disk. For a shape built before, that is a cache hit.
        """
        asyncio.run(self.get_wrapped(ctx))
        asyncio.run(shape_ports.prepare_async(self, ctx))
        info = {}
        info["Memory"] = "%.02f KB" % ((total_size(self) + 1023.0) / 1024.0)
        info.update(asyncio.run(self._reported_async(ctx)))

        if self.with_ports is not None:
            info["Ports"] = self.with_ports.info()

        # What the shape is made of, as the facts rather than as the name. The
        # configuration printed beside this already shows the reference, and the
        # question somebody running 'pc info' on a part is asking is what that
        # reference means: the density its mass came from, the friction a
        # simulation of it used, what the substance is good and bad at.
        material_reference = self.material_reference()
        if material_reference is not None:
            material = self.get_material(ctx)
            info["Material"] = (
                material.material_info()
                if material is not None
                # A reference nothing answers to is reported as it was written
                # rather than dropped: it is the most useful thing that can be
                # said about what this is made of, and the reason no mass and no
                # friction came from it.
                else {"Name": material_reference, "Errors": ["The material is not found"]}
            )

        # What it weighs, where it balances and how it turns, each value with
        # where it came from - stated, lent by the material, or derived from the
        # solid at its density. The same values an export of it is handed, by
        # the same function, so that what 'pc info' says a part weighs is what a
        # simulation of it weighs. See 'partcad.physics'.
        mass_properties = asyncio.run(pc_physics.mass_properties_async(ctx, self))
        if mass_properties:
            info["MassProperties"] = mass_properties

        # The key, once the preparation is over: read before, a hash keeps what
        # it had then (see 'prepare_async()').
        info["Hash"] = asyncio.run(self.get_cache_key_async())
        if self.environment_cache_key is not None:
            # Part of that hash, and the part of it a user is most likely to be
            # asking about when a shape re-renders instead of coming from cache.
            info["Environment"] = self.environment_cache_key
        info["Dependencies"] = self.cache_dependencies
        return info

    def error(self, msg: str):
        mute = self.config.get("mute", False)
        if not mute:
            pc_logging.error(msg)
        self.errors.append(msg)

    # ------------------------------------------------------------------ #
    # Output files: 'pc export' and 'pc render'                          #
    # ------------------------------------------------------------------ #
    #
    # Neither the formats nor the implementations that write them are listed
    # here. They are declared by the packages that implement them - the ones
    # PartCAD ships, '//builtin/export' and '//builtin/render', exactly like a
    # package that implements a format itself - and resolved through 'output'.
    # What is left in this module is the part that is the same for every
    # format: gather the configuration, work out the file name, run the
    # implementation in a sandbox.

    def _output_implementor(self, ctx, format_name):
        """Split a 'package:format' file type into the type and that package.

        A bare name is left alone and answers None, which is every caller that
        has not named a package. One that has named one is asking for that
        package's implementation by its full path, the way an 'import:' type or
        a 'simulation:' plugin is named, and a package it names that is not in
        the graph is an error here rather than a file type nobody declares: the
        caller said where the implementation lives, so "not found" is about the
        package and saying anything else sends them looking in the wrong place.
        """
        format_name, package = output.split_format(self.project_name, format_name)
        if package is None:
            return format_name, None
        impl_project = ctx.get_project(package)
        if impl_project is None:
            raise Exception("The package implementing the '%s' file type is not found: %s" % (format_name, package))
        return format_name, impl_project

    def _output_section(self, ctx, format_name, project=None, options_project=None, impl_project=None) -> str:
        """Whether a file type is an 'export:' or a 'render:' one.

        A package named explicitly ('pc export -t sim-mujoco:mjcf') answers
        first: the caller said whose implementation this is, so that package's
        sections are what the file type means, even where a built-in of the same
        name would have said otherwise.

        Failing that the built-in packages decide it for the formats they
        implement. For one they do not, the package that declares it does: a
        format is an export format if it appears in an 'export:' section and a
        render format if it appears in a 'render:' one.
        """
        if impl_project is not None:
            for candidate in output.SECTIONS:
                if format_name in output.format_names(impl_project.config_obj.get(candidate)):
                    return candidate

        section = output.section_of(ctx, format_name)
        if section is not None:
            return section

        for config_obj in (self.config, *(p.config_obj for p in (project, options_project) if p is not None)):
            for candidate in output.SECTIONS:
                if format_name in output.format_names(config_obj.get(candidate)):
                    return candidate
        return output.EXPORT

    def _output_getopts(
        self, ctx, format_name, section, project=None, options_project=None, impl_project=None, defaults_only=False
    ):
        """Layer every configuration of a file type, lowest priority first.

        The built-in package is the bottom layer, so a package that re-tunes a
        single parameter keeps the built-in implementation for everything else.
        Directly above it, the package a 'package:format' name pointed at, if
        the caller named one. On top of that come the package the options were
        asked to come from (the '--options-package' of 'pc export' /
        'pc render'), then the package the shape belongs to, then the shape
        itself.

        A named package goes in as a layer rather than replacing the lot -- which
        is what 'import_declaration()' does with the same spelling -- because
        this section also decides where the file goes. 'output_dir' and 'prefix'
        are the caller's business whoever writes the file, and a package asking
        somebody else's exporter for a file in its own tree would otherwise be
        told where to put it by that exporter.

        Returns the merged configuration and the output directory the sections
        asked for, if any.

        'defaults_only' keeps the built-in layer and nothing above it: what
        PartCAD itself draws a file type with, whatever the package and the
        shape configure. For a picture PartCAD composes for its own document - an
        assembly instruction book chooses each view for the step it shows (see
        'assembly_guide.RenderedImages') - where a package's 'viewport_origin',
        or a 'with_ports:' it declared for its own drawings, would be wrong.
        """
        layers = []
        builtin = output.builtin_project(ctx, section)
        if builtin is not None:
            layers.append((builtin.name, builtin.config_obj))
        if not defaults_only:
            for source in (impl_project, options_project, project):
                if source is not None:
                    layers.append((source.name, source.config_obj))
            layers.append((self.project_name, self.config))

        opts = {}
        output_dir = None
        for package_name, config_obj in layers:
            for section_name in output.config_sections(section):
                section_obj = config_obj.get(section_name)
                if not isinstance(section_obj, dict):
                    continue
                if section_obj.get("output_dir"):
                    output_dir = section_obj["output_dir"]
                if format_name in section_obj:
                    layer = output.stamp(output.normalize(section_obj[format_name]), package_name)
                    opts = output.merge(opts, layer)
        return opts, output_dir

    def _output_filepath(self, opts, output_dir, extension, project=None, filepath=None, stem_suffix=""):
        """Where a file of this type goes when the caller did not say.

        'prefix' names the directory the file goes in, relative to the output
        directory or, failing that, to the package. A prefix that carries an
        extension is taken to name the file itself, which is the one way to
        give an object's output a name of its own.

        'stem_suffix' goes between the object's name and the extension, and is
        what makes an analysis write 'bracket.fea.vtu' rather than
        'bracket.vtu': the analysis is part of what the file is, and a part has
        as many analysis results as it has analyses. Empty for everything else,
        where the file type is already the extension.

        A name with a '/' in it names a file in a sub-directory of wherever the
        configuration put it -- see 'output.name_to_path()' for why, and
        'Context.ensure_dirs_for_file()' for who creates it.
        """
        if filepath is not None:
            return filepath

        filepath = opts.get("prefix") or "."
        if not os.path.isabs(filepath):
            if output_dir:
                # TODO(clairbee): consider using project.config_dir
                filepath = os.path.join(output_dir, filepath)
            elif project is not None:
                filepath = os.path.join(project.config_dir, filepath)
        filepath = os.path.normpath(filepath)

        # A directory that does not exist yet is still a directory: it is
        # created once the name is known, on the way to writing the file.
        if os.path.isdir(filepath) or not os.path.splitext(filepath)[1]:
            filepath = os.path.join(filepath, output.name_to_path(self.name, stem_suffix + extension))
        return filepath

    def output_getopts(
        self, ctx, format_name, project=None, filepath=None, options_project=None, output_dir=None, defaults_only=False
    ):
        """Resolve one output file type: its implementation, options and path.

        This is the whole of what a format's configuration means, in one place:
        which script writes the file, what it is handed, and where the file
        lands. 'pc export' and 'pc render' differ only in which section the
        answer is read from.
        """
        format_name, impl_project = self._output_implementor(ctx, format_name)
        section = self._output_section(ctx, format_name, project, options_project, impl_project)
        opts, configured_output_dir = self._output_getopts(
            ctx, format_name, section, project, options_project, impl_project, defaults_only=defaults_only
        )
        # An explicitly requested output directory (e.g. 'pc export -O') beats
        # whatever the configuration asked for.
        output_dir = output_dir or configured_output_dir

        if filepath is not None and os.path.isdir(filepath):
            # A directory was passed where a file was expected: it names where
            # the file goes, not the file.
            output_dir, filepath = filepath, None

        impl = output.Implementation(section, format_name, opts)
        # 'jpeg' is the format's name but '.jpg' is the file's; the render-only
        # mapping is consulted first so a format whose extension differs from
        # its name keeps it even when no configuration spells 'extension' out.
        default_extension = (
            RENDER_EXTENSION_MAPPING.get(format_name)
            or PART_EXTENSION_MAPPING.get(format_name)
            or SKETCH_EXTENSION_MAPPING.get(format_name, format_name)
        )
        extension = "." + impl.extension(default_extension)
        filepath = self._output_filepath(opts, output_dir, extension, project, filepath)

        pc_logging.debug("Rendering: %s" % filepath)
        return impl, filepath

    async def _materialize_output_script(self, ctx, impl):
        """The on-disk path of the script that writes this file type.

        'output.materialize_script()' is the whole of it: nothing about finding
        an implementation's script depends on the shape it is about to be run
        for, and the simulation runner needs the very same answer for a plugin
        that writes no file at all (see 'partcad.simulation').
        """
        return await output.materialize_script(ctx, impl)

    async def _output_request(self, ctx, obj, impl, kwargs, overlay=None, ports=None):
        """What the implementation is handed.

        The shape, every parameter the layered configuration ended up with, and
        enough about the shape itself for an implementation to adapt to what it
        was given - which is how the SVG renderer knows to look at a sketch
        head-on without PartCAD having to tell it.

        'overlay'/'ports' are the overlay this file type ended up drawing (see
        render_overlay.effective) and where those ports are. They are set after
        'impl.parameters' rather than before, because the resolved overlay is
        what a file type declaring 'with_ports:' asked for plus what the command
        line asked for - the declaration has already been read.
        """
        request = {
            "wrapped": obj,
            "shape_name": self.name,
            "shape_kind": self.kind,
            "shape_type": self.config.get("type"),
            "package_name": self.project_name,
        }
        request.update(impl.parameters)
        if overlay is not None:
            request["with_ports"] = overlay.ports
            request["with_interfaces"] = overlay.interfaces
            request["ports"] = ports or []
        # An explicit argument wins over the configuration, but only when it is
        # one: 'render_async(**kwargs)' is called with a fixed set of keyword
        # arguments defaulting to None by several callers.
        request.update({key: value for key, value in kwargs.items() if value is not None})

        # 'properties: true' is left in the request as it is. What the shapes
        # report about themselves travels on the envelopes, so the index an
        # exporter looks them up in is built in the sandbox, out of the request
        # that arrives there - see wrappers/wrapper_export.py. Nothing has to be
        # collected here, and nothing has to be instantiated to collect it.
        #
        # What each shape's physics *resolves* to is the exception, because
        # resolving it needs what only the core has: a material is a *name*,
        # ':aluminium', and turning it into a density means loading the package
        # that catalogues it; and a mass is that density times the solid, which
        # is the one rule every exporter has to apply the same way. So it is
        # worked out here, once, for every shape in the tree, and travels beside
        # the shapes keyed by the shape it belongs to - stated values, what the
        # material lends, and the mass, centre of mass and inertia derived from
        # them, at the export's own 'density' for a part made of nothing that
        # states one. The wrapper merges it under what each shape said about
        # itself, and the exporter writes what it is handed. See
        # 'partcad.physics.physics_by_shape()'.
        if request.get(output.PROPERTIES_KEY):
            facts = await pc_physics.physics_by_shape_async(ctx, request, pc_physics.export_fallback(request))
            if facts:
                request[pc_physics.FACTS_KEY] = facts
            # The scene's own physics, beside its shapes': the gravity it states
            # and the fluid it is filled with, the latter resolved here for the
            # reason a shape's material is. See 'output.WORLD_KEY' for why only a
            # file type that asked for 'properties' is handed it. A medium that
            # resolves to nothing raises rather than being left out: a model
            # written in a vacuum for a scene that said it was under water is a
            # wrong answer, not a less detailed one.
            world = self.world_facts(ctx)
            if world:
                request[output.WORLD_KEY] = world
        return request

    async def _overlay_ports_async(self, ctx, overlay, cache):
        """Where this shape's ports are, worked out at most once per render call.

        Two file types of one object can ask for different overlays, and what
        the answers differ in is whether the port boundaries came along - so a
        collection that has them also answers a file type that does not - and
        how deep the walk went and which ports were asked for, each of which is
        a different set of ports rather than the same set told differently (see
        'Overlay.key').

        Failing to work it out must not cost the picture: an overlay is an
        annotation on a render, not the render. The failure is reported and the
        file is written without it - and it is *not* remembered, because what
        failed may be only the half this file type asked for. Building a port's
        boundary sketch can fail where locating the port cannot, and a cached
        "nothing" would then take the markers off the next file type too, which
        never asked for a boundary at all.
        """
        _, internals, select = overlay.key()
        if (True, internals, select) in cache:
            return cache[(True, internals, select)]
        if not overlay.interfaces and (False, internals, select) in cache:
            return cache[(False, internals, select)]

        try:
            records = await render_overlay.collect_async(self, ctx, overlay)
        except Exception as e:
            pc_logging.error("%s:%s: failed to locate the ports to draw: %s" % (self.project_name, self.name, e))
            return []
        render_overlay.report(self, records, overlay)
        cache[overlay.key()] = records
        return records

    async def _run_implementation_async(self, ctx, impl, script, request, final_filepath):
        """Run one output implementation in a sandbox and read back its verdict.

        Shared by every file PartCAD produces through a script: the export and
        render formats, and the analyses of 'cae:'. What differs between them is
        what goes into the request and what is made of the answer, both of which
        belong to the caller; what is the same is the sandbox, the meta-wrapper
        and the shape of the reply, and a second copy of those is a second thing
        to keep correct.

        Returns the implementation's result dict, or None when it said nothing
        that could be read - which has already been reported by then.

        Held under 'locked()' throughout: this is the single place a shape's
        output file is produced, whichever section asked for it, so it is the
        single place the rule belongs. Callers that need a wider critical
        section -- 'analyze_async' clears the path first and verifies it
        afterwards, and every caller that asks the cache first puts a cached
        file where this would have written it -- take the same lock around the
        whole of it, which nests because the lock is re-entrant.
        """
        async with self.locked():
            return await self._run_implementation_locked(ctx, impl, script, request, final_filepath)

    async def _run_implementation_locked(self, ctx, impl, script, request, final_filepath):
        """The body of '_run_implementation_async', with the shape held still."""
        return (await self._run_together_locked(ctx, [_Output(impl, script, request, final_filepath)]))[0]

    async def _run_together_locked(self, ctx, outputs):
        """Run the implementations of 'outputs' in one sandbox call, and read back what each said.

        One is the call there has always been, and its answer and its failure
        are what '_run_implementation_async' returns and raises. Several are the
        files of this shape that one sandbox environment writes, as
        '_run_implementations_async' groups them: one interpreter, which imports
        the CAD stack once and decodes the shape once for every file that may
        share it, and runs each implementation as it would have been run alone
        (see 'wrapper_export.py'). Each is answered as soon as it is written, so
        a call that dies has still said what it finished; every file it did not
        answer is written again in a call of its own, which fails, if it fails,
        exactly as it does on its own - so one file's crash costs no other file
        anything but the time.

        Returns one entry per output, in order: its result dict, or None when it
        said nothing that could be read (which has been reported by then); and,
        for several, the exception a file's own call raised where it raised one.
        """
        for output_ in outputs:
            request = output_.request
            impl = output_.impl
            # Whether the file has to come out the same every time it is produced.
            # Set here rather than left to whatever the configuration happened to
            # carry, so that it is in *every* request and an implementation - one
            # PartCAD ships, or one a package published on its own - can read it
            # without first asking whether the key exists. That is the whole of what
            # makes 'reproducible' mean one thing across every implementation there
            # is; see 'output.REPRODUCIBLE_KEY'.
            #
            # What is already in the request wins, because by the time it gets here
            # it is the layered answer: the file type's declaration merged through
            # 'impl.parameters', with an explicit argument from the caller on top of
            # it. 'impl.reproducible' is the fallback for a caller that built its
            # request some other way, and the coercion is the point of reading both
            # through the same function - "false" is a string on the way in from
            # JSON-RPC and would otherwise be true.
            request[output.REPRODUCIBLE_KEY] = (
                output.as_flag(request[output.REPRODUCIBLE_KEY])
                if output.REPRODUCIBLE_KEY in request
                else impl.reproducible
            )
            # Where the implementing package keeps what it fetches for itself (see
            # 'output.package_cache_dir'). Added here, after anything has been keyed
            # on the request, because it is a path on this machine and says nothing
            # about what the file will contain.
            if getattr(impl, "project", None) is not None:
                request.setdefault("cache_dir", output.package_cache_dir(ctx, impl.project))

        together = len(outputs) > 1
        impl = outputs[0].impl
        script = outputs[0].script

        # Where this implementation runs. A container when it declared one --
        # the only sandbox that can carry what pip cannot install -- and the
        # Python sandbox otherwise, which is every implementation that ships
        # with PartCAD and most of those that do not. Several are never a
        # container's (see '_sandbox_of').
        container = impl.container

        # Serialized by the runtime when the process starts, not here: until a
        # process slot is free this is a request waiting its turn, and the tree
        # it carries is held anyway (see 'runtime.stdin_bytes'). In the Python
        # sandbox the reader is 'wrapper_export.py', which is sent a frame with
        # each distinct payload attached once (see 'shape_envelope.serialize');
        # a container runs a program of the implementation's own, handed the
        # request as it has always been written, as JSON. Several files are one
        # document holding every request and the shape once (see
        # '_together_request'), and are never a container's.
        def request_serialized():
            if together:
                return shape_envelope.serialize(_together_request(outputs))
            if container:
                return shape_envelope.dumps(outputs[0].request)
            return shape_envelope.serialize(outputs[0].request)

        script_path = wrapper.get("export.py")
        config_dirs = [os.path.abspath(output_.impl.project.config_dir) for output_ in outputs]
        input_dirs = []
        session = None

        if container:
            # Raises SandboxUnavailable when there is no container runtime.
            # A failure like any other, and the type is what earns the reader
            # both remedies rather than one (see 'partcad.test.cae').
            runtime = await ctx.get_container_runtime(container)
            # The wrapper and the implementing package both go in whole. Sending
            # only the files the command names would leave both unable to start:
            # the wrapper imports its siblings, and so does the implementation
            # script (see runtime.pack_directory).
            input_dirs = [os.path.dirname(script_path), config_dirs[0]]
        else:
            runtime = ctx.get_python_runtime(version=impl.python_version(), image=impl.docker_image)
            # What the implementations need beyond the sandbox's own environment
            # goes into a layer over it, never into that environment: wrappers
            # are reading it (see 'runtime_python.base_requirements').
            session = await self._output_session_async(runtime, outputs)

        with telemetry.start_as_current_span("*Shape.render_async.{runtime.run_async}"):
            # The meta-wrapper, and for each file what to write, where to run,
            # and what to run. The implementation script is an argument and not
            # part of the request because a container rewrites arguments naming a
            # directory it was sent and cannot rewrite the request, which reaches
            # it as one opaque string on standard input -- see wrapper_export.py.
            # The 'remote' sandbox works out which directories to send from the
            # same arguments, so every file's are there.
            command = [script_path]
            for output_, config_dir in zip(outputs, config_dirs):
                command += [output_.path, config_dir, os.path.abspath(output_.script)]
            if container:
                # The interpreter is named rather than pathed: the container's
                # allowlist maps the name to the executable, which is what keeps
                # a caller from naming one (see PC_CONTAINER_ALLOWED_COMMANDS in
                # tools/containers/_common/pc-container-json-rpc.py).
                command.insert(0, container.get("command") or "python")
            # Only the container runtime is handed these. 'PythonRuntime' and
            # 'JavaScriptRuntime' both override 'run_async' with a narrower
            # signature -- (cmd, stdin, cwd, session, timeout) -- so the base
            # class's parameters are not a contract they honour, and passing
            # one down that path is a TypeError rather than an ignored argument.
            # What a command writes is not in the command, so a sandbox that
            # exchanges files rather than sharing them has to be told. The
            # container path knows its input directories too; the 'remote'
            # sandbox works those out from the command itself, and only the
            # output is beyond inference.
            written = [output_.path for output_ in outputs]
            if container:
                extra = {"input_dirs": input_dirs, "output_files": written}
            elif getattr(runtime, "EXCHANGES_FILES", False):
                extra = {"output_files": written, "session": session}
            else:
                extra = {"session": session}
            exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized, **extra)
            if exitcode != 0 and len(errors) == 0:
                errors = command_failure(command, exitcode)
            if errors and not together:
                errors = errors.rstrip() + sandbox_note(ctx, impl)
                pc_logging.error(errors)
                raise Exception(errors)

        if together:
            return await self._together_outcomes_async(ctx, outputs, response_serialized, errors)

        # Text or the bytes of a frame (see 'process_output.answer'); either way
        # what is in front of the answer is 'deserialize()''s to skip.
        if not response_serialized or not response_serialized.strip():
            self.error("Empty response from the '%s' implementation: %s" % (impl.format_name, script))
            return [None]

        try:
            return [shape_envelope.deserialize(response_serialized)]
        except Exception as e:
            self.error("Failed to deserialize response: %s" % e)
            return [None]

    async def _together_outcomes_async(self, ctx, outputs, response_serialized, errors):
        """What each of several files written in one call came to: its answer, or a call of its own.

        A file the call did not answer is written again on its own - the call
        died before it got there, or something failed before its implementation
        was reached - and what that call answers or raises is its outcome, the
        message included, as though it had never been one of several.
        """
        answers = _together_answers(response_serialized, len(outputs))
        unanswered = [output_ for index, output_ in enumerate(outputs) if index not in answers]
        if unanswered:
            names = ", ".join(output_.impl.format_name for output_ in unanswered)
            if errors:
                pc_logging.warning(
                    "%s:%s: the sandbox writing %d files at once stopped before it wrote %s (%s); "
                    "writing %s again, each on its own"
                    % (
                        self.project_name,
                        self.name,
                        len(outputs),
                        names,
                        errors.strip().splitlines()[-1] if errors.strip() else "no reason given",
                        "it" if len(unanswered) == 1 else "them",
                    )
                )
            else:
                pc_logging.debug(
                    "%s:%s: not answered by the call writing %d files at once, written again on its own: %s"
                    % (self.project_name, self.name, len(outputs), names)
                )
        outcomes = []
        for index, output_ in enumerate(outputs):
            if index in answers:
                outcomes.append(answers[index])
                continue
            try:
                outcomes.append(
                    await self._run_implementation_async(
                        ctx, output_.impl, output_.script, output_.request, output_.path
                    )
                )
            except Exception as e:  # pylint: disable=broad-except
                outcomes.append(e)
        return outcomes

    async def _output_session_async(self, runtime, outputs):
        """The session the implementations of 'outputs' run with: what they need beyond the sandbox's own environment.

        A session names the layer a run happens in (see
        'runtime_python.PythonRuntime.get_session'), and the layer is what the
        requirements the base does not hold make it - so the files a call writes
        together are files whose sessions name one layer, and the session the
        call runs with asks for all of their requirements.

        One implementation's requirements are asked for in the order its package
        declared them, which is part of what it declared. Several are asked for
        in the order 'sandbox_versions.install_order' works out for all of them,
        the packages' own included: their lists are each in an order that keeps
        every one of them installed and their union is not, which matters where
        a sandbox keeps one environment and installs what it is asked, in the
        order asked (the 'remote' one).
        """
        names = ", ".join("%s:%s" % (output_.impl.section, output_.impl.format_name) for output_ in outputs)
        session = runtime.get_session(names)
        projects = []
        for output_ in outputs:
            if all(output_.impl.project is not project for project in projects):
                projects.append(output_.impl.project)
        for project in projects:
            await runtime.prepare_for_package(project, session=session)
        if len(outputs) == 1:
            requirements = outputs[0].impl.python_requirements
        else:
            from .runtime_python import package_requirements

            requirements = sandbox_versions.install_order(
                [dep for project in projects for dep in package_requirements(project)]
                + [dep for output_ in outputs for dep in output_.impl.python_requirements]
            )
        # Asked one at a time, not with asyncio.gather(): the order is part of
        # the answer.
        for dep in requirements:
            await runtime.ensure_async(dep, session=session)
        return session

    async def _layer_of_async(self, ctx, output_):
        """Which environment an implementation runs in once its requirements are counted: a layer, or the base.

        '_sandbox_of' tells sandboxes apart by what is declared of them; within
        one, what a file type requires beyond the sandbox's own environment
        puts it in a layer of its own (the 3MF exporter, which imports
        CadQuery, in the one CadQuery parts run in; the raster projections in
        one carrying what rasterizes an SVG). Files are written together only
        with the files of their own layer, so each runs where it would have run
        alone.
        """
        impl = output_.impl
        runtime = ctx.get_python_runtime(version=impl.python_version(), image=impl.docker_image)
        session = await self._output_session_async(runtime, [output_])
        return session.get("path") if session and session.get("dirty") else None

    async def _run_implementations_async(self, ctx, outputs):
        """'_run_implementation_async' for several files of this shape, in as few sandbox calls as can be.

        The ones that run in one environment - one sandbox ('_sandbox_of'), and
        one layer of it ('_layer_of_async') - run in one call
        ('_run_together_locked'), and one with an environment of its own - a
        container's, say - runs alone, through '_run_implementation_async'
        exactly as a file asked for by itself does. One after another, under
        the shape's lock: the files of one shape never ran at once, and a call
        is one process slot whatever it writes.

        Returns, for each output, its result, None, or the exception its run
        raised: one file failing stops no other.
        """
        outcomes = [None] * len(outputs)
        sandboxes = {}
        for index, output_ in enumerate(outputs):
            sandboxes.setdefault(_sandbox_of(output_.impl) or ("alone", index), []).append(index)
        environments = {}
        for key, indices in sandboxes.items():
            for index in indices:
                layer = None
                if len(indices) > 1:
                    try:
                        layer = await self._layer_of_async(ctx, outputs[index])
                    except Exception:  # pylint: disable=broad-except
                        # Whatever stopped it is said by its own run, alone.
                        layer = ("alone", index)
                environments.setdefault((key, layer), []).append(index)
        async with self.locked():
            for indices in environments.values():
                if len(indices) > 1:
                    try:
                        answers = await self._run_together_locked(ctx, [outputs[index] for index in indices])
                    except Exception as e:  # pylint: disable=broad-except
                        # Before anything ran - an install, a sandbox that is
                        # not there - and so the same for every one of them.
                        answers = [e] * len(indices)
                    for index, answer in zip(indices, answers):
                        outcomes[index] = answer
                    continue
                output_ = outputs[indices[0]]
                try:
                    outcomes[indices[0]] = await self._run_implementation_async(
                        ctx, output_.impl, output_.script, output_.request, output_.path
                    )
                except Exception as e:  # pylint: disable=broad-except
                    outcomes[indices[0]] = e
        return outcomes

    async def _output_run_async(self, ctx, impl, script, request, final_filepath, view=None, section=None, batch=None):
        """'_run_implementation_async' for an export or a render file, asked of the cache first.

        The same file asked for again is a read, exactly as an analysis and a
        route are (see 'partcad.cache_artifacts'): the file goes back where this
        call would have written it, with whatever else the implementation wrote
        beside it named after it, and the result - its warnings, what the
        format could not state - comes with it, so a hit says what a run would
        have said.

        The question is '_artifact_hash()''s. The file's name is not in it: an
        answer is stored with the names of its files as suffixes of the path it
        was asked for, and put back under whatever path is asked for next
        ('cache_artifacts.placed_files') - or dismissed, and produced again,
        when the next path leaves nothing to name them by. A filtered view (see
        'partcad.assembly_filter') adds its filter: a view has no key of its
        own, so it is keyed as the assembly it is a view of and the links it
        keeps - which is everything it is. A cross-section (see
        'partcad.shape_section') adds its box the same way, and for the same
        reason: the request's geometry is left out of the key, and the cut is the
        one thing about that geometry the shape's own key does not say.

        And the tree the file is made of adds what it says about its shapes
        ('shape_envelope.description()'): the geometry is the shape's key, but
        what a renderer paints it with is not - 'properties' is no part of a
        shape's key, so a part painted another colour kept its key, and was
        handed the picture of it in the old colour. Analyses and routes are not
        asked this: what they read of a shape's properties is in their request
        (see '_output_request'), and their answers keep the keys they have.

        An answer is stored only when the implementation said what it wrote
        (see 'output.FILES_KEY') and the file at 'final_filepath' is the one
        this run wrote. Nothing clears that path before the run - a failed
        render leaves the last good picture where it was, as it always has -
        so what is there afterwards proves nothing until it is compared with
        what was there before.

        'batch' is the '_OutputBatch' this file is written with, when it was
        asked for together with other file types of this shape: it is then
        handed in, written with them, and answered from there.
        """
        cache = getattr(ctx, "cache_artifacts", None)
        extra = {"tree": shape_envelope.description(request.get("wrapped"))}
        if view is not None:
            extra["view"] = view.key()
        if section is not None:
            extra["section"] = section
        artifact = await self._artifact_hash(
            impl.section,
            impl.format_name,
            impl,
            script,
            request,
            "%s:%s" % (impl.project.name, impl.format_name),
            extra,
        )

        output_ = _Output(impl, script, request, final_filepath, artifact)
        if batch is not None:
            return await batch.submit(cache, output_)
        (outcome,) = await self._outputs_run_async(ctx, [output_], cache)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def _outputs_run_async(self, ctx, outputs, cache):
        """'_output_run_async' for several files of this shape at once: what each came to.

        Each is still a question of its own: asked of the cache under its own
        key, and its answer stored under it. Only the ones the cache does not
        hold are written, and those together ('_run_implementations_async'),
        so a file type cached already is put back and not drawn again, and the
        call that draws the rest pays for its interpreter, the CAD stack and
        decoding the shape once.

        Two that write one path are not written in one call. Nothing clears a
        path, so the file left there is whichever was written last, and the
        first one's run, compared with what was there before it, would look as
        though it had written the second one's file - and be remembered so. So
        they go in rounds ('_rounds'), each written and stored before the next.

        Returns, for each output, its result, None, or the exception its run
        raised.
        """
        outcomes = [None] * len(outputs)
        # Held across the read, the run and the write, for the reason
        # 'analyze_async' holds it: the path is derived from the shape, so two
        # renders of one shape name one file. Re-entrant, so the lock
        # '_run_implementation_async' takes inside is passed straight through.
        async with self.locked():
            for indices in _rounds(outputs):
                missing = []
                for index in indices:
                    output_ = outputs[index]
                    result = await cache_artifacts.restore_files_async(cache, output_.artifact, output_.path)
                    if result is not None:
                        outcomes[index] = result
                        continue
                    output_.before = _file_identity(output_.path)
                    missing.append(index)
                if not missing:
                    continue
                answers = await self._run_implementations_async(ctx, [outputs[index] for index in missing])
                for index, result in zip(missing, answers):
                    outcomes[index] = result
                    output_ = outputs[index]
                    if output_.artifact is None or not isinstance(result, dict) or not result.get("success", False):
                        # Only an answer is remembered (see 'partcad.cache_artifacts').
                        continue
                    written = self._written_besides(output_.impl, result, output_.path, output_.before)
                    if written is not None:
                        await cache_artifacts.store_files_async(cache, output_.artifact, result, output_.path, written)
        return outcomes

    def _written_besides(self, impl, result, final_filepath, before) -> Optional[list]:
        """What else one run wrote, as the implementation named it, or None if it cannot be said.

        None is "do not remember this answer": the implementation did not say
        what it wrote, or the file at 'final_filepath' is the one that was
        there before the run. Whether what it named can be put back is
        'cache_artifacts.files_layout''s to decide.
        """
        listed = result.get(output.FILES_KEY)
        if not isinstance(listed, list):
            pc_logging.debug(
                "%s:%s: the '%s' implementation does not say what it wrote (%s), so it is not cached"
                % (self.project_name, self.name, impl.format_name, output.FILES_KEY)
            )
            return None
        after = _file_identity(final_filepath)
        if after is None or after == before:
            return None
        return [str(name) for name in listed]

    async def filtered_view_async(self, mask):
        """This shape with only the links a filter keeps, or this shape.

        A hook rather than a branch, because only an assembly has links: a part,
        a sketch and an interface are one shape, and a filter over one of them
        selects from nothing. That is reported rather than ignored - somebody
        asked for part of an object that has no parts - and the whole shape is
        written, which is the picture they would have got anyway.

        'partcad.assembly_filter' is the override (see 'Assembly').
        """
        pc_logging.error(
            "%s:%s: a filter selects the links of an assembly or a scene, and a %s has none; "
            "the whole of it is written" % (self.project_name, self.name, self.kind)
        )
        return self

    async def _output_subject_async(self, ctx, obj, mask, views):
        """The shape one output file is of, and its tree.

        Itself and the tree the caller already built, unless a filter applies -
        and then a view of it (see 'partcad.assembly_filter'), whose tree is
        built here. Kept per filter for the length of one 'render_async' call:
        one object may be written to several file types and a 'filter:' is
        declared per file type, so two of them asking for the same subset build
        it once.
        """
        if mask is None or mask.keeps_all:
            return self, obj, {}
        key = mask.key()
        if key not in views:
            view = await self.filtered_view_async(mask)
            tree = obj if view is self else await view.get_wrapped(ctx)
            # A ports cache of its own: a view's ports are not the whole
            # object's, and the two would otherwise answer for each other.
            views[key] = (view, tree, {})
        return views[key]

    async def _render_one_async(
        self,
        ctx,
        obj,
        format_name,
        project,
        filepath,
        options_project,
        output_dir,
        kwargs,
        overlay=None,
        ports_cache=None,
        link_filter=None,
        views=None,
        defaults_only=False,
        section=None,
        batch=None,
    ):
        """Produce one output file, whatever its type.

        Returns what the implementation answered - its result, with whatever it
        reports about the file beside 'success' - or None when there is none to
        return: a filter that could not be read, an answer that could not be.

        'batch' is the '_OutputBatch' it is written with, if it is one of
        several file types of this shape asked for together.
        """
        impl, final_filepath = self.output_getopts(
            ctx, format_name, project, filepath, options_project, output_dir, defaults_only=defaults_only
        )
        # What the file type is called from here on. The caller may have named
        # it by its full path ('sim-mujoco:mjcf'), which said where to resolve it
        # and has no business in a log line about the file.
        format_name = impl.format_name
        final_filepath = os.path.abspath(final_filepath)
        # Create the output directory for the resolved path (the incoming
        # 'filepath' is None when called from Project.render_async) using the
        # 'ctx' passed in, so direct callers without a project get one too.
        # Everything the path asks for is made, the sub-directories a '/' in the
        # object's name asks for included.
        ctx.ensure_dirs_for_file(final_filepath)
        pc_logging.debug("Rendering: %s:%s for format '%s'" % (self.project_name, self.name, format_name))

        script = await self._materialize_output_script(ctx, impl)

        # What this file is of. The run's own '--filter' wins over the one the
        # file type declares, the way '--view' wins over a configured viewport:
        # a declaration is permanent and a command line is about this picture.
        try:
            mask = link_filter if link_filter is not None else impl.link_filter
        except ValueError as e:
            self.error("%s: %s" % (format_name, e))
            return None
        subject, obj, subject_ports = await self._output_subject_async(
            ctx, obj, mask, views if views is not None else {}
        )
        # Cut after the filter: a section is a box through what is kept, and the
        # links a filter drops have nothing left to cut. The ports drawn on top
        # are found on the subject itself, uncut - a port is where it is whether
        # or not the solid around it is drawn.
        if section is not None:
            obj = await shape_section.section_async(ctx, obj, section, cacheable=self.artifacts_cacheable())

        effective_overlay = render_overlay.effective(overlay, impl)
        ports = None
        if effective_overlay is not None:
            ports = await subject._overlay_ports_async(
                ctx,
                effective_overlay,
                subject_ports if subject is not self else (ports_cache if ports_cache is not None else {}),
            )

        try:
            request = await subject._output_request(ctx, obj, impl, kwargs, overlay=effective_overlay, ports=ports)
        except scene_world.WorldError as e:
            # What a scene states about its world, stated wrongly: a gravity that
            # is not a vector, a medium nothing answers to. The declaration's
            # mistake rather than the implementation's, reported the way a bad
            # filter is above and with nothing written. Raised again, unlike the
            # filter: a caller that converts a scene in place reads back the file
            # it asked for, and one a previous run left there must not pass for
            # this run's.
            self.error("%s: %s" % (format_name, e))
            raise
        result = await self._output_run_async(
            ctx,
            impl,
            script,
            request,
            final_filepath,
            view=mask if subject is not self else None,
            section=section,
            batch=batch,
        )
        if result is None:
            return None

        if not result.get("success", False):
            self.error(
                "Render %s failed for %s:%s: %s%s"
                % (
                    format_name.upper(),
                    self.project_name,
                    self.name,
                    result.get("exception", "Unknown error"),
                    sandbox_note(ctx, impl),
                )
            )
        if result.get("exception"):
            pc_logging.exception("Render %s exception: %s" % (format_name.upper(), result["exception"]))

        # An implementation may report what it could not represent in the target
        # format without that being a failure (URDF, for one, cannot hold
        # everything a PartCAD assembly knows).
        for warning in result.get("warnings") or []:
            pc_logging.warning("%s:%s: %s" % (self.project_name, self.name, warning))

        # Properties PartCAD holds that the target format has no way to state.
        # Not a warning - the file is correct, it just says less than the package
        # does - but not silent either.
        unsupported = result.get("unsupported") or []
        if unsupported:
            pc_logging.info(
                "%s:%s: %s cannot state these properties, so they are not in the exported file: %s"
                % (self.project_name, self.name, format_name.upper(), ", ".join(unsupported))
            )
        return result

    async def render_async(
        self,
        ctx: Context,
        format_name: str,
        project: Optional[Project] = None,
        filepath=None,
        options_package: Optional[str] = None,
        options_project: Optional[Project] = None,
        output_dir=None,
        overlay=None,
        link_filter=None,
        defaults_only: bool = False,
        section=None,
        **kwargs,
    ) -> dict:
        """Write this shape out as one output file type, several, or all of them.

        Args:
            ctx: Execution context.
            format_name: The file type (e.g. "step", "svg", "png"), or a list of
                them. None produces every type that has a built-in
                implementation.
            project: The package the shape belongs to, whose 'export:' and
                'render:' sections configure the output.
            filepath: The file to write. None resolves it from the
                configuration and the object's name.
            options_package: A package to read the export/render options from
                in addition to 'project', which is how a custom implementation
                declared in one package is used from another.
            options_project: The same, as the package itself rather than its
                name, for a caller that already resolved it. Spelling a package
                one is holding and looking it up again is a round trip with one
                outcome that is not the package - so a caller with it in hand
                (`partcad.simulation`, which resolved the plugin to reach its
                'format:') hands it over instead.
            output_dir: Where the file goes when 'filepath' does not say,
                overriding whatever the configuration asked for.
            overlay: A 'render_overlay.Overlay' asking for this shape's ports
                and/or interfaces to be drawn on the projection ("pc render
                --with-ports"/"--with-interfaces"), or None. A file type that
                declares 'with_ports:'/'with_interfaces:' of its own draws them
                either way - see 'render_overlay.effective'.
            section: A cross-section to cut the shape to before it is written,
                as a box in the frame of its root ('shape_section.normalize'),
                or None for the whole shape. What the IDE's 2D and Draft tabs
                send when their section sliders are moved.
            kwargs: Export parameters, overriding what the configuration says.

        Several file types - a list, or None - are written together: each is
        worked out, logged and reported as it is when asked for alone, a list
        each under an action of its own, and what the cache does not hold is
        written by one sandbox call per environment rather than one per file
        (see '_OutputBatch'). That is 'Project.render_async()', which asks for
        every file type of a shape at once.

        Returns:
            What each file type's implementation answered, by the name the type
            was asked for under: the result it reported - 'success', the
            warnings, and whatever else it says about the file, such as the
            viewpoint a projection was drawn from - or None where there is none.
            In the order they were asked for, however they were written. Empty
            when there was nothing to write.
        """
        # A caller that names no package still gets the shape's own. Its
        # 'export:'/'render:' sections are where a package declares its file
        # types, so resolving it here is what makes a package-defined
        # implementation work through this method and not only through
        # 'Project.render_async()', which always passes the package in.
        if project is None:
            project = ctx.get_project(self.project_name)

        if options_project is None and options_package:
            options_project = ctx.get_project(options_package)
            if options_project is None:
                pc_logging.error("The options package is not found: %s" % options_package)
                return

        # Refused before anything is built, as a bad filter is.
        section = shape_section.normalize(section)
        results = {}

        # Shared by every file type this call writes, so that an object
        # whose ports are asked for in three formats is walked once - and,
        # where a 'filter:' applies, so that two file types asking for the
        # same subset of it build that subset once.
        ports_cache = {}
        views = {}

        def render_one(obj, fmt, batch=None):
            return self._render_one_async(
                ctx,
                obj,
                fmt,
                project,
                filepath,
                options_project,
                output_dir,
                kwargs,
                overlay=overlay,
                ports_cache=ports_cache,
                link_filter=link_filter,
                views=views,
                defaults_only=defaults_only,
                section=section,
                batch=batch,
            )

        if isinstance(format_name, (list, tuple)):
            # Each under the action it has when it is asked for alone, the first
            # building - or finding built - the shape it is of, and every one
            # handed that same tree: a batch sends a subject once only where its
            # requests hold the same object ('_together_request'), and a shape
            # the memory tier does not keep answers 'get_wrapped' with a new tree
            # each time - N copies in one request, and no decoding shared. The
            # members are worked out one at a time ('_OutputBatch.member').
            formats = list(format_name)
            batch = self._output_batch(ctx, len(formats))
            fetched = []

            async def each(fmt):
                with pc_logging.Action(_render_action(self.project_name, fmt), self.project_name, self.name):
                    async with batch.member() if batch is not None else contextlib.nullcontext():
                        if not fetched:
                            fetched.append(await self.get_wrapped(ctx))
                        obj = fetched[0]
                        if obj is None:
                            pc_logging.error(f"Cannot render '{self.name}': shape is empty")
                            return
                        results[fmt] = await render_one(obj, fmt, batch)

            await _together(batch, each, formats)
            return _in_order(results, formats)

        with pc_logging.Action(_render_action(self.project_name, format_name), self.project_name, self.name):
            obj = await self.get_wrapped(ctx)
            if obj is None:
                pc_logging.error(f"Cannot render '{self.name}': shape is empty")
                return results

            if format_name:
                results[format_name] = await render_one(obj, format_name)
                return results

            formats = output.all_formats(ctx)
            batch = self._output_batch(ctx, len(formats))

            async def each(fmt):
                async with batch.member() if batch is not None else contextlib.nullcontext():
                    results[fmt] = await render_one(obj, fmt, batch)

            await _together(batch, each, formats)
        return _in_order(results, formats)

    def _output_batch(self, ctx, size):
        """The '_OutputBatch' to write 'size' file types of this shape with, or None to write each on its own.

        None for fewer than two, and for a caller that holds this shape's lock
        already: the file types of a batch are worked out in tasks of their own,
        and a task would wait for that lock for as long as its holder waited for
        the task.
        """
        if size < 2 or _held_by_current_task(self):
            return None
        return _OutputBatch(self, ctx, size)

    def render(
        self,
        ctx: Context,
        format_name: str,
        project: Optional[Project] = None,
        filepath=None,
        options_package: Optional[str] = None,
        options_project: Optional[Project] = None,
        output_dir=None,
        overlay=None,
        link_filter=None,
        **kwargs,
    ) -> None:
        # By keyword, every one of them. 'render_async' grew an
        # 'options_project' parameter between 'options_package' and
        # 'output_dir', and a positional forwarding here handed 'output_dir' to
        # it and 'overlay' to 'output_dir' - so a caller that named
        # 'output_dir=' got a string where '_output_getopts' reads
        # '.config_obj' off a package. Nothing in the signature above can drift
        # away from the one below while the names are what is passed.
        asyncio.run(
            self.render_async(
                ctx,
                format_name,
                project=project,
                filepath=filepath,
                options_package=options_package,
                options_project=options_project,
                output_dir=output_dir,
                overlay=overlay,
                link_filter=link_filter,
                **kwargs,
            )
        )

    # ------------------------------------------------------------------ #
    #
    # Computer-aided engineering: the third thing a script produces from a
    # shape, beside a file another tool opens ('export:') and a picture of it
    # ('render:'). It runs through exactly the same machinery - a file type
    # declared in a section, an implementation named by 'path' and 'package',
    # the same sandbox and the same meta-wrapper - and differs in two places
    # only. What goes in carries the boundary conditions of one of the part's
    # scenarios ('fea: <name>:', see 'partcad.cae'), and what comes back
    # carries findings beside the file.

    def analysis_getopts(
        self,
        ctx,
        analysis: str,
        format_name: str,
        project=None,
        filepath=None,
        options_project=None,
        output_dir=None,
        scenario=None,
    ):
        """Resolve one analysis: its implementation, options and output path.

        The counterpart of 'output_getopts' for the 'cae:' section, and different
        from it in two ways that both follow from an analysis not being a file
        type of the object:

        * The file is named after the analysis and the scenario as well as the
          object, because a part has as many results as it has scenarios of
          each analysis: 'bracket.fea.loaded.vtu' ('cae.model_suffix'; the
          unnamed form a section had before scenarios keeps 'bracket.fea.vtu').
        * There is no default extension to fall back on. Which model format an
          analysis writes is the implementation's decision - a 3D field, a 2D
          plot - so the implementation has to state it, and an implementation
          that does not is a bug in that package rather than something to guess
          at on its behalf.
        """
        opts, configured_output_dir = self._output_getopts(ctx, format_name, output.CAE, project, options_project)
        output_dir = output_dir or configured_output_dir

        if filepath is not None and os.path.isdir(filepath):
            # A directory was passed where a file was expected: it names where
            # the file goes, not the file.
            output_dir, filepath = filepath, None

        # With the implementing package, which the export path fills in later
        # (in '_materialize_output_script') because that is the first moment it
        # needs one. Here it is known already -- the caller resolved it to get
        # 'options_project' -- and something asks earlier: 'pc test' reads
        # 'container'/'dockerImage' off this to tell a machine that cannot run
        # the implementation from an implementation that does not work. Without
        # a project those read as "declared nothing", which is the same answer a
        # package that really declares nothing gives.
        impl = output.Implementation(output.CAE, format_name, opts, project=options_project)
        extension = impl.extension(None)
        if not extension:
            raise Exception(
                "The '%s' implementation does not say what file it writes: it needs an 'extension:'" % format_name
            )
        filepath = self._output_filepath(
            opts, output_dir, "." + extension, project, filepath, stem_suffix=pc_cae.model_suffix(analysis, scenario)
        )
        return impl, filepath

    def cam_getopts(
        self,
        ctx,
        format_name: str,
        project=None,
        filepath=None,
        options_project=None,
        output_dir=None,
    ):
        """Resolve one route: its implementation, options and output path.

        The counterpart of 'analysis_getopts' for the 'cam:' section, and the
        same shape as it but for the file's name. An analysis writes
        'bracket.fea.vtu' because a part has as many results as it has analyses;
        a route writes 'bracket.nc', with no infix, because the extension
        already says what the file is and an object has one route at a time. Two
        file types that both routed the same object would collide -- and they
        cannot, because which one produces the route is a single answer resolved
        before this is called.

        There is no default extension to fall back on, for the reason the
        analysis path has none: what a controller reads is the implementation's
        decision, and an implementation that does not say is a bug in that
        package rather than something to guess at on its behalf.
        """
        opts, configured_output_dir = self._output_getopts(ctx, format_name, output.CAM, project, options_project)
        output_dir = output_dir or configured_output_dir

        if filepath is not None and os.path.isdir(filepath):
            # A directory was passed where a file was expected: it names where
            # the file goes, not the file.
            output_dir, filepath = filepath, None

        # With the implementing package, for the reason 'analysis_getopts' fills
        # it in: something asks about the implementation before it is run, and a
        # missing project answers "declared nothing" rather than failing.
        impl = output.Implementation(output.CAM, format_name, opts, project=options_project)
        extension = impl.extension(None)
        if not extension:
            raise Exception(
                "The '%s' implementation does not say what file it writes: it needs an 'extension:'" % format_name
            )
        filepath = self._output_filepath(opts, output_dir, "." + extension, project, filepath)
        return impl, filepath

    def _route_implementation(self, ctx, implementation=None, declared=None):
        """Who produces this route: the package and the file type in it.

        The very precedence '_analysis_implementation' documents, over the one
        thing that differs: the bottom of it is 'camImplementation', and unlike
        the CAE defaults that one names a package PartCAD ships. So the chain is

        * 'implementation' -- this run's answer, from 'pc cam -i'.
        * 'declared' -- the object's own, from 'implementation:' in its 'cam:'
          section. A statement about the object: the post-processor its numbers
          were written for.
        * the user configuration ('camImplementation'), which is what makes
          'pc cam' work in a package that says nothing about machines.

        A relative package name is resolved against whoever said it, which is
        why the two are handed over separately rather than picked between here.
        """
        own = False
        if not implementation:
            if declared:
                implementation, own = declared, True
            else:
                # The *context's* configuration, not the process-wide singleton:
                # a daemon builds its context from the caller's configuration,
                # and reading the singleton here would route under the daemon's
                # default. The same reason '_analysis_implementation' gives.
                implementation = ctx.user_config.cam_implementation
        implementation = str(implementation).strip()
        if not implementation:
            raise Exception("No 'cam' implementation is configured")

        package, separator, format_name = implementation.rpartition(":")
        if not separator:
            # A package on its own: the file type is 'gcode', which is what the
            # built-in package calls its only one and what a package publishing
            # one route implementation is most likely to call its own.
            package, format_name = implementation, "gcode"
        format_name = format_name or "gcode"
        package = self._resolve_implementing_package(ctx, package, own)

        options_project = ctx.get_project(package)
        if options_project is None:
            raise Exception(
                "The package implementing 'cam' is not found: %s. "
                "Add it to this package's 'dependencies:', or name another one." % package
            )
        if getattr(options_project, "broken", False):
            # A package that failed to load answers every question about itself
            # with nothing, so without this the next thing to go wrong is
            # 'cam_getopts' reporting that the implementation declared no
            # 'extension:' -- which sends the reader to look at a file that was
            # never read.
            raise Exception(
                "The package implementing 'cam' did not load: %s. "
                "The reason is reported above; a dependency that could not be fetched is the usual one."
                % options_project.name
            )
        return options_project, format_name

    def _resolve_implementing_package(self, ctx, package: str, own: bool) -> str:
        """Make a package name absolute, from the point of view of whoever said it.

        'own' is what separates a name this object declared from one a user
        typed. A user's is resolved against the current package, like every
        other name a command line carries; this object's is resolved against the
        package the object is in, because that is the package whose
        'dependencies:' the name was written against.
        """
        if not own or not self.project_name:
            return ctx.resolve_package_path(package or ".")
        if not package or package == ".":
            # The object's own package implements it, which is what a package
            # shipping a solver alongside the parts it analyses would write.
            return self.project_name
        if package.startswith("/"):
            # Already absolute; hand it over for the '/' -> '//' deprecation.
            return ctx.resolve_package_path(package)
        # The root package is named '//', so it already ends in the separator
        # and joining on another one produces '///name'. That does still
        # resolve -- 'get_project()' strips a fixed two characters and the
        # extra one lands in the part it splits -- but it is not the spelling
        # anything else uses, and a path built here is a path that can end up
        # in a message. Build the canonical one.
        base = self.project_name.rstrip("/")
        return ctx.resolve_package_path((base + "/" if base else "//") + package)

    def _analysis_implementation(
        self,
        ctx,
        analysis: str,
        implementation: Optional[str] = None,
        declared: Optional[str] = None,
    ):
        """Who runs this analysis: the package and the file type in it.

        An implementation is named as '<package>:<file type>' - the same spelling
        every other PartCAD object uses - and can be said in three places, which
        is why the precedence lives here rather than in each caller:

        * 'implementation' is this *run's* answer: 'pc cae fea -i', the IDE's
          field. It wins, because it is the most specific thing anybody said.
        * 'declared' is the object's own, from 'implementation:' in its analysis
          section - a statement about the part, naming the solver its numbers
          were produced with.
        * failing both, the user configuration option named after the analysis
          ('caeFeaImplementation', 'caeCfdImplementation', ...), which is what makes
          'pc cae fea :bracket' work in a package that says nothing about
          solvers.

        A **relative** package name is resolved against whoever said it, and the
        three do not agree about who that is. 'pc cae fea -i calculix:fea' means
        the 'calculix' beside the user, so it resolves against the current
        package the way every other name a user types does. 'implementation:' in
        a package's own YAML means the 'calculix' that package imported, and has
        to resolve against *that* package -- otherwise the same declaration
        resolves differently depending on which directory the command was run
        from, and 'pc test -r' over a tree of packages (which runs with the tree
        root current, not each package) cannot resolve any of them.

        The file type need not be called after the analysis. What decides the
        analysis is the command that was run, because that is what says which
        section of the part holds the boundary conditions; the file type only
        says which declaration in the implementing package to read.
        """
        # 'declared' is the only one of the three that belongs to the object.
        own = False
        if not implementation:
            if declared:
                implementation, own = declared, True
            else:
                # The *context's* configuration, not the process-wide singleton.
                # A daemon builds its context from the caller's configuration
                # (see 'operations.context_create'), and its own is whatever the
                # environment held when something first started it. Reading the
                # singleton here would run the analysis under the daemon's
                # default while 'cae.defaults' -- which the IDE pre-fills its
                # field from -- reported the caller's.
                implementation = ctx.user_config.cae_implementation(analysis)
        implementation = str(implementation).strip()
        if not implementation:
            raise Exception("No '%s' implementation is configured" % analysis)

        package, separator, format_name = implementation.rpartition(":")
        if not separator:
            # A package on its own: the file type is the analysis's own name,
            # which is what a package publishing one implementation calls it.
            package, format_name = implementation, analysis
        format_name = format_name or analysis
        package = self._resolve_implementing_package(ctx, package, own)

        options_project = ctx.get_project(package)
        if options_project is None:
            raise Exception(
                "The package implementing '%s' is not found: %s. "
                "Add it to this package's 'dependencies:', or name another one." % (analysis, package)
            )
        if getattr(options_project, "broken", False):
            # A package that failed to load answers every question about itself
            # with nothing, so without this the next thing to go wrong is
            # 'analysis_getopts' reporting that the implementation declared no
            # 'extension:' -- which sends the reader to look at a file that was
            # never read. Whatever went wrong is already in the log above; what
            # is worth saying here is which package it was and that this is why
            # the analysis is not running.
            raise Exception(
                "The package implementing '%s' did not load: %s. "
                "The reason is reported above; a dependency that could not be fetched is the usual one."
                % (analysis, options_project.name)
            )
        return options_project, format_name

    async def _analysis_boundary_async(self, ctx, config):
        """Where the boundary conditions this analysis was given actually are.

        The part names interfaces; a solver needs coordinate frames. The lookup
        is the very one 'pc render --with-ports --with-internals' does, so a user
        who cannot work out why a fixture did nothing can draw the same ports on
        a projection and look at them. All the way down rather than to the first
        boundary: a load is carried by a face of something, and on an assembly
        that something is one of the parts inside it.

        With the interfaces as well as the ports, which is what puts each port's
        sketch on its record: the circle of a bore, the outline of a pad. A
        frame says where a condition lands and the sketch says on how much of
        the surface, and the sandbox turns the two into faces before the
        implementation runs (see 'wrappers/cae_support.py'). A port drawn with
        no sketch travels as the frame it always was.
        """
        from .render_overlay import Overlay, collect_async

        try:
            records = await collect_async(self, ctx, Overlay(ports=True, interfaces=True, internals=True))
        except Exception as e:
            raise pc_cae.CaeConfigError(
                "Failed to locate the ports the '%s:' section names: %s" % (config.label, e)
            ) from e

        assigned, unmatched = pc_cae.assign_ports(config, records)
        for name, reason in unmatched:
            # A boundary condition that matched no port is silently doing
            # nothing, and a solver told to hold nothing still answers with
            # nonsense rather than with an error. The reason is carried rather
            # than assumed: a misspelt *instance* name reads very differently
            # from an interface the object never implements.
            pc_logging.warning(
                "%s:%s: '%s:' names the interface '%s', but %s"
                % (self.project_name, self.name, config.label, name, reason)
            )
        if not assigned:
            raise pc_cae.CaeConfigError(
                "'%s:' names no port of this object: none of the interfaces it lists is implemented here" % config.label
            )
        return assigned

    async def analyze_async(
        self,
        ctx: Context,
        analysis: str,
        implementation: Optional[str] = None,
        project: Optional[Project] = None,
        filepath=None,
        output_dir=None,
        scenario: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Run one scenario of one CAE analysis on this shape and report what it found.

        Args:
            ctx: Execution context.
            analysis: one of 'partcad.cae.ANALYSES' - which section of the object
                holds the boundary conditions, and what the output file is named
                after.
            implementation: '<package>:<file type>' naming who runs it,
                overriding the user configuration's default for this run.
            project: The package the object belongs to, whose 'cae:' section
                re-tunes the implementation's parameters.
            filepath: The file to write. None resolves it from the
                configuration, the object's name and the scenario's.
            output_dir: Where the file goes when 'filepath' does not say.
            scenario: Which of the section's scenarios to run, by name: 'pc cae
                fea -f'. None is the only one it declares, and is refused for a
                section that declares several -- which one is meant is the
                caller's to say (see 'partcad.cae.choose').
            kwargs: Analysis parameters, overriding what the configuration and
                the scenario's own 'params:' say.

        Returns:
            The model file that was written and the findings, as plain data.

        Raises:
            partcad.cae.CaeConfigError: the object declares no boundary
                conditions for this analysis, no scenario of that name, or
                declares them wrongly. Every one is an answer to the user's
                question rather than a failure, and each is reported as the
                sentence it carries.
        """
        what = "%s:%s" % (self.project_name, self.name)
        scenarios = pc_cae.of_shape(self, analysis)
        if not scenarios:
            raise pc_cae.CaeConfigError(
                "%s declares no '%s:' section, so there is nothing to analyse" % (what, analysis)
            )
        chosen = pc_cae.choose(scenarios, scenario, what, analysis)
        config = chosen.conditions()
        # The scenario's own parameters under the caller's: a scenario that
        # says 'params: {mesh_size: 0.01}' asks this question on a finer mesh,
        # and a run that says otherwise is the more specific of the two.
        kwargs = {**config.params, **kwargs}

        if project is None:
            project = ctx.get_project(self.project_name)
        # '-i' first, then what the part declared, then the user configuration.
        # The part's own answer sits in the middle because it is a statement
        # about the part -- the solver it was written against -- and the two
        # things that outrank it are the two that are about this run and this
        # machine. Handed over separately rather than picked between here: the
        # two are resolved against different packages when either names one
        # relatively, and only the callee knows which it ended up using.
        options_project, format_name = self._analysis_implementation(
            ctx, analysis, implementation, declared=config.implementation
        )

        try:
            result = await self._analysis_run_async(
                ctx, analysis, chosen, config, project, options_project, format_name, filepath, output_dir, kwargs
            )
        except (pc_cae.CaeConfigError, pc_runtime.SandboxUnavailable):
            # Neither is the implementation failing, and neither gets the
            # report. The first is the part's own section being wrong, which is
            # answered by editing it; the second is this machine having no
            # container runtime, so nothing was ever asked and there is nothing
            # to report about the implementation or the platform.
            raise
        except Exception as e:
            # Everything else is "asked, and no answer", and every caller says
            # so the same way. Written here rather than by each of them because
            # this is where the implementation's name is known, and because a
            # user who ran `pc cae fea` and then `pc test -f fea` must be told
            # the same thing about the same machine both times.
            raise pc_cae.CaeFailed(
                pc_cae.dysfunction_report(
                    what,
                    analysis,
                    "%s:%s" % (options_project.name, format_name),
                    e,
                    scenario=None if chosen.legacy else chosen.name,
                )
            ) from e
        result["scenario"] = chosen.name
        result["desc"] = chosen.desc
        return result

    async def _analysis_run_async(
        self,
        ctx: Context,
        analysis: str,
        scenario,
        config,
        project: Project,
        options_project: Project,
        format_name: str,
        filepath,
        output_dir,
        kwargs: dict,
    ) -> dict:
        """`analyze_async` once it knows what to run and who runs it.

        Split out so that the caller can say what every failure in here means
        without a ninety-line `try:` around the part that does the work. Every
        exception that leaves this is the implementation failing to deliver -
        see `analyze_async`.
        """
        with pc_logging.Action(analysis.upper(), self.project_name, self.name):
            impl, final_filepath = self.analysis_getopts(
                ctx, analysis, format_name, project, filepath, options_project, output_dir, scenario
            )
            final_filepath = os.path.abspath(final_filepath)
            # A load with a direction, or a gravity, asked of an implementation
            # that does not read it would be answered as if it had not been
            # said: refused, as the section asking something this
            # implementation cannot answer (see 'partcad.cae.unread_by').
            unread = pc_cae.unread_by(config, impl.reads, "%s:%s" % (options_project.name, format_name))
            if unread:
                raise pc_cae.CaeConfigError(unread)

            # A solve is a long silence: the sandbox says nothing between
            # starting the solver and the solver finishing, and a client gives
            # up on a daemon that says nothing for its default five minutes. An
            # implementation that knows it can take longer says so with
            # 'timeout:' (seconds) among its parameters -- a CFD package, a
            # fine mesh re-tuned by the package using it -- and the daemon
            # announces that window for as long as the analysis runs, exactly as
            # it does for an assembly that declares one (see
            # 'partcad_utils.timeouts').
            # A scenario that says it takes longer ('params: {timeout: ...}')
            # is taken at its word, as one run's parameters are.
            window = timeouts.seconds({**(impl.parameters or {}), **kwargs}.get(timeouts.KEY))
            with pc_logging.Timeout(window, self.project_name, self.name):
                # Clearing the path, writing it and reading the answer back are one
                # operation on one file, and the path is derived from the shape --
                # so a second run over the same shape resolves to the same path and
                # would otherwise interleave with this one: its 'os.remove' landing
                # between this run's write and this run's check, or its model being
                # the one handed back here. Held for all three, and the nested
                # 'get_wrapped' and '_run_implementation_async' take the same lock
                # again without waiting for it.
                #
                # What this does not make it is a snapshot. The path below is the
                # shape's model file, not this call's, and a later run of the same
                # analysis on the same shape replaces it once this one has returned
                # -- the same contract 'pc render' and 'pc export' have, and the
                # reason the IDE and the CLI can both name the file without being
                # told where it went. A caller that needs the bytes to outlive the
                # next run copies them; giving each run its own path instead would
                # take that name away from everyone who relies on it.
                async with self.locked():
                    ctx.ensure_dirs_for_file(final_filepath)
                    # A model is the answer to *this* run, and the path it goes to
                    # is stable -- '<part>.<analysis>.<extension>', beside the
                    # package. So one an earlier run left there would satisfy the
                    # check below and be handed back as the new result: last week's
                    # stresses under today's load, with nothing to say they are not
                    # today's. Removed before the implementation is asked, which
                    # makes the file's existence afterwards mean what it is read as
                    # meaning.
                    if os.path.exists(final_filepath):
                        os.remove(final_filepath)

                    obj = await self.get_wrapped(ctx)
                    if obj is None:
                        raise Exception("Cannot analyse '%s': shape is empty" % self.name)

                    boundary = await self._analysis_boundary_async(ctx, config)
                    script = await self._materialize_output_script(ctx, impl)

                    request = await self._output_request(ctx, obj, impl, kwargs)
                    request.update(config.to_data())
                    # The ports each condition landed on, in the shape's own
                    # coordinate system. 'fix' and 'load' above say what the user
                    # wrote; this says where it goes, which is what a solver needs.
                    request["boundary"] = boundary

                    # The same question asked again is a read: the model goes back
                    # where this run would have written it, and the findings come
                    # with it. Asked here, once the request is complete, because the
                    # request is most of the question.
                    cache = getattr(ctx, "cache_artifacts", None)
                    artifact = await self._artifact_hash(
                        output.CAE, analysis, impl, script, request, "%s:%s" % (options_project.name, format_name)
                    )
                    model = {"model": final_filepath}
                    result = await cache_artifacts.restore_async(cache, artifact, files=model)
                    cached = result is not None
                    if not cached:
                        result = await self._run_implementation_async(ctx, impl, script, request, final_filepath)

                    if result is None:
                        raise Exception("The '%s' implementation reported nothing: %s" % (format_name, script))
                    if not result.get("success", False):
                        raise Exception(
                            "%s failed for %s:%s: %s%s"
                            % (
                                analysis.upper(),
                                self.project_name,
                                self.name,
                                result.get("exception", "Unknown error"),
                                sandbox_note(ctx, impl),
                            )
                        )
                    written = os.path.exists(final_filepath)
                    if written and not cached:
                        # Only an answer is remembered: everything that failed has
                        # raised by now (see 'partcad.cache_artifacts').
                        await cache_artifacts.store_async(cache, artifact, result, files=model)

        if not written:
            # The meta-wrapper reports what the script returned and does not look
            # at the path, so "success" alone is the script's word for it. This
            # result is handed to a caller that acts on 'filepath' -- the IDE
            # reads the bytes back, the CLI prints where to find them -- so a
            # path to nothing is worse than a refusal. The same check
            # '_convert_to_serialized()' makes of an exporter, for the same
            # reason. Sound only because the path was cleared above: otherwise
            # this passes on a file the implementation never touched.
            raise Exception(
                "%s produced no model for %s:%s: %s was not written"
                % (analysis.upper(), self.project_name, self.name, final_filepath)
            )
        for warning in result.get("warnings") or []:
            pc_logging.warning("%s:%s: %s" % (self.project_name, self.name, warning))

        return {
            "object": "%s:%s" % (self.project_name, self.name),
            "analysis": analysis,
            "implementation": "%s:%s" % (options_project.name, format_name),
            "filepath": final_filepath,
            "extension": os.path.splitext(final_filepath)[1].lstrip("."),
            "findings": pc_cae.normalize_findings(result.get("findings")),
            # Without the sketches: they are geometry for the sandbox, and a
            # client -- the CLI's '--json', the IDE's tab -- is told where each
            # condition landed, not handed a BREP of every port outline.
            "boundary": [{key: value for key, value in record.items() if key != "sketch"} for record in boundary],
        }

    async def _artifact_hash(
        self, section: str, label: str, impl, script: str, request: dict, implementation: str, extra=None
    ):
        """The cache key of one analysis's, one route's or one output file's answer, or None.

        'section' is the output section that produced it ('cae', 'cam',
        'export' or 'render') and 'label' what this run is of the shape - the
        analysis, the machine a route is for, the file type - which only names
        the entry; what decides the key is the rest. That is the shape's own
        key, and everything the run adds to it ('extra' being whatever of that
        the request does not carry - see '_output_run_async'):
        the request the implementation is handed (an analysis's boundary
        conditions as the user wrote them and where they landed, a route's job
        and the machine it is for, every resolved option, the shape's material
        facts), which implementation it is, the sandbox it runs in, and the
        content of its script and of the meta-wrapper that runs it -- and of
        every module either can import from where it lives ('source_key'): a
        solver package that keeps its mesher settings in a helper module is
        another solver when only the helper changed -- and the version both
        scripts report ('code_version'). What the
        request carries the geometry in is left out, because the shape's key
        already covers it and the payload is the one thing in there that is not
        a description.

        The machine matters here more than anywhere: 'manufacturing:' is one of
        the keys the shape's own hash leaves out, so a part moved from a router
        to a laser keeps its key - and it is the request, which carries the
        machine, that tells the two routes apart.

        Never raises. A key that cannot be worked out - the implementation's
        container declaration is broken, say - is a run that is not cached, and
        the run itself is what reports why.
        """
        try:
            subject_key = await self.get_artifact_key_async()
            question = {
                "section": section,
                "label": label,
                "implementation": implementation,
                "options": impl.config,
                "request": {key: value for key, value in request.items() if key != "wrapped"},
                "reproducible": impl.reproducible,
                # Declared, never observed: see 'Implementation.environment_cache_key'.
                "environment": impl.environment_cache_key(),
                # What the script imports from its package, and the revision a
                # fetched one is at; and the wrappers 'wrapper_export.py'
                # imports. See 'partcad.source_key'.
                "source": impl.source_cache_key(),
                "wrappers": source_key.wrappers_key(),
            }
            if extra:
                # Only when there is some, so that an analysis and a route keep
                # the keys - and the cached answers - they had before.
                question.update(extra)
            return cache_artifacts.question_hash(
                "%s:%s#%s" % (self.project_name, self.name, label),
                subject_key,
                question,
                files=[script, wrapper.get("export.py")],
            )
        except Exception as e:
            pc_logging.debug("%s:%s: the %s result will not be cached: %s" % (self.project_name, self.name, label, e))
            return None

    def analyze(
        self,
        ctx: Context,
        analysis: str,
        implementation: Optional[str] = None,
        project: Optional[Project] = None,
        filepath=None,
        output_dir=None,
        scenario: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """`analyze_async` for a caller that has no event loop of its own."""
        return asyncio.run(
            self.analyze_async(ctx, analysis, implementation, project, filepath, output_dir, scenario, **kwargs)
        )

    async def route_async(
        self,
        ctx: Context,
        implementation: Optional[str] = None,
        project: Optional[Project] = None,
        filepath=None,
        output_dir=None,
        machine: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Produce the route file this shape declares, and report what it is.

        Args:
            ctx: Execution context.
            implementation: '<package>:<file type>' naming who produces it,
                overriding the user configuration's default for this run.
            project: The package the object belongs to, whose 'cam:' section
                re-tunes the implementation's parameters.
            filepath: The file to write. None resolves it from the
                configuration and the object's name.
            output_dir: Where the file goes when 'filepath' does not say.
            kwargs: Job parameters, overriding what the configuration says.

        Returns:
            The route file that was written, what it took, and anything the
            implementation wanted said about it, as plain data.

        Raises:
            partcad.cam.CamConfigError: the object declares no 'cam:' section,
                or declares one that cannot be made sense of. Both are answers
                to the user's question rather than failures, and both are
                reported as the sentence they carry - which is what lets a run
                over a whole package tell the objects it skips from the one
                that is broken.
            partcad.cam.CamFailed: the implementation was asked and produced no
                route.
        """
        try:
            config = pc_cam.config_of(self, machine)
        except pc_cam.CamConfigError as e:
            # Named, because a run over a package reports one line per object
            # and "'cam: tool:' is not a length" against forty parts is a
            # sentence with no address on it. Done here rather than in
            # 'partcad.cam', which deliberately knows nothing about shapes.
            raise self._cam_config_error(e) from e
        if config is None:
            raise pc_cam.CamConfigError(
                "%s:%s says nothing about being cut, so there is nothing to route" % (self.project_name, self.name)
            )

        if project is None:
            project = ctx.get_project(self.project_name)
        # '-i' first, then what the object declared, then the user
        # configuration. The object's own answer sits in the middle because it
        # is a statement about the object -- the post-processor its numbers were
        # written for -- and the two things that outrank it are the two that are
        # about this run and this machine.
        try:
            options_project, format_name = self._route_implementation(
                ctx, implementation, declared=config.implementation
            )
        except pc_cam.CamConfigError as e:
            raise self._cam_config_error(e) from e
        except Exception as e:
            # Naming who should produce the route is configuration, so failing
            # to resolve that name is a 'CamConfigError' and not a plain one.
            # The type is what decides the blast radius: a package-wide run
            # gathers these, and '_route_packages_async' re-raises anything it
            # does not recognise -- so an unresolvable implementation used to
            # abort the whole request and discard the routes already produced
            # for every other object in the package.
            raise self._cam_config_error(
                pc_cam.CamConfigError("the 'cam' implementation could not be resolved: %s" % e)
            ) from e

        try:
            return await self._route_run_async(
                ctx, config, project, options_project, format_name, filepath, output_dir, kwargs, machine
            )
        except pc_cam.CamConfigError as e:
            # The same naming, for the layers underneath the object: a feed the
            # *package* wrote in a spelling nothing can read is reported against
            # every object it covers, and each of those reports has to say which
            # object could not be routed because of it.
            raise self._cam_config_error(e) from e
        except pc_runtime.SandboxUnavailable:
            # Neither is the implementation failing, and neither gets the
            # report. The first is the object's own section being wrong, which
            # is answered by editing it; the second is this machine having no
            # sandbox, so nothing was ever asked.
            raise
        except Exception as e:
            # Everything else is "asked, and no route", and every caller says so
            # the same way. Written here rather than by each of them because
            # this is where the implementation's name is known.
            raise pc_cam.CamFailed(
                pc_cam.dysfunction_report(
                    "%s:%s" % (self.project_name, self.name),
                    "%s:%s" % (options_project.name, format_name),
                    e,
                )
            ) from e

    def _route_machine_data(self, machine: Optional[str] = None) -> dict:
        """Which machine this route is written for, as the request says it.

        Empty for everything that declares no machine: an assembly, a part made
        some other way, anything with no `manufacturing:` section at all. An
        implementation that gets nothing writes what it has always written,
        which is a CNC program -- so such an object is unaffected by any of this.

        **A sketch is asked like anything else.** A drawing declares the section
        with no `method:` in it -- it is not made out of anything, it is a path a
        machine follows -- and `_read_machines` reads that case on purpose. So
        the answer has to come from what the object declared rather than from
        what class it is: a `not isinstance(self, Part)` here returned `{}` for a
        sketch that had named a `laser:`, its `machine`, `toolAxis` and `kerf`
        never reached the request, and the drawing was handed to the *router*
        emitter -- which asked it for a cutter diameter a beam does not have.

        Read from the part's own declaration rather than passed in as a job
        parameter, because the machine is not something a run gets to re-tune:
        `pc cam` on a laser-cut part produces a laser program on anybody's
        machine, and the day it does not is the day somebody sends a router
        program to a laser. What a run *may* do is choose between the machines
        the part itself named, which is what `machine` is.

        Raises:
            partcad.cam.CamConfigError: the part named a machine and the naming
                cannot be read -- a `laser:` that is not a section, a key that
                machine does not take, an axis that is not one. `route_async`
                already wraps this call's caller in a `try` that re-raises such
                an error through `_cam_config_error`, so it is raised bare here
                and named there.

        It has to *refuse* rather than fall back, and that is the whole reason
        this is not a `debug` line. `_read_machines` records such a declaration
        in `machine_error` and keeps no machine, which is indistinguishable here
        from the part that simply named none -- and a part that named none
        routes as CNC. (`cam.declared_config` refuses first for the same reason,
        which makes this the backstop; the sentence is the same either way.) So a part whose `laser:` subsection has a typo in it
        would be handed a *router* program, silently. `pc test` reporting it too
        is not enough, because nothing makes `pc cam` wait for `pc test`.
        """
        try:
            from .part_config import PartConfiguration

            manufacturing_data = PartConfiguration.get_manufacturing_data(self)
        except Exception as e:  # pylint: disable=broad-except
            raise pc_cam.CamConfigError("the 'manufacturing:' section could not be read: %s" % e) from e
        machine_error = getattr(manufacturing_data, "machine_error", None)
        if machine_error:
            # A backstop rather than the refusal a user meets: `declared_config`
            # reads the same field and raises first, on every path that reaches
            # here. Verbatim and not wrapped, so that the one fault reads as one
            # sentence whichever of the two spoke it.
            raise pc_cam.CamConfigError(machine_error)

        from .part_config_manufacturing import ROUTED_MACHINES

        if machine:
            chosen = manufacturing_data.machine_named(machine)
        else:
            # The one machine a program could be written for. A saw beside it is
            # an alternative with no program, so it does not make the choice
            # ambiguous -- the same reading 'cam.declared_config' makes.
            routed = [kind for kind in manufacturing_data.machine_choices() if kind in ROUTED_MACHINES]
            chosen = manufacturing_data.machine_named(routed[0]) if len(routed) == 1 else None
        if chosen is not None and chosen.kind not in ROUTED_MACHINES:
            raise pc_cam.CamConfigError("a '%s' runs no program, so there is no route to write for it" % chosen.kind)
        if chosen is None:
            # Made some other way, so there is no machine to name and nothing
            # wrong with that: an implementation handed nothing writes what it
            # has always written. A part that named several and had none chosen
            # never reaches here -- `cam.declared_config` refuses first, where
            # the sentence can name the choices.
            return {}
        return chosen.to_data()

    def _cam_config_error(self, error) -> "pc_cam.CamConfigError":
        """One `cam:` configuration error, with the object it is about in front.

        Idempotent by construction: it is applied where the error leaves
        `route_async`, which is once.
        """
        return pc_cam.CamConfigError("%s:%s: %s" % (self.project_name, self.name, error))

    async def _route_run_async(
        self,
        ctx: Context,
        config,
        project: Project,
        options_project: Project,
        format_name: str,
        filepath,
        output_dir,
        kwargs: dict,
        machine: Optional[str] = None,
    ) -> dict:
        """'route_async' once it knows what to run and who runs it.

        Split out so that the caller can say what every failure in here means
        without a ninety-line 'try:' around the part that does the work - the
        same split 'analyze_async' and '_analysis_run_async' are.
        """
        with pc_logging.Action("CAM", self.project_name, self.name):
            impl, final_filepath = self.cam_getopts(ctx, format_name, project, filepath, options_project, output_dir)
            if machine is not None and (filepath is None or os.path.isdir(filepath)):
                # 'panel.laser.nc' beside 'panel.drill.nc'. Only when a machine
                # was chosen, which only happens when the part offered more than
                # one -- so an object with a single machine keeps the name it
                # has always had, and a caller that named a path gets that path.
                #
                # A directory is not naming a path: 'cam_getopts' has just read
                # it as the *output_dir* and derived the filename from the
                # object, which is the same filename for every machine. Asking
                # the same question it asked is what keeps two alternatives from
                # resolving to one file -- where the second route deletes the
                # first before writing itself, and the run reports two.
                root, extension = os.path.splitext(final_filepath)
                final_filepath = "%s.%s%s" % (root, machine, extension)
            final_filepath = os.path.abspath(final_filepath)

            # Clearing the path, writing it and checking it afterwards are one
            # operation on one file, and the path is derived from the shape --
            # so a second run over the same shape resolves to the same path and
            # would otherwise interleave with this one. Held for all three; the
            # nested 'get_wrapped' and '_run_implementation_async' take the same
            # re-entrant lock without waiting for it.
            async with self.locked():
                ctx.ensure_dirs_for_file(final_filepath)
                # A route is the answer to *this* run, and the path it goes to
                # is stable. So one an earlier run left there would satisfy the
                # check below and be handed back as the new result: last week's
                # depths under today's tool, with nothing to say they are not
                # today's. Removed before the implementation is asked, which
                # makes the file's existence afterwards mean what it is read as
                # meaning -- the same thing 'analyze_async' does and for the
                # same reason.
                if os.path.exists(final_filepath):
                    os.remove(final_filepath)

                obj = await self.get_wrapped(ctx)
                if obj is None:
                    raise Exception("Cannot route '%s': shape is empty" % self.name)

                script = await self._materialize_output_script(ctx, impl)
                # Handed no kwargs, deliberately: '_output_request' applies them
                # before the object's own section is merged in, and the object
                # would then overwrite the very values this call was given.
                # 'route_async' promises the opposite -- an explicit parameter
                # is the most specific thing anybody said -- so they go on top,
                # below.
                request = await self._output_request(ctx, obj, impl, {})
                # The object's own job, on top of the file type's parameters:
                # only what the object actually declared, so that a package that
                # set a tool for all of its parts still answers for the ones
                # that did not name one (see 'partcad.cam.CamConfig.to_data').
                request.update(config.to_data())
                # And last, what this call was told: 'pc cam' passes none today,
                # but 'route_async(tool=...)' is the documented way to route one
                # object against another cutter without editing its section.
                request.update({key: value for key, value in kwargs.items() if value is not None})
                # And last of all, which machine this is cut on. It comes from
                # the part's 'manufacturing:' section rather than from any of
                # the three layers above, so it is applied after them and
                # cannot be overridden by a 'cam:' key: what a part is made on
                # is a property of the part, not a parameter of the route, and
                # a route written for a laser by a section that said 'machine'
                # would be a program for a machine nobody owns.
                request.update(self._route_machine_data(machine))
                # And then every layer of it converted together. The object's
                # own values are already numbers; the ones the package and
                # '//builtin/cam' contributed have never been near a parser, and
                # a '2400 mm/min' written one layer down is as much PartCAD's to
                # understand as the same words written on the object.
                request = pc_cam.normalize_job(request)

                # The same route asked for again is a read, exactly as an
                # analysis is: the program goes back where this run would have
                # written it, with what the implementation counted. Keyed after
                # the request is complete, because the machine and the job are
                # in it and in nothing else.
                cache = getattr(ctx, "cache_artifacts", None)
                artifact = await self._artifact_hash(
                    output.CAM,
                    "cam.%s" % (machine or request.get("machine") or "default"),
                    impl,
                    script,
                    request,
                    "%s:%s" % (options_project.name, format_name),
                )
                route = {"route": final_filepath}
                result = await cache_artifacts.restore_async(cache, artifact, files=route)
                cached = result is not None
                if not cached:
                    result = await self._run_implementation_async(ctx, impl, script, request, final_filepath)

                if result is None:
                    raise Exception("The '%s' implementation reported nothing: %s" % (format_name, script))
                if not result.get("success", False):
                    raise Exception(
                        "No route for %s:%s: %s%s"
                        % (
                            self.project_name,
                            self.name,
                            result.get("exception", "Unknown error"),
                            sandbox_note(ctx, impl),
                        )
                    )
                written = os.path.exists(final_filepath)
                if written and not cached:
                    # Only an answer is remembered: everything that failed has
                    # raised by now (see 'partcad.cache_artifacts').
                    await cache_artifacts.store_async(cache, artifact, result, files=route)

        if not written:
            # The meta-wrapper reports what the script returned and does not look
            # at the path, so "success" alone is the script's word for it. A
            # caller acts on 'filepath' -- the CLI prints it, and whoever sends
            # it to a machine opens it -- so a path to nothing is worse than a
            # refusal. Sound only because the path was cleared above.
            raise Exception("The route for %s:%s was not written: %s" % (self.project_name, self.name, final_filepath))
        for warning in result.get("warnings") or []:
            pc_logging.warning("%s:%s: %s" % (self.project_name, self.name, warning))

        return {
            "object": "%s:%s" % (self.project_name, self.name),
            "implementation": "%s:%s" % (options_project.name, format_name),
            "filepath": final_filepath,
            "extension": os.path.splitext(final_filepath)[1].lstrip("."),
            # Whatever the implementation counted. Reported rather than
            # interpreted: what is worth knowing about a route differs between a
            # router and a wire EDM, and a fixed set of keys here would be
            # PartCAD deciding that on their behalf (see 'cam.route_report').
            "stats": result.get("stats") or {},
            "warnings": list(result.get("warnings") or []),
        }

    def route(
        self,
        ctx: Context,
        implementation: Optional[str] = None,
        project: Optional[Project] = None,
        filepath=None,
        output_dir=None,
        **kwargs,
    ) -> dict:
        """'route_async' for a caller that has no event loop of its own."""
        # By keyword, for the reason 'render' carries at length: a parameter
        # added to the middle of 'route_async' would otherwise silently
        # re-address every argument after it here.
        return asyncio.run(
            self.route_async(
                ctx,
                implementation=implementation,
                project=project,
                filepath=filepath,
                output_dir=output_dir,
                **kwargs,
            )
        )

    async def render_svg_somewhere_async(
        self,
        ctx,
        project=None,
        filepath=None,
        line_weight=None,
        viewport_origin=None,
        annotations=None,
        reproducible=None,
        viewport_up=None,
        defaults_only=False,
    ):
        """Renders an SVG file somewhere, ignoring where the project wants it.

        'defaults_only' draws it with PartCAD's own SVG options rather than the
        package's and the shape's (see '_output_getopts').

        'annotations' are 3D line segments - each a pair of points in the shape's
        own coordinate system - to draw on top of the projection. An assembly
        instruction book uses them to show the gap an exploded view introduces
        (see assembly_guide.py); they are projected together with the shape, so
        they land where the geometry they point at does.

        'reproducible' asks for the projection that is the same on any machine
        rather than the fast one, as an explicit argument because this render
        goes somewhere the configuration never named -- so there is no file type
        whose declaration could say it (see 'output.REPRODUCIBLE_KEY'). 'None'
        leaves it to the configuration, which is what every caller that only
        wants to look at the picture means; 'False' would be this caller
        insisting, and would turn the flag off for a package that had asked for
        it. An instruction book that is checked in asks for 'True': its pages
        are drawn from these projections, so a picture that differs between two
        machines is a document that differs between them.
        """
        if filepath is None:
            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
                filepath = f.name

        if not annotations:
            self.svg_path = None
        await self.render_async(
            ctx,
            "svg",
            project=project,
            filepath=filepath,
            line_weight=line_weight,
            viewport_origin=viewport_origin,
            viewport_up=viewport_up,
            annotations=annotations,
            reproducible=reproducible,
            defaults_only=defaults_only,
        )
        if not annotations and not defaults_only and os.path.exists(filepath):
            # An annotated projection is a one-off illustration, not this shape's
            # picture: remembering it here would hand it to every later caller
            # that asks for the shape's SVG.
            self.svg_path = filepath

    def render_svg_somewhere(
        self,
        ctx,
        project=None,
        filepath=None,
        line_weight=None,
        viewport_origin=None,
        annotations=None,
        reproducible=None,
    ):
        asyncio.run(
            self.render_svg_somewhere_async(
                ctx,
                project=project,
                filepath=filepath,
                line_weight=line_weight,
                viewport_origin=viewport_origin,
                annotations=annotations,
                reproducible=reproducible,
            )
        )

    async def get_solidity_async(self, ctx):
        """Whether this shape is a solid OCCT will do arithmetic on.

        Returned as {"solids": n, "volume": v, "valid": bool}, with 'volume' and
        'valid' None when the shape holds no solid at all - a sketch, a shell,
        a wire - or None outright when the shape could not be built.

        A negative volume means the faces are oriented inward: the shape is
        inside out. It still builds, renders, exports and measures; only its
        arithmetic is wrong, which is why this has to be asked rather than
        noticed. Measured in a sandbox, like every other operation on geometry.
        """
        if self._solidity is not None:
            return self._solidity

        # Held across the question, and the answer remembered, for the reason
        # 'get_bounding_box_async' gives: 'pc test' runs the 'solidity' and the
        # 'validity' tests of one part at once, and both ask exactly this.
        async with self.locked():
            if self._solidity is not None:
                return self._solidity
            obj = await self.get_wrapped(ctx)
            if obj is None:
                return None
            result = await self._ask_solidity(ctx, obj)
            if result is None:
                return None
            self._solidity = {
                "solids": result.get("solids", 0),
                "volume": result.get("volume"),
                "min_solid_volume": result.get("min_solid_volume"),
                "valid": result.get("valid"),
                "problems": result.get("problems"),
            }
            return self._solidity

    async def _ask_solidity(self, ctx, obj, solidify=False):
        """The solidity wrapper's answer about 'obj', or None if it gave none.

        'solidify' is a part being built rather than one being asked about, and
        its action is named for that: the two are different work on one shape.
        """
        with pc_logging.Action("Solidify" if solidify else "Solidity", self.project_name, self.name):
            request = {"wrapped": obj}
            if solidify:
                request["solidify"] = True
            request_serialized = shape_envelope.serialize(request)

            runtime = ctx.get_python_runtime(version="3.11")
            await runtime.ensure_async(sandbox_versions.OCP)

            with tempfile.TemporaryDirectory(prefix="partcad-solidity-") as unused_dir:
                command = [wrapper.get("solidity.py"), os.path.join(unused_dir, "unused.txt")]
                exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized)
            if exitcode != 0 and len(errors) == 0:
                errors = command_failure(command, exitcode)
            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

            if not response_serialized or not response_serialized.strip():
                pc_logging.error("Empty response from wrapper: %s" % command[0])
                return None
            result = shape_envelope.deserialize(response_serialized)

            if not result.get("success", False):
                pc_logging.error(
                    "Solidity check failed for %s:%s: %s"
                    % (self.project_name, self.name, result.get("exception", "Unknown error"))
                )
                return None
            return result

    def _solidifies(self) -> bool:
        """Whether this part's closed shells are turned into the solids they bound as it leaves its factory.

        All but a part read from a STEP or BREP file, which is judged and never
        converted: those hand over what the file holds, because the file is the
        authority on what the part is and 'pc convert' round-trips through them
        (see "A part is a body, not a skin" in AGENTS.md). A shell in one is
        reported, not quietly changed.
        """
        return (self.config or {}).get("type") not in FILE_AUTHORITY_TYPES

    def finish_request(self):
        """What the wrapper that builds this part is asked to do to it before it hands it over.

        What 'get_wrapped' does to every part a factory returns, before it is
        recorded or cached: validate it ('_validated_part'), then move it by its
        'offset' and scale it by its 'scale'. Each is work on the geometry, so
        done here it is a sandbox apiece - a fresh interpreter importing OCP
        and parsing the BREP the factory's wrapper wrote a moment before, to do
        what that wrapper could have done while the shape was live. A file part
        with an 'offset' and a 'scale' was four interpreters; the wrapper that
        read the file is one.

        So a part factory puts this in its request (under
        'shape_envelope.KEY_FINISH'), and a wrapper that can ('wrapper_common
        .finished') does it and says so in its answer. 'get_wrapped' then does
        whatever is left - all of it, for a wrapper that cannot - which is why
        none of this changes what a part is, only where it is worked out: the
        same functions, on the same shape, in the same order.

        The cache key is untouched by it, and has to be: 'offset' and 'scale'
        are in the key already (see '__init__', and 'transform.py' among the
        code versions of a shape that declares either - 'code_versions'), and
        what is cached is what comes out of all of it, wherever it was done.

        None for anything but a part: a sketch's 'offset' and 'scale' are still
        applied by 'get_wrapped' alone.
        """
        if self.kind != "part":
            return None
        request = {"validate": {"solidify": self._solidifies()}}
        for key in ("offset", "scale"):
            if key in self.config:
                request[key] = self.config[key]
        return request

    def _finished_by_wrapper(self, claim) -> dict:
        """The steps of 'finish_request()' the wrapper that built this part says it took, checked.

        A dict holding what is accepted of 'claim' (see
        'shape_envelope.METADATA_FINISHED'); empty when it claims nothing, which
        leaves every step to 'get_wrapped'. What is accepted is what was asked,
        exactly as it was asked, in the order it is done in - validated, moved,
        scaled - and stopping where the wrapper stopped.

        A claim of anything else is a wrapper saying it did to the geometry
        something nobody can account for - moved it by another offset, or
        scaled it without validating it first - and there is no undoing that
        from here, so it is an error rather than something to work around.
        """
        if not claim:
            return {}
        declined = claim.get(shape_envelope.FINISHED_DECLINED)
        if declined:
            # Not a failure: whatever the wrapper could not do, 'get_wrapped'
            # does in a sandbox of its own, and says so in its own words if it
            # cannot do it either.
            pc_logging.debug("%s:%s: left to a sandbox of its own: %s" % (self.project_name, self.name, declined))
        asked = self.finish_request() or {}
        steps = []
        if "validate" in asked:
            steps.append(shape_envelope.FINISHED_VALIDATED)
        steps += [key for key in ("offset", "scale") if key in asked]

        def same(a, b):
            return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

        accepted = {}
        for step in steps:
            if step not in claim:
                break
            value = claim[step]
            if step == shape_envelope.FINISHED_VALIDATED:
                if not isinstance(value, dict) or value.get("solidify") != asked["validate"]["solidify"]:
                    break
            elif not same(value, asked[step]):
                break
            accepted[step] = value
        unexplained = sorted(key for key in claim if key not in accepted and key != shape_envelope.FINISHED_DECLINED)
        if unexplained:
            raise Exception(
                "%s:%s: the wrapper that built it says it did what it was not asked to: %s (asked: %s; claimed: %s)"
                % (self.project_name, self.name, ", ".join(unexplained), asked, claim)
            )
        return accepted

    def _not_a_solid(self, problems) -> None:
        """Say what keeps this part from being a solid, if anything does - in the one wording, wherever it was judged."""
        if problems:
            pc_logging.warning("%s:%s is not a solid: %s" % (self.project_name, self.name, "; ".join(problems)))

    async def _validated_part(self, ctx, envelope):
        """A part's envelope as every part leaves its factory: solidified, and judged.

        The one validation every part goes through, whatever made it - a
        cadquery or build123d script, a STEP, STL, 3MF, OBJ or BREP file, an
        OpenSCAD or KiCad export, an SDF, an extrusion, a partType plugin such
        as the LDraw library. Before this, only the script and plugin wrappers
        turned a closed shell into the solid it bounds, and nothing at all
        judged the result until somebody ran 'pc test': a STEP file's closed
        shell stayed a shell where the same shell from a script became a solid.

        Two things happen, in the sandbox, in one call. A closed shell becomes
        the solid it bounds ('wrapper_common.solidify'); the geometry comes back
        only when that changed it, and nothing else about the envelope moves.
        And the part is held to 'wrapper_common.solid_problems' - the same
        definition the interference check intersects by - with a warning that
        says what is wrong when it is not a solid. A warning and not a failure:
        a surface model is a legitimate thing to import and draw. Everything
        that needs a solid asks the same question and declines to compute with
        one that is not.

        A sandbox that cannot answer leaves the part as it was, with a warning;
        validating geometry is not a reason to stop building it.

        Asked in that sandbox only of a part nothing has validated yet. The
        wrapper that built the part does it itself wherever it can, on the live
        shape and with the same two functions, and hands back the part already
        converted ('wrapper_common.finished'), which leaves 'get_wrapped' only
        the problems it found to report. What still comes here is what no such
        wrapper built: a JavaScript part, a part an in-process factory made, a
        reference to another part, and a wrapper that could not finish it.
        """
        # Except a part read from a STEP or BREP file: see '_solidifies'.
        solidify = self._solidifies()
        try:
            result = await self._ask_solidity(
                ctx, {shape_envelope.KEY_BREP: envelope[shape_envelope.KEY_BREP]}, solidify
            )
        except Exception as e:
            pc_logging.warning("%s:%s: could not be validated: %s" % (self.project_name, self.name, e))
            return envelope
        if result is None:
            return envelope
        solidified = result.get("solidified")
        if isinstance(solidified, dict) and shape_envelope.KEY_BREP in solidified:
            envelope = dict(envelope)
            envelope[shape_envelope.KEY_BREP] = solidified[shape_envelope.KEY_BREP]
            # What the geometry measures is replaced with what the converted
            # geometry measures - a shell holds no solid and the solid holds
            # one - and nothing else: what the source stated about itself and
            # its elements is still true of the same faces.
            recorded = shape_envelope.without_measurements(shape_envelope.metadata_of(envelope))
            fresh = shape_envelope.metadata_section(
                shape_envelope.metadata_of(solidified), shape_envelope.METADATA_MEASUREMENTS
            )
            metadata = dict(recorded)
            if fresh:
                metadata[shape_envelope.METADATA_MEASUREMENTS] = fresh
            if metadata:
                envelope[shape_envelope.KEY_METADATA] = metadata
            else:
                envelope.pop(shape_envelope.KEY_METADATA, None)
        self._not_a_solid(result.get("problems") or [])
        return envelope

    async def get_bounding_box_async(self, ctx):
        """The axis-aligned bounding box of this shape, in its own coordinates.

        Returned as '(x_min, y_min, z_min, x_max, y_max, z_max)', or 'None' when
        the shape is empty or failed to instantiate, and remembered afterwards:
        the callers that need a size (exploded views) ask for the same one
        repeatedly.

        It is the box the shape recorded when it was built (see
        'get_measurements_async'), which is the answer every shape a wrapper
        returned already carries - building it is what measured it, and reading
        it back is a cache read. Only a shape that recorded no box is measured
        here, in a sandbox, by the same code that measures one as it is built:
        two ways of computing "how big is it" would be two answers to it.
        """
        if self._bounding_box is not None:
            return self._bounding_box

        # Held across the measurement, so that a caller arriving while it runs
        # waits for it and reads the box it remembered, rather than measuring the
        # same shape again beside it. An instruction book asks for one part's box
        # from every step that part takes part in, all at once; without this
        # each of them was a sandbox process, and an action open under the same
        # name as the others (see 'logging_ansi_terminal.action_key').
        async with self.locked():
            if self._bounding_box is not None:
                return self._bounding_box
            return await self._measure_bounding_box(ctx)

    async def _measure_bounding_box(self, ctx):
        obj = await self.get_wrapped(ctx)
        if obj is None:
            return None

        measured = await self.get_measurements_async(ctx)
        if measured is not None:
            # Measured, so trusted either way: a box of None is a shape that
            # built and bounds nothing, and measuring it again says so again.
            box = measured.get(shape_envelope.METADATA_BBOX)
        else:
            # Lazily, because this is the one path in this module that measures
            # on demand, and it is reached only by a shape nothing measured.
            from . import measure as pc_measure

            with pc_logging.Action("BoundingBox", self.project_name, self.name):
                box = await pc_measure.bbox(ctx, obj, cacheable=self.artifacts_cacheable())
        if box is None:
            return None

        self._bounding_box = tuple(box)
        return self._bounding_box

    def get_bounding_box(self, ctx):
        return asyncio.run(self.get_bounding_box_async(ctx))

    async def get_max_dimension_async(self, ctx):
        """The largest linear dimension of this shape, or 'None' if unknown."""
        box = await self.get_bounding_box_async(ctx)
        if box is None:
            return None
        return max(box[3] - box[0], box[4] - box[1], box[5] - box[2])

    def get_max_dimension(self, ctx):
        return asyncio.run(self.get_max_dimension_async(ctx))

    async def get_metadata_async(self, ctx):
        """Everything recorded about this shape when it was built, or None.

        The three sections 'shape_envelope' defines - what the geometry
        measures, what its source stated about its elements, what that source
        stated about itself - as one dict, exactly as the wrapper that built the
        shape produced them.

        Materializing the shape is what produces this, and materializing it from
        the cache is what reads it back: the metadata lives in the same cache
        entry as the geometry, so a hit carries both and there is no second
        lookup to make and no second entry to be missing. That is the whole
        reason this is cheap enough to ask for.

        'None' for a shape that recorded nothing - one that did not build, or
        one whose geometry could not be measured. A reader cannot tell those
        apart and should not: all of them mean "nothing to report".

        Internally the two *are* told apart, because they decide different
        things: 'None' on the attribute means nobody has looked yet and is what
        sends this to build the shape, while an empty dict means the shape has
        been materialized and recorded nothing. Without that an object with
        nothing to report would rebuild on every ask.
        """
        if self._metadata is None:
            await self.get_wrapped(ctx)
        return self._metadata or None

    async def get_measurements_async(self, ctx):
        """How big this shape is and how much of it there is, or None.

        ``{"bbox": [...] | None, "volume": float | None, "solids": int}`` - the
        box in the shape's own coordinates and without the gap OCCT pads one by,
        the volume in cubic millimetres, and how many solids that is the volume
        of.

        Measured as the shape was *built*, in the process that held the live
        geometry, and carried here in the envelope's metadata. Nothing is
        computed on demand: by the time anybody asks, either the shape has been
        built - in which case the numbers came back with it - or it has not, in
        which case building it is what produces them, and that is the same work
        as answering any other question about it.
        """
        metadata = await self.get_metadata_async(ctx)
        return shape_envelope.metadata_section(metadata, shape_envelope.METADATA_MEASUREMENTS)

    async def get_annotations_async(self, ctx) -> list:
        """What this shape's source said about its individual elements.

        One opaque record per element, as the importing wrapper read them. A
        DXF states these as XDATA against a line, which is where the angle and
        the radius of a sheet metal bend come from; a source that states nothing
        of the kind yields an empty list.

        The records are the source's own vocabulary and are never read into
        here. What asks the real question is a manufacturing check, and it has
        no business knowing which format answered.
        """
        metadata = await self.get_metadata_async(ctx)
        return shape_envelope.metadata_section(metadata, shape_envelope.METADATA_ANNOTATIONS) or []

    async def _reported_async(self, ctx):
        """What 'pc info' adds to a shape once the shape itself has been built.

        All of it comes out of the one metadata dict the shape was built with,
        and it is reported in two registers:

        The measurements are the generic half and are named here, because they
        are the same three numbers for every shape whatever produced it.
        ``BoundingBox`` is the measured box as ``min``/``max``/``size`` triples
        of millimetres. ``size`` is stated rather than left to be subtracted -
        it is the one of the three anybody reads out loud. ``Volume`` is in
        cubic millimetres and ``Solids`` is how many solids that is the volume
        of; both are left out for a shape holding no solid at all, because a
        volume of zero and no volume to speak of are different things. A
        negative volume is reported as it stands: the faces are oriented inward,
        which is worth seeing rather than taking the modulus of.

        Everything else is merged in **as the wrapper named it**. The sections
        are a STEP file's or a DXF drawing's own vocabulary, and the core has no
        business translating one into the other - it did not read the file and
        does not know which format answered.
        """
        info = {}

        metadata = await self.get_metadata_async(ctx)
        if not metadata:
            return info

        measured = shape_envelope.metadata_section(metadata, shape_envelope.METADATA_MEASUREMENTS)
        if measured:
            box = measured.get(shape_envelope.METADATA_BBOX)
            if box:
                info["BoundingBox"] = {
                    "min": list(box[:3]),
                    "max": list(box[3:]),
                    "size": [box[axis + 3] - box[axis] for axis in range(3)],
                }
            if measured.get(shape_envelope.METADATA_VOLUME) is not None:
                info["Volume"] = measured[shape_envelope.METADATA_VOLUME]
                info["Solids"] = measured.get(shape_envelope.METADATA_SOLIDS, 0)

        sections = shape_envelope.metadata_section(metadata, shape_envelope.METADATA_SECTIONS)
        if sections:
            info.update(sections)

        # The per-element records are deliberately *not* reported from here.
        # They are carried for 'get_annotations_async()', whose caller is a
        # manufacturing check that needs every element including the ones
        # nothing was written against. Deciding which of them are worth showing
        # a reader means reading into a record, and what a record holds is the
        # producing wrapper's vocabulary - so the wrapper reports the ones worth
        # showing under a heading of its own, in 'sections' above, and this
        # stays unable to tell a bend angle from a layer name.
        return info

    async def _run_test_async(self, ctx: Context, tests: list | None = None, use_wrapper: bool = False) -> bool:
        if not self.finalized:
            # Skip shapes that are not yet finalized
            return

        if tests is None:
            tests = ctx.get_all_tests()

        test_method = "test_log_wrapper" if use_wrapper else "test_cached"
        tasks = [asyncio.create_task(getattr(t, test_method)(tests, ctx, self)) for t in tests]

        return all(await asyncio.gather(*tasks))

    async def test_async(self, ctx, tests=None) -> bool:
        return await self._run_test_async(ctx, tests, use_wrapper=False)

    def test(self, ctx, tests=None) -> bool:
        return asyncio.run(self.test_async(ctx, tests))

    async def test_log_wrapper_async(self, ctx, tests=None) -> bool:
        return await self._run_test_async(ctx, tests, use_wrapper=True)

    def test_log_wrapper(self, ctx, tests=None) -> bool:
        return asyncio.run(self.test_log_wrapper_async(ctx, tests))
