import rich_click as click
import yaml
import partcad as pc
import coloredlogs, logging
from partcad.logging_ansi_terminal import init as logging_ansi_terminal_init  # 1s
from partcad_cli.click.loader import Loader

help_config = click.RichHelpConfiguration(
    text_markup="rich",
    show_arguments=True,
)
help_config.dump_to_globals()


@click.command(cls=Loader)
@click.option("-v", is_flag=True, help="Increase the level of verbosity")
@click.option("-q", is_flag=True, help="Decrease the level of verbosity")
@click.option(
    "--no-ansi",
    is_flag=True,
    help="Plain logging output. Do not use colors or animations.",
)
@click.option(
    "-p",
    type=click.Path(exists=True),
    help="xxx Package path (a YAML file or a directory with 'partcad.yaml')",
)
@click.option(
    "--format",
    help="Log prefix format",
    type=click.Choice(["time", "path", "level"]),
    default=None,
    show_envvar=True,
)
@click.pass_context
def cli(ctx, v, q, no_ansi, p, format):
    """
    \b
    ██████╗  █████╗ ██████╗ ████████╗ ██████╗ █████╗ ██████╗
    ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔══██╗
    ██████╔╝███████║██████╔╝   ██║   ██║     ███████║██║  ██║
    ██╔═══╝ ██╔══██║██╔══██╗   ██║   ██║     ██╔══██║██║  ██║
    ██║     ██║  ██║██║  ██║   ██║   ╚██████╗██║  ██║██████╔╝
    ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝╚═════╝

    """
    if no_ansi:
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

    if q:
        pc.logging.setLevel(logging.CRITICAL + 1)
    else:
        if v:
            pc.logging.setLevel(logging.DEBUG)
        else:
            pc.logging.setLevel(logging.INFO)

    # TODO: @alexanderilyin: figure out what force_update is
    commands_with_forced_update = [
        "install",
        "update",
    ]
    if ctx.invoked_subcommand in commands_with_forced_update:
        from partcad.user_config import user_config

        user_config.force_update = True

    # TODO: @alexanderilyin: try to get this list dynamically
    commands_with_context = [
        "add",
        "info",
        "init",
        "inspect",
        "install",
        "list",
        "render",
        "update",
    ]

    if ctx.invoked_subcommand in commands_with_context:
        from partcad.globals import init

        try:
            ctx.obj = init(p)
            # if p is None:
            #     ctx.obj = init()
            # else:
            #     ctx.obj = init(p)
        except (yaml.parser.ParserError, yaml.scanner.ScannerError) as e:
            exc = click.BadParameter("Invalid configuration file", ctx=ctx, param=p, param_hint=None)
            exc.exit_code = 2
            raise exc
        except Exception as e:
            pc.logging.error(e)
            raise click.Abort()


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
    # terminal_width
    # max_content_width
    # "": StderrContext,
}


@cli.result_callback()
def process_result(result, v, q, no_ansi, p, format):
    if pc.logging.had_errors:
        raise click.Abort()


if __name__ == "__main__":
    cli()
    # TODO: @alexanderilyin: add a test for this
    # if pc_logging.had_errors:
    #     sys.exit(1)
