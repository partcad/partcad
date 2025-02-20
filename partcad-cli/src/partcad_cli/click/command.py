import rich_click as click
import yaml
import partcad as pc
import coloredlogs
import logging
import locale
import platform

from partcad.logging_ansi_terminal import init as logging_ansi_terminal_init  # 1s
from partcad_cli.click.loader import Loader

locale.setlocale(locale.LC_ALL, "en_US.UTF-8")

help_config = click.RichHelpConfiguration(
    color_system="windows" if platform.system() == "Windows" else "auto",
    force_terminal=platform.system() != "Windows",
    show_arguments=True,
    text_markup="rich",
    use_markdown_emoji=False,
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
@click.option(
    "--format",
    help="Set the log prefix format",
    type=click.Choice(["time", "path", "level"]),
    default=None,
    show_envvar=True,
)
@click.option(
    "--threads-max",
    type=int,
    default=None,
    show_envvar=True,
    help="Maximum number of processing threads to use (not a strict limit)",
)
@click.option(
    "--cache",
    is_flag=True,
    default=None,
    show_envvar=True,
    help="Enable caching of intermediate results to the filesystem",
)
@click.option(
    "--cache-max-entry-size",
    type=int,
    default=None,
    show_envvar=True,
    help="Maximum size of a single file cache entry in bytes (defaults to 10485760 or 10MB)",
)
@click.option(
    "--cache-min-entry-size",
    type=int,
    default=None,
    show_envvar=True,
    help="Minimum size of a single file cache entry (except test results) in bytes (defaults to 104857600 or 100MB)",
)
@click.option(
    "--cache-memory-max-entry-size",
    type=int,
    default=None,
    show_envvar=True,
    help="Maximum size of a single memory cache entry in bytes (defaults to 104857600 or 100MB)",
)
@click.option(
    "--cache-memory-double-cache-max-entry-size",
    type=int,
    default=None,
    show_envvar=True,
    help="Maximum size of a single memory cache entry in bytes(defaults to 1048576 or 1MB)",
)
@click.option(
    "--cache-dependencies-ignore",
    is_flag=True,
    default=None,
    show_envvar=True,
    help="Ignore broken dependencies and cache at your own risk",
)
@click.option(
    "--python-sandbox",
    default=None,
    show_envvar=True,
    type=click.Choice(["none", "pypy", "conda"]),
    help="Sandboxing environment for invoking python scripts(defaults to conda)",
)
@click.option(
    "--internal-state-dir",
    type=str,
    default=None,
    show_envvar=True,
    help="Directory to store all temporary files(defaults to '.partcad' folder in home directory)",
)
@click.option(
    "--force-update",
    is_flag=True,
    show_envvar=True,
    default=None,
    help="Update all repositories even if they are fresh",
)
@click.option(
    "--offline",
    is_flag=True,
    show_envvar=True,
    default=None,
    help="Operate in offline mode, without any repo updates",
)
@click.option(
    "--google-api-key",
    type=str,
    default=None,
    show_envvar=True,
    help="GOOGLE API key for AI services",
)
@click.option(
    "--openai-api-key",
    type=str,
    default=None,
    show_envvar=True,
    help="OPENAI API key for AI services",
)
@click.option(
    "--ollama-num-thread",
    type=int,
    default=None,
    show_envvar=True,
    help="Number of CPU threads Ollama should utilize",
)
@click.option(
    "--max-geometric-modeling",
    type=int,
    default=None,
    show_envvar=True,
    help="Maximum number of attempts for geometric modeling",
)
@click.option(
    "--max-model-generation",
    type=int,
    default=None,
    show_envvar=True,
    help="Maximum number of attempts for CAD script generation",
)
@click.option(
    "--max-script-correction",
    type=int,
    default=None,
    show_envvar=True,
    help="Maximum number of attempts to incrementally fix the ai generated script if it's not working",
)
@click.option(
    "--sentry-dsn",
    type=str,
    default=None,
    show_envvar=True,
    help="Sentry DSN for error reporting",
)
@click.option(
    "--sentry-debug",
    is_flag=True,
    default=None,
    show_envvar=True,
    help="Enable Sentry debug mode",
)
@click.option(
    "--sentry-shutdown-timeout",
    type=int,
    default=None,
    show_envvar=True,
    help="Shutdown timeout for Sentry in seconds",
)
@click.option(
    "--sentry-traces-sample-rate",
    type=float,
    default=None,
    show_envvar=True,
    help="Traces sample rate for Sentry in percent",
)
@click.option("--level", "format", flag_value="level", default=True, help="Use log level as log prefix")
@click.option("--time", "format", flag_value="time", help="Use time with milliseconds as log prefix")
@click.option("--path", "format", flag_value="path", help="Use source file path and line number as log prefix")
@click.pass_context
def cli(ctx, verbose, quiet, no_ansi, package, format, **kwargs):
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
        if verbose and format is not None:

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
    from partcad.user_config import user_config

    user_config_options = [
        ("PC_THREADS_MAX", "threads_max"),
        ("PC_CACHE_FILES", "cache"),
        ("PC_CACHE_FILES_MAX_ENTRY_SIZE", "cache_max_entry_size"),
        ("PC_CACHE_FILES_MIN_ENTRY_SIZE", "cache_min_entry_size"),
        ("PC_CACHE_MEMORY_MAX_ENTRY_SIZE", "cache_memory_max_entry_size"),
        ("PC_CACHE_MEMORY_DOUBLE_CACHE_MAX_ENTRY_SIZE", "cache_memory_double_cache_max_entry_size"),
        ("PC_CACHE_DEPENDENCIES_IGNORE", "cache_dependencies_ignore"),
        ("PC_PYTHON_SANDBOX", "python_sandbox"),
        ("PC_INTERNAL_STATE_DIR", "internal_state_dir"),
        ("PC_FORCE_UPDATE", "force_update"),
        ("PC_OFFLINE", "offline"),
        ("PC_GOOGLE_API_KEY", "google_api_key"),
        ("PC_OPENAI_API_KEY", "openai_api_key"),
        ("PC_OLLAMA_NUM_THREAD", "ollama_num_thread"),
        ("PC_MAX_GEOMETRIC_MODELING", "max_geometric_modeling"),
        ("PC_MAX_MODEL_GENERATION", "max_model_generation"),
        ("PC_MAX_SCRIPT_CORRECTION", "max_script_correction"),
        ("PC_SENTRY_DSN", "sentry_dsn"),
        ("PC_SENTRY_DEBUG", "sentry_debug"),
        ("PC_SENTRY_SHUTDOWN_TIMEOUT", "sentry_shutdown_timeout"),
        ("PC_SENTRY_TRACES_SAMPLE_RATE", "sentry_traces_sample_rate"),
    ]

    for env_var, attrib in user_config_options:
        value = kwargs.get(attrib, None)
        if value is not None and user_config._get_env(env_var) is None:
            if "sentry" in attrib:
                attrib = attrib.replace("sentry_", "sentry.")
                user_config.set(attrib, value)
            else:
                setattr(user_config, attrib, value)

    if ctx.invoked_subcommand in commands_with_forced_update:
        user_config.force_update = True

    # TODO-88: @alexanderilyin: try to get this list dynamically
    commands_with_context = [
        "add",
        "ai",
        "convert",
        "import",
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
def process_result(result, verbose, quiet, no_ansi, package, format, **kwargs):
    # TODO-89: @alexanderilyin: What is this for?
    if not no_ansi:
        pc.logging_ansi_terminal_fini()

    # Abort if there was at least one error reported during the exeution time.
    # `result` is needed for the case when the command was not correct.
    if pc.logging.had_errors or result:
        raise click.Abort()


if __name__ == "__main__":
    cli()
