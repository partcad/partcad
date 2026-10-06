#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import math

from partcad import cam_preview

# What '//builtin/cam' writes, cut down: a square profile at two depths.
PROGRAM = """(PartCAD route)
G21
G90
G17
G94
M3 S18000
G0 Z5
G0 X0 Y0
G1 Z-3 F300
G1 X10 Y0 F1200
G1 X10 Y10
G1 X0 Y10
G1 X0 Y0
G1 Z-6 F300
G1 X10 Y0 F1200
G0 Z5
M5
M30
"""


def test_the_moves_of_a_program_are_read_in_millimetres():
    moves = cam_preview.parse(PROGRAM)

    rapids = [move for move in moves if move[0] == "rapid"]
    cuts = [move for move in moves if move[0] == "cut"]
    # The plunges are cutting moves too: the tool is in the material.
    assert len(cuts) == 7
    assert cuts[1] == ("cut", (0.0, 0.0), (10.0, 0.0), -3.0)
    # Up to the clearance at the start and at the end; the move to X0 Y0 goes
    # nowhere, since that is where the tool already is.
    assert len(rapids) == 2


def test_inches_are_read_as_millimetres():
    (move,) = [move for move in cam_preview.parse("G20\nG1 X1 Y0 F10\n") if move[0] == "cut"]
    assert move[2] == (25.4, 0.0)


def test_relative_moves_add_up():
    moves = cam_preview.parse("G91\nG1 X1\nG1 X1\n")
    assert [move[2] for move in moves] == [(1.0, 0.0), (2.0, 0.0)]


def test_an_arc_is_flattened_and_ends_where_it_says():
    moves = cam_preview.parse("G0 X10 Y0\nG3 X0 Y10 I-10 J0\n")
    arc = [move for move in moves if move[0] == "cut"]
    assert len(arc) > 2
    assert arc[-1][2] == (0.0, 10.0)
    # Every point of it is on the circle.
    assert all(math.isclose(math.hypot(*move[2]), 10.0, rel_tol=1e-9) for move in arc)


def test_a_program_is_drawn_with_its_cuts_and_its_rapids_apart():
    drawing, stats = cam_preview.svg(PROGRAM)

    assert drawing.startswith('<?xml version="1.0" encoding="utf-8"?>')
    assert 'id="Cut"' in drawing and 'id="Rapid"' in drawing
    assert stats["cuts"] == 7
    # Four sides of 10 mm and one more, measured on the plane they are drawn on:
    # a plunge goes nowhere there.
    assert math.isclose(stats["cut_length"], 50.0)


def test_a_program_that_goes_nowhere_draws_nothing():
    drawing, stats = cam_preview.svg("(nothing)\nM30\n")
    assert drawing is None
    assert stats["cuts"] == 0
