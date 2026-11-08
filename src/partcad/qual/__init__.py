#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Qualification: whether an object is what it claims to be.

Every question PartCAD asks of an object to qualify it is a 'Qualification'
('partcad.qual.qualification'), of one of four subtypes, told apart by what it
produces and so by how it is shown:

    basic       a verdict, and what was said about it in words. Most built-in
                checks: it builds, it can be made or bought, its connections
                hold, its requirements are met.
    topology    a verdict, and the geometry a failure is about, left behind to be
                looked at: the volumes two parts share, the faces and edges of a
                part to be made that have no tolerance.
    sim         the simulations the object declares, run: the state before and
                after, the pictures and the video.
    other       a report of an external tool's own, in its vocabulary.

The built-in checks are always applied, each to the objects it has something to
ask of ('partcad.qual.registry'); a plugin's check runs where an object declares
it under 'qual:' ('partcad.qual.config', 'partcad.qual.plugin'). `pc qual test`
runs them, a subtype at a time with '--basic', '--topology', '--simulation' and
'--other', and the IDE's Qualification group has a tab for each.

This was called validation.
"""

from .config import BASIC, OTHER, SECTION, SIM, SUBTYPES, TITLES, TOPOLOGY  # noqa: F401
