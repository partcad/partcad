import pkgutil
import importlib
from pathlib import Path
from abc import ABC, abstractmethod

import partcad.logging as pc_logging

class HealthCheckReport:
    def __init__(self, test: str, findings: list[str], fixed: bool):
        self.test: str = test
        self.findings: list[str] = findings
        self.fixed: bool = fixed
        self.log_header = "Healthcheck: {}: {}"

    def error(self, message: str) -> None:
        pc_logging.error(self.log_header.format(self.test, message))

    def debug(self, message:str):
        pc_logging.debug(self.log_header.format(self.test, message))

    def warning(self, message: str):
        pc_logging.warning(self.log_header.format(self.test, message))

    def info(self, message: str):
        pc_logging.info(self.log_header.format(self.test, message))

class HealthCheckTest(ABC):
    def __init__(self, name: str):
      self.name: str = name
      self.findings: list[str] = []

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

from partcad.healthcheck.windows_registry import WindowsRegistryCheck

def discover_tests() -> list[HealthCheckTest]:
    """Dynamically load all health check test modules and return instances"""
    test_instances = []
    package_path = Path(__file__).parent

    for _, module_name, _ in pkgutil.iter_modules([str(package_path)]):
        module = importlib.import_module(f"partcad.healthcheck.{module_name}")
        for Test in vars(module).values():
            if isinstance(Test, type) and issubclass(Test, HealthCheckTest) and Test not in [HealthCheckTest, WindowsRegistryCheck]:
                obj = Test()
                if obj.is_applicable():
                    test_instances.append(obj)

    if not test_instances:
        pc_logging.info("No applicable health check tests found")

    return test_instances
