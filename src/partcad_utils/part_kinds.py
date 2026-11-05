#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The part types a part can be added as from a file: what ``pc add part`` takes, as both ends read it.

``pc add part <type> <file>`` refuses a type it does not know before it asks the
daemon anything, and it used to be the only thing that did: the daemon's
``add.object``, which is what the CLI, the editor extension's "Add part" and an
agent's ``execute`` all end in, wrote whatever ``type`` it was handed. So an
agent naming ``3dm`` got a declaration saying ``type: 3dm`` and a success, and
the mistake surfaced only when something tried to build the part. Now both
refuse it, and they refuse it from one list -- a copy per reader is a copy that
lets through what the other refuses.

The list is in two halves, because they are known in two places:

* :data:`FILE_PART_FACTORIES`, the types PartCAD builds with a factory of its
  own from a file the package holds (``partcad.globals`` registers them). That
  half is here.
* The native CAD formats PartCAD ships as ``partTypes`` declarations in
  ``//builtin/import`` -- ``fcstd``, ``f3d``, ``iges``, ... A client reads them
  from ``partcad_client.object_types`` (it must stay cheap to import), the daemon
  from PartCAD itself (``partcad.output.builtin_part_type``), and a test holds
  the two together.

A type a package declares for itself (``:mytype``, ``//pkg:mytype``) is not one
a part is added from a file as, and neither is a type that is not file-backed
(``basic``, ``alias``, ``extrude``): neither end takes them.
"""

from typing import Tuple

#: The part types PartCAD has a factory of its own for that read a file, in the
#: order ``pc add part --help`` lists them: the scripts first, then the formats.
FILE_PART_FACTORIES: Tuple[str, ...] = (
    "cadquery",
    "build123d",
    "chili3d",
    "sdf",
    "scad",
    "step",
    "brep",
    "stl",
    "3mf",
    "obj",
    "gltf",
)
