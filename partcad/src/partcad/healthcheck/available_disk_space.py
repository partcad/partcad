#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

from pathlib import Path
import shutil

from .tests import HealthCheckReport, HealthCheckTest
from partcad.user_config import user_config


class AvailableDiskSpaceCheck(HealthCheckTest):
    min_space: int = 5

    def __init__(self):
        super().__init__(
            name="AvailableDiskSpace",
            tags=["disk", "space"],
            description="check at least 5GB free disk space is available on the system",
        )

    def auto_fixable(self) -> bool:
        return False

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        try:
            path = user_config.internal_state_dir

            _, _, free = shutil.disk_usage(path)

            min_space_bytes = self.min_space * 1_000_000_000

            if free < min_space_bytes:
                self.findings.append(
                    f"Insufficient disk space. Need at least {self.min_space} GB free in {path}. Currently, only {free // (1024 * 1024 * 1024)} GB is available."
                )
        except Exception as e:
            self.findings.append("Error checking disk space")

        return HealthCheckReport(self.name, self.findings, False)

    def fix(self) -> bool:
        return False
