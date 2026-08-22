#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment
# (no need for a sandbox) to speed up parallel rendering and
# to reduce Python dependencies on the host environment

import os
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import wrapper_render_raster


def process(path, request):
    # renderPM forwards 'configPIL' to 'PIL.Image.save()', so these are the JPEG
    # encoder's own options. Only the ones the request carries are passed on, so
    # that Pillow's defaults remain the defaults for everything else.
    config_pil = {}
    for option in ("quality", "progressive", "optimize", "subsampling"):
        if request.get(option) is not None:
            config_pil[option] = request[option]

    return wrapper_render_raster.process(path, request, "JPEG", config_pil=config_pil)


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()

    # Perform rendering
    response = process(path, request)

    wrapper_common.handle_output(response)
