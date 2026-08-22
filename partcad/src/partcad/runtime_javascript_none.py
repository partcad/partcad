#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A JavaScript sandbox that runs the Node.js already installed on the host.

The twin of runtime_python_none: no interpreter is provisioned, only the
dependency tree is. What the package asked for is therefore a request rather
than a guarantee - so this runtime is identified by the Node.js it actually
found, not by the one it was asked for.

That distinction matters because the version is what names the sandbox
directory and what a shape is cached under (see
Shape.set_environment_cache_key). Taking the request at face value would let a
package that asks for Node.js 24 run on the host's 22 and then record the result
as though 24 had produced it. Use the conda sandbox when a version has to be
enforced rather than observed.
"""

import os
import shutil
import subprocess

from . import runtime_javascript
from . import sandbox_versions
from . import logging as pc_logging
from . import telemetry


def find_node() -> str | None:
    """The host's Node.js, or None if there is none on PATH."""
    return shutil.which("node" if os.name != "nt" else "node.exe")


def find_npm() -> str | None:
    """The host's npm, or None if there is none PartCAD can execute.

    On Windows, only the launcher forms CreateProcess can start are worth
    finding: npm also ships as an extensionless shell script, which subprocess
    cannot execute, so falling back to a bare "npm" would trade this module's
    clear error for an OSError later on.
    """
    if os.name != "nt":
        return shutil.which("npm")
    for candidate in ("npm.cmd", "npm.exe", "npm.bat"):
        npm_path = shutil.which(candidate)
        if npm_path is not None:
            return npm_path
    return None


def host_node_version(exec_path: str | None) -> str | None:
    """The major version of the host's Node.js, or None if it cannot be asked.

    Runs at construction because the version decides the sandbox directory, so
    it has to be known before the base class builds one.
    """
    if exec_path is None:
        return None
    try:
        completed = subprocess.run(
            [exec_path, "--version"],
            capture_output=True,
            encoding="utf-8",
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        pc_logging.warning("Failed to ask %s for its version: %s" % (exec_path, e))
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        pc_logging.warning("%s --version reported nothing usable" % exec_path)
        return None
    return sandbox_versions.node_major_version(completed.stdout.strip())


@telemetry.instrument()
class NoneJavaScriptRuntime(runtime_javascript.JavaScriptRuntime):
    def __init__(self, ctx, version=None):
        exec_path = find_node()
        detected = host_node_version(exec_path)
        if detected is not None and version is not None:
            requested = sandbox_versions.node_major_version(str(version))
            if requested != detected:
                # Not an error: the Python 'none' sandbox is equally free to be
                # a different interpreter than the one a package asked for, and
                # refusing here would make this sandbox unusable for anyone
                # whose Node.js is not the default. Saying so is what matters,
                # because the shape is about to be cached as version 'detected'.
                pc_logging.warning(
                    "This package asks for Node.js %s but the host has %s, which is what will render it. "
                    "Set the 'javascriptSandbox' user configuration option to 'conda' to have PartCAD "
                    "provision the requested version instead." % (requested, detected)
                )

        # The version that actually renders, so the sandbox directory and the
        # environment cache key both describe what produced the shape.
        super().__init__(ctx, "none", detected if detected is not None else version)

        self.exec_path = exec_path
        self.npm_path = find_npm()

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
        if not sandbox_versions.is_at_least(self.version, sandbox_versions.MIN_NODE_VERSION):
            raise Exception(
                "ERROR: PartCAD found Node.js %s at %s, but the Chili3D wrapper needs %s or newer. "
                "Upgrade it, or set the 'javascriptSandbox' user configuration option to 'conda' to "
                "have PartCAD provision one." % (self.version, self.exec_path, sandbox_versions.MIN_NODE_VERSION)
            )
        pc_logging.debug("Using the host's Node.js %s: %s" % (self.version, self.exec_path))
