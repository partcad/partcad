import rich_click as click

from ..service import run


@click.command(help="Run linting checks on files within packages")
@click.option(
    "--package",
    "-P",
    type=str,
    default="",
    show_envvar=True,
    help="Package to retrieve the object from",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    show_envvar=True,
    help="Recursively performs lint checks on all imported packages",
)
@click.option(
    "--filter",
    "-f",
    help="Only run lint checks that start with the given prefix",
    type=str,
    show_envvar=True,
    default=None,
)
@click.pass_obj
def cli(cli_ctx, package: str, recursive: bool, filter: str) -> None:
    run(
        cli_ctx,
        "lint.run",
        {"package": package, "recursive": recursive, "filter": filter},
        needs_context=True,
    )
