#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A JavaScript sandbox that runs the Node.js already installed on the host.

The twin of runtime_python_none: no interpreter is provisioned, only the
dependency tree is. The requested Node.js version is therefore advisory - the
sandbox is still named after it, so that a package which asks for a different
one does not silently share a dependency tree with this one.
"""

import os
import shutil

from . import runtime_javascript
from . import sandbox_versions
from . import logging as pc_logging
from . import telemetry


@telemetry.instrument()
class NoneJavaScriptRuntime(runtime_javascript.JavaScriptRuntime):
    def __init__(self, ctx, version=None):
        super().__init__(ctx, "none", version)

        self.exec_path = shutil.which(self.exec_name)
        self.npm_path = shutil.which(self.npm_name)
        if os.name == "nt" and self.npm_path is None:
            # On Windows npm ships as both 'npm.cmd' and a shell script named
            # 'npm'; only the former is executable through CreateProcess, but a
            # Node.js installed from an archive may carry only the latter.
            self.npm_path = shutil.which("npm")

    def once(self):
        os.makedirs(self.path, exist_ok=True)
        self.verify_node()
        super().once()

    async def once_async(self):
        os.makedirs(self.path, exist_ok=True)
        self.verify_node()
        await super().once_async()

    def verify_node(self):
        """Fail with a clear message rather than with ENOENT from Popen."""
        if self.exec_path is None:
            raise Exception(
                "ERROR: PartCAD is configured to use the host's Node.js to execute JavaScript scripts "
                "(Chili3D etc), but no 'node' was found. Install Node.js %s or newer, or set the "
                "'javascriptSandbox' user configuration option to 'conda' to have PartCAD provision one."
                % sandbox_versions.MIN_NODE_VERSION
            )
        if self.npm_path is None:
            raise Exception(
                "ERROR: PartCAD found Node.js at %s but no 'npm' next to it, and npm is what installs "
                "the CAD stack into a sandbox." % self.exec_path
            )
        pc_logging.debug("Using the host's Node.js: %s" % self.exec_path)
