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

# The response channel, once it has been taken away from everything else. See
# 'protect_response_channel()'.
_response_fd = None


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
    #   - Read until EOF
    input_str = sys.stdin.read()
    #   - Unpack the content received via stdin
    request = ocp_serialize.deserialize(input_str) if decode else ocp_serialize.deserialize_raw(input_str)
    global _request_name, _request_label
    if isinstance(request, dict):
        _request_name = request.get("name")
        _request_label = request.get("label")
    return path, request


def handle_output(model):
    """Answer PartCAD, on the descriptor `protect_response_channel()` kept.

    Written with 'os.write' rather than through a file object, because the
    descriptor is deliberately not 'sys.stdout' any more -- that one is standard
    error now, and is where everything else in this process prints.
    """
    # Serialize the output, echoing the request's name/label onto the shape.
    serialized = ocp_serialize.serialize(model, name=_request_name, label=_request_label)
    if _response_fd is None:
        sys.stdout.write(serialized)
        sys.stdout.flush()
        return
    payload = serialized.encode("utf-8")
    while payload:
        payload = payload[os.write(_response_fd, payload) :]


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


def holds_a_solid(shape) -> bool:
    """Whether 'shape' is, or contains at any depth, a solid.

    'TopExp_Explorer' walks the whole tree, so a solid nested inside compounds
    inside a compound is found - which is the case worth asking about, since a
    script is free to hand back a compound of compounds.

    The question exists because "what is in this compound" decides whether it
    is safe to explode: a compound that holds a solid is a body and its solids
    are what a part wants, while one that holds none is a skin or a surface,
    and exploding it loses what says so.
    """
    import OCP.TopAbs  # noqa: F401
    import OCP.TopExp  # noqa: F401

    if shape is None or shape.IsNull():
        return False
    return OCP.TopExp.TopExp_Explorer(shape, OCP.TopAbs.TopAbs_SOLID).More()


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
