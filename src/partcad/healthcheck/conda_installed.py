#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""Whether this machine can build a conda sandbox at all.

The standalone bundle carries a conda of its own, so on a machine that has none
this check passes through the bundled copy -- which is the point of carrying it.
The wheels carry nothing, and there this reports what it always did.
"""

from partcad_utils import conda as pc_conda

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
        report = HealthCheckReport(self.name, self.findings, False)
        if conda_path is not None:
            # Which one, because "a conda works here" and "the conda you
            # installed works here" are different statements, and on a machine
            # that has both this is the only thing that says which was taken.
            source = "carried by this bundle" if pc_conda.is_bundled(conda_path) else "found on this machine"
            report.debug("Using the conda %s: %s" % (source, conda_path))
        return report

    def fix(self) -> bool:
        return False
