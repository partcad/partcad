#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

from . import runtime_python_none
from . import runtime_python_pypy
from . import runtime_python_conda


def create(ctx, version, python_runtime=None):
    if python_runtime is None:
        python_runtime = ctx.user_config.python_runtime
    if python_runtime == "none":
        return runtime_python_none.NonePythonRuntime(ctx, version)
    elif python_runtime == "pypy":
        return runtime_python_pypy.PyPyPythonRuntime(ctx, version)
    elif python_runtime == "conda":
        return runtime_python_conda.CondaPythonRuntime(ctx, version)
    else:
        raise Exception("ERROR: invalid python runtime type (sandbox type) %s" % python_runtime)
