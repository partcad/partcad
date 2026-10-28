#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-01
#
# Licensed under Apache License, Version 2.0.
#

# This script contains code shared by all wrapper scripts.

# import fcntl  # TODO(clairbee): replace it with whatever works on Windows if needed
import locale
import os
import sys

import ocp_serialize

# The name/label the request carried, echoed onto the shape a response returns
# (the sandbox does not otherwise know a shape's PartCAD name).
_request_name = None
_request_label = None

# What the request asks to be done to the part on its way out, or None: see
# 'finished()'. Only a part factory sends one.
_request_finish = None

# The response channel, once it has been taken away from everything else. See
# 'protect_response_channel()'.
_response_fd = None

# Whether the request came as a frame, which is what the answer then is too
# (see 'handle_output()'). Nothing read yet answers in JSON, which every reader
# of an answer reads.
_answer_framed = False


def protect_response_channel():
    """Give the response a file descriptor nothing else can write to.

    A wrapper answers PartCAD on its standard output, so anything else that
    writes there corrupts the answer -- and "anything else" is not hypothetical.
    OCCT's STEP writer prints a transfer summary on every 'Write()'; gmsh prints
    unless told twice not to; a script's own 'print()' lands there, as do the
    diagnostics in 'custom_cqgi.py' beside this file. A native library's output
    goes to file descriptor 1 directly, so 'contextlib.redirect_stdout' does not
    catch it and neither does reassigning 'sys.stdout' -- the only thing that
    does is taking the descriptor away.

    So descriptor 1 is pointed at standard error and the real one is kept here
    for 'handle_output()'. Everything that prints keeps working and its output
    lands in the log, where it is useful; the one thing that changes is that it
    can no longer be mistaken for part of the response.

    Called by 'handle_input()', which every wrapper starts with, so a wrapper
    need not know this happened. Best effort: a platform or a context where the
    descriptors cannot be moved leaves the channel as it was, which is what
    every wrapper had before this.
    """
    global _response_fd
    if _response_fd is not None:
        return
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        _response_fd = os.dup(1)
        os.dup2(2, 1)
    except OSError:
        _response_fd = None


def handle_input(decode=True):
    """Read the (path, request) pair a wrapper is invoked with.

    'decode' off keeps the request exactly as it travelled, with shape and
    assembly envelopes left as their dicts instead of being rebuilt into live
    OCCT geometry. A wrapper that needs a node's 'name' or 'label', or its
    location as separate data, needs that: decoding mirrors the tree in nested
    compounds but keeps geometry alone, dropping the names and baking the
    placements in (see ocp_serialize.decode, which hands each envelope it finds
    to decode_shape - the per-node walk that does this).
    """
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: %s <path>\n" % sys.argv[0])
        sys.exit(1)

    # Before the script runs, and before anything it imports can print.
    protect_response_channel()

    try:
        locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
    except locale.Error:
        # Same fallback as the CLI: the sandbox interpreter inherits the host's
        # locales, and a bare machine may have only "C" generated.
        try:
            locale.setlocale(locale.LC_ALL, "C.UTF-8")
        except locale.Error:
            pass

    # Handle the input
    # - Comand line parameters
    path = os.path.normpath(sys.argv[1])
    if len(sys.argv) > 2:
        os.chdir(os.path.normpath(sys.argv[2]))
    # - Content passed via stdin
    # #   - Make stdin blocking so that we can read until EOF
    # flag = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
    # fcntl.fcntl(sys.stdin, fcntl.F_SETFL, flag & ~os.O_NONBLOCK)
    #   - Read until EOF: a frame as it arrives, JSON to the end
    document = _read_request()
    #   - Unpack the content received via stdin
    request = ocp_serialize.decode(document) if decode else document
    remember_request(request)
    return path, request


def remember_request(request):
    """Keep what the response needs to know of 'request', and take off what is not the wrapper's.

    The name and label are echoed onto the shape the response returns. What the
    request asks to be done to a part on its way out is taken off rather than
    left in: it is addressed to 'finished()', not to the wrapper - and least of
    all to the package's own script, which a partType wrapper hands the request
    on to.
    """
    global _request_name, _request_label, _request_finish
    if isinstance(request, dict):
        _request_name = request.get("name")
        _request_label = request.get("label")
        finish = request.pop(ocp_serialize.KEY_FINISH, None)
        _request_finish = finish if isinstance(finish, dict) else None


def _read_request():
    """The request on standard input, undecoded, noting whether it came as a frame.

    As bytes: a frame's attachments are raw (see 'ocp_serialize.serialize'),
    and text is only what a JSON request - a container's - decodes to. A
    standard input that something replaced with text has no bytes to offer,
    and is read as JSON, which is all text can be.
    """
    global _answer_framed
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return ocp_serialize.deserialize_raw(sys.stdin.read())
    document, _answer_framed = ocp_serialize.read(stream)
    return document


def handle_output(model, end=""):
    """Answer PartCAD, on the descriptor `protect_response_channel()` kept.

    Written with 'os.write' rather than through a file object, because the
    descriptor is deliberately not 'sys.stdout' any more -- that one is standard
    error now, and is where everything else in this process prints.

    In the form the request came in. A request of PartCAD's own is a frame, and
    so is its answer: the document, then each distinct payload behind it as the
    bytes 'encode_shape()' wrote ('ocp_serialize.frame'). A request that came as
    JSON - a wrapper run in a container is sent that - is answered in JSON, with
    a payload the answer carries more than once written once all the same (see
    'ocp_serialize.KEY_BREPS'). The core reads both forms of every answer.

    'end' follows an answer in JSON: a wrapper that answers more than once, a
    line at a time as each answer is ready, passes a newline (see
    'wrapper_export'). A frame says itself where it ends, and is followed by
    nothing.
    """
    # Echoing the request's name/label onto the shape.
    out = None if _response_fd is not None else getattr(sys.stdout, "buffer", None)
    if _answer_framed and (_response_fd is not None or out is not None):
        pieces = ocp_serialize.frame(model, name=_request_name, label=_request_label)
    else:
        serialized = ocp_serialize.dumps(model, name=_request_name, label=_request_label, share=True) + end
        pieces = [serialized.encode("utf-8")]
    if _response_fd is None:
        # The channel is shared with everything that prints, so what printed
        # first goes out first: past the text layer's buffer, not around it.
        sys.stdout.flush()
        if out is None:
            sys.stdout.write(pieces[0].decode("utf-8"))
            sys.stdout.flush()
            return
        for piece in pieces:
            out.write(piece)
        out.flush()
        return
    for piece in pieces:
        # Through a view: 'os.write' may take less than it is given (a pipe, a
        # signal), and slicing the bytes themselves would copy what is left of a
        # multi-megabyte payload after every write that fell short.
        view = memoryview(piece).cast("B")
        while view:
            view = view[os.write(_response_fd, view) :]


def solidify(shape):
    """Replace every closed shell in 'shape' with the solid it already bounds.

    A shell is a skin: faces joined along their edges, with nothing said about
    which side of them is material. A solid is a shell that has been declared to
    bound a volume, and the declaration is the whole difference. It changes
    nothing about how the shape looks and everything about what can be computed
    from it: two 10 mm cubes overlapping by 5 mm share 500 mm^3 and add up to
    1500, and asking OCCT for either against the second one's *shell* returns a
    result with no solid in it and a volume of zero. So a part handed back as a
    shell builds, renders, exports and measures its right size while being
    useless for interference, CAM, FEA or a bill of materials, and nothing about
    it looks wrong.

    Which is worth fixing here rather than reporting, because a *closed* shell
    and the solid it bounds are the same geometry: the solid states what the
    shell already is. So a script that hands back 'Shell' instead of 'Solid' -
    which cadquery and build123d both let it do, as does a partType wrapper
    meshing triangles - produces the part that was meant.

    A shell that is **not** closed is left alone. There is no solid it bounds,
    and declaring one anyway would replace a shape that is honestly a surface
    with a solid OCCT reports as invalid and computes nonsense from - a worse
    thing than the shell, and a silent one. Such a shape reaches the core as a
    shell, which is what 'partcad.brep_inspect' looks for and the 'shell' check
    reports.

    A compound is descended into and rebuilt with the shells in it converted,
    which is the case that matters most in practice: both wrappers compound
    whatever a script returns, so a shell usually arrives inside one rather than
    on its own. Solids are left as they are, boundary shell included - a solid's
    shell is not a free shell, and rebuilding it would be the one way to break a
    shape this is supposed to leave alone.

    Returns the argument itself when nothing changed, so a part with no shell in
    it serializes to exactly the bytes it did before: rebuilding a compound bakes
    the parent's location into its children, and a shape nobody asked about must
    not move.
    """
    import OCP.TopAbs  # noqa: F401
    import OCP.TopoDS  # noqa: F401

    if shape is None or not isinstance(shape, OCP.TopoDS.TopoDS_Shape) or shape.IsNull():
        return shape

    shape_type = shape.ShapeType()
    if shape_type == OCP.TopAbs.TopAbs_SHELL:
        solid = _shell_to_solid(shape)
        return shape if solid is None else solid
    if shape_type != OCP.TopAbs.TopAbs_COMPOUND:
        return shape

    children = []
    changed = False
    iterator = OCP.TopoDS.TopoDS_Iterator(shape)
    while iterator.More():
        child = iterator.Value()
        solidified = solidify(child)
        changed = changed or solidified is not child
        children.append(solidified)
        iterator.Next()
    if not changed:
        return shape

    # Iterated cumulatively (TopoDS_Iterator's default), so each child comes out
    # with this compound's own location composed into it; the replacement is
    # therefore built at the identity rather than carrying that location twice.
    builder = OCP.TopoDS.TopoDS_Builder()
    rebuilt = OCP.TopoDS.TopoDS_Compound()
    builder.MakeCompound(rebuilt)
    for child in children:
        builder.Add(rebuilt, child)
    return rebuilt


def solid_problems(shape):
    """What keeps 'shape' from being a part made of solids. Empty when nothing does.

    The one definition of it, for every part whatever produced it - a script, a
    file importer, a partType plugin - and for everything that relies on it:
    the core validating a part as it is built, and the interference check
    deciding which parts it can intersect at all. A part fails it when:

    - it has no solid in it;
    - it has faces that belong to no solid (a shell, or loose faces beside the
      solids) - 'solidify' has already turned every closed shell into a solid,
      so what is left is open;
    - a solid in it is open: an edge carries one face only, which is a hole in
      the surface (an edge a face carries inside itself, INTERNAL, is not);
    - OCCT finds it invalid;
    - a solid in it has no volume, or a negative one - inside out.

    Each of those is a shape a boolean against answers with a number unrelated
    to any geometry, while it renders and measures like the part. That is the
    whole reason to ask.
    """
    import OCP.BRep
    import OCP.BRepCheck
    import OCP.BRepGProp
    import OCP.GProp
    import OCP.TopAbs
    import OCP.TopExp
    import OCP.TopoDS
    import OCP.TopTools

    if shape is None or not isinstance(shape, OCP.TopoDS.TopoDS_Shape) or shape.IsNull():
        return ["nothing was built"]

    found = []
    solids = []
    explorer = OCP.TopExp.TopExp_Explorer(shape, OCP.TopAbs.TopAbs_SOLID)
    while explorer.More():
        solids.append(explorer.Current())
        explorer.Next()
    if not solids:
        found.append("it holds no solid")
    if OCP.TopExp.TopExp_Explorer(shape, OCP.TopAbs.TopAbs_FACE, OCP.TopAbs.TopAbs_SOLID).More():
        found.append("it has faces that belong to no solid")
    for solid in solids:
        edges = OCP.TopTools.TopTools_IndexedDataMapOfShapeListOfShape()
        OCP.TopExp.TopExp.MapShapesAndAncestors_s(solid, OCP.TopAbs.TopAbs_EDGE, OCP.TopAbs.TopAbs_FACE, edges)
        for i in range(1, edges.Extent() + 1):
            edge = OCP.TopoDS.TopoDS.Edge_s(edges.FindKey(i))
            if (
                edges.FindFromIndex(i).Extent() == 1
                and not OCP.BRep.BRep_Tool.Degenerated_s(edge)
                and edge.Orientation() in (OCP.TopAbs.TopAbs_FORWARD, OCP.TopAbs.TopAbs_REVERSED)
            ):
                found.append("a solid in it is open")
                break
        props = OCP.GProp.GProp_GProps()
        OCP.BRepGProp.BRepGProp.VolumeProperties_s(solid, props)
        if props.Mass() <= 0.0:
            found.append("a solid in it has no volume inside it (%.3f mm^3)" % props.Mass())
    if solids and not OCP.BRepCheck.BRepCheck_Analyzer(shape).IsValid():
        found.append("OCCT finds it invalid")
    # Said once each: a part of a hundred open solids has one problem.
    return list(dict.fromkeys(found))


def _shell_to_solid(shell):
    """The solid a closed shell bounds, or None if the shell is not closed.

    'BRepCheck_Shell.Closed()' asks the geometry rather than reading the shell's
    'Closed' flag: the flag is set by the algorithms that happen to know, so a
    shell that came out of sewing or out of a mesher can be closed with the flag
    unset, and trusting it would leave exactly the shapes this is for as shells.

    The solid is oriented after it is built. A closed shell whose faces point
    inward bounds the space *outside* it, and the solid made from it measures a
    negative volume - the failure 'partcad.test.solidity' exists to report. So
    converting without orienting would turn a shell nothing computed from into a
    solid everything computes from wrongly; 'BRepLib.OrientClosedSolid_s'
    reverses it when needed and is what makes this conversion safe.

    Which is why its answer is read rather than assumed. It returns False for a
    solid it cannot orient - "open or incoherent" - and a shell can reach it in
    that state: 'BRepCheck_Shell.Closed()' asks whether the faces leave a free
    edge, not whether their orientations agree with each other, so a shell whose
    faces are coherently joined and inconsistently turned passes the check above
    and cannot be oriented here. The shell is then kept as it is, which is the
    same answer an unclosed one gets and for the same reason: the solid that
    would be returned is exactly the one this is written to avoid making.
    """
    import OCP.BRep  # noqa: F401
    import OCP.BRepCheck  # noqa: F401
    import OCP.BRepLib  # noqa: F401
    import OCP.TopoDS  # noqa: F401

    try:
        shell = OCP.TopoDS.TopoDS.Shell_s(shell)
        if OCP.BRepCheck.BRepCheck_Shell(shell).Closed() != OCP.BRepCheck.BRepCheck_Status.BRepCheck_NoError:
            return None

        builder = OCP.BRep.BRep_Builder()
        solid = OCP.TopoDS.TopoDS_Solid()
        builder.MakeSolid(solid)
        builder.Add(solid, shell)
        if not OCP.BRepLib.BRepLib.OrientClosedSolid_s(solid):
            return None
        if solid.IsNull():
            return None
        return solid
    except Exception as e:
        # Whatever it was, the shell is still a usable answer; say so where it
        # can be read rather than failing the part over an improvement.
        sys.stderr.write("wrapper_common: could not turn a closed shell into a solid: %s\n" % e)
        return None


def finished(shape, metadata=None):
    """A part as it leaves the wrapper that built it: finished as its request asked, and encoded.

    Every part leaves its factory through one step (see 'Shape.get_wrapped'):
    a closed shell becomes the solid it bounds ('solidify', unless the part is
    read from a file that is the authority on it), the result is judged
    ('solid_problems'), and then it is moved by its 'offset' and scaled by its
    'scale'. All of it is work on the geometry, and the core used to ask for
    each step in a sandbox of its own: a fresh interpreter importing OCP and
    parsing the BREP this one had just written, to do what is cheap here, where
    the shape is still live. So the request says which of it to do
    ('ocp_serialize.KEY_FINISH', from 'Shape.finish_request()'), and this does
    it with the very functions those sandboxes ran, in the same order.

    What was done is said in the envelope's METADATA_FINISHED section, each
    step echoing what it was asked, so that the core does exactly what is left:
    a step that fails here - an exception from OCCT, say - is not claimed, and
    nothing after it is attempted, and the core takes it from there as it
    always did, failing or warning in its own words. Nothing is written to
    standard error for it, which on a run that succeeds would be a warning of
    its own: whatever the core's sandbox then says is all that is said.

    'metadata' is what the wrapper learnt that the geometry cannot answer, as
    'ocp_serialize.encode_shape' takes it. A request that asks for nothing - a
    sketch, built by the same script wrappers - and has nothing to add gets
    the shape back as it was, for 'handle_output' to encode as it always has;
    and so does anything that is not an OCCT shape, for 'handle_output' to
    encode or refuse.
    """
    if shape is None or (not _request_finish and not metadata):
        return shape
    import OCP.TopoDS  # noqa: F401

    if not isinstance(shape, OCP.TopoDS.TopoDS_Shape):
        return shape
    done = {}
    if _request_finish:
        shape, done = _finish(shape, _request_finish)
    combined = dict(metadata or {})
    if done:
        combined[ocp_serialize.METADATA_FINISHED] = done
    return ocp_serialize.encode_shape(shape, name=_request_name, label=_request_label, metadata=combined or None)


def finished_shapes(shapes):
    """'finished()' for a wrapper whose answer is a list of shapes: the one part they make.

    A partType script, and an SDF script, may hand back several shapes, and a
    part is one: the core compounded them, in a sandbox of its own, before it
    validated the compound in another. Here they are compounded the way that
    sandbox did ('ocp_serialize.compound_of', skipping what is not a shape or is
    a null one) and finished as one shape, and the answer is a list holding it,
    which the factory already takes as the part itself.

    Without a request to finish, the list as it was: what the core asks for is
    what the core gets. And as it was, too, when anything in it is something
    'handle_output' would refuse to encode, so that it is refused as it always
    was; an OCCT object that is not a shape (a location a script showed) is
    dropped with the same warning it was dropped with on the way out.
    """
    if not _request_finish or not isinstance(shapes, list) or not shapes:
        return shapes
    if len(shapes) == 1:
        return [finished(shapes[0])]

    import OCP.TopoDS  # noqa: F401

    def is_occt(value):
        return type(value).__module__.split(".")[0] == "OCP"

    if any(shape is not None and not is_occt(shape) for shape in shapes):
        return shapes
    kept = []
    for shape in shapes:
        if isinstance(shape, OCP.TopoDS.TopoDS_Shape):
            if not shape.IsNull():
                kept.append(shape)
        elif shape is not None:
            ocp_serialize.encode(shape)  # warns, as it did when every shape travelled
    return [finished(ocp_serialize.compound_of(kept))]


def _finish(shape, finish):
    """Do to 'shape' what 'finish' asks, as far as that goes: '(result, what to claim)'."""
    done = {}
    validate = finish.get("validate")
    if isinstance(validate, dict):
        solid = bool(validate.get("solidify"))
        try:
            judged = solidify(shape) if solid else shape
            problems = solid_problems(judged)
        except Exception as e:
            # Unclaimed, and so is everything after it: the core validates and
            # then moves the part, and it cannot validate a part already moved.
            done[ocp_serialize.FINISHED_DECLINED] = "validating it: %s" % exception_to_str(e)
            return shape, done
        shape = judged
        done[ocp_serialize.FINISHED_VALIDATED] = {"solidify": solid, "problems": problems}
    for operation in ("offset", "scale"):
        if operation not in finish:
            continue
        try:
            # The fallback's own functions, so that there is one definition of
            # what moving a part means; imported only by a part that moves.
            import wrapper_transform

            apply = wrapper_transform.relocate if operation == "offset" else wrapper_transform.scale
            moved = apply(shape, finish[operation])
        except Exception as e:
            done[ocp_serialize.FINISHED_DECLINED] = "%s: %s" % (operation, exception_to_str(e))
            break
        shape = moved
        done[operation] = finish[operation]
    return shape, done


def combine(shapes, kind):
    """Compound the script's result shapes and collect its components.

    This is the filtering the part/sketch factories used to do in the core
    process; it now happens here so the core never touches a live OCP object.
    'kind' picks the rule:
      - "sketch": keep only the 1D/2D geometry (edges/wires/faces) - a sketch is
        made of those - both in the compound and as components. A compound that
        wraps such geometry is descended into rather than dropped: cadquery and
        build123d routinely hand a sketch back as a compound of faces (cadquery
        2.8's Workplane.placeSketch is one), and discarding it would leave the
        sketch empty. A shell is descended into for the same reason: it is a set
        of faces, and a sketch has no volume for it to bound.
      - "part" (default): every shape is a component, and everything except bare
        edges/wires/faces goes into the compound. A closed shell becomes the
        solid it bounds first (see solidify), because a part that is a skin
        rather than a body computes nothing.
    Nested lists are walked and preserved in the components tree. Returns
    (TopoDS_Compound, components).
    """
    import OCP.TopoDS  # noqa: F401
    import OCP.TopAbs  # noqa: F401

    lower_dim = (OCP.TopAbs.TopAbs_EDGE, OCP.TopAbs.TopAbs_WIRE, OCP.TopAbs.TopAbs_FACE)
    builder = OCP.TopoDS.TopoDS_Builder()
    compound = OCP.TopoDS.TopoDS_Compound()
    builder.MakeCompound(compound)
    components = []

    def walk(items, out):
        for shape in items:
            if shape is None or isinstance(shape, str):
                continue
            if isinstance(shape, list):
                child = []
                walk(shape, child)
                out.append(child)
                continue
            if not isinstance(shape, OCP.TopoDS.TopoDS_Shape) or shape.IsNull():
                continue
            if kind == "sketch":
                shape_type = shape.ShapeType()
                if shape_type in (OCP.TopAbs.TopAbs_COMPOUND, OCP.TopAbs.TopAbs_SHELL):
                    # Descend into the wrapper and keep the edges/wires/faces it
                    # holds, instead of discarding it whole.
                    iterator = OCP.TopoDS.TopoDS_Iterator(shape)
                    while iterator.More():
                        walk([iterator.Value()], out)
                        iterator.Next()
                    continue
                if shape_type in lower_dim:
                    out.append(shape)
                    builder.Add(compound, shape)
            else:
                # The one place both wrappers funnel whatever a script returned,
                # so the one place to state a closed shell as the solid it is.
                shape = solidify(shape)
                out.append(shape)
                if shape.ShapeType() not in lower_dim:
                    builder.Add(compound, shape)

    walk(shapes, components)
    return compound, components


def exception_to_str(exc):
    """Normalize an exception for the response envelope.

    The wire format carries plain data only, so an exception travels as its
    message. 'None' is preserved as 'None': several consumers distinguish
    "no exception" from "an exception whose message happens to be empty".
    """
    if exc is None:
        return None
    return str(exc)


def handle_exception(exc, cqscript=None):
    sys.stderr.write("Error: [")
    sys.stderr.write(str(exc).strip())
    sys.stderr.write("] on the line: [")

    tb = exc.__traceback__
    if tb is None:
        sys.stderr.write("No traceback available")
    else:
        # Try to move one level down if available
        if tb.tb_next is not None:
            tb = tb.tb_next
        # Check if tb is still valid
        try:
            fname = tb.tb_frame.f_code.co_filename
            if cqscript is not None and fname == "<cqscript>":
                fname = cqscript

            # Attempt to read the file and print the specific line
            try:
                with open(fname, "r") as fp:
                    lines = fp.read().split("\n")
                    if tb.tb_lineno - 1 < len(lines):
                        line = lines[tb.tb_lineno - 1]
                        sys.stderr.write(line.strip())
                    else:
                        sys.stderr.write("Line number out of range")
            except Exception as read_err:
                sys.stderr.write(f"Failed to read file {fname}: {read_err}")
        except AttributeError:
            sys.stderr.write("No traceback details available")
    sys.stderr.write("]\n")
    sys.stderr.flush()
