import rich_click as click
import yaml
import partcad as pc
import coloredlogs
import logging

from partcad.logging_ansi_terminal import init as logging_ansi_terminal_init  # 1s
from partcad_cli.click.loader import Loader

help_config = click.RichHelpConfiguration(
    text_markup="rich",
    show_arguments=True,
)
help_config.dump_to_globals()

# https://github.com/ewels/rich-click/blob/main/examples/03_groups_sorting.py
# click.rich_click.COMMAND_GROUPS = {
#     "partcad": [
#         {"name": "Project Management", "commands": ["add", "init", "install", "update", "list"]},
#         {"name": "Design and Analysis", "commands": ["inspect", "info", "test", "render"]},
#         {"name": "Manufacturing & Generative AI", "commands": ["supply", "ai"]},
#         {"name": "Utility", "commands": ["status", "version"]},
#     ]
# }

# Initialize plugins that are not enabled by default
# TODO-85: @alexanderilyin: figure out what this is for
pc.plugins.export_png = pc.PluginExportPngReportlab()


@click.command(cls=Loader)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Increase verbosity level",
    show_envvar=True,
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Decrease verbosity level",
    show_envvar=True,
)
@click.option(
    "--no-ansi",
    is_flag=True,
    help="Produce plain text logs without colors or animations",
    show_envvar=True,
)
@click.option(
    "-p",
    "--package",
    show_envvar=True,
    type=click.Path(exists=True),
    help="Specify the package path (YAML file or directory with 'partcad.yaml')",
)
@click.option('--level', 'format', flag_value='level', default=True, help="Use log level as log prefix")
@click.option('--time', 'format', flag_value='time', help="Use time with milliseconds as log prefix")
@click.option('--path', 'format', flag_value='path', help="Use source file path and line number as log prefix")
@click.pass_context
def cli(ctx, verbose, quiet, no_ansi, package, format):
    """
    \b
    ██████╗  █████╗ ██████╗ ████████╗ ██████╗ █████╗ ██████╗
    ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔══██╗
    ██████╔╝███████║██████╔╝   ██║   ██║     ███████║██║  ██║
    ██╔═══╝ ██╔══██║██╔══██╗   ██║   ██║     ██╔══██║██║  ██║
    ██║     ██║  ██║██║  ██║   ██║   ╚██████╗██║  ██║██████╔╝
    ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝╚═════╝

    """
    # TODO-86: @clairbee add a config option to change logging mechanism and level
    if no_ansi:
        logging.getLogger("partcad").propagate = True
        logging.basicConfig()
    else:
        if format is not None:

            # Create a logger object.
            logger = logging.getLogger(__name__)

            # By default the install() function installs a handler on the root logger,
            # this means that log messages from your code and log messages from the
            # libraries that you use will all show up on the terminal.
            coloredlogs.install(level="DEBUG")

            formats = {
                "level": "%(levelname)s %(message)s",
                "path": "%(pathname)s:%(lineno)d %(message)s",
                "time": "%(asctime)s.%(msecs)03d %(levelname)s %(message)s",
            }

            # If you don't want to see log messages from libraries, you can pass a
            # specific logger object to the install() function. In this case only log
            # messages originating from that logger will show up on the terminal.
            coloredlogs.install(
                level="DEBUG",  # env.COLOREDLOGS_LOG_LEVEL
                logger=logger,
                # .venv/lib/python3.11/site-packages/coloredlogs/__init__.py:DEFAULT_LOG_FORMAT
                fmt=formats[format],  # env.COLOREDLOGS_LOG_FORMAT
                datefmt="%H:%M:%S",
            )

        logging_ansi_terminal_init()

    if quiet:
        pc.logging.setLevel(logging.CRITICAL + 1)
    else:
        if verbose:
            pc.logging.setLevel(logging.DEBUG)
        else:
            pc.logging.setLevel(logging.INFO)

    # TODO-87: @alexanderilyin: figure out what force_update is
    commands_with_forced_update = [
        "install",
        "update",
    ]
    if ctx.invoked_subcommand in commands_with_forced_update:
        from partcad.user_config import user_config

        user_config.force_update = True

    # TODO-88: @alexanderilyin: try to get this list dynamically
    commands_with_context = [
        "add",
        "ai",
        "info",
        "inspect",
        "install",
        "list",
        "render",
        "export",
        "supply",  # Actually context is needed for "quote" but for now it it is what it is
        "test",
        "update",
    ]

    if ctx.invoked_subcommand in commands_with_context:
        from partcad.globals import init

        try:
            ctx.obj = init(package)
        except (yaml.parser.ParserError, yaml.scanner.ScannerError) as e:
            exc = click.BadParameter("Invalid configuration file", ctx=ctx, param=package, param_hint=None)
            exc.exit_code = 2
            raise exc from e
        except Exception as e:
            import traceback

            pc.logging.error(e)
            traceback.print_exc()
            raise click.Abort from e


# class StderrHelpFormatter(click.RichHelpFormatter):
#   pass

# class StderrContext(click.RichContext):
#   formatter_class = StderrHelpFormatter
#   def get_help(self):
#     help_text = super().get_help()
#     sys.stderr.write(help_text)
# return ""
# @click.command(context_settings={"context_class": StderrContext})
# cli.context_class = StderrContext
cli.context_settings = {
    "show_default": True,
    "auto_envvar_prefix": "PC",
    # terminal_width
    # max_content_width
    # "": StderrContext,
}


@cli.result_callback()
def process_result(result, verbose, quiet, no_ansi, package, format):
    # TODO-89: @alexanderilyin: What is this for?
    if not no_ansi:
        pc.logging_ansi_terminal_fini()

    # Abort if there was at least one error reported during the exeution time.
    # `result` is needed for the case when the command was not correct.
    if pc.logging.had_errors or result:
        raise click.Abort()


if __name__ == "__main__":
    cli()
