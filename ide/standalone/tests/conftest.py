#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import pathlib
import sys

# The tools are scripts rather than an installed package: they run inside a
# build, from a checkout, with nothing installed but their dependencies.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPONENT_ROOT = pathlib.Path(__file__).resolve().parents[1]
