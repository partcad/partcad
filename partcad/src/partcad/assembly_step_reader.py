#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Driving the sandboxed STEP assembly reader.

Two things read the structure of a STEP assembly: 'pc import assembly', which
turns it into an '.assy' file plus parts committed to the package, and the
'step' assembly type, which builds the very same tree in memory every time the
assembly is used. They want exactly the same thing out of the file, so the code
that runs the reader lives here rather than in either of them.

The reader itself is wrappers/wrapper_import_assy.py and it runs in a python
sandbox: STEP-CAF is OCCT, and PartCAD's own process never loads a CAD library.
What comes back is plain data.
"""

import os

from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, wrapper


async def read_assembly_tree(ctx, assembly_file, output_folder, file_type="step", precision=5):
    """Read an assembly file in a sandbox and return its tree of nodes.

    'output_folder' is where the reader writes one STEP file per distinct shape;
    it is created if it is not there yet. The tree that comes back is made of
    '{"type": "assembly", "name", "links": [...]}' and
    '{"type": "part", "name", "part_file", "location"}' nodes. Several part
    nodes may name the same 'part_file': the reader deduplicates by geometry, so
    the same shape in two places is one file placed twice.
    """
    if ctx is None:
        raise ValueError("A context is required to import an assembly")

    os.makedirs(output_folder, exist_ok=True)

    runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
    # The wrapper only needs OCCT (STEP-CAF), not build123d/cadquery.
    await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

    request = {
        "operation": "import_assy",
        "file_type": file_type,
        "assembly_file": os.path.abspath(assembly_file),
        # Only used to name the synthetic root node the reader adds when the
        # file turns out to have more than one free shape in it.
        "assembly_name": os.path.splitext(os.path.basename(assembly_file))[0],
        "output_folder": str(output_folder),
        "precision": precision,
    }

    wrapper_path = wrapper.get("import_assy.py")
    command = [wrapper_path, "import_assy"]
    exitcode, response_serialized, errors = await runtime.run_async(command, shape_envelope.serialize(request))
    if exitcode != 0 and not errors:
        errors = "assembly import failed with exit code %s" % exitcode
    if errors:
        pc_logging.error(errors)
        raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "assembly import failed")
    return result["root"]
