#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'walls' scene type: the walls of a room, standing on the outline of a sketch.

    scenes:
      living-room:
        type: walls
        sketch: living-room-plan   # one closed outline of lines and arcs, on XY
        height: 2700               # mm
        wall: //builtin/building:wall   # (optional) the part each wall is

The sketch is read as a plan is, from above: one enclosed outline - a face with
no holes, or one closed wire - made of straight lines and arcs of circles. The
scene is one wall per edge of it, in the order a walk around it clockwise
meets them, each named 'wall-<n>' and each a 'wall' part placed where its edge
starts and turned the way the edge sets off (see 'wrappers/wrapper_outline.py').
A wall looks to its right, and the right of a clockwise walk is the inside:
so every wall looks into the room, and the room is seen into from outside
through whichever walls are nearest.

A sketch that is not such an outline - two of them, one with a hole in it, an
open one, one with a spline in it, one that is not on the XY plane - is refused
with the reason, rather than approximated into some other room.

A room's own colour, material and finish - its CMF parameters - paint every
wall of it: 'room;color=//my/package:sage' (see '_link').

'sketch' and 'height' may be '%...%' expressions over the scene's parameters,
which is how '//builtin/building:room' is one declaration of every room:
'room;sketch=//my/package:plan,height=2500'. 'wall' names the part each wall
is, '//builtin/building:wall' unless it says otherwise; whatever it names is
asked for with the parameters 'length', 'height' and 'radius', and has to take
them.

It is built the way an ASSY scene is - this is 'SceneFactoryAssy' with the file
replaced by the links worked out from the sketch - so it places its walls,
stages them, keys them and reports them exactly as a hand-written scene placing
the same walls would. The one thing it does that an ASSY scene does not is read
geometry to know what its links are, which costs a sandbox once per instance of
the scene, as it is prepared.
"""

import asyncio
import threading

from . import cmf
from . import config as pc_config
from . import expr
from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, sync_threads, telemetry, wrapper
from .assembly_factory import AssemblyFactory
from .process_crash import describe_exit_code
from .scene_factory import SceneFactoryAssy

# The part a wall of the scene is, unless the scene names another.
DEFAULT_WALL = "//builtin/building:wall"

# How many decimal places of a millimetre the numbers a wall is asked for with
# are written to. They are part of the wall's instance name, and so of its
# identity: two scenes on the same outline ask for the same walls, and a
# nanometre of arithmetic noise in one of them would make them different walls.
DIGITS = 6

# How often a caller that finds the outline being read by another looks again,
# in seconds: from the first value, doubling to the second. The values
# 'Shape.prepare_async' waits for another caller's preparation with.
_POLL_MIN = 0.002
_POLL_MAX = 0.1


class WallsDeclarationError(Exception):
    """A 'walls' scene declared in a way that cannot be built, in words for its author."""


def _parameter_hint(config) -> str:
    """How to name the sketch, for a scene that takes it as a parameter; nothing for one that does not.

    A function rather than a static method: the factory is wrapped by the
    telemetry decorator, which does not keep a 'staticmethod'.
    """
    parameters = config.get("parameters")
    if isinstance(parameters, dict) and "sketch" in parameters:
        return ", as '%s;sketch=//package:sketch'" % config["name"]
    return ""


@telemetry.instrument()
class SceneFactoryWalls(SceneFactoryAssy):
    """The walls standing on a sketch's outline, as a scene."""

    WRAPPERS = ("outline.py",)

    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitWalls", source_project.name, config["name"]):
            # The ASSY factory's own constructor, short of the file it would go
            # looking for: there is none, the links are worked out instead.
            AssemblyFactory.__init__(self, ctx, source_project, target_project, config)

            where = "%s:%s" % (target_project.name, config["name"])
            values = pc_config.parameter_values(config.get("parameters"))

            sketch = expr.resolve(config.get("sketch"), values, where)
            if sketch in (None, ""):
                raise WallsDeclarationError(
                    "%s: a 'walls' scene stands on the outline of a sketch, and names none: give it a 'sketch'%s"
                    % (where, _parameter_hint(config))
                )
            sketch = str(sketch)
            if ":" in sketch:
                project_name, sketch_name = source_project.resolve(sketch)
            else:
                project_name, sketch_name = source_project.name, sketch
            self.sketch_spec = "%s:%s" % (project_name, sketch_name)

            height = expr.resolve(config.get("height"), values, where)
            if height is None:
                raise WallsDeclarationError("%s: a 'walls' scene needs a 'height' for its walls" % where)
            try:
                self.height = float(height)
            except (TypeError, ValueError):
                raise WallsDeclarationError(
                    "%s: 'height' is a number of millimetres, and '%s' is not" % (where, height)
                )
            if not self.height > 0.0:
                raise WallsDeclarationError("%s: walls are taller than nothing, and 'height' is %s" % (where, height))

            # As a link of an ASSY file names it: resolved against this
            # package when it is not a path (see 'node_object_name').
            self.wall = str(expr.resolve(config.get("wall") or DEFAULT_WALL, values, where))

            # Worked out once per instance, from the sketch, by one caller at a
            # time - the thread of the one reading it, while it does: see
            # '_links_async'.
            self._links = None
            self._reader = None
            self._links_guard = threading.Lock()

            self._create(config)
            # What the scene is built from, resolved. The sketch's content goes
            # in once it is resolved (see 'prepare_async'); what each wall is
            # built from goes in with the walls, as an ASSY scene's links do.
            self.assembly.hash.add_dict(
                {"walls": {"sketch": self.sketch_spec, "height": self.height, "wall": self.wall}}
            )
            self.assembly.cache_dependencies_broken = True

    def post_create(self) -> None:
        # Not the file factory's: there is no file to point the scene at, and
        # nothing to warn about for its absence.
        AssemblyFactory.post_create(self)

    def read_assy(self) -> dict:
        """The links an ASSY file placing these walls would hold.

        Worked out by '_links_async' before anything asks: preparing the scene,
        staging it and building it each do that first.
        """
        if self._links is None:
            return {}
        return {"links": self._links}

    async def _links_async(self) -> list:
        """One link per edge of the sketch's outline, read in a sandbox the first time it is asked for.

        Read once, by whoever asks first, and handed to everybody else: the
        scene is prepared, staged and built by callers that can overlap, and
        two of them reading it at once would be the same work twice and, worse,
        two 'Outline' actions open under one name (see "No two actions open
        under one name" in AGENTS.md). The others wait for the first, as a shape
        waits for another caller's preparation of it ('Shape.prepare_async'):
        by polling, since they come from more than one event loop
        ('AssemblyFactoryAssy.instantiate' runs one of its own) and no
        'asyncio.Lock' survives that, and giving back a slot of the thread pools
        for as long as the reader may be waiting for the pools itself
        ('sync_threads.waiting'). A reader that fails leaves the next caller to
        try again, and to say why in its own words.
        """
        delay = _POLL_MIN
        with sync_threads.waiting(lambda: self._reader) as wait:
            while True:
                with self._links_guard:
                    if self._links is not None:
                        return self._links
                    if self._reader is None:
                        self._reader = threading.get_ident()
                        break
                wait.update()
                await asyncio.sleep(delay)
                delay = min(delay * 2, _POLL_MAX)
        try:
            links = await self._read_links_async()
            with self._links_guard:
                self._links = links
            return links
        finally:
            with self._links_guard:
                self._reader = None

    async def _read_links_async(self) -> list:
        """What '_links_async' hands out: the outline read in a sandbox, as links. Asked by one caller at a time."""
        name = "%s:%s" % (self.target_project.name, self.name)
        sketch = self.ctx.get_sketch(self.sketch_spec)
        if sketch is None:
            raise WallsDeclarationError("%s: the sketch '%s' is not found" % (name, self.sketch_spec))
        envelope = await sketch.get_wrapped(self.ctx)
        if envelope is None:
            raise WallsDeclarationError("%s: the sketch '%s' produced no shape" % (name, self.sketch_spec))

        with pc_logging.Action("Outline", self.target_project.name, self.name):
            runtime = self.ctx.get_python_runtime(version=self.PYTHON_SANDBOX_VERSION)
            await runtime.ensure_async(sandbox_versions.OCP)
            request = {"sketch": envelope, "sketchName": self.sketch_spec}
            exitcode, response, errors = await runtime.run_async(
                [wrapper.get("outline.py"), "outline"], shape_envelope.serialize(request)
            )
        if exitcode != 0 and not errors:
            errors = "%s: reading the outline failed: %s" % (name, describe_exit_code(exitcode))
        if errors:
            raise Exception(errors)
        result = shape_envelope.deserialize(response)
        if not result.get("success"):
            raise WallsDeclarationError("%s: %s" % (name, result.get("exception")))

        return [self._link(index, segment) for index, segment in enumerate(result["segments"], 1)]

    def _link(self, index: int, segment: dict) -> dict:
        """The ASSY link that places the wall following one edge of the outline.

        With the room's own colour, material and finish, where it states any:
        a room painted sage is a room whose walls are sage, whatever colour the
        wall it is built of is drawn in by default. That is more than an ASSY
        assembly passes on - its CMF reaches only a link whose item states none
        (see 'AssemblyFactoryAssy.with_propagated_cmf') - and on purpose: a room
        *is* its walls, and the wall PartCAD ships states a colour precisely so
        that a room nobody painted is drawn in one. Nothing here is made, so
        nothing is claimed by it either.
        """
        x, y = segment["start"]
        params = {
            "length": round(float(segment["length"]), DIGITS),
            "height": self.height,
            "radius": round(float(segment["radius"]), DIGITS),
        }
        params.update(cmf.own_parameters(self.assembly, self.ctx))
        return {
            "part": self.wall,
            "name": "wall-%d" % index,
            "params": params,
            "location": [[round(x, DIGITS), round(y, DIGITS), 0.0], [0.0, 0.0, 1.0], round(segment["heading"], DIGITS)],
        }

    async def prepare_async(self, assembly) -> None:
        """Read the outline, key the scene on the sketch's content, and then prepare it as an ASSY scene.

        The sketch's name is in the key already, and what it contains is not
        until its own key is: without it, an edited plan would go on being
        walled as the plan it used to be.
        """
        await self._links_async()
        sketch = self.ctx.get_sketch(self.sketch_spec)
        sketch_keyed = sketch is not None and await assembly.add_cache_key_of(sketch)
        await super().prepare_async(assembly)
        if not sketch_keyed:
            assembly.cache_dependencies_broken = True
            assembly.cacheable = False

    async def subassemblies_async(self, assembly) -> list:
        await self._links_async()
        return await super().subassemblies_async(assembly)

    async def instantiate_async(self, assembly):
        await self._links_async()
        await super().instantiate_async(assembly)

    def info(self, shape):
        """What the scene stands on, beside the usual information about it."""
        info = super().info(shape)
        info["Walls"] = {"sketch": self.sketch_spec, "height": self.height, "wall": self.wall}
        if self._links is not None:
            info["Walls"]["count"] = len(self._links)
        return info
