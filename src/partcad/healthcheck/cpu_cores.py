#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Whether this machine has the cores PartCAD sizes itself for.

PartCAD never runs with fewer than 'THREADS_MAX_MINIMUM' threads and sandbox
processes, whatever the machine: that is the least it does at once, for the
reasons given in 'partcad_utils.user_config'. On a machine with fewer cores than
that, those run on cores they have to share, so everything works and everything
is slower -- which is a warning, not a failure.

The same sentence is said once by whatever sizes the sandbox slots on such a
machine; this is the place a user goes looking for it.
"""

from partcad_utils.user_config import THREADS_MAX_MINIMUM, cpu_cores, few_cores_warning

from .tests import HealthCheckReport, HealthCheckTest


class CpuCoresCheck(HealthCheckTest):
    def __init__(self):
        super().__init__(
            name="CpuCores",
            tags=["cpu", "cores", "performance"],
            description="check the machine has at least %d CPU cores" % THREADS_MAX_MINIMUM,
        )

    def auto_fixable(self) -> bool:
        return False

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        cores = cpu_cores()
        if cores < THREADS_MAX_MINIMUM:
            self.findings.append(few_cores_warning(cores))
        return HealthCheckReport(self.name, self.findings)

    def fix(self) -> bool:
        return False
