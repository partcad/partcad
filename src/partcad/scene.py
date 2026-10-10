#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A scene: where things are, without saying how they got there.

A scene is a placed arrangement of objects -- a workcell, a table with the
parts laid out on it, a simulation world. It is built exactly the way an
assembly is, out of the very same ASSY files, and every operation that works on
an assembly works on a scene: it renders, it exports, it has a bill of
materials, it can be inspected.

What separates the two is intent, and one rule follows from it. An assembly is
a *product*: it says what it is made of and, through the ``how:`` section of
each ``connect:``, how it is put together -- which is what the assembly
instruction book is generated from. A scene only states an end state. Nothing
in it was assembled, so there is nothing to say about the assembling, and
``how:`` is rejected rather than ignored (see 'SceneFactoryAssy'). The
``connect:``/``connectPorts:`` sections themselves stay: placing a robot's
gripper against the fixture it holds is a statement about where things are, and
saying it with the ports the two objects declare is better than saying it with
coordinates somebody worked out by hand.

Because it is an 'Assembly', a scene is also a legal child of one -- an
assembly may appear in a scene, which is the usual direction, and nothing
stops a scene from being reused inside another scene.

A scene is also a *world*, which an assembly is not: it may state the gravity
in it and the fluid it is filled with (``gravity:``, ``medium:``), and a
simulation of it is a simulation under that gravity, through that fluid. Both
are optional and both defaults are what a scene has always meant -- Earth's
gravity as the engine states it, and vacuum. See 'partcad.scene_world' for the
units and why they are those.
"""

import typing

from . import scene_world, telemetry
from .assembly import Assembly


@telemetry.instrument()
class Scene(Assembly):
    path: typing.Optional[str] = None

    def __init__(self, project_name: str, config: typing.Optional[dict] = None):
        # A fresh dictionary rather than a shared default: 'ShapeConfiguration'
        # writes a generated name into whatever it is handed, so one default
        # dictionary would be one name for every scene that was built without a
        # configuration.
        super().__init__(project_name, {} if config is None else config)
        # What every consumer branches on: the shape cache keys on it, the
        # renderer maps it to the 'scenes' section, and the viewer labels the
        # object with it.
        self.kind = "scene"

    def _where(self) -> str:
        return "%s:%s" % (self.project_name, self.name)

    @property
    def gravity(self) -> typing.Optional[list]:
        """The gravity this scene states, as [x, y, z] in m/s^2, or None if it states none.

        None rather than a number when nothing was stated, and that is the
        default rather than a gap: it leaves gravity to the engine, whose own
        default is Earth's along -Z, which is what every scene was simulated
        under before a scene could say anything else.

        Read from the configuration as it stands, which for an enrich or an
        alias is what it resolved to (see 'adopt_source_config'), so a scene
        that only re-states another's gravity reads the same way.

        Raises:
            scene_world.WorldError: what is declared is not three numbers.
        """
        return scene_world.gravity_of(self.config, self._where())

    def medium_reference(self) -> typing.Optional[str]:
        """The material this scene says it is filled with, as written, or None (vacuum)."""
        return scene_world.medium_reference_of(self.config)

    def get_medium(self, ctx):
        """The material this scene is filled with, or None for vacuum.

        Resolved against this scene's own package, exactly as a part's material
        is (see 'Shape.get_material()'): ':water' is "the 'water' this package
        catalogues".

        Raises:
            scene_world.WorldError: it names a material nothing answers to.
        """
        reference = self.medium_reference()
        if reference is None:
            return None
        return scene_world.resolve_medium(ctx, self.project_name, reference, self._where())

    def world_facts(self, ctx) -> typing.Optional[dict]:
        """What an exporter is handed about this scene's world, or None if it states nothing.

        See 'scene_world.facts()' for the shape of it, and 'output.WORLD_KEY'
        for when it is handed over at all.
        """
        return scene_world.facts(ctx, self.project_name, self.config, self._where())

    def shape_info(self, ctx):
        """'pc info' of an assembly, plus the world: what it is filled with, and its gravity.

        Reported as the facts the simulation will use rather than as the
        declaration, which is printed beside this already: the question somebody
        running 'pc info' on an underwater scene is asking is what density the
        water was taken to be, and which package said so. Nothing is added for a
        scene that states neither, which is most of them.
        """
        info = super().shape_info(ctx)
        try:
            gravity = self.gravity
            if gravity is not None:
                info["Gravity"] = "%s m/s^2" % ", ".join("%g" % component for component in gravity)
            reference = self.medium_reference()
            if reference is not None:
                info["Medium"] = self.get_medium(ctx).material_info()
        except scene_world.WorldError as e:
            # Reported in the answer rather than raised out of it: 'pc info' is
            # how somebody finds out what is wrong with the declaration.
            info.setdefault("Errors", []).append(str(e))
        return info
