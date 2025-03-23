#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from click.testing import CliRunner

from ...cli_context import CliContext
from .assemblies import cli as list_assemblies
from .interfaces import cli as list_interfaces
from .mates import cli as list_mates
from .packages import cli as list_packages
from .parts import cli as list_parts
from .sketches import cli as list_sketches


@click.option(
    "-u",
    "--used_by",
    help="Only process objects used by the given assembly or scene.",
    type=str,
    required=False,
    show_envvar=True,
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages",
    show_envvar=True,
)
@click.command(help="List all available parts, assemblies and scenes")
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(cli_ctx: CliContext, used_by, recursive: bool, package: str) -> None:
    """List all available parts, assemblies and scenes recursively."""
    runner = CliRunner()
    options = []

    if recursive:
        options.append("--recursive")
    if used_by:
        options.append("--used_by")
    if package:
        options.append(package)

    catch_exceptions = False

    runner.invoke(list_packages, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_sketches, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_interfaces, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_parts, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_assemblies, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    # TODO: @alexanderilyin: TypeError: startswith first arg must be str or a tuple of str, not Project
    # runner.invoke(list_mates, options, catch_exceptions=catch_exceptions, obj=ctx)
