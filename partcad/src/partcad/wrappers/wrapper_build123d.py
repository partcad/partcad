#
# OpenVMP, 2023-2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-01-01
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to invoke `build1213d` scripts.

from collections.abc import Iterable
import os
import re
import sys

from cadquery import cqgi
import build123d

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import py_stubs.ocp_vscode  # Make 'sys.modules["py_stubs.ocp_vscode"]' available
from ocp_tessellate.ocp_utils import (
    get_downcasted_shape,
    downcast,
    is_build123d,
    is_build123d_compound,
    is_build123d_shell,
    is_wrapped,
    is_vector,
    is_topods_compound,
    is_topods_shape,
    vertex,
)


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

    results = list()
    # TODO(clairbee): make it recursive to handle nested lists and unify handling of items on different levels of nesting
    for result in build_result.results:
        shape = result.shape
        converted = list()

        # BuildPart, BuildSketch, BuildLine
        if is_build123d(shape):
            shape = getattr(shape, shape._obj_name)  # convert to direct API

        # TODO(clairbee): do we really want to explode compounds?
        if is_build123d_compound(shape):
            converted.append(get_downcasted_shape(shape.wrapped))

        elif is_build123d_shell(shape):
            faces = []
            for face in shape.faces():
                faces.append(get_downcasted_shape(face.wrapped))
            converted.extend(faces)

        # TODO(clairbee): is this needed?
        # elif is_build123d_shape(shape):
        #     converted.append(get_downcasted_shape(shape.wrapped))

        # TODO(clairbee): migrate the below to cadquery
        # elif is_cadquery_sketch(shape):
        #     converted.extend(conv_sketch(shape))

        # elif is_cadquery(shape):
        #     for v in shape.vals():
        #         if is_cadquery_sketch(v):
        #             # obj = conv_sketch(v)
        #             pass
        #         elif is_vector(v):
        #             obj = [vertex(v.wrapped)]
        #             converted.extend(obj)
        #         else:
        #             obj = [v.wrapped]
        #             converted.extend(obj)

        elif is_wrapped(shape):
            if is_vector(shape):
                converted.append(vertex(shape.wrapped))
            elif is_topods_shape(shape):
                converted.extend(
                    get_downcasted_shape(shape.wrapped)
                )  # TODO(clairbee): append(shape.wrapped)? append(downcast(shape.wrapped))?
            else:
                converted.append(shape.wrapped)

        elif isinstance(shape, str):
            converted.append(shape)

        elif isinstance(shape, Iterable):

            def unpack(objs):
                for obj in objs:
                    if is_wrapped(obj):
                        if is_vector(obj):
                            yield vertex(obj.wrapped)
                        else:
                            yield downcast(obj.wrapped)
                    else:
                        yield obj

            converted.append(list(unpack(shape)))

        elif is_topods_compound(shape):
            converted.append(shape)

        elif is_topods_shape(shape):
            converted.append(downcast(shape))

        else:
            sys.stderr.write(f"Unknown object type: {type(shape)}\n")
            converted.append(shape)

        # TODO(clairbee): is this needed?
        # if len(converted) > 0 and is_compound_list(converted):
        #     converted = get_downcasted_shape(converted[0])

        def solidify(obj):
            if hasattr(obj, "solid"):
                try:
                    obj = obj.solid().wrapped
                except Exception as e:
                    pass
            return obj

        converted = list(
            map(
                solidify,
                converted,
            )
        )
        results.extend(converted)

    return {
        "success": build_result.success,
        "exception": build_result.exception,
        "shapes": results,
    }


path, request = wrapper_common.handle_input()

# Call build123d through CQGI
model = process(path, request)

wrapper_common.handle_output(model)
