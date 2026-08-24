#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in DXF renderer (see '//builtin/render' in partcad.yaml).

DXF is the SVG projection, converted: 'render_svg.py' does the projection and
this turns its paths into DXF entities.
"""

import os
import sys
import tempfile

import svgpathtools
import ezdxf
from ezdxf.math import Vec2

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import render_svg

# How many straight segments a curve is approximated with. DXF R2010 has no
# general Bezier entity, so curves are flattened.
CURVE_SEGMENTS = 20


def convert_svg_to_dxf(svg_file, dxf_file, reproducible=True):
    paths, _attributes, _svg_attributes = svgpathtools.svg2paths2(svg_file)

    # A DXF is stamped, on every save, with the time it was written
    # ($TDCREATE/$TDUPDATE and their UTC twins), a freshly generated
    # $VERSIONGUID/$FINGERPRINTGUID pair, and an ezdxf marker string carrying
    # another timestamp. Two saves of the same drawing a second apart therefore
    # differ, which makes a DXF useless as something to check in and diff - and
    # checked-in output is how PartCAD notices that a render has changed.
    #
    # ezdxf writes fixed values for all of them behind this one option (a fixed
    # date, the all-zero GUID that 'ezdxf.new()' itself starts with, and a
    # constant marker). It is a global on the ezdxf module rather than an
    # argument to 'saveas', so it is set here, per call, in a process that
    # renders one file and exits.
    ezdxf.options.write_fixed_meta_data_for_testing = bool(reproducible)

    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()

    for path in paths:
        for segment in path:
            if segment.__class__.__name__ == "Line":
                msp.add_line(
                    Vec2(segment.start.real, segment.start.imag),
                    Vec2(segment.end.real, segment.end.imag),
                )
            elif segment.__class__.__name__ in ["CubicBezier", "QuadraticBezier", "Arc"]:
                for i in range(CURVE_SEGMENTS):
                    p0 = segment.point(i / float(CURVE_SEGMENTS))
                    p1 = segment.point((i + 1) / float(CURVE_SEGMENTS))
                    msp.add_line(Vec2(p0.real, p0.imag), Vec2(p1.real, p1.imag))

    if reproducible:
        # The other half of writing the same bytes twice. ezdxf registers a
        # CLASS entry for every DXF type the document uses, and it discovers
        # them by iterating 'EntityDB.dxf_types_in_use()' - a 'set' of type
        # names. Set iteration over strings follows the interpreter's hash seed,
        # which is randomized per process and cannot be pinned from the
        # environment here: the sandbox runs this wrapper with '-I', and that
        # makes Python ignore PYTHONHASHSEED. So two saves of one drawing emit
        # the CLASSES section in a different order about half the time.
        #
        # Registering the same names ourselves first, sorted, settles it:
        # 'ClassesSection.register()' keeps the first entry for a key and
        # ignores later ones, so ezdxf's own pass during 'saveas' adds only what
        # is left and cannot reorder what is already there.
        for dxftype in sorted(doc.entitydb.dxf_types_in_use()):
            doc.classes.add_class(dxftype)

    doc.saveas(dxf_file)


def process(path, request):
    svg_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            svg_path = f.name
        result_svg = render_svg.process(svg_path, request)

        if not result_svg.get("success", False):
            return {
                "success": False,
                "exception": f"SVG render failed: {result_svg.get('exception')}",
            }

        if not os.path.exists(svg_path):
            return {
                "success": False,
                "exception": f"SVG file was not created: {svg_path}",
            }

        # 'reproducible' defaults on: see convert_svg_to_dxf(). A package that
        # would rather have the real timestamps sets 'reproducible: false' on
        # the 'dxf' file type.
        reproducible = request.get("reproducible", True)
        convert_svg_to_dxf(svg_path, path, reproducible=reproducible)

        return {"success": True, "exception": None}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
    finally:
        # Every path above leaves through here, so the intermediate SVG never
        # accumulates in the temporary directory of a long render job.
        if svg_path and os.path.exists(svg_path):
            try:
                os.remove(svg_path)
            except OSError:
                pass
