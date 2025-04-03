#
# OpenVMP, 2023-2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to invoke `build1213d` scripts.

import os
import runpy
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def process(path, request):
    try:
        result = runpy.run_path(
            path,
            init_globals={
                "request": request,
            },
            run_name=request["api"],
        )
    except Exception as e:
        result = {"exception": e}

    if "output" in result:
        output = result["output"]
    else:
        output = {}

    if "exception" in result:
        output["exception"] = result["exception"]
        wrapper_common.handle_exception(result["exception"], path)

    return output


path, request = wrapper_common.handle_input()

# Call the API endpoint
result = process(path, request)

wrapper_common.handle_output(result)
