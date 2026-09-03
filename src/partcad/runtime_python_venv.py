#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A sandbox that is a real virtual environment of its own.

The middle ground between the two sandboxes that existed before it, and the
reason it is the fallback rather than either of them:

  * 'conda' provisions the interpreter as well as the packages, so it can give a
    package the Python version it asked for. It has to be installed first, and
    on a host without it there was nothing to fall back to but:
  * 'none', which is not an environment at all. It runs whatever Python the host
    has and installs into it -- so rendering a part writes packages into the
    interpreter the user runs everything else with, and a machine whose Python
    is not writable (a system package manager's, a read-only image) cannot
    render at all.

This one creates a virtual environment at the sandbox's own path and both
installs into it and runs from it, which is what a sandbox is for. It cannot
choose an interpreter version -- a venv is made *from* an interpreter, so what
the host has is what a package gets -- and it says so when the host's version is
not the one asked for, rather than quietly rendering on the wrong one.
"""

import os
import shutil
import subprocess
import sys

from . import logging as pc_logging
from . import runtime_python
from . import telemetry


@telemetry.instrument()
class VenvPythonRuntime(runtime_python.PythonRuntime):
    def __init__(self, ctx, version=None):
        super().__init__(ctx, "venv", version)

        # The interpreter the environment is made *from*. Held separately
        # because 'exec_path' has to be this one while the environment is being
        # created and the environment's own one for everything afterwards, and
        # the machinery that runs a command reads 'exec_path'.
        self.host_exec_path = self._host_interpreter()
        self.exec_path = self.venv_exec_path if os.path.exists(self.venv_exec_path) else self.host_exec_path

    @property
    def venv_exec_path(self) -> str:
        """The interpreter inside the environment, once it exists."""
        if os.name == "nt":
            return os.path.join(self.path, "Scripts", self.exec_name)
        return os.path.join(self.path, "bin", self.exec_name)

    def _host_interpreter(self) -> str:
        """The host interpreter to build this environment from.

        The one named for the version asked for where the host has it, so a
        package that asks for 3.11 gets 3.11 on a host that has several. Failing
        that, whatever 'python3' is, and failing that the interpreter PartCAD
        itself is running on -- which always exists, and is the answer that needs
        no PATH at all.
        """
        if os.name != "nt":
            for name in ("python%s" % self.version, "python3", "python"):
                found = shutil.which(name)
                if found is not None:
                    return found
        else:
            found = shutil.which(self.exec_name)
            if found is not None:
                return found
        return sys.executable

    def _report_version(self) -> None:
        """Say so when the host cannot give the version that was asked for.

        Once per sandbox, and a warning rather than a refusal: rendering on
        3.12 when a package asked for 3.11 usually works, and refusing to render
        at all is worse than saying which interpreter did it.
        """
        try:
            actual = subprocess.run(
                [self.host_exec_path, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout.strip()
        except Exception as e:
            pc_logging.debug("Could not ask %s its version: %s" % (self.host_exec_path, e))
            return
        if actual and actual != self.version:
            pc_logging.warning(
                "Python %s was asked for and this host has %s; the '%s' sandbox is built from the host's"
                " interpreter, so %s is what this renders on. Install conda for a sandbox that can provision"
                " an interpreter of its own." % (self.version, actual, self.sandbox, actual)
            )

    def _create_locked(self) -> list:
        """The command that builds the environment, or an empty list.

        Empty when it is already there, which is the common case: an environment
        is built once and used by every render afterwards.
        """
        if os.path.exists(self.venv_exec_path):
            self.exec_path = self.venv_exec_path
            return []
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._report_version()
        # Built by the host's interpreter, so 'exec_path' has to be that one for
        # the length of this command and the environment's own one afterwards.
        self.exec_path = self.host_exec_path
        return ["-m", "venv", "--upgrade-deps", self.path]

    def _created(self, exitcode, stderr) -> None:
        """Accept the environment, or fail with what actually went wrong.

        'run_onced_locked' reports an exit code rather than raising, so a failed
        '-m venv' -- no ensurepip, a full disk, a directory that cannot be
        written -- would otherwise be stepped straight past. 'exec_path' would
        then name an interpreter that was never created, and the first thing the
        base does with it is install a package: the error the user sees would be
        that install failing on a missing file, with the creation failure that
        caused it nowhere in sight.
        """
        if exitcode != 0 or not os.path.exists(self.venv_exec_path):
            raise Exception(
                "Failed to create the '%s' sandbox at %s: %s"
                % (self.sandbox, self.path, (stderr or "").strip() or "'-m venv' exited with %s" % exitcode)
            )
        self.exec_path = self.venv_exec_path

    def once(self):
        if self.provisioned:
            return
        with self.sync_lock(write=True):
            command = self._create_locked()
            if command:
                with pc_logging.Action("Venv", self.version, self.path):
                    exitcode, _, stderr = self.run_onced_locked(command)
                self._created(exitcode, stderr)
        # Outside the lock above rather than inside it: the base takes the same
        # lock, and it is a file lock rather than a re-entrant one.
        super().once()

    async def once_async(self):
        if self.provisioned:
            return
        async with self.async_lock(write=True):
            command = self._create_locked()
            if command:
                with pc_logging.Action("Venv", self.version, self.path):
                    exitcode, _, stderr = await self.run_async_onced_locked(command)
                self._created(exitcode, stderr)
        await super().once_async()
