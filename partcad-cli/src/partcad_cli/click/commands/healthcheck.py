import rich_click as click

import partcad.logging as pc_logging
from partcad.healthcheck.healthcheck import discover_tests


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
