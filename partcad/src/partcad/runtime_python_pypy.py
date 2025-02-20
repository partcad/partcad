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

from . import runtime_python_conda


class PyPyPythonRuntime(runtime_python_conda.CondaPythonRuntime):
    def __init__(self, ctx, version=None):
        super().__init__(ctx, version, variant="pypy")

        self.exec_name = "pypy" if os.name != "nt" else "pypy.exe"
        which = shutil.which(self.exec_name)
        if which is None:
            raise Exception(
                "ERROR: PartCAD is configured to use missing pypy to execute Python scripts (CadQuery, build123d etc)"
            )
        self.exec_path = which
