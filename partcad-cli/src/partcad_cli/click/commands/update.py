import rich_click as click
from partcad.context import Context
from partcad.user_config import user_config
from partcad import logging as logging
from partcad.sentry import tracer as pc_tracer


@click.command(help="Force update all imported packages to their latest versions. ")
@click.pass_obj
@pc_tracer.start_as_current_span("Command [pc update]")
def cli(ctx: Context):
    # TODO-119: @alexanderilyin: Add prompt to confirm force update
    # if not click.confirm("This will force update all packages. Continue?", default=False):
    #     click.echo("Update cancelled")
    #     return
    user_config.force_update = True
    try:
        packages = ctx.get_all_packages()
        packages_list = list(packages)
        if ctx.stats_git_ops:
            logging.info(f"Git operations: {ctx.stats_git_ops}")
        logging.info(f"Successfully updated {len(packages_list)} packages")
    except Exception as e:
        logging.error(f"Error updating packages: {str(e)}")
        raise click.Abort()
