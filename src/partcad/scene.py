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
"""

import typing

from . import telemetry
from .assembly import Assembly


@telemetry.instrument()
class Scene(Assembly):
    path: typing.Optional[str] = None

    def __init__(self, project_name: str, config: dict = {}):
        super().__init__(project_name, config)
        # What every consumer branches on: the shape cache keys on it, the
        # renderer maps it to the 'scenes' section, and the viewer labels the
        # object with it.
        self.kind = "scene"
