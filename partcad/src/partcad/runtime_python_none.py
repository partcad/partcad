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

        which = shutil.which("python")
        if which is not None:
            self.exec_path = which
        else:
            which3 = shutil.which("python3")
            if which3 is not None:
                self.exec_path = which3
            else:
                self.exec_path = which

        if not self.initialized:
            os.makedirs(self.path)
            self.initialized = True
