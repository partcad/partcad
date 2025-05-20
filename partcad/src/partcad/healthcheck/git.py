import git
import sys
import subprocess
from git.exc import GitCommandNotFound

from .tests import HealthCheckReport, HealthCheckTest


class GitCheck(HealthCheckTest):
    def __init__(self):
        super().__init__(
            name="Git",
            tags=["git"],
            description="Check if git is installed",
        )
        if sys.platform == "linux":
            self.git_install_cmd = ["apt-get", "install", "git"]
        elif sys.platform == "darwin":
            self.git_install_cmd = ["brew", "install", "git"]

    def auto_fixable(self) -> bool:
        return sys.platform in ["linux", "darwin"]

    def is_applicable(self) -> bool:
        return True

    def test(self) -> HealthCheckReport:
        try:
            git.Git().version()
        except GitCommandNotFound:
            self.findings.append("Git is not installed on this system.")
        return HealthCheckReport(self.name, self.findings, False)

    def fix(self) -> bool:
        result = subprocess.run(self.git_install_cmd)
        return result.returncode == 0
