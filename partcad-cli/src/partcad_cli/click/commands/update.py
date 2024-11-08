import rich_click as click
from partcad.context import Context
from partcad.user_config import user_config


@click.command(help="* Update all imported packages")
@click.pass_obj
def cli(ctx: Context):
    user_config.force_update = True
    ctx.get_all_packages()
