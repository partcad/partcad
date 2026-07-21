import os
import json
import asyncio
import subprocess
import threading

from partcad.context import Context
from partcad.project import Project
from partcad.lint.lint import Linting, LintingReport, Severity
from partcad.optional_deps import OptionalDependencyError, import_optional

# Lazy-load the linting dependency as it is not always needed.
# `ruff` is an optional extra: it is only required when Python linting runs.
# import ruff.__main__
ruff_main = None
# The absolute path of the `ruff` executable shipped by the `ruff` package
ruff_bin = None

lock = threading.Lock()


def ruff_once() -> str:
    """Return the absolute path of the `ruff` executable shipped by the `ruff` package.

    The `ruff` distribution ships a Rust binary and exposes no Python linting API,
    so linting has to run as a subprocess. Resolving the binary through the package
    rather than looking up the bare name `ruff` on PATH ties the linter to the
    installed, version-pinned package instead of whatever happens to be on PATH.

    Raises OptionalDependencyError, naming the exact install command, when the
    package is missing or does not carry its executable.
    """
    global ruff_main
    global ruff_bin

    # Initialize each global under its own guard, so that a failure to resolve the
    # executable does not leave a half-initialized state that a retry would skip.
    with lock:
        if ruff_main is None:
            ruff_main = import_optional("ruff.__main__", "Python linting", "lint")

        if ruff_bin is None:
            try:
                ruff_bin = ruff_main.find_ruff_bin()
            except FileNotFoundError as e:
                raise OptionalDependencyError(
                    f"The 'ruff' package is installed but its executable was not found ({str(e)}). "
                    "Install it with: pip install 'partcad[lint]' "
                    "(or 'partcad-cli[lint]' when using the command line interface)."
                ) from e

    return ruff_bin


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
                *[ruff_once(), "check", "--no-cache", "--output-format=json", target],
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
