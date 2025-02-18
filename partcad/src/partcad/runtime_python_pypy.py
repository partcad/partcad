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

        self.exec_name = "pypy" if os.name != "nt" else "pypy.exe"
        # Lock the global conda lock and create a new conda environment
        with runtime_python._global_conda_lock:
            if not self.initialized:
                which = shutil.which("pypy")
                if which is None:
                    raise Exception(
                        "ERROR: PartCAD is configured to use missing pypy to execute Python scripts (CadQuery, build123d etc)"
                    )
                self.exec_path = which

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

                    self.initialized = True
                except Exception as e:
                    shutil.rmtree(self.path)
                    raise e
