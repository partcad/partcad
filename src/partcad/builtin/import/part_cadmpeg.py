#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The part types cadmpeg reads: a native CAD file's bodies, as one part.

One script for every format '//builtin/import' reads this way -- Fusion 360,
SolidWorks, Inventor, CATIA V5, ACIS and Creo View -- because for each of them
the route is the same: cadmpeg converts the file to STEP, and the part is
what that STEP file shows ('cadmpeg_step'). cadmpeg decides the format by the
file's content, not its name, so nothing here does either; which format a part
is, is said by its declaration.

What the part is, is the bodies the document displays. A body its author hid is
not in it, and neither are the sketches and points beside the bodies. A body
that did not come through whole -- an open shell, an invalid solid -- *is* in
it, and the part types declare 'requireSolid', so that PartCAD fails the part by
the definition every part is held to rather than this script deciding what
broken means. The document's history -- its features, sketches and parameters
-- does not survive: what PartCAD gets is the geometry the application last
computed.

Run by 'wrappers/wrapper_part_type.py' with 'request["path"]' set to the file and
'request["cache_dir"]' to where cadmpeg is kept.
"""

import os
import sys
import tempfile

# Siblings are imported by bare name, and the sandbox sets PYTHONSAFEPATH.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Raise with any change to what this produces (see 'partcad.code_version'),
# which includes every change of the cadmpeg 'cadmpeg_tool' pins: a release that
# reads a format further is a release whose parts are different shapes.
CACHE_VERSION = 1


def read(source, cache_dir):
    """'(shape, cmf)' of 'source', a native CAD file: one OCCT shape, and what it is in (or None)."""
    import cadmpeg_step

    with tempfile.TemporaryDirectory(prefix="partcad-cadmpeg-") as tmp:
        shape, facts = cadmpeg_step.read(cadmpeg_step.to_step(source, cache_dir, tmp))
    found = cadmpeg_step.bodies(shape)
    if not found:
        raise RuntimeError("%s holds no solid" % os.path.basename(source))
    part = cadmpeg_step.compound(found)
    return part, cadmpeg_step.stated_cmf(part, facts)


def convert(source, cache_dir):
    """Read 'source', a native CAD file, into one OCCT shape."""
    return read(source, cache_dir)[0]


if __name__ == "__partcad_part__":
    try:
        shape, cmf = read(request["path"], request["cache_dir"])  # noqa: F821
        output = {"shape": shape}
        if cmf is not None:
            output["cmf"] = cmf
    except Exception as e:
        output = {"exception": str(e)}
