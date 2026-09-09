#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc

from ..cli_context import CliContext


@click.command(help="Show the current user configuration")
@click.pass_obj
def cli(cli_ctx: CliContext) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        # ctx: pc.Context = cli_ctx.get_partcad_context()

        for key, value in _resolved(pc.user_config):
            pc.logging.info(f"{key}: {value}")
        pc.logging.debug(f"File: {pc.user_config.get_config_dir()}")


def _resolved(config):
    """Every option the configuration resolved, whatever shape it is kept in.

    'vars()' alone is not that. An option kept as a *property* -- which is how
    'pythonSandbox' notices being assigned, so that '--python-sandbox' counts as
    a decision and a startup default does not -- keeps its value in a private
    attribute and its name on the class. So it dropped out of the command whose
    whole job is to say what the configuration resolved to.
    """
    for key, value in vars(config).items():
        if not callable(value) and not key.startswith("_"):
            yield key, value
    for key, member in vars(type(config)).items():
        if isinstance(member, property) and not key.startswith("_"):
            yield key, getattr(config, key)
