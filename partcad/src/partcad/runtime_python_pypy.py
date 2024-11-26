#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import os
import shutil
import subprocess

from . import runtime_python


class PyPyPythonRuntime(runtime_python.PythonRuntime):
    def __init__(self, ctx, version=None):
        super().__init__(ctx, "pypy", version)

        if not self.initialized:
            which = shutil.which("pypy")
            if which is None:
                raise Exception(
                    "ERROR: PartCAD is configured to use missing pypy to execute Python scripts (CadQuery, build123d etc)"
                )
            self.exec_path = which

            os.makedirs(self.path)
            try:
                subprocess.run(
                    [
                        "conda",
                        "create",
                        "-p",
                        self.path,
                        "pypy",
                        "python=%s" % version,
                    ]
                )
                subprocess.run(["conda", "install", "-p", self.path, "scipy"])
            except Exception as e:
                shutil.rmtree(self.path)
                raise e

    def run_onced(self, cmd, stdin="", cwd=None, session=None, path=None):
        # TODO: python_path = self.get_venv_python_path(session, path)
        return super().run_onced(
            ["conda", "run", "--no-capture-output", "-p", self.path, "pypy"]
            + cmd,
            stdin,
            cwd=cwd,
            session=session,
        )

    async def run_async_onced(
        self, cmd, stdin="", cwd=None, session=None, path=None
    ):
        # TODO: python_path = self.get_venv_python_path(session, path)
        return await super().run_async_onced(
            ["conda", "run", "--no-capture-output", "-p", self.path, "pypy"]
            + cmd,
            stdin,
            cwd=cwd,
            session=session,
        )
