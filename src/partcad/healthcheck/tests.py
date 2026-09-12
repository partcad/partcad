#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import importlib
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path

from .. import logging as pc_logging


class HealthCheckReport:
    def __init__(self, test: str, findings: list[str], fixed: bool = False):
        self.test: str = test
        self.findings: list[str] = findings
        self.fixed: bool = fixed
        self.log_header = "Healthcheck: {}: {}"

    def error(self, message: str) -> None:
        pc_logging.error(self.log_header.format(self.test, message))

    def debug(self, message: str):
        pc_logging.debug(self.log_header.format(self.test, message))

    def warning(self, message: str):
        pc_logging.warning(self.log_header.format(self.test, message))

    def info(self, message: str):
        pc_logging.info(self.log_header.format(self.test, message))


class HealthCheckTest(ABC):
    def __init__(self, name: str, tags: list[str], description: str):
        self.name: str = name
        self.findings: list[str] = []
        self.tags: list[str] = tags
        self.description: str = description

    @abstractmethod
    def auto_fixable(self) -> bool:
        pass

    @abstractmethod
    def is_applicable(self) -> bool:
        # Return false since the base class is not applicable
        # directly because it has an abstract method, hence this method
        # must be overridden by subclasses
        return False

    @abstractmethod
    def test(self) -> HealthCheckReport:
        pass

    @abstractmethod
    def fix(self) -> bool:
        pass


from ..healthcheck.openscad import OpenSCADCheck
from ..healthcheck.windows_registry import WindowsRegistryCheck


def discover_healthchecks() -> list[HealthCheckTest]:
    """Dynamically load all health check test modules and return instances"""
    test_instances = []
    package_path = Path(__file__).parent

    for _, module_name, _ in pkgutil.iter_modules([str(package_path)]):
        module = importlib.import_module(f"partcad.healthcheck.{module_name}")
        for Test in vars(module).values():
            if (
                isinstance(Test, type)
                and issubclass(Test, HealthCheckTest)
                and Test not in [HealthCheckTest, WindowsRegistryCheck, OpenSCADCheck]
            ):
                obj = Test()
                if obj.is_applicable():
                    test_instances.append(obj)

    if not test_instances:
        pc_logging.info("No applicable healthcheck tests found")

    return test_instances


def run_healthchecks(filters: str = None, fix: bool = False, dry_run: bool = False) -> None:
    with pc_logging.Process("Healthcheck", "global"):
        tests = discover_healthchecks()

        if filters:
            for val in filters.split(","):
                tests = filter(lambda test: any(val.strip().lower() in tag.lower() for tag in test.tags), tests)

        if dry_run:
            if tests:
                for test in tests:
                    pc_logging.info(f"Suggested healthcheck: {test.name} - {test.description}")
            return

        for test in tests:
            with pc_logging.Action(test.name, "global"):
                report = test.test()
                if report.findings:
                    report.warning(test.findings)
                    if fix and test.auto_fixable():
                        report.debug("Attempting to fix issues...")
                        # A fix that raises is a failed fix, not the end of the
                        # run. It was the end of the run: the macOS OpenSCAD fix
                        # exec'd a Homebrew that was not installed, the
                        # `FileNotFoundError` came out here, and `--fix` died
                        # before reaching any of the checks after it -- so a Mac
                        # with no Homebrew could not clear its stale git locks
                        # either, for a reason that had nothing to do with them.
                        # Each fix is independent and the caller asked for all of
                        # them.
                        try:
                            report.fixed = test.fix()
                        except Exception as error:
                            report.fixed = False
                            report.error(f"Auto fix raised: {error}")
                            pc_logging.exception(f"Healthcheck '{test.name}' failed while fixing")
                        if report.fixed:
                            report.info("Auto fix successful")
                        else:
                            report.error("Auto fix failed")
                else:
                    report.info("Passed")
