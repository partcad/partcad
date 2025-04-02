#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc


@click.command(help="Force update all imported packages to their latest versions. ")
@click.pass_obj
def cli(cli_ctx):
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        # TODO-119: @alexanderilyin: Add prompt to confirm force update
        # if not click.confirm("This will force update all packages. Continue?", default=False):
        #     click.echo("Update cancelled")
        #     return
        ctx.user_config.force_update = True

        try:
            packages = ctx.get_all_packages()
            packages_list = list(packages)
            if ctx.stats_git_ops:
                pc.logging.info(f"Git operations: {ctx.stats_git_ops}")
            pc.logging.info(f"Successfully updated {len(packages_list)} packages")
        except Exception as e:
            pc.logging.error(f"Error updating packages: {str(e)}")
            raise click.Abort()
