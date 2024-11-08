import rich_click as click
import partcad as pc


@click.command()
@click.argument("alias", type=str)
@click.argument("location", type=str)
@click.pass_obj
def cli(ctx, alias, location):
    """
    Import a package

    \b
    ----------------
    ALIAS: Alias to be used to reference the package.
    LOCATION: Path or URL to the package.
    """
    prj = ctx.get_project(pc.ROOT)
    prj.add_import(alias, location)
