import pkgutil
import importlib
import rich_click as click
from pathlib import Path

import partcad.healthcheck.healthcheck
from partcad.healthcheck.healthcheck import HealthCheckTest
import partcad.logging as pc_logging


def discover_tests() -> list[HealthCheckTest]:
    """Dynamically load all health check test modules and return instances"""
    test_instances = []
    package_path = Path(partcad.healthcheck.healthcheck.__file__).parent

    for _, module_name, _ in pkgutil.iter_modules([str(package_path)]):
        module = importlib.import_module(f"partcad.healthcheck.{module_name}")
        for obj in vars(module).values():
            if hasattr(obj, "is_applicable") and obj.is_applicable():
                test_instances.append(obj())

    if not test_instances:
        pc_logging.info("No applicable health check tests found")

    return test_instances

@click.command(help="Perform a health check, to get instructions on what needs to be fixed")
@click.option(
    "--fix",
    is_flag=True,
    help="Attempt to fix any issues found",
)
def cli(fix) -> None:
    for test in discover_tests():
        pc_logging.debug(f"Running '{test.name}' health check...")
        report = test.test()
        if report.findings:
            report.warning(test.findings)
            if fix:
                report.debug("Attempting to fix issues...")
                report.fixed = test.fix()
                if report.fixed:
                    report.info(f"Auto fix successful")
                else:
                    report.error(f"Auto fix failed")
        else:
            report.info(f"Passed")
