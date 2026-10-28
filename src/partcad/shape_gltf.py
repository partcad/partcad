#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The glTF form of a shape tree: the same tree, tessellated.

A shape is carried as a tree of nodes - a part is one node, an assembly is a node
per thing it holds, an interface is a node per port - and the geometry at each
node takes one of two forms (see 'shape_envelope.FORM_BREP' / 'FORM_GLTF'). BREP
is what the core composes and caches, because it is exact. glTF is what something
can draw, because it is triangles. This module is the conversion from the first
to the second, and it is a conversion of the *tree*: nothing about the hierarchy,
the names, the placements or the ports changes, only what sits at each node that
has geometry.

It runs in a sandbox, like every other operation on geometry: the core has no CAD
library and never holds a live OCP object. One sandbox for all of a tree's shapes
rather than one per node, because starting an interpreter and importing OCP is
seconds and tessellating a part is not - an assembly of five hundred parts
converted one node at a time would cost longer than building it. And only for the
shapes it has not tessellated before: each shape's glTF is cached on its own, and
the tree is put back together here, around them (see 'convert_async').

Nothing here is specific to the IDE viewer. The viewer is the one caller today
(see 'viewer.py'), and it is the reason the form exists, but a caller that wants
a drawable tree asks the shape for one: 'shape.get_representation(ctx, "gltf")'.
"""

import math

from . import cache_artifacts
from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, wrapper
from .process_crash import describe_exit_code

# The tessellation a preview gets, as a budget in *pixels* rather than a distance
# in millimetres. A preview is looked at, so what decides whether it is fine
# enough is how far a facet lands from the surface on the screen - and that is the
# chord error divided by what a pixel is worth, which depends on the size of the
# thing being shown. A part 5 mm across and an assembly 5 m across want the same
# answer to "is this smooth enough" and two very different deflections to get it.
#
# So the linear deflection is derived, per tree, from the overall size of that
# tree: SCREEN_PIXELS is the viewport this budget assumes, PIXEL_BUDGET is how much
# of one pixel the tessellation may be out by, and the wrapper divides the
# bounding box diagonal by the two of them together (see 'wrapper_gltf._budget').
# At a half pixel over a thousand, a facet is out by a five-hundredth of what is on
# screen, whatever the object is.
#
# It is a budget for the whole object shown at once, which is what the viewer shows
# when a tree arrives, and deliberately not for a close-up: zoom far enough into
# any tessellation and it is faceted. Trading that away is what makes an assembly
# openable at all.
SCREEN_PIXELS = 1000
PIXEL_BUDGET = 0.5
SCREEN_DIVISOR = SCREEN_PIXELS / PIXEL_BUDGET

# What that budget may not exceed in either direction, in mm. The floor keeps a
# tiny object from being tessellated to death for no visible gain, and the ceiling
# keeps a bogus bounding box - a stray node a kilometre from the origin - from
# flattening everything else into facets.
MIN_TOLERANCE = 0.001
MAX_TOLERANCE = 10.0

# The values the linear deflection is rounded down onto: the R10 series of
# preferred numbers (ISO 3), ten to a decade, each about a fifth smaller than the
# one above it - 0.1, 0.125, 0.16, 0.2, 0.25, 0.315, 0.4, 0.5, 0.63, 0.8, 1 mm.
#
# Rounded at all because a tessellation is cached per shape, keyed on the
# deflection it was made at (see 'convert_async'), and the deflection is a
# fraction of the size of the whole tree: without the rounding, moving one part of an assembly a millimetre,
# or adding a washer at its edge, would change the diagonal by a hair, the
# deflection with it, and so the key of every shape in the tree - and the whole
# assembly would be tessellated again for a difference nobody could see. Rounded,
# a tree keeps its deflection until its size moves by a step, and every cached
# shape in it stays a hit. Rounding down by less than a step is a preview at most
# a fifth finer than the budget asks for, never coarser: within what the budget
# is a guess at anyway.
TOLERANCE_SERIES = (1.0, 1.25, 1.6, 2.0, 2.5, 3.15, 4.0, 5.0, 6.3, 8.0)

# What to assume when a tree records no size at all. Every shape a wrapper returned
# carries the box it was measured in as it was built, so this is for the tree that
# carries none: one whose metadata was stripped, or one with no geometry in it,
# where the tolerance decides nothing because there is nothing to tessellate.
#
# A stated nominal size rather than the floor, because the floor is the finest
# setting there is and a tree of unknown size is the last one to spend that on.
# Palm-sized, which is what a part usually is.
NOMINAL_SIZE = 100.0

# The angular cap, in radians, and the one number here that is *not* a function of
# the object's size - which is exactly why it is the one that matters most on a
# large assembly. A curve is tessellated to whichever is the finer of the linear
# budget above and this angle between successive segments, and for a small radius
# the angle always wins: at 0.2 rad a 3 mm hole is drawn with 31 segments whether
# it covers two hundred pixels or two. So its job here is only to keep a circle
# from degenerating into a triangle, and the linear budget above does the real
# work.
#
# Measured on '//pub/examples/partcad/feature_import:AeroAssembly_assy_example/
# AeroAssembly_connected' (8 parts, 413 mm diagonal), holding the linear budget at
# diagonal/2000: 0.2 rad gives 48304 triangles, 0.3 gives 30624, 0.4 gives 23480,
# 0.5 gives 19752. The knee is between 0.3 and 0.5; below it the extra triangles
# are nearly all in small features that are a few pixels across when the whole
# object is shown.
DEFAULT_ANGULAR_TOLERANCE = 0.4

# export_gltf is build123d's, and both are what every sandbox's own environment
# holds (see 'runtime_python.base_requirements').
_DEPENDENCIES = (sandbox_versions.BUILD123D, sandbox_versions.OCP)

# What a stored tessellation is: one entry per shape, keyed by its geometry,
# rather than one per tree. Part of the question an entry answers, so that a
# change to what an entry holds is a change of key, and never two layouts read
# under one.
GEOMETRY_ENTRIES = "glTF per geometry, v1"

# What the rest of an entry is, as its first byte: the glTF payload as the text
# it travelled as, the same payload as bytes, or the finding that the shape has
# nothing to draw, followed by the reason. The payload is stored exactly as it
# came back from the sandbox and handed back exactly so. What it is - how the
# glTF is compressed, how it is written down - is the wrapper's business (see
# 'ocp_serialize.encode_gltf'), and the wrapper's code is in the key, so two
# encodings are never read back under one. It is deflated already, which is why
# nothing compresses it again here: that would cost every hit a decompression
# for next to nothing.
_ENTRY_TEXT = b"t"
_ENTRY_BYTES = b"b"
_ENTRY_NOTHING = b"n"


def size_of(tree):
    """The diagonal of what 'tree' occupies, in mm, or None if it records none.

    Arithmetic over numbers already in hand: every shape a wrapper returned carries
    the box it was measured in when it was built, because building it is what
    measured it (`ocp_serialize.encode_shape` -> `metadata.measurements.bbox`). So
    the size of a whole tree costs no kernel, no sandbox and no second opinion - it
    is the same box `Shape.get_bounding_box_async()` hands every other caller that
    needs a size, composed down the tree.

    The placements are composed on the way down, because that is what decides how
    big the thing on the screen is: eight parts 50 mm across are 50 mm if they sit
    on top of each other and 2 m if they are spread out. A node's box is in its own
    coordinates, so its eight corners are placed and re-bounded rather than its two
    extremes moved - a rotated box's extremes are not the extremes of the rotated
    box. Re-bounding a rotated box over-states it, never the reverse, so a tree of
    rotated parts is sized a little large and tessellated a little coarse: the safe
    direction for a budget whose other end is the cost of drawing.

    Only the nodes. The sketches a port is drawn with sit at a port, which is inside
    the object whose port it is, so they cannot make a tree bigger than its nodes
    already make it.
    """
    from .geom import Location

    low = [None, None, None]
    high = [None, None, None]

    def corners(box):
        x0, y0, z0, x1, y1, z1 = box
        return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]

    def walk(node, location):
        if not isinstance(node, dict):
            return
        own = node.get(shape_envelope.KEY_LOCATION)
        if own is not None:
            placement = own if isinstance(own, Location) else Location(own)
            location = placement if location is None else location * placement
        box = (
            shape_envelope.metadata_section(node.get(shape_envelope.KEY_METADATA), shape_envelope.METADATA_MEASUREMENTS)
            or {}
        ).get(shape_envelope.METADATA_BBOX)
        if box and len(box) == 6:
            for point in corners(box):
                placed = point if location is None else location.transform_point(point)
                for axis in range(3):
                    value = placed[axis]
                    if low[axis] is None or value < low[axis]:
                        low[axis] = value
                    if high[axis] is None or value > high[axis]:
                        high[axis] = value
        for child in node.get(shape_envelope.KEY_ASSEMBLY) or []:
            walk(child, location)

    walk(tree, None)
    if low[0] is None:
        return None
    return math.sqrt(sum((high[axis] - low[axis]) ** 2 for axis in range(3)))


def tolerance_for(tree):
    """The linear deflection to tessellate 'tree' at, in mm: the budget, applied.

    The one place that turns "half a pixel of a thousand" into millimetres, so that
    the viewer, a test and anything else asking the same question get the same
    number. Rounded down onto 'TOLERANCE_SERIES' (see 'bucketed').
    """
    size = size_of(tree)
    if not size:
        size = NOMINAL_SIZE
    return bucketed(min(max(size / SCREEN_DIVISOR, MIN_TOLERANCE), MAX_TOLERANCE))


def bucketed(tolerance: float) -> float:
    """'tolerance' rounded down to the nearest value of 'TOLERANCE_SERIES', in mm.

    Down, never up: the deflection used is at most one step finer than the budget
    asked for and never coarser, so a preview is never less smooth than the budget
    says. The value is written out from its decimal digits rather than computed,
    so that it is the same float on every machine - it is part of a cache key, and
    a key that differed in its last bit between two machines would split a shared
    tier in two.
    """
    # A hair of slack throughout, so that a tolerance a rounding error short of a
    # value of the series - 0.1 worked out as 0.0999... - is that value rather
    # than the one below it.
    slack = 1 + 1e-9
    exponent = math.floor(math.log10(tolerance))
    mantissa = tolerance / 10.0**exponent
    if mantissa * slack >= 10.0:
        exponent += 1
        mantissa /= 10.0
    step = TOLERANCE_SERIES[0]
    for value in TOLERANCE_SERIES:
        if value <= mantissa * slack:
            step = value
    return float("%re%d" % (step, exponent))


async def in_form_async(ctx, tree, form, cacheable: bool = True, section=None):
    """'tree' with its geometry in 'form', whatever form it arrived in.

    The one place that decides what a form means, so that every kind of subject -
    a part, an assembly, an interface - answers 'get_representation()' the same
    way and none of them has to know that glTF is produced by a sandbox.

    'cacheable' is False for a subject that says `cache: false`, whose
    tessellation is then never remembered (see 'convert_async').

    'section' cuts the geometry by a box first (see 'shape_section'), in a
    sandbox of its own and cached as its own answer, and the glTF form is then
    the cut tree tessellated a shape at a time (see 'convert_async').
    """
    from . import shape_section

    section = shape_section.normalize(section)
    if form == shape_envelope.FORM_BREP:
        if section is None:
            return tree
        return await shape_section.section_async(ctx, tree, section, cacheable=cacheable)
    shape_envelope.geometry_key(form)
    if tree is None:
        return None
    return await convert_async(ctx, tree, cacheable=cacheable, section=section)


async def convert_async(ctx, tree, tolerance=None, angular_tolerance=None, cacheable: bool = True, section=None):
    """'tree' with its geometry tessellated into glTF, one copy per distinct shape.

    'tolerance' is the linear deflection in mm. Left at None - which is how the
    viewer asks - it is worked out here from what the tree records about its own
    size (see 'tolerance_for'). Passing one overrides that outright, for a caller
    that knows what it wants in millimetres.

    What comes back carries the geometry on the root, in KEY_GEOMETRY, with every
    node naming its entry: a hundred instances of one bolt are one entry named a
    hundred times.

    Raises if the sandbox could not be run or answered a failure. A single node
    whose geometry will not tessellate is not that: it comes back without
    geometry and with the reason logged, because the rest of the tree is still
    worth looking at. A sketch made of edges alone is not such a node: its edges
    are drawn as line segments (see 'wrapper_gltf._to_glb').

    **Each shape's tessellation is cached on its own** (see 'GEOMETRY_ENTRIES'),
    keyed on the digest of its exact geometry and the tolerances, so that showing
    an object again, in this process or the next, starts no sandbox - and showing
    it after one of its parts was edited tessellates that part and nothing else.
    The tree is not in the key, and is never serialized to find one: the digests
    are worked out from the payloads the tree already holds, every distinct one
    is looked up, and only what is missing goes to a sandbox - only the payloads,
    one each. The answer is then put together here, out of the tree as it came
    and the glTF of each of its shapes, wherever that came from. Keyed on the
    bytes rather than on the subject's own cache key, because the port sketches
    are attached after the shape cache has answered and no key of the subject
    covers them. 'cacheable' False - a subject with `cache: false` - is
    tessellated every time.

    'section', a box from 'shape_section.normalize', cuts the tree first, by
    'shape_section.section_async' - which caches the cut as it caches any - and
    what is tessellated is the cut tree's shapes, by the same rule: a cut cannot
    be made a shape at a time, since a box in the root's frame cuts each
    placement of a shape differently, but what it leaves are shapes like any
    other, and a part the box misses keeps its geometry, its digest and so its
    entry. A node the box takes all of is left with no geometry at all. The
    tolerance is still the whole tree's: what the nodes record about their size
    is the object's and not the cut's, so a cut is drawn as finely as the object
    it was cut from.
    """
    if ctx is None:
        raise ValueError("A context is required to tessellate a shape tree")
    if not shape_envelope.is_node(tree):
        raise ValueError("Not a shape tree: %r" % (list(tree) if isinstance(tree, dict) else type(tree),))

    # Decided here and sent as millimetres. The sandbox is handed a number rather
    # than a policy because the size it would be worked out from is already known
    # here: asking the geometry again, in the one process that has a kernel, would
    # be a second answer to "how big is it" (see 'size_of').
    tolerance = tolerance_for(tree) if tolerance is None else float(tolerance)
    angular_tolerance = DEFAULT_ANGULAR_TOLERANCE if angular_tolerance is None else float(angular_tolerance)

    if section:
        from . import shape_section

        tree = await shape_section.section_async(ctx, tree, section, cacheable=cacheable, keep_empty=False)

    shapes = _Shapes()
    converted = shapes.convert(tree)
    payloads = shapes.payloads.by_digest

    cache = getattr(ctx, "cache_artifacts", None)
    artifact = None
    if cacheable and payloads:
        artifact = cache_artifacts.wrapper_entries_hash(
            "%s#gltf" % (tree.get("name") or "tree"),
            "gltf.py",
            _DEPENDENCIES,
            question={"entries": GEOMETRY_ENTRIES, "tolerance": tolerance, "angularTolerance": angular_tolerance},
        )
    geometry, nothing = _restored(await cache_artifacts.restore_entries_async(cache, artifact, list(payloads)))
    from_cache = len(geometry) + len(nothing)

    missing = {
        digest: payload for digest, payload in payloads.items() if digest not in geometry and digest not in nothing
    }
    if missing:
        tessellated, empty, failed = await _tessellate_async(ctx, tree, missing, tolerance, angular_tolerance)
        # Only an answer is remembered: a shape that has glTF, or one that has
        # nothing to draw, which is the same answer for the same geometry on any
        # machine. A shape that would not tessellate is tried again next time,
        # alone, because why it failed may be this sandbox's doing rather than
        # the geometry's - and everything else in the tree is a hit regardless.
        entries = {digest: _entry(payload) for digest, payload in tessellated.items()}
        entries.update({digest: _nothing_entry(reason) for digest, reason in empty.items()})
        await cache_artifacts.store_entries_async(cache, artifact, entries)
        geometry.update(tessellated)
        nothing.update(empty)
        nothing.update(failed)

    # Once per distinct shape rather than once per node naming it: a hundred
    # instances of one part that will not tessellate are one thing wrong.
    for digest in payloads:
        if digest not in geometry:
            pc_logging.warning("Nothing to draw for %s: %s" % (shapes.labels[digest], nothing.get(digest)))
    for node, digest in shapes.nodes:
        if digest in geometry:
            node[shape_envelope.KEY_GLTF_REF] = digest
    converted[shape_envelope.KEY_GEOMETRY] = {digest: geometry[digest] for digest in payloads if digest in geometry}
    if not shape_envelope.is_node(converted):
        # A lone shape with nothing to draw: there is no tree left to show, and
        # why was reported just above.
        raise Exception("The tessellation of %s produced no shape tree" % (tree.get("name") or "a shape"))

    if from_cache:
        pc_logging.debug(
            "Tessellated %s: %d of %d shape(s) from the cache"
            % (tree.get("name") or "a shape tree", from_cache, len(payloads))
        )
    return converted


def _entry(payload) -> bytes:
    if isinstance(payload, str):
        return _ENTRY_TEXT + payload.encode("utf-8")
    return _ENTRY_BYTES + bytes(payload)


def _nothing_entry(reason) -> bytes:
    return _ENTRY_NOTHING + str(reason or "").encode("utf-8")


def _restored(entries):
    """The glTF and the 'nothing to draw' findings in what the cache had, by digest.

    An entry that is not one of the three is passed over, which makes it a miss:
    it is read from tiers other machines write to, and tessellating again is
    always a valid answer.
    """
    geometry, nothing = {}, {}
    for digest, data in entries.items():
        kind, rest = data[:1], data[1:]
        if kind == _ENTRY_TEXT and rest:
            try:
                geometry[digest] = rest.decode("utf-8")
            except UnicodeDecodeError:
                continue
        elif kind == _ENTRY_BYTES and rest:
            geometry[digest] = rest
        elif kind == _ENTRY_NOTHING:
            nothing[digest] = rest.decode("utf-8", errors="replace") or "there is nothing to draw"
    return geometry, nothing


class _Shapes:
    """The distinct shapes of one tree, as the tree is converted around them.

    'convert()' makes the glTF form of the tree with the geometry left out: the
    same nodes, names, placements, ports and everything else, copied rather than
    shared so that nothing done to the answer reaches the tree it was made from
    (which is the BREP tree a shape keeps). Every node that had a payload is kept
    in 'nodes' with the digest of that payload, to be given the reference to its
    glTF once it is known.

    The digests come from 'shape_envelope.Payloads', which computes one per
    payload *object*: every node of a tree built in this process holds the bytes
    object of the part it is made of, so an assembly of a thousand instances of
    twenty parts costs twenty digests.
    """

    def __init__(self):
        self.payloads = shape_envelope.Payloads()
        self.labels = {}
        self.nodes = []

    def convert(self, value):
        """'value' with every piece of BREP in it taken out and its node recorded.

        A walk of the whole structure rather than of the places a node's
        geometry is known to sit. Geometry turns up in more than one of them - a
        node's own, the nodes inside it, the sketches the ports of an object are
        drawn with - and a walk that knew the list would quietly hand the browser
        BREP the day the core added another. Anything that is not geometry is
        copied through untouched, as JSON would have it: a tuple as a list.
        """
        if isinstance(value, dict):
            converted = {key: self.convert(item) for key, item in value.items() if key != shape_envelope.KEY_BREP}
            brep = value.get(shape_envelope.KEY_BREP)
            if brep:
                digest = self.payloads.ref(brep)
                if digest not in self.labels:
                    self.labels[digest] = value.get("label") or value.get("name") or "a shape"
                self.nodes.append((converted, digest))
            return converted
        if isinstance(value, (list, tuple)):
            return [self.convert(item) for item in value]
        return value


async def _tessellate_async(ctx, tree, payloads, tolerance, angular_tolerance):
    """Tessellate 'payloads' (by digest) in one sandbox: '(glTF, empty, failed)', each by digest.

    Raises if the sandbox could not be run or answered a failure. One shape that
    would not tessellate is not that: it is in 'failed' with the reason.
    """
    runtime = ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
    for dep in _DEPENDENCIES:
        await runtime.ensure_async(dep)

    # Each payload once, under the digest it is named by here, and nothing of
    # the tree: the tree is put back together in the core (see 'convert_async').
    # Serialized when the process starts, for the reason 'runtime.stdin_bytes'
    # gives.
    request = {
        "shapes": [{"digest": digest, shape_envelope.KEY_BREP: payload} for digest, payload in payloads.items()],
        "tolerance": tolerance,
        "angularTolerance": angular_tolerance,
    }
    # argv[1] is mandatory for every wrapper (wrapper_common.handle_input reads
    # it as the output path). This one writes no file - the glTF comes back over
    # the pipe - so it carries the operation name, which is what shows up in
    # process listings and logs.
    exitcode, response_serialized, errors = await runtime.run_async(
        [wrapper.get("gltf.py"), "gltf"],
        lambda: shape_envelope.serialize(request),
    )
    if exitcode != 0 and not errors:
        errors = "Failed to tessellate the shape tree (%s)" % describe_exit_code(exitcode)
    if errors:
        raise Exception(errors)

    result = shape_envelope.deserialize(response_serialized)
    if not result.get("success", False):
        raise Exception(result.get("exception") or "Failed to tessellate the shape tree")

    def table(key):
        value = result.get(key)
        return value if isinstance(value, dict) else {}

    geometry, empty, failed = {}, {}, {}
    answered, found_empty, found_failed = table("geometry"), table("empty"), table("failed")
    for digest in payloads:
        payload = answered.get(digest)
        if isinstance(payload, (str, bytes)) and payload:
            geometry[digest] = payload
        elif digest in found_empty:
            empty[digest] = found_empty[digest]
        else:
            # Said to have failed, or not mentioned at all: either way nothing
            # to draw this time, and nothing to remember.
            failed[digest] = found_failed.get(digest) or "the tessellation did not answer for it"

    # A preview whose faces were not merged is one with a draw call per face rather
    # than per shape, which is the difference between an assembly that can be
    # orbited and one that cannot. It still draws, so this is a warning and not a
    # failure - but it is not something to discover by watching the frame rate.
    if result.get("mergedFaces") is False:
        pc_logging.warning(
            "Tessellated without merging faces, so this preview has one draw call per face: %s"
            % (result.get("mergeFacesReason") or "the exporter did not support it")
        )

    # Worth one line in the log: it is the number that decides both how long this
    # took and how big what it produced is, and it is not in the configuration
    # anywhere to be read off.
    pc_logging.debug(
        "Tessellated %d shape(s) of %s: %s"
        % (
            len(payloads),
            tree.get("name") or "a shape tree",
            ", ".join(
                "%s=%s" % (key, result[key])
                for key in ("tolerance", "angularTolerance", "mergedFaces")
                if key in result
            ),
        )
    )
    return geometry, empty, failed
