#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Console-mode entry point for the PartCAD addon.

FreeCAD runs this in both GUI and console mode, before ``InitGui.py``. The addon
is a GUI tool, so there is nothing to set up here -- but a FreeCAD script may
still want the addon's non-GUI half, and this file being present (and importing
nothing heavy) keeps ``import partcad_freecad`` working in ``freecadcmd``.
"""
