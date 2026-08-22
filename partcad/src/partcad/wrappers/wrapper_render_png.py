#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-16
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
    return wrapper_render_raster.process(
        path,
        request,
        "PNG",
        config_pil={"transparent": True},
    )


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()

    # Perform rendering
    response = process(path, request)

    wrapper_common.handle_output(response)
