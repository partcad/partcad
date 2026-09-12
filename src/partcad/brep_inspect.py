#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a BREP payload is made of, read off the bytes without a CAD kernel.

The core process never holds a live shape. A shape reaches it as the
zstd-compressed BREP bytes of a '{"name", "label", "brep"}' envelope (see
shape_envelope.py), and every question about geometry is put to a wrapper
running in a sandbox, because answering one needs OCCT. That is the right
arrangement for a question about geometry, and an expensive way to ask one
about *topology* -- which the payload already answers, in plain text, in the
section BRepTools writes last:

    TShapes 34              the number of records that follow
    Ve                      a vertex: its type code, alone on the line
    1e-07                   its geometry
    0 0 30
    0 0

    0101101                 its flags
    *                       the sub-shapes it is made of: none
    ...
    Sh                      a shell
    0101100
    -25 0 +15 0 -11 0 ... * the faces it is made of
    So                      a solid
    1100000
    +2 0 *                  the shell it is made of

The last record written is the outermost shape: sub-shapes are added to the map
before the shape that holds them, so the shape everything else belongs to is
written at the end. That is the one thing about the ordering this relies on --
which direction the reference indices count in is deliberately not (see the last
paragraph).

Nothing here parses geometry. The curves, surfaces and triangulations that are
nearly all of the bytes are skipped by looking only at where each record ends:
the line its sub-shape list closes on, which is the one line in a record that
ends with '*'. So this stays a scan over lines rather than a second
implementation of a BREP reader, and it needs no CAD dependency to do it -- the
point of having it here rather than in a wrapper.

What it is for is the shell. A shell is a skin: a set of faces joined along
their edges, with nothing said about which side of them is material. A solid is
a shell that has been declared to bound a volume, and that declaration is the
whole difference. It changes nothing about how the shape looks and everything
about what can be computed from it: two 10 mm cubes overlapping by 5 mm share
500 mm^3 and add up to 1500, and asking OCCT for either against the second one's
*shell* returns a result with no solid in it and a volume of zero. So a part
that comes back as a shell renders, exports and measures like the part that was
meant, and is wrong for everything downstream of a boolean -- interference, CAM,
FEA, the mass in a bill of materials. PartCAD's wrappers convert a closed shell
into the solid it already bounds (see wrappers/wrapper_common.solidify), so this
is the check that they did.

Which is not the same as "the payload contains a shell", and the difference
matters: every solid is bounded by one, so a box's payload has a shell record in
it. What makes a shell a problem is that no solid owns it, and each record's
sub-shape list says who owns what. A solid is made of shells and of nothing else
-- OCCT's topological rule, which TopoDS_Builder enforces -- so the distinct
references the solid records make are exactly the shells that bound something.
Any shell beyond those is a shell nothing owns: the shape, or a piece of the
compound it is, is a surface rather than a body.

Counting those references rather than resolving them is deliberate. It means
this never has to know which end of the record list the indices count from,
which is the one thing about the format that would be easy to get backwards and
impossible to notice: a mapping that is off by a reflection still resolves to
*some* record, and would quietly call a solid's own boundary a free shell.
"""

import re

from . import shape_envelope

# The two-letter codes TopTools_ShapeSet writes for each shape type (the
# compact spelling its PrintShapeEnum produces), and the names used here.
SHAPE_TYPES = {
    b"Ve": "vertex",
    b"Ed": "edge",
    b"Wi": "wire",
    b"Fa": "face",
    b"Sh": "shell",
    b"So": "solid",
    b"CS": "compsolid",
    b"Co": "compound",
}

# What a BREP payload starts with. 'BRepTools.Write_s' writes the second one;
# the first is what DBRep prepends when a shape is saved from Draw, and a
# '.brep' file a package carries may well have come from there.
_MAGIC = (b"CASCADE Topology", b"DBRep_DrawableShape")
# How far in to look for it. The marker is on the first or second line.
_MAGIC_WINDOW = 128

# The header of the section this reads, at the start of its own line.
_TSHAPES = b"TShapes "

# A reference to another record: an orientation sign and the record's index,
# followed by a location index this has no use for.
_REFERENCE = re.compile(rb"[+-]\d+")


# What a record's sub-shape list names, one dimension down: a solid is bounded
# by shells, a shell by faces, a face by wires, a wire by edges. Only the type
# one dimension up counts as bounding, which is why 'Co' is deliberately absent
# - a compound holding a bare face does not make that face part of a body, and
# counting its references as bounding is exactly how a surface handed back as a
# part would disappear from this.
_BOUNDED_BY = {
    b"So": "shell",
    b"Sh": "face",
    b"Fa": "wire",
    b"Wi": "edge",
}


class Topology:
    """The shape types a BREP payload holds, and how many of each.

    'counts' is keyed by the names in SHAPE_TYPES, and holds only the types
    that occur. 'root' is the outermost shape's type -- what the payload *is*.

    'free' is the part worth asking about: for each of shell, face, wire and
    edge, how many records of that type nothing one dimension up refers to. A
    body's geometry is all bounded - its faces belong to a shell, its shell to
    a solid - so a non-zero entry is geometry that is in the payload without
    being part of a body: a skin, a surface, a bare curve. 'free_shells' is
    kept as an attribute of its own because it is the question this module was
    written for; see the module docstring.
    """

    __slots__ = ("counts", "root", "free_shells", "free")

    def __init__(self, counts, root, free_shells, free=None):
        self.counts = counts
        self.root = root
        self.free_shells = free_shells
        self.free = free if free is not None else {"shell": free_shells}

    def count(self, shape_type: str) -> int:
        """How many records of 'shape_type' the payload holds."""
        return self.counts.get(shape_type, 0)

    def free_count(self, shape_type: str) -> int:
        """How many records of 'shape_type' nothing one dimension up refers to."""
        return self.free.get(shape_type, 0)

    def __repr__(self) -> str:
        return "Topology(root=%r, free=%r, counts=%r)" % (self.root, self.free, self.counts)


def looks_like_brep(data: bytes) -> bool:
    """Whether 'data' is the ASCII BREP this module knows how to read.

    False for anything else, including a BREP written in OCCT's binary format:
    the answer is then "not read" rather than "no shell in it".
    """
    head = bytes(data[:_MAGIC_WINDOW])
    return any(marker in head for marker in _MAGIC)


def _line(data: bytes, pos: int):
    """The line at 'pos' and where the next one starts; (None, pos) at the end."""
    if pos >= len(data):
        return None, pos
    end = data.find(b"\n", pos)
    if end < 0:
        return data[pos:].strip(), len(data)
    return data[pos:end].strip(), end + 1


def _section_start(data: bytes) -> int:
    """Where the TShapes header begins, or -1.

    Matched at the start of a line: nothing else in the format spells
    "TShapes", but a section a later version adds could mention it.
    """
    pos = 0
    while True:
        found = data.find(_TSHAPES, pos)
        if found < 0:
            return -1
        if found == 0 or data[found - 1 : found] == b"\n":
            return found
        pos = found + 1


def _records(data: bytes):
    """Yield (type code, sub-shape line) for every record in the TShapes section.

    Raises ValueError when the section is not shaped the way BRepTools writes
    it, so that a format this no longer understands reads as "not read" rather
    than as an answer.
    """
    start = _section_start(data)
    if start < 0:
        raise ValueError("no TShapes section in the BREP payload")

    header, pos = _line(data, start)
    try:
        count = int(header[len(_TSHAPES) :])
    except (TypeError, ValueError):
        raise ValueError("unreadable TShapes count: %r" % header[:32])

    for index in range(count):
        line, pos = _line(data, pos)
        # No blank line separates the records, but skipping one costs nothing
        # and a format that grew one would otherwise read as unreadable.
        while line == b"":
            line, pos = _line(data, pos)
        if line is None:
            raise ValueError("the BREP payload ends after %d of %d records" % (index, count))
        if line not in SHAPE_TYPES:
            raise ValueError("record %d of %d opens with %r, not a shape type" % (index + 1, count, line[:16]))
        code = line

        # Everything between here and the line the sub-shape list closes on is
        # geometry, and is skipped unread. That is the whole of what makes this
        # a scan rather than a parse.
        while True:
            line, pos = _line(data, pos)
            if line is None:
                raise ValueError("record %d of %d is truncated" % (index + 1, count))
            if line.endswith(b"*"):
                yield code, line
                break


def topology(payload) -> Topology | None:
    """What 'payload' is made of, or None if it could not be read.

    'payload' is a "brep" field in any of the forms it travels in: the
    compressed bytes, the base64 text of them, or uncompressed BREP.

    None means exactly that nothing was read -- an empty payload, a format
    this does not recognize, a section that does not scan. It is never an
    answer about the shape, and a caller has to treat it apart from a
    Topology reporting no shell.
    """
    try:
        data = shape_envelope.brep_plain(payload)
    except Exception:
        return None
    if not data or not looks_like_brep(data):
        return None

    counts: dict[str, int] = {}
    root = None
    # The records something one dimension up refers to, by record index, per
    # type. Sets rather than counts: two solids may be bounded by the same
    # shell, and two faces may share an edge.
    bounded: dict[str, set[int]] = {name: set() for name in _BOUNDED_BY.values()}
    try:
        for code, references in _records(data):
            root = SHAPE_TYPES[code]
            counts[root] = counts.get(root, 0) + 1
            child = _BOUNDED_BY.get(code)
            if child is not None:
                bounded[child].update(abs(int(token)) for token in _REFERENCE.findall(references))
    except ValueError:
        return None

    # 'root' is the last record: see the module docstring.
    free = {name: max(counts.get(name, 0) - len(indices), 0) for name, indices in bounded.items()}
    return Topology(counts=counts, root=root, free_shells=free["shell"], free=free)


def free_shells(payload) -> int | None:
    """How many shells in 'payload' no solid bounds itself with, or None."""
    result = topology(payload)
    return None if result is None else result.free_shells


def envelope_free_geometry(envelope) -> tuple[dict[str, int], int]:
    """Walk a shape/assembly envelope: (free geometry by type, payloads not read).

    An assembly is a tree of envelopes (see shape_envelope), and geometry that
    belongs to no body anywhere in it is geometry that belongs to no body in
    the shape. The second number is how many payloads could not be read at all,
    which a caller has to keep separate from the first: nothing found out of
    nothing read says nothing.
    """
    found = {name: 0 for name in _BOUNDED_BY.values()}
    unread = 0

    def walk(obj):
        nonlocal unread
        if isinstance(obj, list):
            for item in obj:
                walk(item)
            return
        if not isinstance(obj, dict):
            return
        if shape_envelope.KEY_ASSEMBLY in obj:
            walk(obj[shape_envelope.KEY_ASSEMBLY])
            return
        if shape_envelope.KEY_BREP not in obj:
            return
        result = topology(obj[shape_envelope.KEY_BREP])
        if result is None:
            unread += 1
            return
        for name in found:
            found[name] += result.free_count(name)

    walk(envelope)
    return found, unread


def envelope_free_shells(envelope) -> tuple[int, int]:
    """Walk a shape/assembly envelope: (free shells found, payloads not read).

    The shell half of 'envelope_free_geometry', which is the question this
    module was written for.
    """
    found, unread = envelope_free_geometry(envelope)
    return found["shell"], unread
