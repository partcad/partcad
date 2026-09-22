#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""Whether this machine can build a conda sandbox at all.

The standalone bundle carries a conda of its own, so on a machine that has none
this check passes through the bundled copy -- which is the point of carrying it.
The wheels carry nothing, and there this reports what it always did.

Reported and not failed. A machine with no conda is not a broken machine: a
container runtime renders every part conda would have, and a virtual
environment renders most of them. Saying "error" here would fail
`pc healthcheck` on every machine that renders its parts in Docker, which is
the default wherever a daemon answers. `SandboxAvailable` is the check that
fails, and only when this one and `DockerAvailable` have both found nothing.
"""

from partcad.runtime_python_conda import CondaPythonRuntime
from partcad_utils import conda as pc_conda

from .tests import SEVERITY_WARNING, HealthCheckReport, HealthCheckTest


class CondaAvailableCheck(HealthCheckTest):
    min_space: int = 5

    def __init__(self):
        super().__init__(
            name="CondaAvailable",
            tags=["conda", "sandbox"],
            description="check if conda is installed and available",
            severity=SEVERITY_WARNING,
        )

    def auto_fixable(self) -> bool:
        return False

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        self.findings = []
        conda_path = CondaPythonRuntime.find_conda_executable()
        if conda_path is None:
            self.findings.append(
                "Conda is not installed or not available in the PATH. PartCAD builds a virtual "
                "environment instead, which works wherever the host has a usable Python; conda is what "
                "lets a package ask for an interpreter this machine does not have."
            )
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
