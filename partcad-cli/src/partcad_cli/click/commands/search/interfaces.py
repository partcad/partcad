import rich_click as click

from partcad.context import Context
import partcad.logging as pc_logging
from partcad.actions.shape import search_interfaces
from partcad_cli.click.cli_context import CliContext


@click.command(help="Search interfaces by keyword")
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Recursively search in all imported packages",
    show_envvar=True,
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter interfaces using the specified keyword",
    type=str,
    required=True,
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help="Package to search the interfaces in, defaults to '//'(the root package)",
)
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, package: str, keyword: str) -> None:
    ctx: Context = cli_ctx.get_partcad_context()

    interface_kinds = 0
    package = ctx.resolve_package_path(package)
    output = f"PartCAD interfaces with '{keyword}' keyword:\n"
    with pc_logging.Process("Search Interfaces", package):
        for interface in search_interfaces(ctx, package, recursive, keyword):
            line = "\t"
            line += "%s %s" % (interface.project.name, interface.name)
            line += " " + " " * (84 - len(line))

            desc = interface.desc if interface.desc is not None else ""
            desc = desc.replace("\n", "\n\t" + " " * (len(line) - 1))
            line += f"{desc}"
            output += line + "\n"
            interface_kinds = interface_kinds + 1

        if interface_kinds > 0:
            output += f"Matches: {interface_kinds}\n"
        else:
            output += "\t<none>\n"
    pc_logging.info(output)
