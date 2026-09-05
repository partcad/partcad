#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Sandbox entry point for an export/render implementation.

Every output file PartCAD writes - the built-in formats in '//builtin/export'
and '//builtin/render' as much as a format a package implements itself - is
produced by a Python script run through here. This meta-wrapper runs inside the
PartCAD sandbox (so the script it runs may import OCP / build123d / cadquery),
executes that script with 'runpy', and serializes its verdict back to
'Shape.render_async()'.

The script is executed with these globals available:

    request  -- the shape ('request["wrapped"]') plus every export parameter
                declared for this format (see '//builtin/export/partcad.yaml'),
                along with 'shape_name', 'shape_kind' and 'shape_type' so the
                script can adapt to what it was handed
    path     -- the absolute path of the file to write

and reports what happened in one of two ways, whichever suits it:

    output = {"success": True}                        # wrote the file
    output = {"success": False, "exception": "..."}   # did not

or by defining a function, which is called with the same two values:

    def process(path, request): ...                   # returns the dict above

Both '__file__' and the run name '__partcad_export__' are set on the script, so
it can gate any top-level work ("if __name__ == '__partcad_export__':") and
remain importable by its siblings - which is how the PNG and DXF renderers
reuse the SVG one.

A format that declared 'properties: true' finds 'request["properties"]' holding
what each shape reports about itself - its material, its colour, its physics -
keyed by the full name the shape carries. See 'properties_index()'.
"""

import os
import runpy
import sys

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common

# The key the request carries the implementation script under. Passed in the
# request rather than on the command line: 'wrapper_common.handle_input()'
# already spends both positional arguments on the output path and the working
# directory.
SCRIPT_KEY = "__script__"

# The key that says whether the envelopes are rebuilt into live OCCT geometry
# before the implementation sees them. It has to travel in the request and be
# read before anything is decoded, which is why the request is always read raw
# here and decoded afterwards. An implementation that needs what an envelope
# says *about* a node (the URDF exporter names each link after the node and
# reads its location as a joint origin) declares 'decode: false', because
# decoding keeps the tree's shape but only its geometry: names and labels are
# gone and placements are baked in rather than left as data.
DECODE_KEY = "__decode__"

# The parameter a file type sets to 'true' to be handed what the shapes it is
# given report about themselves, keyed by the full name ("<package>:<name>")
# those shapes carry on their envelopes. It is a plain export parameter, not a
# reserved key: a format that has no way to state a material or a mass never
# declares it and never sees the index.
PROPERTIES_KEY = "properties"

# The key the core puts what each shape inherits from its material under, keyed
# by the same full name the index below is keyed by. A shape says what it is
# made of by *name*, and turning ':aluminium' into a coefficient of friction
# means resolving it against the package that wrote it and then loading the
# package that catalogues it - which the core can do and a sandbox cannot. So
# the facts arrive already resolved, per shape, and are merged into the index
# below underneath whatever each shape said about itself. See
# 'partcad.material.physics_by_shape()'.
MATERIALS_KEY = "__materials__"


def properties_index(request):
    """Full name -> what that shape reports about itself, over the whole request.

    Built from the request as it arrives, before anything is decoded, and that
    ordering is the point. The properties ride on the envelopes, beside the very
    name an exporter looks a node up by, so they are here for an implementation
    that walks the tree ('decode: false') *and* for one that is handed live
    geometry ('decode: true'), whose decoding throws every envelope away.

    What the shape's *material* says is folded in here too, underneath what the
    shape itself says: a part that states a friction of its own keeps it, and one
    that only states what it is made of gets the material's. That way an exporter
    reads 'physics' and never learns that materials exist - which is what keeps
    all three of them (URDF, SDFormat, MJCF) agreeing about it for free.

    Only shapes that report something appear. A shape with no name cannot be
    looked up and is skipped, but its children are still walked.
    """
    index = {}
    materials = request.get(MATERIALS_KEY) or {}

    def resolved(name, properties):
        """One shape's properties, with its material's physics under its own."""
        facts = materials.get(name)
        if not facts:
            return properties
        physics = dict(facts)
        physics.update(properties.get("physics") or {})
        return dict(properties, physics=physics)

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
            return
        if not isinstance(obj, dict):
            return
        is_envelope = ocp_serialize.KEY_BREP in obj or ocp_serialize.KEY_ASSEMBLY in obj
        if is_envelope:
            properties = obj.get(PROPERTIES_KEY)
            name = obj.get("name")
            if name and isinstance(properties, dict) and properties:
                index[name] = resolved(name, properties)
            for child in obj.get(ocp_serialize.KEY_ASSEMBLY) or []:
                walk(child)
            return
        for key, value in obj.items():
            # Never the index itself: it is keyed by name, not by anything that
            # holds an envelope, and walking it would be pointless. Nor the
            # material table, which is keyed by reference and holds no shapes.
            if key not in (PROPERTIES_KEY, MATERIALS_KEY):
                walk(value)

    walk(request)
    return index


def _failed(exception):
    return {"success": False, "exception": wrapper_common.exception_to_str(exception)}


def process(script, path, request):
    try:
        result = runpy.run_path(
            script,
            init_globals={"request": request, "path": path},
            run_name="__partcad_export__",
        )
    except Exception as e:
        wrapper_common.handle_exception(e, script)
        return _failed(e)

    output = result.get("output")
    if output is None:
        entry_point = result.get("process")
        if not callable(entry_point):
            return _failed(
                Exception("%s: neither set 'output' nor defined 'process(path, request)'" % os.path.basename(script))
            )
        try:
            output = entry_point(path, request)
        except Exception as e:
            wrapper_common.handle_exception(e, script)
            return _failed(e)

    if not isinstance(output, dict):
        return _failed(Exception("%s: produced %s, expected a dict" % (os.path.basename(script), type(output))))

    # A script that reports an exception but forgets to clear 'success', or that
    # reports neither, is normalized here so the core only ever sees the two
    # consistent shapes.
    exception = wrapper_common.exception_to_str(output.get("exception"))
    result = {"success": bool(output.get("success")) and exception is None, "exception": exception}
    # What the implementation could not represent in the target format, which is
    # not a failure: the file is correct, it just says less than the package
    # does. Reported by 'Shape._render_one_async()'.
    for key in ("warnings", "unsupported"):
        if output.get(key):
            result[key] = output[key]
    return result


if __name__ == "__main__":
    # Read raw, then decode unless the implementation asked not to: whether the
    # envelopes become live geometry is the implementation's choice, and that
    # choice travels inside the request itself.
    path, request = wrapper_common.handle_input(decode=False)
    script = request.pop(SCRIPT_KEY, None)
    # Before the decode, while the envelopes - and so the properties they carry
    # - are still there to be read.
    if request.get(PROPERTIES_KEY) is True:
        request[PROPERTIES_KEY] = properties_index(request)
    # Read by 'properties_index' above and nothing else: an implementation is
    # handed the physics of each shape, not a table of substances to look one up
    # in. A format that declares no 'properties: true' never asked for either.
    request.pop(MATERIALS_KEY, None)
    if request.pop(DECODE_KEY, True) is not False:
        request = ocp_serialize.decode(request)
    if script is None:
        result = _failed(Exception("No implementation script was passed to the export wrapper"))
    else:
        result = process(script, path, request)
    wrapper_common.handle_output(result)
