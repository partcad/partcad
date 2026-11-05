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

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1


def process(path, request):
    init_globals = {"request": request}
    if request.get("api") == "login":
        # The one api that is given a callback: 'partcad_login.open_browser'
        # (see plugin_login.py). Imported here rather than at the top, so the
        # other apis - every key a repository is asked - pay nothing for it.
        import plugin_login

        init_globals["partcad_login"] = plugin_login.LoginCallback(request.get("login"))
    try:
        result = runpy.run_path(
            path,
            init_globals=init_globals,
            run_name=request["api"],
        )
    except Exception as e:
        result = {"exception": e}
    except BaseException as e:
        # The plugin asked for the browser. Not a failure: PartCAD opens it and
        # runs 'login' again with what it brought back - or, with nobody there
        # to use one, says what to do instead.
        if not hasattr(e, "spec"):
            raise
        if type(e).__name__ == "BrowserNeeded":
            return {"browser": e.spec}
        if type(e).__name__ == "InstructionsNeeded":
            return {"instructions": e.spec}
        raise

    if "output" in result:
        output = result["output"]
    else:
        output = {}

    if "exception" in result:
        output["exception"] = wrapper_common.exception_to_str(result["exception"])
        wrapper_common.handle_exception(result["exception"], path)

    return output


path, request = wrapper_common.handle_input()

# Call the API endpoint
result = process(path, request)

wrapper_common.handle_output(result)
