import rich_click as click

from partcad.context import Context
from partcad import logging as pc_logging
from partcad.actions.package import search_packages
from partcad_cli.click.cli_context import CliContext


@click.command(help="Search packages by keyword")
@click.option("-r", "--recursive", is_flag=True, help="Recursively search packages")
@click.option(
    "-k",
    "--keyword",
    help="Search and filter packages using the specified keyword",
    type=str,
    required=True,
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="//",
    show_envvar=True,
    help="Package to search the subpackages in, defaults to '//'(the root package)",
)
@click.pass_obj
def cli(cli_ctx: CliContext, recursive: bool, package: str, keyword: str) -> None:
    ctx: Context = cli_ctx.get_partcad_context()

    pkg_count = 0
    package = ctx.resolve_package_path(package)
    output = f"PartCAD packages with '{keyword}' keyword:\n"
    with pc_logging.Process("Search Packages", package):
        for project in search_packages(ctx, package, recursive, keyword):
            line = "\t%s" % project.name
            padding_size = 60 - len(project.name)
            if padding_size < 4:
                padding_size = 4
            line += " " * padding_size
            desc = project.desc
            if project.config_obj.get("url"):
                desc += f"\n{project.config_obj['url']}"
            desc = desc.replace("\n", "\n" + " " * 68)
            line += "%s" % desc
            output += line + "\n"
            pkg_count = pkg_count + 1

        if pkg_count > 0:
            output += "Matches: %d\n" % pkg_count
        else:
            output += "\t<none>\n"
    pc_logging.info(output)
