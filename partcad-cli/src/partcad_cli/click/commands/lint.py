import os
import rich_click as click

import partcad as pc
from partcad_cli.click.cli_context import CliContext


@click.command(help="Run schema validation on partcad.yaml")
@click.pass_context
@click.pass_obj
def cli(cli_ctx: CliContext, click_ctx: click.rich_context.RichContext) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        if not click_ctx.parent.params.get("package") is None:
            if os.path.isdir(click_ctx.parent.params.get("package")):
                config_path = os.path.join(click_ctx.parent.params.get("package"), "partcad.yaml")
            else:
                config_path = click_ctx.parent.params.get("package")
        else:
            config_path = os.getcwd()
        config_file = os.path.join(config_path, "partcad.yaml")

        pc.logging.info(f"validating '{config_file}'")
        lint_result = pc.lint(config_file)

        for message in lint_result.messages:
            if message.level == pc.LintLevel.ERROR:
                pc.logging.error(message)
            elif message.level == pc.LintLevel.WARNING:
                pc.logging.warning(message)
            elif message.level == pc.LintLevel.INFO:
                pc.logging.info(message)
