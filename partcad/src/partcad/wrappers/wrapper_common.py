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
    # Serialize the output, echoing the request's name/label onto the shape.
    sys.stdout.write(ocp_serialize.serialize(model, name=_request_name, label=_request_label))
    sys.stdout.flush()


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
        sketch empty.
      - "part" (default): every shape is a component, and everything except bare
        edges/wires/faces goes into the compound.
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
            shape_type = shape.ShapeType()
            if kind == "sketch":
                if shape_type == OCP.TopAbs.TopAbs_COMPOUND:
                    # Descend into the compound and keep the edges/wires/faces it
                    # holds, instead of discarding the whole wrapper.
                    iterator = OCP.TopoDS.TopoDS_Iterator(shape)
                    while iterator.More():
                        walk([iterator.Value()], out)
                        iterator.Next()
                    continue
                if shape_type in lower_dim:
                    out.append(shape)
                    builder.Add(compound, shape)
            else:
                out.append(shape)
                if shape_type not in lower_dim:
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
