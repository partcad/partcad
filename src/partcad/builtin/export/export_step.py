#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in STEP exporter (see '//builtin/export' in partcad.yaml).

Runs inside a PartCAD sandbox, driven by 'wrappers/wrapper_export.py'. It is
handed the shape to write in 'request["wrapped"]' and the export parameters
declared for 'step' as the remaining keys of 'request'.
"""

import os
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def _set_comment(writer, comment):
    """Put 'comment' into the STEP file's FILE_DESCRIPTION header entity.

    ISO 10303-21 has no free-form comment field; the closest thing a reader
    will show is the description carried by the exchange file's header, which
    is what a STEP "comment" conventionally means. Setting it has to happen
    after Transfer() -- that is when the writer populates the model whose
    header this rewrites -- and before Write().
    """
    from OCP.APIHeaderSection import APIHeaderSection_MakeHeader
    from OCP.TCollection import TCollection_HAsciiString

    header = APIHeaderSection_MakeHeader(writer.Model())
    if not header.IsDone():
        raise Exception("Failed to access the STEP header to write the comment")
    header.SetDescriptionValue(1, TCollection_HAsciiString(str(comment)))


def process(path, request):
    try:
        from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
        from OCP.Interface import Interface_Static

        obj = request["wrapped"]
        write_pcurves = 1 if request.get("write_pcurves", True) else 0
        precision_mode = request.get("precision_mode", 0)
        comment = request.get("comment")

        writer = STEPControl_Writer()
        Interface_Static.SetIVal_s("write.surfacecurve.mode", write_pcurves)
        Interface_Static.SetIVal_s("write.precision.mode", precision_mode)
        writer.Transfer(obj, STEPControl_AsIs)
        if comment:
            _set_comment(writer, comment)
        writer.Write(path)

        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create STEP file: {path}")

        return {"success": True, "exception": None}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
