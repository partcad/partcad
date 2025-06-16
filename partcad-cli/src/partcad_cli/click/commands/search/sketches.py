import rich_click as click

from partcad.context import Context
from partcad import logging as pc_logging
from partcad.actions.shape import search_sketches
from partcad_cli.click.cli_context import CliContext


@click.command(help="Search sketches by keyword")
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
    help="Search and filter sketches using the specified keyword",
    type=str,
    required=True,
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help="Package to search the sketches in, defaults to '//'(the root package)",
)
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, package: str, keyword: str) -> None:
    ctx: Context = cli_ctx.get_partcad_context()

    sketch_kinds = 0
    package = ctx.resolve_package_path(package)
    output = f"PartCAD sketches with '{keyword}' keyword:\n"
    with pc_logging.Process("Search Sketches", package):
        for sketch in search_sketches(ctx, package, recursive, keyword):
            line = "\t"
            line += "%s %s" % (sketch.project_name, sketch.name)
            line += " " + " " * (84 - len(line))

            desc = sketch.desc if sketch.desc is not None else ""
            desc = desc.replace("\n", "\n\t" + " " * (len(line) - 1))
            line += "%s" % desc
            output += line + "\n"
            sketch_kinds = sketch_kinds + 1

        if sketch_kinds > 0:
            output += "Matches: %d\n" % sketch_kinds
        else:
            output += "\t<none>\n"
    pc_logging.info(output)
