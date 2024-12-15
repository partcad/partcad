import rich_click as click
from partcad.context import Context
from partcad.user_config import user_config
from partcad.user_config import user_config
from partcad import logging as logging


@click.command(help="Force update all imported packages to their latest versions. ")
@click.pass_obj
def cli(ctx: Context):
    user_config.force_update = True
    try:
        packages = ctx.get_all_packages()
        logging.info(f"Successfully updated {len(packages)} packages")
    except Exception as e:
        logging.error(f"Error updating packages: {str(e)}")
        raise click.Abort()
