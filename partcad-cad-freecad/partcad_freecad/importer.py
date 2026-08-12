#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Bringing an exported STEP file into the active FreeCAD document.

FreeCAD is imported inside the functions, not at module import time, so the rest
of the addon (and its tests) can use :func:`unique_label` and
:func:`step_filename` without FreeCAD being present.
"""

import os
import re
from typing import Optional

# Characters that are legal in a PartCAD object name but awkward in a file name.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def step_filename(directory: str, item, params: Optional[dict] = None) -> str:
    """A collision-free path for the temporary STEP of one object instance.

    The parameter values go into the name so two variants of the same part
    exported into the same directory do not overwrite each other.
    """
    stem = _UNSAFE.sub("_", item.name).strip("_") or "object"
    if params:
        stem += "_" + "_".join("%s%s" % (name, _UNSAFE.sub("", str(params[name]))) for name in sorted(params))
    candidate = os.path.join(directory, stem + ".step")
    index = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, "%s_%d.step" % (stem, index))
        index += 1
    return candidate


def unique_label(existing, base: str) -> str:
    """``base``, or ``base (2)``, ``base (3)``... when the document already has it.

    FreeCAD tolerates duplicate labels but they make an assembly imported twice
    impossible to tell apart, and it is the label -- not the internal name --
    that the tree shows.
    """
    existing = set(existing)
    if base not in existing:
        return base
    index = 2
    while "%s (%d)" % (base, index) in existing:
        index += 1
    return "%s (%d)" % (base, index)


def _import_module():
    """FreeCAD's STEP importer: the GUI one when there is a GUI.

    ``ImportGui`` carries colours and the assembly structure across; ``Import``
    is the headless fallback and loses them.
    """
    try:
        import FreeCADGui  # noqa: F401  pylint: disable=unused-import,import-outside-toplevel

        import ImportGui  # pylint: disable=import-outside-toplevel

        return ImportGui
    except ImportError:
        import Import  # pylint: disable=import-outside-toplevel

        return Import


def insert_step(path: str, label: str, document=None):
    """Insert ``path`` into ``document`` (the active one by default).

    Returns the list of objects the import created, labelled after the PartCAD
    object and grouped under it when the import produced more than one.
    """
    import FreeCAD  # pylint: disable=import-outside-toplevel

    if document is None:
        document = FreeCAD.ActiveDocument or FreeCAD.newDocument("PartCAD")

    before = {obj.Name for obj in document.Objects}
    _import_module().insert(path, document.Name)
    document.recompute()
    created = [obj for obj in document.Objects if obj.Name not in before]
    if not created:
        raise RuntimeError("FreeCAD imported no objects from %s" % path)

    labels = {obj.Label for obj in document.Objects if obj.Name not in {c.Name for c in created}}
    roots = [obj for obj in created if not obj.InList]
    if len(roots) == 1:
        roots[0].Label = unique_label(labels, label)
    elif roots:
        # A multi-solid STEP arrives as several top-level objects; keep them
        # together so a second import does not interleave with the first.
        group = document.addObject("App::DocumentObjectGroup", "PartCAD")
        group.Label = unique_label(labels, label)
        group.Group = roots
        created.append(group)
    document.recompute()
    return created
