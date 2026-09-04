#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'mjcf' scene type: a MuJoCo model used directly as a PartCAD scene.

The very same reader as the ``mjcf`` assembly type -- 'AssemblyFactoryMjcf' --
producing a 'Scene' instead of an 'Assembly'. Which of the two a given file
becomes is decided by the section that declares it, exactly as it is for an
ASSY file: an MJCF model in ``assemblies:`` is a product, one in ``scenes:`` is
an arrangement of things.

MJCF is where that split matters most. URDF describes one robot and SDFormat's
``.world`` describes one world, so each of them naturally reaches PartCAD as
one kind of object. An MJCF file is used for both in practice -- the same
element holds a manipulator and the table it is bolted to -- and there is
nothing in the file that says which it is. So both types exist, one reader
serves them, and the package says what it meant.

Kept in a module of its own rather than beside the other scene factories in
'scene_factory' because it imports the MJCF reader, which those do not: that
module is imported by every context that loads a package with a scene in it.
"""

from . import telemetry
from .assembly_factory_mjcf import AssemblyFactoryMjcf
from .scene_factory import SceneFactoryMixin


@telemetry.instrument()
class SceneFactoryMjcf(SceneFactoryMixin, AssemblyFactoryMjcf):
    # What the object is called in the messages the shared reader logs. The
    # 'SceneFactoryMixin' above changes what is built; this changes what it is
    # called, so that a scene is never reported as an assembly.
    OBJECT_NOUN = "scene"
