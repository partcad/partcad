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
        elif shutil.which("python3") is not None:
            self.exec_name = "python3"
        else:
            self.exec_name = "python"

        if not self.initialized:
            os.makedirs(self.path)
            self.initialized = True

    def run_onced(self, cmd, stdin="", cwd=None):
        return super().run_onced(
            [self.exec_name] + cmd,
            stdin,
            cwd=cwd,
        )

    async def run_async_onced(self, cmd, stdin="", cwd=None):
        return await super().run_async_onced(
            [self.exec_name] + cmd,
            stdin,
            cwd=cwd,
        )
