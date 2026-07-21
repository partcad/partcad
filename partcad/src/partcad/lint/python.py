import os
import json
import asyncio
import subprocess

from partcad.context import Context
from partcad.project import Project
from partcad.lint.lint import Linting, LintingReport, Severity


class PythonLinting(Linting):
    def __init__(self, name: str) -> None:
        super().__init__(name)

    def get_targets(self, ctx: Context, package: Project) -> list[str]:
        """Return a list of Python files in the package's config directory."""
        return [os.path.join(package.config_dir, f) for f in os.listdir(package.config_dir) if f.endswith(".py")]

    async def validate(self, ctx: Context, package: Project, target: str, lint_ctx: dict = {}) -> LintingReport:
        linting_report = LintingReport(package.name)

        # Check if file exists
        if not os.path.isfile(target):
            linting_report.add(Severity.FAILED, f"File not found: {target}")
            return linting_report

        try:
            p = await asyncio.create_subprocess_exec(
                *["ruff", "check", "--no-cache", "--output-format=json", target],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = await p.communicate()
            stdout = stdout.decode()

            if stdout and 'passed' not in stdout:
                for item in json.loads(stdout):
                    location = item.get("location", {})
                    linting_report.add(
                        Severity.WARNING,
                        f"{item.get('filename', target)}:{location.get('row', 0)}:{location.get('column', 0)} {item.get('message', '')}",
                    )

        except Exception as e:
            linting_report.add(Severity.FAILED, f"Error running ruff: {str(e)}")

        return linting_report
