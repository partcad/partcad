#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from . import runtime_javascript_none
from . import runtime_javascript_conda


def create(ctx, version, javascript_runtime=None):
    if javascript_runtime is None:
        javascript_runtime = ctx.user_config.javascript_sandbox
    if javascript_runtime == "none":
        return runtime_javascript_none.NoneJavaScriptRuntime(ctx, version)
    elif javascript_runtime == "conda":
        return runtime_javascript_conda.CondaJavaScriptRuntime(ctx, version)
    else:
        raise Exception("ERROR: invalid javascript runtime type (sandbox type) %s" % javascript_runtime)
