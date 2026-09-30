#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A single-stroke vector font, for the labels a projection is annotated with.

'pc render --with-ports' names every port it draws, and a name has to be drawn
with something. The two obvious candidates are both wrong here:

* An SVG '<text>' element only exists in the SVG. The PNG and JPEG renderers go
  through the SVG and would keep it, but the DXF one converts paths and nothing
  else, so the labels would silently disappear from one of the four formats.
* Real text geometry (build123d's 'Text') needs a font file. Which font a
  machine has, and which version of it, is not something this repository
  controls -- and the rendered examples are checked in precisely so that a
  change in what PartCAD draws is a diff somebody looks at.

So the labels are drawn as line segments, from a font defined right here: the
same polylines on every machine, projected together with the shape, and
therefore present in every format that can draw a line.

Glyphs are defined on a 4-wide, 6-tall grid with the baseline at y=0, and
'polylines()' returns them scaled so that the cap height is exactly 1.0 -- the
caller multiplies by whatever text height it wants. Lowercase is drawn as small
capitals (SMALL_CAPS scale): it keeps the alphabet to one set of shapes, and a
port name reads as well in small caps as in lowercase.

This module is pure Python and imports nothing. It runs inside the render
sandbox, beside 'wrapper_export.py', and is unit-tested directly.
"""

# The grid the glyphs below are drawn on.
CAP_HEIGHT = 6.0
# The width of a glyph cell, and the step from one glyph's origin to the next.
# The gap between two glyphs is the difference.
GLYPH_WIDTH = 4.0
ADVANCE = 5.0

# Lowercase is drawn with the uppercase shapes at this fraction of the cap
# height, sitting on the same baseline.
SMALL_CAPS = 0.72

# Each glyph is a list of polylines; each polyline a list of (x, y) points on
# the grid described above. A glyph absent from here is drawn as a box, so that
# a character this font does not have is visibly a character rather than a gap.
_GLYPHS = {
    " ": [],
    "A": [[(0, 0), (2, 6), (4, 0)], [(0.7, 2.1), (3.3, 2.1)]],
    "B": [
        [(0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)],
        [(3, 3), (4, 2), (4, 1), (3, 0), (0, 0)],
    ],
    "C": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1)]],
    "D": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 1), (3, 0), (0, 0)]],
    "E": [[(4, 6), (0, 6), (0, 0), (4, 0)], [(0, 3), (3, 3)]],
    "F": [[(4, 6), (0, 6), (0, 0)], [(0, 3), (3, 3)]],
    "G": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2.5), (2, 2.5)]],
    "H": [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    "I": [[(1, 6), (3, 6)], [(2, 6), (2, 0)], [(1, 0), (3, 0)]],
    "J": [[(3, 6), (3, 1), (2, 0), (1, 0), (0, 1)]],
    "K": [[(0, 0), (0, 6)], [(4, 6), (0, 2.5)], [(1.5, 3.6), (4, 0)]],
    "L": [[(0, 6), (0, 0), (4, 0)]],
    "M": [[(0, 0), (0, 6), (2, 3), (4, 6), (4, 0)]],
    "N": [[(0, 0), (0, 6), (4, 0), (4, 6)]],
    "O": [[(1, 6), (3, 6), (4, 5), (4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6)]],
    "P": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)]],
    "Q": [
        [(1, 6), (3, 6), (4, 5), (4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6)],
        [(2.4, 1.6), (4, 0)],
    ],
    "R": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)], [(2, 3), (4, 0)]],
    "S": [
        [(4, 5), (3, 6), (1, 6), (0, 5), (0, 4), (1, 3), (3, 3), (4, 2), (4, 1), (3, 0), (1, 0), (0, 1)],
    ],
    "T": [[(0, 6), (4, 6)], [(2, 6), (2, 0)]],
    "U": [[(0, 6), (0, 1), (1, 0), (3, 0), (4, 1), (4, 6)]],
    "V": [[(0, 6), (2, 0), (4, 6)]],
    "W": [[(0, 6), (1, 0), (2, 3), (3, 0), (4, 6)]],
    "X": [[(0, 0), (4, 6)], [(0, 6), (4, 0)]],
    "Y": [[(0, 6), (2, 3), (4, 6)], [(2, 3), (2, 0)]],
    "Z": [[(0, 6), (4, 6), (0, 0), (4, 0)]],
    "0": [
        [(1, 6), (3, 6), (4, 5), (4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6)],
        [(0.6, 1.2), (3.4, 4.8)],
    ],
    "1": [[(1, 5), (2, 6), (2, 0)], [(1, 0), (3, 0)]],
    "2": [[(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (0, 0), (4, 0)]],
    "3": [[(0, 6), (4, 6), (2, 3.4)], [(2, 3.4), (3, 3.4), (4, 2.4), (4, 1), (3, 0), (1, 0), (0, 1)]],
    "4": [[(3, 0), (3, 6), (0, 2), (4, 2)]],
    "5": [[(4, 6), (0, 6), (0, 3.4), (3, 3.4), (4, 2.4), (4, 1), (3, 0), (1, 0), (0, 1)]],
    "6": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (1, 3), (0, 2)]],
    "7": [[(0, 6), (4, 6), (1.5, 0)]],
    "8": [
        [(1, 3), (0, 4), (0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3), (1, 3)],
        [(1, 3), (0, 2), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (3, 3), (1, 3)],
    ],
    "9": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 4), (1, 3), (3, 3), (4, 4)]],
    "-": [[(0.5, 3), (3.5, 3)]],
    "_": [[(0, 0), (4, 0)]],
    ".": [[(1.7, 0), (2.3, 0), (2.3, 0.6), (1.7, 0.6), (1.7, 0)]],
    ",": [[(2.3, 0.6), (1.5, -1)]],
    ":": [
        [(1.7, 1), (2.3, 1), (2.3, 1.6), (1.7, 1.6), (1.7, 1)],
        [(1.7, 4), (2.3, 4), (2.3, 4.6), (1.7, 4.6), (1.7, 4)],
    ],
    ";": [[(1.7, 4), (2.3, 4), (2.3, 4.6), (1.7, 4.6), (1.7, 4)], [(2.3, 1.6), (1.5, 0)]],
    "/": [[(0, 0), (4, 6)]],
    "\\": [[(0, 6), (4, 0)]],
    "(": [[(3, 6), (1, 4), (1, 2), (3, 0)]],
    ")": [[(1, 6), (3, 4), (3, 2), (1, 0)]],
    "[": [[(3, 6), (1, 6), (1, 0), (3, 0)]],
    "]": [[(1, 6), (3, 6), (3, 0), (1, 0)]],
    "<": [[(3.5, 5), (0.5, 3), (3.5, 1)]],
    ">": [[(0.5, 5), (3.5, 3), (0.5, 1)]],
    "+": [[(0.5, 3), (3.5, 3)], [(2, 1.5), (2, 4.5)]],
    "*": [[(2, 1.5), (2, 4.5)], [(0.7, 2.2), (3.3, 3.8)], [(0.7, 3.8), (3.3, 2.2)]],
    "=": [[(0.5, 2), (3.5, 2)], [(0.5, 4), (3.5, 4)]],
    "#": [[(1, 0), (1.5, 6)], [(2.5, 0), (3, 6)], [(0.4, 2), (3.6, 2)], [(0.4, 4), (3.6, 4)]],
    "!": [[(2, 6), (2, 1.6)], [(2, 0), (2, 0.6)]],
    "?": [[(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (2, 2.4), (2, 1.6)], [(2, 0), (2, 0.6)]],
    "'": [[(2, 6), (2, 4.5)]],
    '"': [[(1.4, 6), (1.4, 4.5)], [(2.6, 6), (2.6, 4.5)]],
    "%": [
        [(0, 0), (4, 6)],
        [(0, 4), (1.2, 4), (1.2, 6), (0, 6), (0, 4)],
        [(2.8, 0), (4, 0), (4, 2), (2.8, 2), (2.8, 0)],
    ],
    "@": [
        [(1, 6), (3, 6), (4, 5), (4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6)],
        [(1.3, 2), (2.7, 2), (2.7, 4), (1.3, 4), (1.3, 2)],
    ],
}

# What an unmapped character is drawn as.
_UNKNOWN = [[(0.5, 0), (3.5, 0), (3.5, 5), (0.5, 5), (0.5, 0)]]


def _glyph(char):
    """The polylines of one character, and the scale they are drawn at."""
    if char in _GLYPHS:
        return _GLYPHS[char], 1.0
    upper = char.upper()
    if upper in _GLYPHS:
        # A lowercase letter (or anything else that upper-cases into the font):
        # the capital's shape, drawn small.
        return _GLYPHS[upper], SMALL_CAPS
    return _UNKNOWN, 1.0


def width(text) -> float:
    """The advance width of 'text', in units where the cap height is 1.0."""
    return len(text) * ADVANCE / CAP_HEIGHT


def polylines(text):
    """'text' as polylines, in units where the cap height is 1.0.

    The text starts at x=0 and sits on the baseline y=0, so a caller scales the
    result by the height it wants and moves it where the label goes. Returns a
    list of polylines, each a list of (x, y) tuples.
    """
    result = []
    pen = 0.0
    for char in text:
        glyph, scale = _glyph(char)
        for polyline in glyph:
            result.append([((pen + x * scale) / CAP_HEIGHT, y * scale / CAP_HEIGHT) for x, y in polyline])
        pen += ADVANCE
    return result
