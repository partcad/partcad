import rich_click as click

from partcad.context import Context
from partcad import logging as pc_logging
from partcad.actions.shape import search_assemblies
from partcad_cli.click.cli_context import CliContext


@click.command(help="Search assemblies by keyword")
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
    help="Search and filter assemblies using the specified keyword",
    type=str,
    required=True,
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help="Package to search the assemblies in, defaults to '//'(the root package)",
)
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, package: str, keyword: str) -> None:
    ctx: Context = cli_ctx.get_partcad_context()

    assy_kinds = 0
    package = ctx.resolve_package_path(package)
    output = f"PartCAD assemblies with '{keyword}' keyword:\n"
    with pc_logging.Process("Search Assemblies", package):
        for assy in search_assemblies(ctx, package, recursive, keyword):
            line = "\t"
            line += "%s %s" % (assy.project_name, assy.name)
            line += " " + " " * (84 - len(line))

            desc = assy.desc if assy.desc is not None else ""
            desc = desc.replace("\n", "\n\t" + " " * (len(line) - 1))
            line += f"{desc}"
            output += line + "\n"
            assy_kinds = assy_kinds + 1

        if assy_kinds > 0:
            output += f"Matches: {assy_kinds}\n"
        else:
            output += "\t<none>\n"
    pc_logging.info(output)
