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

    output = {"success": True, "files": []}           # wrote the file, and only it
    output = {"success": False, "exception": "..."}   # did not

'files' is what else the implementation wrote, as paths relative to the
directory of 'path' - the meshes a URDF names, the '.bin' beside a '.gltf' - and
an empty list when it wrote nothing else. Their names begin the way 'path' does
('logo.urdf' writes 'logo_meshes/...'), which is what lets a cached answer be
put back under another name. It is optional, and what it buys is the cache: an
answer that says what it consists of is remembered and put back whole the next
time the same file is asked for, and one that does not is produced again every
time. See FILES_KEY.

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

Several files of one object are written by one call when they are asked for
together - 'pc render' of a package that declares more than one file type, the
exports and the pictures of one object. The arguments are then one triple per
file, its path, its working directory and its script, and standard input is one
document: under OUTPUTS_KEY the request each would have been handed on its own,
less the object, which is under SUBJECTS_KEY once and named by every request
that is of it (SUBJECT_KEY). Each file is written exactly as it would have been
on its own - in its own working directory, with 'sys.argv' and 'sys.path' as it
would have found them - and answered the moment it is done, on a line of its
own that says which file the answer is for (OUTPUT_KEY, RESULT_KEY). A file
left unanswered, because the process died or because something failed before
its implementation was reached, the core writes again in a call of its own, so
that it fails the way it always did and takes nothing else with it.

What it saves is what is not done again. The interpreter starts once and
imports the CAD stack once, which for anything short of a large assembly is
most of the time a file takes; and the files that may share one decoding of the
object get one, and find on its faces the mesh the first of them made (see
TESSELLATION_NAME).
"""

import ast
import gc
import hashlib
import json
import os
import runpy
import sys

sys.path.append(os.path.dirname(__file__))
import kinematics
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

# The key the core puts each shape's resolved physics under, keyed by
# 'kinematics.properties_key()' - a part's full name, an assembly's or a scene's
# kind and full name, so that a part and an assembly that share a name each get
# their own (see 'properties_index()' below): what the shape states, what its
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

# What an implementation wrote besides the file at 'path', as a list of paths
# relative to the directory that file is in, and the one result key passed on
# even when it is empty: an empty list says "nothing else", which is a statement,
# and the absence of the key says nothing at all. The core caches an answer only
# when it was told what the answer consists of. Its twin is
# 'partcad.output.FILES_KEY'.
FILES_KEY = "files"

# The document a call writing several files is handed, and the lines it answers
# with (see the module's docstring). The twins of these are the 'BATCH_*' keys of
# 'partcad.output', spelled out separately for the reason JOINT_KEY is.
#
# OUTPUTS_KEY: one entry per file, in the order of the arguments, each holding
# the request under REQUEST_KEY and, when the request is of the object, which
# of SUBJECTS_KEY that is under SUBJECT_KEY. The object is there once rather
# than once per file because it is the one big thing in the document: every
# payload in it is written once already (see 'ocp_serialize.KEY_BREPS'), and
# the tree around them - names, placements, properties - is the rest.
OUTPUTS_KEY = "outputs"
SUBJECTS_KEY = "subjects"
SUBJECT_KEY = "subject"
REQUEST_KEY = "request"
# Each answer: which file, by its place in OUTPUTS_KEY, and what writing it said.
OUTPUT_KEY = "output"
RESULT_KEY = "result"

# What an implementation may say, as a module-level literal, about what it does
# to the shape it is handed. Read rather than asked for, the way CACHE_VERSION
# is ('partcad.code_version'), because which files may share a decoding has to
# be known before any of them is handed one:
#
#     TESSELLATION = ("relative", "tolerance", "angularTolerance")
#
# says that the one thing it leaves on the shape is a mesh, and that what it
# writes is decided by the exact geometry and that mesh and nothing else. The
# first name says how it meshes, and the rest which of its request's parameters
# the mesh is made with. Two files of one object whose implementations declare
# the same, with the same values for those parameters, are handed one decoding
# of the object, and the second finds the first one's mesh on its faces. That
# is the mesh it would have made itself: OCCT keeps a face's mesh when it is as
# fine as the one asked for, and a mesh is a function of the face and of how it
# was asked for. So each file comes out exactly as it does on its own, and the
# object is decoded and meshed once for all of them.
#
# Saying nothing is saying "assume nothing", and is what every implementation
# PartCAD does not ship says: it is handed a decoding of its own, as it was
# when every file had a process of its own. So is every file of an object that
# arrived with a mesh on it already ('carries_mesh'), because there a second
# mesh call may keep some of what arrived and replace the rest, and two files
# that would each have replaced it all could disagree about what is left.
#
# It is a claim to be checked rather than assumed, by writing the file after
# another of its group and comparing it with the file written alone: the glTF
# exporter meshes the way STL and 3MF do and still may not say so, because it
# turns the shape to Y-up before meshing it (see 'export_gltf.py').
TESSELLATION_NAME = "TESSELLATION"


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

    A part and an assembly (or a scene) used to be able to share a name within
    a package, and so a full name: the assembly 'nut' that holds the part 'nut'.
    A package can no longer declare that ('partcad_utils.object_names'), but a
    tree cached before it could not is still handed here as it was. The full name
    is then the part's - it is what every exporter looks a part up by, for its
    colour and its density - and the assembly's entry is under its kind and
    full name as well ('kinematics.properties_key()'), even when it has nothing
    in it, so that 'kinematics.properties_of()' never hands it the part's
    instead. Until it was, whichever of the two the walk reached last took the
    entry, and an assembly exported with its namesake inside it weighed what
    that part weighs. A full name nothing else carries is indexed exactly as it
    always was.
    """
    resolved_physics = request.get(PHYSICS_KEY) or {}

    def resolved(obj, properties):
        """One shape's properties, with its resolved physics under its own."""
        facts = resolved_physics.get(kinematics.properties_key(obj))
        if not facts:
            return properties
        physics = dict(facts)
        physics.update(properties.get("physics") or {})
        return dict(properties, physics=physics)

    # (kind, full name, key, entry) for every named shape, in the order walked.
    found = []

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
            if name:
                found.append((kinematics.kind_of(obj), name, kinematics.properties_key(obj), resolved(obj, properties)))
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

    kinds = {}
    for kind, name, _key, _entry in found:
        kinds.setdefault(name, set()).add(kind)
    index = {}
    for kind, name, key, entry in found:
        shared = len(kinds[name]) > 1
        if shared and kind != kinematics.PART:
            index[key] = entry
        if entry and (kind == kinematics.PART or kinematics.PART not in kinds[name]):
            index[name] = entry
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
    #
    # 'viewport' is a 'render:' implementation's: where a projection was looked
    # at from, whoever chose it - the request, the package, or the default for the
    # kind of shape (see 'render_svg.VIEWPORT_KEY'). What the IDE's 2D tab shows
    # beside the picture, so that its viewpoint is the picture's rather than a
    # guess at it.
    for key in ("warnings", "unsupported", "findings", "stats", "viewport"):
        if output.get(key):
            result[key] = output[key]
    # Passed on when it is a list at all, empty included: see FILES_KEY. A value
    # that is not one is the implementation saying something nobody can act on,
    # which is the same as saying nothing.
    if isinstance(output.get(FILES_KEY), (list, tuple)):
        result[FILES_KEY] = [str(name) for name in output[FILES_KEY]]
    return result


def decode(request, shared=None):
    """The request as the implementation is handed it: every envelope in it decoded.

    The object itself is decoded into both of the forms it is handed in -
    'wrapped' and 'shape_tree' - out of one decoding of each of its shapes.
    Anything else that is a shape (the sketch of a port, say) becomes live
    geometry, as it always has.

    'shared' is the decoding this request shares with others of the same call,
    payload by payload (see 'ocp_serialize.decode_tree'): every request is
    handed shapes of its own, and they share their geometry with the others.
    """
    shared = {} if shared is None else shared
    wrapped = request.pop(WRAPPED_KEY, None)
    request = ocp_serialize.decode(request, shared)
    if ocp_serialize.is_shape_object(wrapped) or ocp_serialize.is_assembly_object(wrapped):
        request[WRAPPED_KEY], request[SHAPE_TREE_KEY] = ocp_serialize.decode_tree(wrapped, shared)
    elif wrapped is not None:
        request[WRAPPED_KEY] = ocp_serialize.decode(wrapped, shared)
    return request


def run(script, path, request, shared=None, decoded=None):
    """Write one file, and say how it went: all of what this wrapper does for one of them.

    'request' is as it travelled, its envelopes undecoded; 'shared' as 'decode'
    has it. 'decoded', if given, is called once the request has been decoded and
    before the implementation is handed it.
    """
    # Before the decode, while the envelopes - and so the properties they carry
    # - are still there to be read.
    if request.get(PROPERTIES_KEY) is True:
        request[PROPERTIES_KEY] = properties_index(request)
    # Read by 'properties_index' above and nothing else: an implementation is
    # handed the physics of each shape in the index, not a second table to
    # look it up in. A format that declares no 'properties: true' never asked
    # for either.
    request.pop(PHYSICS_KEY, None)
    request = decode(request, shared)
    if decoded is not None:
        decoded()
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
    return result


def arguments(argv):
    """The (path, working directory, script) of each file a call writes, as its arguments name them."""
    return [
        (os.path.normpath(argv[index]), os.path.normpath(argv[index + 1]), argv[index + 2])
        for index in range(1, len(argv) - 2, 3)
    ]


# What each script declared, by path: a call reads each one once.
_declared = {}


def declared_tessellation(script):
    """What 'script' declares under TESSELLATION_NAME, as a tuple of names, or None.

    Parsed, never run, for the reason given beside TESSELLATION_NAME. Anything
    but a non-empty tuple or list of strings - nothing at all, a value that is
    not a literal, a script that cannot be read - is None: a decoding of its own.
    """
    if script in _declared:
        return _declared[script]
    found = None
    try:
        with open(script, encoding="utf-8") as f:
            body = ast.parse(f.read(), filename=script).body
    except (OSError, SyntaxError, ValueError):
        body = []
    for node in body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == TESSELLATION_NAME for target in targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            value = None
        if isinstance(value, (tuple, list)) and value and all(isinstance(item, str) for item in value):
            found = tuple(value)
        break
    _declared[script] = found
    return found


def sharing_key(script, entry):
    """Which decoding one of several files may share, as a key two of them have equal, or None for one of its own.

    The object it is of, the way its implementation meshes, and the values of
    the parameters it meshes with: see TESSELLATION_NAME.
    """
    declared = declared_tessellation(script) if script else None
    subject = entry.get(SUBJECT_KEY)
    if declared is None or not isinstance(subject, int) or isinstance(subject, bool):
        return None
    request = entry.get(REQUEST_KEY) or {}
    # By digest: a parameter may be the ports to draw, sketches and all.
    values = tuple(
        hashlib.sha256(json.dumps(request.get(name), sort_keys=True, default=str).encode("utf-8")).hexdigest()
        for name in declared[1:]
    )
    return (subject, declared[0]) + values


def carries_mesh(shapes):
    """Whether any of these shapes holds a mesh already: a triangulation on a face, a polygon on an edge.

    Asked of the shapes as they were decoded and before anything is written from
    them, so that what it finds arrived with the object.
    """
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    for shape in shapes:
        explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
        while explorer.More():
            if BRep_Tool.Triangulation_s(TopoDS.Face_s(explorer.Current()), TopLoc_Location()) is not None:
                return True
            explorer.Next()
        explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_EDGE)
        while explorer.More():
            if BRep_Tool.Polygon3D_s(TopoDS.Edge_s(explorer.Current()), TopLoc_Location()) is not None:
                return True
            explorer.Next()
    return False


def plan(outputs, keys):
    """The order to write several files in: those that share a decoding one after another.

    Each group where its first file was asked for, and the files of a group in
    the order asked for. Unless two of them are one file: then nothing is
    reordered, because which of them is left there is whichever was written
    last. (The core does not put two such in one call; this does not rely on it.)
    """
    paths = [os.path.normcase(os.path.abspath(path)) for path, _directory, _script in outputs]
    if len(set(paths)) != len(paths):
        return list(range(len(outputs)))
    first = {}
    for index, key in enumerate(keys):
        if key is not None:
            first.setdefault(key, index)
    return sorted(range(len(outputs)), key=lambda index: (first.get(keys[index], index), index))


def request_of(entry, subjects):
    """One file's request as it would have arrived on its own: with the object it is of put back."""
    request = dict(entry.get(REQUEST_KEY) or {})
    subject = entry.get(SUBJECT_KEY)
    if isinstance(subject, int) and not isinstance(subject, bool) and 0 <= subject < len(subjects):
        request[WRAPPED_KEY] = subjects[subject]
    return request


def run_together(outputs, document):
    """Write several files of one object in this one process, answering for each as soon as it is written.

    One decoding of the object is alive at a time: the one a group of files
    shares, for as long as the group lasts, and otherwise one per file, let go
    of before the next is made. That is what keeps a call writing five files of
    a large assembly at the memory one of them takes.
    """
    entries = document.get(OUTPUTS_KEY) if isinstance(document, dict) else None
    subjects = document.get(SUBJECTS_KEY) or []
    if not isinstance(entries, list) or len(entries) != len(outputs):
        raise ValueError(
            "Asked to write %d files and handed %s"
            % (len(outputs), "%d requests" % len(entries) if isinstance(entries, list) else "none")
        )
    keys = [sharing_key(script, entry) for (_path, _directory, script), entry in zip(outputs, entries)]
    # Whether each object arrived with a mesh on it, once its first decoding says.
    meshed = {}
    # The decoding alive, as (which files may share it, payload -> shape).
    decoding = None
    frozen = False
    argv = list(sys.argv)

    def let_go():
        nonlocal decoding, frozen
        if decoding is None:
            return
        decoding = None
        # Its shapes are held by the last implementation's globals as well,
        # which 'runpy' leaves in a reference cycle with the functions defined
        # there, so they are freed by a collection rather than by the last name
        # for them going. The first collection is the one that pays for the CAD
        # stack the first file imported; what is left alive after it is frozen
        # (moved out of every later collection's way), so the ones after it look
        # at what the files since have made and nothing else.
        gc.collect()
        if not frozen:
            gc.freeze()
            frozen = True

    for index in plan(outputs, keys):
        path, directory, script = outputs[index]
        key = keys[index]
        if key is not None and meshed.get(key[0]):
            key = None
        if decoding is None or key is None or decoding[0] != key:
            let_go()
            decoding = (key, {})
        shared = decoding[1]
        fresh = not shared

        def decoded():
            if key is not None and fresh and key[0] not in meshed:
                meshed[key[0]] = carries_mesh(list(shared.values()))

        saved_path = list(sys.path)
        try:
            os.chdir(directory)
            sys.argv[:] = [argv[0], path, directory, script]
            result = run(script, path, request_of(entries[index], subjects), shared, decoded)
        except Exception as e:
            # Not the implementation's failure, which 'process' answers for: the
            # wrapper's own, before or around it. Left unanswered, so the core
            # writes this file again in a call of its own and it fails there the
            # way it does on its own.
            wrapper_common.handle_exception(e, script)
            result = None
        finally:
            sys.path[:] = saved_path
            sys.argv[:] = argv
        if result is not None:
            wrapper_common.handle_output({OUTPUT_KEY: index, RESULT_KEY: result}, end="\n")
        # A file that may not share, or that failed and may have left the
        # shapes half done, lets its decoding go with it.
        if key is None or meshed.get(key[0]) or result is None or not result.get("success"):
            let_go()


if __name__ == "__main__":
    # Read raw and decoded below rather than on the way in, because the
    # properties index is read off the envelopes, and decoding consumes them.
    path, request = wrapper_common.handle_input(decode=False)
    outputs = arguments(sys.argv)
    if len(outputs) > 1:
        run_together(outputs, request)
    else:
        script = sys.argv[SCRIPT_ARGUMENT] if len(sys.argv) > SCRIPT_ARGUMENT else None
        wrapper_common.handle_output(run(script, path, request))
