#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import sys

from .tests import HealthCheckReport, HealthCheckTest


class PythonVersionCheck(HealthCheckTest):
    # The interpreters PartCAD supports, and nothing else: these are
    # `requires-python` in `pyproject.toml` (">=3.10,<3.15") said as tuples.
    # They drifted once -- `pyproject.toml` accepted 3.13 and 3.14 while this
    # still stopped at 3.12 -- and the standalone bundle, which carries its own
    # 3.14, spent every start telling the user that the interpreter PartCAD
    # ships is unsupported and that they should go and change their system
    # Python. `tests/partcad/unit/test_healthcheck_python_version.py` reads
    # `pyproject.toml` and fails when the two disagree again.
    #
    # The upper bound is an open one, `< 3.15`, written as "3.14 and any patch
    # release of it" so that it can be compared against `sys.version_info`.
    min_version: tuple[int, int] = (3, 10)
    latest_version: tuple[int, int, float] = (3, 14, float("inf"))

    def __init__(self):
        super().__init__(
            name="PythonVersion",
            tags=["python"],
            description="Check PartCAD's compatibility with the system's Python version",
        )

    def auto_fixable(self) -> bool:
        return False

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        if not self.min_version <= sys.version_info <= self.latest_version:
            self.findings.append(
                f"Python version {sys.version_info.major}.{sys.version_info.minor} is not supported. Please make sure your system python version is >={self.min_version[0]}.{self.min_version[1]}, <={self.latest_version[0]}.{self.latest_version[1]}"
            )
        return HealthCheckReport(self.name, self.findings)

    def fix(self) -> bool:
        return False
