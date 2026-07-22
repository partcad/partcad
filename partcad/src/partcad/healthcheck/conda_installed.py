#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

from partcad.runtime_python_conda import CondaPythonRuntime

from .tests import HealthCheckReport, HealthCheckTest


class CondaAvailableCheck(HealthCheckTest):
    min_space: int = 5

    def __init__(self):
        super().__init__(
            name="CondaAvailable",
            tags=["conda"],
            description="check if conda is installed and available",
        )

    def auto_fixable(self) -> bool:
        return False

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        conda_path = CondaPythonRuntime.find_conda_executable()
        if conda_path is None:
            self.findings.append("Conda is not installed or not available in the PATH.")
        return HealthCheckReport(self.name, self.findings, False)

    def fix(self) -> bool:
        return False
