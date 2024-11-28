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
import re
import sys

from cadquery import cqgi

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import py_stubs.ocp_vscode  # Make 'sys.modules["py_stub.ocp_vscode"]' available


def process(path, request):
    build_parameters = {}
    if "patch" in request:
        patch = request["patch"]
    else:
        patch = {}
    if "build_parameters" in request:
        build_parameters = request["build_parameters"]

    with open(path, "r") as f:
        script = f.read()
    for old, new in patch.items():
        script = re.sub(old, new, script, flags=re.MULTILINE)

    if "import partcad" in script:
        script = (
            "import logging\nlogging.basicConfig(level=60)\n"  # Disable PartCAD logging
            + script
        )

    # Ignore ocp_vscode as it is of no use in the sandboxed environment
    # and it produces a lot of sporadic output to stdout and stderr
    sys.modules["ocp_vscode"] = sys.modules["py_stubs.ocp_vscode"]
    if "from ocp_vscode import " in script:
        script = re.sub(
            r"(from ocp_vscode import .*)\n",
            "saved_show_object_early=show_object\n\\1\nimport ocp_vscode\nocp_vscode.saved_show_object=saved_show_object_early\n",
            script,
        )
    if "import ocp_vscode" in script:
        script = script.replace(
            "import ocp_vscode",
            "import ocp_vscode\nocp_vscode.saved_show_object=show_object\n#",
        )

    # Execute the script
    script_object = cqgi.parse(script)
    build_result = script_object.build(build_parameters=build_parameters)

    if not build_result.success:
        wrapper_common.handle_exception(build_result.exception, path)

    shapes = []
    for result in build_result.results:
        shape = result.shape
        if hasattr(shape, "toOCC"):
            shape = shape.toOCC()
        if hasattr(shape, "val"):
            shape = shape.val()
        if hasattr(shape, "toCompound"):
            shape = shape.toCompound()
        if hasattr(shape, "wrapped"):
            shape = shape.wrapped
        shapes.append(shape)

    return {
        "success": build_result.success,
        "exception": build_result.exception,
        "shapes": shapes,
    }


path, request = wrapper_common.handle_input()

# Call CadQuery
model = process(path, request)

wrapper_common.handle_output(model)
