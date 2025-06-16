import rich_click as click

from partcad.context import Context
from partcad import logging as pc_logging
from partcad.actions.shape import search_parts
from partcad_cli.click.cli_context import CliContext


@click.command(help="Search parts by keyword")
@click.option(
    "-r",
    "--recursive",
    "recursive",
    is_flag=True,
    help="Recursively search in all imported packages",
    show_envvar=True,
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help="Package to search the parts in, defaults to '//'(the root package)",
)
@click.option(
    "-k",
    "--keyword",
    help="Search and filter parts using the specified keyword",
    type=str,
    required=True,
)
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, package: str, keyword: str) -> None:
    ctx: Context = cli_ctx.get_partcad_context()

    part_kinds = 0
    package = ctx.resolve_package_path(package)
    output = f"PartCAD parts with '{keyword}' keyword:\n"
    with pc_logging.Process("Search Parts", package):
        for part in search_parts(ctx, package, recursive, keyword):
            line = "\t"
            line += "%s %s" % (part.project_name, part.name)
            line += " " + " " * (84 - len(line))

            desc = part.desc if part.desc is not None else ""
            desc = desc.replace("\n", "\n\t" + " " * (len(line) - 1))
            line += "%s" % desc
            output += line + "\n"
            part_kinds = part_kinds + 1

        if part_kinds > 0:
            output += "Matches: %d\n" % part_kinds
        else:
            output += "\t<none>\n"
    pc_logging.info(output)
