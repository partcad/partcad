#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
import os
from pathlib import Path
import ruamel.yaml

import partcad as pc


@click.command(help="Set the Sentry DSN")
@click.argument(
    "dsn",
    metavar="DSN",
    required=True,
)
@click.pass_obj
def cli(cli_ctx, dsn: str) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("SysSetTelDsn", "global"):
            config_path = os.path.join(pc.user_config.internal_state_dir, "config.yaml")

            yaml = ruamel.yaml.YAML()
            yaml.preserve_quotes = True
            if not os.path.exists(config_path):
                Path(config_path).touch()
                config = {}
            else:
                with open(config_path) as fp:
                    config = yaml.load(fp)
                    fp.close()

            if not config:
                config = {}
            if not "telemetry" in config:
                config["telemetry"] = {}

            config["telemetry"]["sentryDsn"] = dsn
            pc.logging.info("Sentry DSN set to %s", dsn)

            with open(config_path, "w") as fp:
                yaml.dump(config, fp)
                fp.close()
