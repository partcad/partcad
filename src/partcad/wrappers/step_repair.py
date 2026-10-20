#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Repair what OpenCASCADE cannot survive in a STEP file, before it reads it.

A ``cartesian_transformation_operator`` (ISO 10303-42) is both a
``geometric_representation_item`` and a ``functionally_defined_transformation``,
so its instance lists the name each of those gives it, and the latter's
description, ahead of its own attributes:

    CARTESIAN_TRANSFORMATION_OPERATOR_2D('', '', $, #axis1, #axis2, #origin, 1.);

Seven parameters in 2D and eight in 3D, where 'axis3' follows. Some writers --
cadmpeg among them, for every pcurve and surface it places by transformation --
leave the two inherited ones out. OpenCASCADE then rejects the instance when it
loads the file, which on its own would cost a warning, and goes on to dereference
the origin it never read when it translates the geometry that uses it: the
process dies with SIGSEGV, and nothing says why.

The two missing parameters carry no geometry -- a name and an optional
description -- so restoring them as ``''`` and ``$`` loses nothing and gives
OpenCASCADE the instance it expects. That is all this does: a file that needs
no repair is read as it is, without a copy.

Runs inside the sandbox, so it uses nothing but the standard library.
"""

import contextlib
import os
import re
import tempfile

KEYWORD = b"CARTESIAN_TRANSFORMATION_OPERATOR_"

# A simple entity instance of either operator, up to its opening parenthesis.
# Only the simple form: in a complex instance '(A() B() ...)' each partial list
# holds that one supertype's own attributes, so its count means something else.
INSTANCE = re.compile(r"#\d+\s*=\s*CARTESIAN_TRANSFORMATION_OPERATOR_(2D|3D)\s*\(")

# How many parameters STEP gives each, and so how many the short form has.
COMPLETE = {"2D": 7, "3D": 8}
INHERITED = 2


def top_level_commas(text, start):
    """The offsets of the commas between the parameters opened at 'start', and the closing one.

    'start' is just past the opening parenthesis. A string is skipped whole --
    a quote inside one is written twice -- and so is a nested list.
    """
    commas = []
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "'":
            i += 1
            while i < len(text):
                if text[i] == "'":
                    if i + 1 < len(text) and text[i + 1] == "'":
                        i += 2
                        continue
                    break
                i += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            if depth == 0:
                return commas, i
            depth -= 1
        elif c == "," and depth == 0:
            commas.append(i)
        i += 1
    return commas, len(text)


def repair_text(text):
    """'text' with every short operator completed, and how many were."""
    pieces = []
    last = 0
    repaired = 0
    for match in INSTANCE.finditer(text):
        commas, _end = top_level_commas(text, match.end())
        if len(commas) + 1 != COMPLETE[match.group(1)] - INHERITED:
            continue
        # After the first parameter, the representation item's name.
        pieces.append(text[last : commas[0]])
        pieces.append(",'',$")
        last = commas[0]
        repaired += 1
    pieces.append(text[last:])
    return "".join(pieces), repaired


@contextlib.contextmanager
def readable(path):
    """The STEP file OpenCASCADE should read for 'path': itself, or a repaired copy.

    The copy lives as long as the 'with' block does.
    """
    with open(path, "rb") as f:
        data = f.read()
    if KEYWORD not in data:
        yield path
        return
    # Part 21 is 7-bit text with escapes for anything else, so latin-1 is a
    # lossless way to get at it as a string and back.
    text, repaired = repair_text(data.decode("latin-1"))
    if not repaired:
        yield path
        return
    handle, copy = tempfile.mkstemp(prefix="partcad-repaired-", suffix=os.path.splitext(path)[1] or ".step")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(text.encode("latin-1"))
        yield copy
    finally:
        try:
            os.remove(copy)
        except OSError:
            pass
