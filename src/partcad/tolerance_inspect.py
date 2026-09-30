#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What manufacturing tolerance a CAD file states, read off the bytes.

A part that is going to be made has to say how precisely, and for most part
types the only place that can be said is the declaration: a mesh is a surface
with nothing in it to state a tolerance, and a script that builds a solid says
nothing about how well it has to be cut. A STEP file is the exception. AP242
carries the whole of GD&T -- a plus/minus tolerance on a dimension, a
straightness or a position tolerance on a feature -- so a part read from one may
well already say how precisely it has to be made, in the file, and asking its
author to repeat that in 'partcad.yaml' is asking for two answers that can
disagree.

So this reads the file. Not all STEP files carry any of it (a great many are
geometry and nothing else, which is why the declaration keeps an optional
'tolerance:' of its own), and the ones that do rarely carry *one* of it: a real
drawing tolerances several features, each to what that feature needs. There is
then no single number that is true of the part, and this says so with a NaN
rather than picking one of them -- see 'reduce()'.

Nothing here needs a CAD kernel. A STEP file is ISO 10303-21, which is text: a
list of '#<id> = ENTITY(<arguments>);' records, and the handful of entity types
that state a tolerance can be read straight out of it. That is the same trade
'brep_inspect' makes for topology, and for the same reason -- the core process
holds no live shapes, and putting this question to a sandbox would cost a
process per part to answer a question the bytes already answer.

What is read:

* 'TOLERANCE_VALUE(#lower, #upper)', the value of a plus/minus tolerance on a
  dimension. Both bounds are length measures, and what is taken from the pair is
  the largest deviation it permits -- 'max(|lower|, |upper|)'. That is the
  reading a manufacturer can be held to: a shop that works to it satisfies the
  file, whichever side of nominal the bound is on.

* The magnitude of a 'GEOMETRIC_TOLERANCE', and of every subtype of it --
  flatness, position, runout and the rest. A subtype is written either as a
  simple record ("FLATNESS_TOLERANCE('','',#1,#2)") or as one entity of a
  complex instance ("(GEOMETRIC_TOLERANCE(...)POSITION_TOLERANCE())"), so what
  is matched is the shape of the argument list rather than a list of names:
  anything ending in 'TOLERANCE' whose first two arguments are strings and whose
  third is a reference is a geometric tolerance and its third argument is the
  magnitude. A list of names would have to be kept up to date with a standard
  that keeps adding to it.

Deliberately *not* read: the 'UNCERTAINTY_MEASURE_WITH_UNIT' every STEP file
carries. It is the precision the geometry was written to (1e-07 mm, typically),
not a tolerance anybody is being asked to hold, and reading it would give every
STEP file ever exported a manufacturing tolerance of a ten-millionth of a
millimetre.

Units are resolved rather than assumed. PartCAD works in millimetres and most
STEP files are written in them, but a file written in inches states so, and
reading 0.005 inch as 0.005 mm would be wrong by a factor of 25.4 with nothing
to show for it.
"""

import math
import os
import re

from . import logging as pc_logging

# How much of the file is read at a time. The scan is a sequence of byte
# searches over each block, so this trades a little memory for the number of
# them; a STEP file of any size is read in one pass either way.
CHUNK = 1 << 20

# What has to appear in a block of records for it to be worth looking at
# closely. Nearly every record in a STEP file is a point, a curve or a face, and
# a file with no GD&T in it holds nothing this module wants at all -- so a block
# none of these occur in is dropped whole, and the expensive half of this
# (regular expressions, argument lists) is never reached for it. That is what
# keeps reading a 500 MB assembly a scan rather than a parse.
_KEYWORDS = (b"TOLERANCE", b"MEASURE_WITH_UNIT", b"SI_UNIT", b"CONVERSION_BASED_UNIT")

# A Part 21 string: single-quoted, with a doubled quote standing for one inside
# it. Spelled without an alternation so that a run of ordinary characters has
# one way to be matched and the engine has nothing to backtrack over.
_STRING = re.compile(rb"'[^']*(?:''[^']*)*'")

# The three records that have to be found by their id, because something else
# refers to them. Each is anchored on the '#<id> =' that starts the record and
# reaches no further than the ';' that ends it, so a match cannot be stitched
# together out of two records.
_MEASURE = re.compile(
    rb"#(\d+)\s*=\s*[^;]*?MEASURE_WITH_UNIT\s*\(\s*(?:POSITIVE_)?LENGTH_MEASURE\s*\(\s*([^(),]*?)\s*\)\s*,\s*#(\d+)"
)
_SI_UNIT = re.compile(rb"#(\d+)\s*=\s*[^;]*?\bSI_UNIT\s*\(\s*(\$|\.[A-Z]+\.)\s*,\s*\.([A-Z]+)\.\s*\)")
_CONVERSION_UNIT = re.compile(rb"#(\d+)\s*=\s*[^;]*?\bCONVERSION_BASED_UNIT\s*\(\s*'[^']*(?:''[^']*)*'\s*,\s*#(\d+)")

# The two that are read where they stand, because nothing needs to refer back to
# them: a tolerance is stated in order to be stated.
_TOLERANCE_VALUE = re.compile(rb"\bTOLERANCE_VALUE\s*\(\s*#(\d+)\s*,\s*#(\d+)\s*\)")
_GEOMETRIC_TOLERANCE = re.compile(rb"\b[A-Z][A-Z0-9_]*TOLERANCE\s*\(")

# An argument that is a reference to another record, and nothing else.
_REFERENCE = re.compile(rb"^#(\d+)$")

# The SI prefixes, as the factor each stands for. 'None' is the unprefixed unit
# itself, which for a length is the metre.
_SI_PREFIXES = {
    None: 1.0,
    b"KILO": 1e3,
    b"HECTO": 1e2,
    b"DECA": 1e1,
    b"DECI": 1e-1,
    b"CENTI": 1e-2,
    b"MILLI": 1e-3,
    b"MICRO": 1e-6,
    b"NANO": 1e-9,
}

# Millimetres in a metre. PartCAD states every length in millimetres, so this is
# what a length read out of a file is brought to.
_MM_PER_METRE = 1000.0

# How far apart two tolerances may be and still be the same tolerance. They are
# decimal literals in a text file, so two spellings of one value ("0.1" and
# "1.E-01") can differ in the last bit, and a part must not be called
# inconsistently tolerated over that.
_EQUAL_WITHIN = 1e-9

# The file formats this knows how to read, mapped to the reader for each. A part
# type names the *format* of the file it is read from rather than appearing here
# itself, so that a type that produces a STEP file some other way ('kicad' does)
# is read by the same reader without being named twice.
_READERS = {}


def of_file(file_format, path):
    """The tolerance the file at 'path' states, or None if it states none.

    NaN when it states several that are not the same -- see 'reduce()'. None
    for a format nothing here can read, for a file that is not there (a 'kicad'
    part's STEP file does not exist until the part is built, and a part fetched
    from a URL not until it is downloaded), and for a file that cannot be read
    at all: none of the three is a tolerance, and which of them it was is a
    question for whatever is about to try to build the part.
    """
    reader = _READERS.get(file_format)
    if reader is None or not path:
        return None
    if not os.path.isfile(path):
        pc_logging.debug("No %s file to read a tolerance out of: %s" % (file_format, path))
        return None
    try:
        return reader(path)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.warning("Failed to read the tolerance stated by '%s': %s" % (path, e))
        return None


def reduce(values):
    """The one tolerance a list of them amounts to.

    None when the list is empty: the file states nothing, which is not the same
    as stating that nothing is required of it, and leaves the declaration to
    answer.

    NaN when they are not all the same. A file that tolerances three features
    differently has no single tolerance, and there is no honest way to pick one:
    the tightest overstates what most of the part needs, the loosest understates
    what one of its features does, and an average is true of nothing. NaN is
    what "this part is tolerated, feature by feature" reads as, and the
    manufacturability test takes it as an answer rather than as a missing one -
    the file says how precisely, in more detail than one number can hold.
    """
    if not values:
        return None
    smallest = min(values)
    largest = max(values)
    if largest - smallest <= _EQUAL_WITHIN * max(1.0, abs(largest)):
        return largest
    return math.nan


def of_step_file(path):
    """The tolerance a STEP file states, read without a CAD kernel."""
    measures = {}
    units = {}
    tolerance_values = []
    magnitudes = []

    with open(path, "rb") as f:
        buffer = b""
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            buffer += chunk
            cut = _boundary(buffer)
            if cut <= 0:
                continue
            head, buffer = buffer[:cut], buffer[cut:]
            _read_block(head, measures, units, tolerance_values, magnitudes)
        if buffer:
            _read_block(buffer, measures, units, tolerance_values, magnitudes)

    values = []
    for lower, upper in tolerance_values:
        low = _length_mm(lower, measures, units)
        high = _length_mm(upper, measures, units)
        if low is None or high is None:
            continue
        values.append(max(abs(low), abs(high)))
    for magnitude in magnitudes:
        value = _length_mm(magnitude, measures, units)
        if value is not None:
            values.append(abs(value))

    return reduce(values)


_READERS["step"] = of_step_file


def _boundary(buffer):
    """How much of 'buffer' is whole records, ending just past the last ';'.

    The file arrives a block at a time and a record straddles the join, so each
    block is cut back to the last record that ended in it and the rest is
    carried forward. The cut has to skip the ';' that a Part 21 string may hold
    -- a tolerance carries a name and a description, both free text -- because
    cutting inside a record would split it into two halves that each parse as
    something else, and quietly lose the tolerance it stated.

    'buffer' always begins at a record boundary, which is what lets this start
    outside a string every time it is called.

    Strings are stepped over by hand rather than with '_STRING', because the
    question here is asked of text that may stop in the middle of one. A quote
    at the very end of the buffer is either the end of a string or the first
    half of the doubled quote that stands for one inside it, and there is no way
    to tell until the next block arrives - so this stops rather than guessing,
    and the same bytes are looked at again with more of them to hand.

    Comments are stepped over for the same reason a string is: Part 21 allows
    '/* ... */' wherever a separator is allowed, and the ';' one may hold ends
    nothing. Which of the three comes first is what decides how the next stretch
    is read - a quote inside a comment is not a string, and a '/*' inside a
    string is not a comment.
    """
    cut = 0
    i = 0
    length = len(buffer)
    while i < length:
        quote = buffer.find(b"'", i)
        semicolon = buffer.find(b";", i)
        comment = buffer.find(b"/*", i)
        if semicolon < 0:
            break
        if 0 <= quote < semicolon and (comment < 0 or quote < comment):
            i = _end_of_string(buffer, quote)
            if i < 0:
                break
            continue
        if 0 <= comment < semicolon:
            end = buffer.find(b"*/", comment + 2)
            if end < 0:
                # The comment has not closed in what has arrived.
                break
            i = end + 2
            continue
        cut = semicolon + 1
        i = semicolon + 1
    return cut


def _without_comments(block):
    """'block' with its Part 21 comments taken out.

    What is inside one means nothing, and every regular expression below would
    read it as though it did: a comment may hold a semicolon, or text shaped
    like an entity. Removing them once is cheaper than teaching each pattern to
    ignore them, and the common case costs a single scan - a block with no '/*'
    in it is handed straight back.

    A '/*' inside a quoted string opens nothing, which is why this walks the
    strings rather than looking only for the delimiters.
    """
    if block.find(b"/*") < 0:
        return block

    kept = []
    start = 0
    i = 0
    length = len(block)
    while i < length:
        quote = block.find(b"'", i)
        comment = block.find(b"/*", i)
        if comment < 0:
            break
        if 0 <= quote < comment:
            end = _end_of_string(block, quote)
            if end < 0:
                break
            i = end
            continue
        kept.append(block[start:comment])
        end = block.find(b"*/", comment + 2)
        if end < 0:
            # Unterminated, so the rest of the block is inside it.
            start = length
            break
        start = end + 2
        i = start
    kept.append(block[start:])
    return b"".join(kept)


def _end_of_string(buffer, start):
    """Where the Part 21 string opening at 'start' ends, or -1 if it is cut off."""
    i = start + 1
    length = len(buffer)
    while True:
        quote = buffer.find(b"'", i)
        if quote < 0 or quote + 1 >= length:
            # Unterminated, or terminated by the last byte there is - which may
            # yet turn out to be the first of a doubled quote.
            return -1
        if buffer[quote + 1 : quote + 2] == b"'":
            i = quote + 2
            continue
        return quote + 1


def _read_block(block, measures, units, tolerance_values, magnitudes):
    """Take what a block of whole records says, if it says anything at all.

    The keywords are looked for before the comments are taken out, so that the
    block a file with no GD&T in it is made of costs one scan rather than two.
    A block that is interesting only because of what a comment says then pays
    for a strip and finds nothing, which is the right answer arrived at the
    slower way round.
    """
    if not any(keyword in block for keyword in _KEYWORDS):
        return
    block = _without_comments(block)

    for match in _MEASURE.finditer(block):
        try:
            value = float(match.group(2))
        except ValueError:
            continue
        measures[int(match.group(1))] = (value, int(match.group(3)))

    for match in _SI_UNIT.finditer(block):
        if match.group(3) != b"METRE":
            # An angle, a mass, a time: not something a length is stated in.
            continue
        prefix = match.group(2)
        prefix = None if prefix == b"$" else prefix.strip(b".")
        factor = _SI_PREFIXES.get(prefix)
        if factor is not None:
            units[int(match.group(1))] = ("scale", factor * _MM_PER_METRE)

    for match in _CONVERSION_UNIT.finditer(block):
        # An inch, a foot, a thou: a unit defined as so much of another one,
        # which is itself stated as a length measure.
        units[int(match.group(1))] = ("measure", int(match.group(2)))

    for match in _TOLERANCE_VALUE.finditer(block):
        tolerance_values.append((int(match.group(1)), int(match.group(2))))

    for match in _GEOMETRIC_TOLERANCE.finditer(block):
        magnitude = _geometric_magnitude(block, match.end() - 1)
        if magnitude is not None:
            magnitudes.append(magnitude)


def _geometric_magnitude(block, start):
    """The magnitude of the geometric tolerance whose arguments open at 'start'.

    None for anything that is not one. Every entity in AP242 whose name ends in
    'TOLERANCE' is checked here, which catches the ones that are not geometric
    tolerances at all: 'PLUS_MINUS_TOLERANCE' takes two references,
    'MODIFIED_GEOMETRIC_TOLERANCE' one enumeration, and a subtype named in a
    complex instance ('POSITION_TOLERANCE()') takes nothing. The shape of the
    argument list is what tells them apart, because 'geometric_tolerance' is the
    one with four attributes beginning with a name, a description and the
    magnitude.
    """
    arguments = _arguments(block, start)
    if arguments is None or len(arguments) < 4:
        return None
    if not _is_text_or_omitted(arguments[0]) or not _is_text_or_omitted(arguments[1]):
        return None
    reference = _REFERENCE.match(arguments[2])
    if reference is None:
        return None
    return int(reference.group(1))


def _is_text_or_omitted(argument):
    """Whether an argument is a Part 21 string, or the '$' that stands for none.

    A tolerance's description is optional in AP242 and a file is free to write
    '$' for it rather than an empty string, so insisting on a quote there would
    reject a valid record and lose the tolerance it states - silently, which is
    the worst way to lose one. The name is allowed the same spelling: it costs
    nothing, and what tells a geometric tolerance apart from the other entities
    ending in 'TOLERANCE' is the rest of the shape of the list - four arguments
    or more, with a reference third.
    """
    return argument == b"$" or argument.startswith(b"'")


def _arguments(block, start):
    """The top-level arguments of the parameter list that opens at 'block[start]'.

    None if it does not close. Reached only for the handful of records that
    state a tolerance, so this walks the bytes rather than looking for a pattern
    in them: a nested list and a string may both hold a comma, and a regular
    expression that got that right would be harder to read than the loop.
    """
    arguments = []
    depth = 0
    begin = start + 1
    i = start
    length = len(block)
    while i < length:
        char = block[i : i + 1]
        if char == b"'":
            match = _STRING.match(block, i)
            if match is None:
                return None
            i = match.end()
            continue
        if char == b"(":
            depth += 1
        elif char == b")":
            depth -= 1
            if depth == 0:
                arguments.append(block[begin:i].strip())
                return arguments
        elif char == b"," and depth == 1:
            arguments.append(block[begin:i].strip())
            begin = i + 1
        i += 1
    return None


def _length_mm(measure_id, measures, units, seen=None):
    """One length measure in millimetres, or None if it cannot be resolved."""
    measure = measures.get(measure_id)
    if measure is None:
        return None
    value, unit_id = measure
    scale = _unit_mm(unit_id, measures, units, seen)
    if scale is None:
        return None
    return value * scale


def _unit_mm(unit_id, measures, units, seen=None):
    """How many millimetres one of this unit is, or None if it cannot be told.

    A conversion-based unit is defined in terms of another unit, so this
    recurses, and a file that defines one in terms of itself would recurse
    forever -- hence 'seen'. Nothing legitimate does that; a file that has been
    truncated or edited by hand can.
    """
    unit = units.get(unit_id)
    if unit is None:
        return None
    kind, value = unit
    if kind == "scale":
        return value
    seen = set() if seen is None else seen
    if unit_id in seen:
        return None
    seen.add(unit_id)
    return _length_mm(value, measures, units, seen)
