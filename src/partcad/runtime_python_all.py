#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

from . import runtime_python_docker
from . import runtime_python_none
from . import runtime_python_pypy
from . import runtime_python_conda
from . import runtime_python_venv


def create(ctx, version, python_runtime=None, image=None):
    if python_runtime is None:
        python_runtime = ctx.user_config.python_sandbox
    if python_runtime == "docker":
        # 'image' is the one parameter only this sandbox can use: it is which
        # image to build the environment in, and every other sandbox builds one
        # out of what the host has.
        return runtime_python_docker.DockerPythonRuntime(ctx, version, image=image)
    elif python_runtime == "none":
        return runtime_python_none.NonePythonRuntime(ctx, version)
    elif python_runtime == "venv":
        return runtime_python_venv.VenvPythonRuntime(ctx, version)
    elif python_runtime == "pypy":
        return runtime_python_pypy.PyPyPythonRuntime(ctx, version)
    elif python_runtime == "conda":
        return runtime_python_conda.CondaPythonRuntime(ctx, version)
    elif python_runtime == "remote":
        # Half of this exists. `partcad-service-remote-docker` runs the
        # containers and forwards the requests; what is not written is the
        # client that sends them, because where its virtual environment lives
        # is a decision rather than a detail -- it cannot be on the caller's
        # disk, which is the whole point of `remote`.
        #
        # Said plainly rather than left to "invalid python runtime type", which
        # is what a documented value falling through to the else branch reads
        # as: a user who has read the documentation being told they made the
        # name up.
        raise Exception(
            "The 'remote' sandbox is not finished: 'partcad-service-remote-docker' serves the "
            "containers, but the client that talks to it is still being written. Use 'docker' for "
            "a container on this machine, or 'conda'."
        )
    else:
        raise Exception("ERROR: invalid python runtime type (sandbox type) %s" % python_runtime)
