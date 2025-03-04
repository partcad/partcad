import sys

from .healthcheck import HealthCheckReport, HealthCheckTest

class PythonVersionCheck(HealthCheckTest):
    min_version: tuple[int, int] = (3, 10)
    latest_version: tuple[int, int] = (3, 12)

    def __init__(self):
        super().__init__("PythonVersion")

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        if not self.min_version <= sys.version_info <= self.latest_version:
            self.findings.append(
                f"Python version {sys.version_info.major}.{sys.version_info.minor} is not supported. Please make sure your system python version is >={self.min_version[0]}.{self.min_version[1]}, <={self.latest_version[0]}.{self.latest_version[1]}"
            )
        return HealthCheckReport(self.name, self.findings, False)
