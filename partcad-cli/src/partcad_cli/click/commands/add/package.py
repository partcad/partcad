import rich_click as click
import partcad as pc


# TODO-92: @alexanderilyin: Patch rich_click to support help strings for arguments
@click.command(help="Import a package")
@click.argument("alias", type=str)  # help="Alias to be used to reference the package"
@click.argument("location", type=str)  # help="Path or URL to the package"
@click.pass_obj
def cli(ctx, alias, location):
    prj = ctx.get_project(pc.ROOT)
    prj.add_import(alias, location)
