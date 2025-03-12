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

    @staticmethod
    def is_applicable():
        # Return false since the base class is not applicable
        # directly because it has an abstract method, hence this method
        # must be overridden by subclasses
        return False

    @abstractmethod
    def test(self) -> HealthCheckReport:
        pass

    def fix(self) -> bool:
        # Cannot auto-fix the issue
        return False
