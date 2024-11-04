#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to invoke `cadquery` scripts.

import os
import sys

from OCP.STEPControl import STEPControl_Reader
import OCP.IFSelect

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    reader = STEPControl_Reader()
    readStatus = reader.ReadFile(path)
    if readStatus != OCP.IFSelect.IFSelect_RetDone:
        raise ValueError("STEP File could not be loaded")
    for i in range(reader.NbRootsForTransfer()):
        reader.TransferRoot(i + 1)

    occ_shapes = []
    for i in range(reader.NbShapes()):
        occ_shapes.append(reader.Shape(i + 1))

    return {
        "success": True,
        "exception": None,
        "shape": occ_shapes,
    }


path, request = wrapper_common.handle_input()

model = process(path, request)

wrapper_common.handle_output(model)
