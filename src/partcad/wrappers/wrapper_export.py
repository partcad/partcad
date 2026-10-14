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

The script to run is the wrapper's third argument, after the output path and the
working directory; see SCRIPT_ARGUMENT below for why it is an argument rather
than part of the request.

The script is executed with these globals available:

    request  -- the shape ('request["wrapped"]') plus every export parameter
                declared for this format (see '//builtin/export/partcad.yaml'),
                along with 'shape_name', 'shape_kind' and 'shape_type' so the
                script can adapt to what it was handed, and 'shape_tree' - see
                below
    path     -- the absolute path of the file to write

Every implementation is handed the object two ways at once. 'wrapped' is the
whole of it as live OCCT geometry, which is what a file of geometry is written
from. 'shape_tree' is the tree it was decoded from, one node per object placed
in it, nested as deeply as it goes: each node's 'name' and 'label', its
'location' as data (the packed '[[x, y, z], [ax, ay, az], angle]' form) rather
than baked into the geometry, what it says about itself under 'properties' -
its 'color', its 'material', its 'physics' - and its 'joint' and 'metadata'
where it has them; and on every shape node its own geometry, decoded, in its own
frame, under 'shape'. It is what the URDF exporter makes a link of each node
out of, and what a drawing reads the colour of each part from. Both are built
from one decoding of each shape, so the second costs nothing an implementation
that ignores it would notice.

A 'cae:' implementation is run through here too, and is handed more keys:
'analysis' (one of 'partcad.cae.ANALYSES'), the conditions the part declared
under that analysis's own keys ('fix' and 'load', 'temperature', ...), and
'boundary', the ports each of them landed on with their locations (see
'partcad.cae'). Before it runs, 'cae_support.prepare()' imprints every port's
sketch on the part and puts on each boundary record the faces it covers, so
the 'wrapped' an implementation is handed is the part with its ports drawn on
it. It answers with the same dict plus one key of its own:

    output = {"success": True, "findings": [...]}   # wrote the model, and found this

'findings' is a JSON array - strings or objects with a 'message' and, optionally,
a 'severity' and a 'where'. An empty one means the analysis found nothing to
report, which is what "pc test" requires of a part.

A 'cam:' implementation is run through here as well, and is handed the job the
object declared merged with the file type's own parameters - the tool, the
depths, the feeds, all of them numbers in millimetres and millimetres per minute
by the time they arrive (see 'partcad.cam'). It answers with a key of its own
too:

    output = {"success": True, "stats": {...}}      # wrote the route, and it is this

'stats' is whatever that implementation counted about the route. It is reported
and never interpreted, so an implementation may put in it whatever a reader of
its output would want to know.

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
what each shape reports about itself - its material, its colour, its physics,
with every shape's mass, centre of mass, inertia, density and friction already
resolved - keyed by the full name the shape carries. See 'properties_index()'.

Such a format, handed a scene that states a gravity or a medium, also finds
'request["world"]': the gravity as [x, y, z] in m/s^2, and the fluid the scene is
filled with as the material it names and that material's 'density' (kg/m^3) and
'viscosity' (Pa*s), each only when stated - SI, so it is written as it arrives.
Absent means the
scene states neither - Earth's gravity as the engine has it, and vacuum - and an
implementation that writes what it always wrote in that case changes nothing for
anybody. See WORLD_KEY.

Every request carries 'request["reproducible"]', a boolean, whether or not the
file type declared it: whether the caller needs this file to come out the same
every time it is written, from the same object. An
implementation with nothing to decide ignores it; one that would otherwise stamp
the file with the clock, or reach for the quicker of two algorithms that do not
agree to the last bit, reads it and does the other thing. See REPRODUCIBLE_KEY.

Every node of 'shape_tree' that an assembly placed by connecting it to a
sibling it then moves against carries that node's joint under JOINT_KEY: its
name, the labels of the two siblings it joins, the ordered steps the node's
placement is the product of - 'fixed' ones and 'free' ones, each free one with
its kind ("turn" or "move"), axis, range, starting value and the parameters it
came from - and its physics. A node placed rigidly carries none: there are no
fixed joints. It is the core's 'Joint.to_envelope()', and 'wrapped' has no room
for it: decoding into geometry keeps the shape and nothing said about it.

Every node an assembly or a scene placed also says what it holds, under "kind"
("part", "assembly" or "scene"), and so does the root of an assembly or a scene;
an element a scene welds to the world says "fixed": true. Those three keys and
the joint are what decide which nodes are rigid bodies, and that rule is
'kinematics.bodies()', beside this file - which is what an exporter of bodies
and joints calls rather than walking the tree for itself.
"""

import os
import runpy
import sys

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# Where the implementation script's path is: the third argument, after the two
# 'wrapper_common.handle_input()' spends on the output path and the working
# directory.
#
# On the command line rather than in the request, and that is not a matter of
# taste. An implementation may run in a container, and a container's arguments
# are rewritten on the way in -- the directories PartCAD sent are unpacked
# somewhere of the container's choosing, and every argument naming one is
# adjusted to match (see 'tools/containers/_common/pc-container-json-rpc.py').
# The request cannot be: it arrives on standard input as one opaque serialized
# string. A script path inside it would name a directory on the machine that
# sent it and would be a path to nothing here.
SCRIPT_ARGUMENT = 3

# Where the object is handed to the implementation as live geometry, and where
# the tree it was decoded from is handed beside it. Both always: what each node
# of the tree says about itself - its name, its colour, where it sits - is not
# something an implementation should have to ask for in order to be told, and
# decoding the geometry is exactly what loses it.
WRAPPED_KEY = "wrapped"
SHAPE_TREE_KEY = "shape_tree"

# The parameter a file type sets to 'true' to be handed what the shapes it is
# given report about themselves, keyed by the full name ("<package>:<name>")
# those shapes carry on their envelopes. It is a plain export parameter, not a
# reserved key: a format that has no way to state a material or a mass never
# declares it and never sees the index.
PROPERTIES_KEY = "properties"

# The key a node's joint rides under, beside its properties. Not a parameter of
# anything - nothing has to ask for it - and spelled out here rather than
# imported because its twin is 'partcad.shape_envelope.KEY_JOINT', and a
# wrapper runs in a sandbox and cannot import 'partcad'.
JOINT_KEY = "joint"

# Whether the file this implementation is about to write has to come out
# byte-for-byte the same every time it is written, from the same object.
#
# It is in every request the core sends, whether or not the file type declared
# it, and that is the point of naming it here: an implementation reads
# 'request["reproducible"]' without first asking whether the key exists, and
# means by it what every other implementation means. Its twin is
# 'partcad.output.REPRODUCIBLE_KEY', spelled out separately for the reason
# JOINT_KEY is - a wrapper runs in a sandbox and cannot import 'partcad'.
#
# A plain parameter rather than a reserved one, so a package declares it as
# 'reproducible: true' on a file type like any other field, and so an
# implementation that has nothing to decide is free to ignore it. The built-in
# renderers do decide: it picks which of OCCT's two hidden-line algorithms the
# projection goes through, because only one of the two draws the same bytes on
# two machines - see 'builtin/render/render_svg.py'.
REPRODUCIBLE_KEY = "reproducible"

# The key the core puts each shape's resolved physics under, keyed by the same
# full name the index below is keyed by: what the shape states, what its
# material lends - a shape says what it is made of by *name*, and turning
# ':aluminium' into a density means loading the package that catalogues it,
# which the core can do and a sandbox cannot - and the mass, centre of mass and
# inertia derived from those and the solid. It arrives worked out, per shape,
# and is merged into the index below underneath whatever each shape said about
# itself. See 'partcad.physics.physics_by_shape()', whose 'FACTS_KEY' is this
# key's twin.
PHYSICS_KEY = "__physics__"

# What a scene says about the world it is: its gravity and the fluid it is
# filled with, resolved by the core (the fluid is a material, named the way a
# part names what it is made of, and only the core can load the package that
# catalogues it). Its twin is 'partcad.output.WORLD_KEY'. Nothing here reads it:
# it is a fact about the scene rather than about any one shape, so it reaches the
# implementation as the core sent it, beside 'wrapped', and is not folded into
# the properties index.
WORLD_KEY = "world"


def properties_index(request):
    """Full name -> what that shape reports about itself, over the whole request.

    Built from the request as it arrives, before anything is decoded. The
    properties ride on the envelopes, beside the very name an exporter looks a
    node up by, and every envelope in the request is walked - not only the
    object's, but any shape another parameter carries.

    What the core resolved for each shape is folded in here too, underneath
    what the shape itself says: a part that states a friction or a mass of its
    own keeps it, and one that only states what it is made of gets the
    material's friction and the mass its solid weighs at the material's density.
    That way an exporter reads 'physics' and never learns that materials,
    densities or derivations exist - which is what keeps all three of them
    (URDF, SDFormat, MJCF) agreeing about it for free.

    Only shapes that report something, or that the core resolved something
    for, appear. A part with no 'properties:' of its own still weighs what its
    solid weighs, so it is indexed for its physics alone. A shape with no name
    cannot be looked up and is skipped, but its children are still walked.
    """
    index = {}
    resolved_physics = request.get(PHYSICS_KEY) or {}

    def resolved(name, properties):
        """One shape's properties, with its resolved physics under its own."""
        facts = resolved_physics.get(name)
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
            properties = properties if isinstance(properties, dict) else {}
            name = obj.get("name")
            if name and (properties or resolved_physics.get(name)):
                index[name] = resolved(name, properties)
            for child in obj.get(ocp_serialize.KEY_ASSEMBLY) or []:
                walk(child)
            return
        for key, value in obj.items():
            # Never the index itself: it is keyed by name, not by anything that
            # holds an envelope, and walking it would be pointless. Nor the
            # resolved physics, which is keyed by name and holds no shapes.
            if key not in (PROPERTIES_KEY, PHYSICS_KEY):
                walk(value)

    walk(request)
    return index


def _failed(exception):
    return {"success": False, "exception": wrapper_common.exception_to_str(exception)}


def process(script, path, request):
    """Run one implementation script and normalize whatever it answered with.

    A script may set `output` or define `process(path, request)`; either way what
    comes back here is reduced to the two consistent shapes the core expects,
    plus the optional `warnings`, `unsupported` and `findings` it may carry.
    """
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
    #
    # 'findings' is the second output of a 'cae:' implementation: what the
    # analysis has to say about the part, beside the model it wrote. It travels
    # here rather than in a file of its own because an analysis has exactly one
    # verdict and two files would let them disagree - and because the IDE's FEA
    # tab is a webview with no file system, so a finding has to arrive as data.
    # Meaningless for an export or a render implementation, which never set it.
    #
    # 'stats' is the same arrangement for a 'cam:' implementation: what it
    # counted about the route it wrote - how many passes, how far the tool
    # travels in the cut - reported beside the file rather than parsed back out
    # of it. Passed through as the implementation shaped it and never
    # interpreted here, because what is worth counting differs between a router
    # and a wire EDM, and a fixed set of keys in this line would be PartCAD
    # deciding that on their behalf.
    for key in ("warnings", "unsupported", "findings", "stats"):
        if output.get(key):
            result[key] = output[key]
    return result


def decode(request):
    """The request as the implementation is handed it: every envelope in it decoded.

    The object itself is decoded into both of the forms it is handed in -
    'wrapped' and 'shape_tree' - out of one decoding of each of its shapes.
    Anything else that is a shape (the sketch of a port, say) becomes live
    geometry, as it always has.
    """
    wrapped = request.pop(WRAPPED_KEY, None)
    request = ocp_serialize.decode(request)
    if ocp_serialize.is_shape_object(wrapped) or ocp_serialize.is_assembly_object(wrapped):
        request[WRAPPED_KEY], request[SHAPE_TREE_KEY] = ocp_serialize.decode_tree(wrapped)
    elif wrapped is not None:
        request[WRAPPED_KEY] = ocp_serialize.decode(wrapped)
    return request


if __name__ == "__main__":
    # Read raw and decoded below rather than on the way in, because the
    # properties index is read off the envelopes, and decoding consumes them.
    path, request = wrapper_common.handle_input(decode=False)
    script = sys.argv[SCRIPT_ARGUMENT] if len(sys.argv) > SCRIPT_ARGUMENT else None
    # Before the decode, while the envelopes - and so the properties they carry
    # - are still there to be read.
    if request.get(PROPERTIES_KEY) is True:
        request[PROPERTIES_KEY] = properties_index(request)
    # Read by 'properties_index' above and nothing else: an implementation is
    # handed the physics of each shape in the index, not a second table to
    # look it up in. A format that declares no 'properties: true' never asked
    # for either.
    request.pop(PHYSICS_KEY, None)
    request = decode(request)
    # An analysis has its ports turned into faces before the implementation
    # sees it, once here rather than once per solver. What could not be done
    # is a warning beside whatever the implementation answers, never a failure:
    # the records then carry no faces, which an implementation already copes
    # with.
    prepared = []
    if request.get("analysis") and request.get("boundary"):
        try:
            import cae_support

            prepared = cae_support.prepare(request)
        except Exception as e:
            for record in request.get("boundary") or []:
                record.pop("sketch", None)
            prepared = ["The ports could not be turned into surfaces: %s" % wrapper_common.exception_to_str(e)]
    if script is None:
        result = _failed(Exception("No implementation script was passed to the export wrapper"))
    else:
        result = process(script, path, request)
    if prepared:
        result["warnings"] = prepared + list(result.get("warnings") or [])
    wrapper_common.handle_output(result)
