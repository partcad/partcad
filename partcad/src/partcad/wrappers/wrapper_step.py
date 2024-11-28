#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
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
from OCP.TopoDS import (
    TopoDS_Builder,
    TopoDS_Compound,
)

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    compound = None
    try:
        reader = STEPControl_Reader()
        readStatus = reader.ReadFile(path)
        if readStatus != OCP.IFSelect.IFSelect_RetDone:
            raise Exception("STEP File could not be loaded")
        for i in range(reader.NbRootsForTransfer()):
            reader.TransferRoot(i + 1)

        occ_shapes = []
        for i in range(reader.NbShapes()):
            occ_shapes.append(reader.Shape(i + 1))

        builder = TopoDS_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for shape in occ_shapes:
            builder.Add(compound, shape)
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            # "exception": e,
            "exception": str(e.with_traceback(None)),
            "shape": None,
        }

    return {
        "success": True,
        "exception": None,
        "shape": compound,
    }


path, request = wrapper_common.handle_input()

model = process(path, request)

wrapper_common.handle_output(model)
