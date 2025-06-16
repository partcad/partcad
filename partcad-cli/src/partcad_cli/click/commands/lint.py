import asyncio
import rich_click as click

import partcad as pc
from partcad.context import Context
from partcad.user_config import user_config
from partcad.lint.all import get_linting_checks
from partcad_cli.click.cli_context import CliContext


async def cli_lint_async(ctx: Context, packages: list[str], filter_prefix: str) -> None:
    tasks = []
    lint_checks = get_linting_checks(user_config.threads_max)
    if filter_prefix:
        lint_checks = list(filter(lambda l: l.name.startswith(filter_prefix), lint_checks))
        pc.logging.debug(f"Running lint checks with prefix {filter_prefix}")

    for package in packages:
        prj = ctx.get_project(package)
        tasks.extend(
          [
            l.lint_log_wrapper(ctx, prj, t) for l in lint_checks \
            for t in l.get_targets(ctx, prj)
          ]
        )
    await asyncio.gather(*tasks)


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
def cli(cli_ctx: CliContext, package: str, recursive: bool, filter: str) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        package = ctx.resolve_package_path(package)
        package_obj = ctx.get_project(package)
        if not package_obj:
            pc.logging.error(f"Package {package} is not found")
            return
        package = package_obj.name

        with pc.logging.Process("Lint", package):
            if recursive:
                all_packages = ctx.get_all_packages(parent_name=package)
                if ctx.stats_git_ops:
                    pc.logging.info(f"Git operations: {ctx.stats_git_ops}")
                packages = [p["name"] for p in all_packages]
            else:
                packages = [package]

            asyncio.run(
                cli_lint_async(ctx, packages, filter)
            )
