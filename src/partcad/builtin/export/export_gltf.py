#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in glTF exporter (see '//builtin/export' in partcad.yaml)."""

import os
import sys

# Imported before build123d, which reaches OCP and VTK: see the note in
# ocp_serialize about VTK's bundled expat shadowing the standard library's.
sys.path.append(os.path.dirname(__file__))
import wrapper_common

import build123d as b3d


def process(path, request):
    try:
        obj = request.get("wrapped")
        if obj is None:
            raise ValueError("No wrapped object provided for GLTF export")

        # The caller sends raw OCCT geometry, so rebuild the build123d wrapper that
        # export_gltf() needs. 'cast' picks the matching type, which matters here
        # because an assembly arrives as a compound rather than a solid.
        #
        # Compound.cast, not Shape.cast: build123d 0.11 made Shape.cast abstract,
        # so it silently returns None and export_gltf then fails on None.location.
        # Compound.cast carries the full lookup table (vertex through compound)
        # that Shape.cast used to have, and is what build123d's own import_step
        # uses.
        obj = b3d.Compound.cast(obj)

        tolerance = request.get("tolerance", 0.1)
        angular_tolerance = request.get("angularTolerance", 0.1)
        binary = request.get("binary", False)

        if not os.path.isabs(path):
            path = os.path.abspath(path)

        out_dir = os.path.dirname(path)
        os.makedirs(out_dir, exist_ok=True)

        b3d.export_gltf(
            obj,
            path,
            binary=binary,
            linear_deflection=tolerance,
            angular_deflection=angular_tolerance,
        )

        # Check if file is successfully created
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise Exception(f"Failed to create GLTF file: {path}")

        return {"success": True, "exception": None}

    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}
