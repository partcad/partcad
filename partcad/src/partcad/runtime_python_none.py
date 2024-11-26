#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import os
import shutil

from . import runtime_python


class NonePythonRuntime(runtime_python.PythonRuntime):
    exec_name: str

    def __init__(self, ctx, version=None):
        super().__init__(ctx, "none", version)

        if os.name == "nt" and shutil.which("pythonw") is not None:
            self.exec_name = "pythonw"
        else:
            which = shutil.which("python3")
            if which is not None:
                self.exec_path = which
            else:
                self.exec_name = "python"

        if not self.initialized:
            os.makedirs(self.path)
            self.initialized = True

    def run_onced(self, cmd, stdin="", cwd=None, session=None, path=None):
        python_path = self.get_venv_python_path(session, path)
        return super().run_onced(
            [python_path] + cmd,
            stdin,
            cwd=cwd,
            session=session,
        )

    async def run_async_onced(
        self, cmd, stdin="", cwd=None, session=None, path=None
    ):
        python_path = self.get_venv_python_path(session, path)
        return await super().run_async_onced(
            [python_path] + cmd,
            stdin,
            cwd=cwd,
            session=session,
        )
