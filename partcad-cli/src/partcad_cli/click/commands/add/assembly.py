import rich_click as click  # import click
from pathlib import Path
import partcad as pc


@click.command(help="Add an assembly")
@click.argument("kind", type=click.Choice(["assy"]))  # help="Type of the assembly"
@click.argument("path", type=str)  # help="Path to the file"
@click.pass_obj
def cli(ctx, kind, path):
    prj = ctx.get_project(pc.ROOT)
    if prj.add_assembly(kind, path):
        Path(path).touch()
