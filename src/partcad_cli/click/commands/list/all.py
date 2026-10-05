#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
from click.testing import CliRunner

from ... import fast_only
from ...cli_context import CliContext
from ...exclude import exclude_option
from .assemblies import cli as list_assemblies
from .interfaces import cli as list_interfaces
from .materials import cli as list_materials
from .mates import cli as list_mates  # noqa: F401  # its runner.invoke() below is commented out (TODO there)
from .packages import cli as list_packages
from .parts import cli as list_parts
from .providers import cli as list_providers
from .scenes import cli as list_scenes
from .sketches import cli as list_sketches
from .software import cli as list_software


@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively process all imported packages (older spelling of '<package>...')",
    show_envvar=True,
)
@fast_only.option()
@click.command(
    help="List all available parts, assemblies and scenes. PACKAGE may end in '...' to reach every package below it",
)
@exclude_option
@click.argument("package", type=str, required=False, default=".")  # help='Package to retrieve the object from'
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, fast_only: bool, exclude, package: str) -> None:
    """List all available parts, assemblies and scenes recursively."""
    runner = CliRunner()
    options = []

    if recursive:
        options.append("--recursive")
    for excluded in exclude:
        options.extend(["--exclude", excluded])
    if package:
        options.append(package)
    # Only the listings that hold assemblies take it: nothing else declares a
    # timeout, so nothing else has anything to leave out.
    assembly_options = (["--fast-only"] if fast_only else []) + options

    catch_exceptions = False

    runner.invoke(list_packages, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_materials, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_sketches, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_interfaces, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_parts, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_assemblies, assembly_options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_scenes, assembly_options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_providers, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    runner.invoke(list_software, options, catch_exceptions=catch_exceptions, obj=cli_ctx)
    # TODO: @alexanderilyin: TypeError: startswith first arg must be str or a tuple of str, not Project
    # runner.invoke(list_mates, options, catch_exceptions=catch_exceptions, obj=ctx)
