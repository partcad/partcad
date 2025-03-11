import rich_click as click
from typing import List

import partcad.logging as pc_logging
from partcad.healthcheck.healthcheck import discover_tests


@click.command(help="Perform a health check, to get instructions on what needs to be fixed")
@click.option(
    "--filters",
    help="Run only tests with the specified tag(s), comma separated",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="List supported healthcheck tests",
)
@click.option(
    "--fix",
    is_flag=True,
    help="Attempt to fix any issues found",
)
def cli(filters: str, fix: bool, dry_run: bool) -> None:
    tests = discover_tests()

    if filters:
        for val in filters.split(","):
            tests = filter(
                lambda test: any(val.strip().lower() in tag.lower() for tag in test.tags),
                tests
            )

    if dry_run:
        if tests:
            pc_logging.info("Applicable healthcheck tests:")
            for test in tests:
                pc_logging.info(f"{test.name} - {test.description}")
    else:
        for test in tests:
            pc_logging.debug(f"Running '{test.name}' health check...")
            report = test.test()
            if report.findings:
                report.warning(test.findings)
                if fix and test.auto_fixable():
                    report.debug("Attempting to fix issues...")
                    report.fixed = test.fix()
                    if report.fixed:
                        report.info(f"Auto fix successful")
                    else:
                        report.error(f"Auto fix failed")
            else:
                report.info(f"Passed")
