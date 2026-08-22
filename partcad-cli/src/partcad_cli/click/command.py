#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
import atexit
import logging
import locale
import platform
import re
import sentry_sdk
import sys
import sentry_sdk.session
import yaml

import partcad_utils
import partcad_utils.logging_remote_client as logging_remote_client
from partcad_utils import logging as pc_logging
from partcad_utils import telemetry as pc_telemetry
from partcad_utils.user_config import user_config as pc_user_config
from partcad_cli.click.loader import Loader
from partcad_cli.click.cli_context import CliContext

# partcad's package __init__ used to run this when the CLI imported it; the CLI
# no longer imports the heavy partcad package, so initialize telemetry here.
pc_telemetry.init(partcad_utils.__version__)

global cli_span
cli_span: pc_telemetry.trace.Span = None

try:
    locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
except locale.Error:
    # A machine that carries no en_US.UTF-8 locale must not fail before the
    # first command runs. Minimal container images and the bare machines the
    # standalone bundle targets frequently have only "C" generated.
    try:
        locale.setlocale(locale.LC_ALL, "C.UTF-8")
    except locale.Error:
        pass

if True:
    # IMPORTANT:
    # We need to maintain setting default values in both the CLI and the user_config, because of:
    # 1) CLI needs default values to show them to the user
    # 2) CLI pushes the default values to user_config unconditionally (if no user values are set)
    # 3) user_config is used outside of CLI, where CLI default values are not available
    from . import __spec__

    # If the module is loaded from a file, then we are in development mode
    if __spec__.loader.__class__.__name__ == "SourceFileLoader":
        default_environment = "dev"
    else:
        default_environment = "prod"

help_config = click.RichHelpConfiguration(
    color_system="windows" if platform.system() == "Windows" else "auto",
    force_terminal=platform.system() != "Windows",
    show_arguments=True,
    text_markup="rich",
    use_markdown_emoji=False,
)
help_config.dump_to_globals()

option_groups = [
    {
        "name": "Output options",
        "options": ["--verbose", "--quiet", "--no-ansi"],
    },
    {
        "name": "Dependency management options",
        "options": ["--force-update", "--offline", "--devel-index", "--internal-state-dir"],
    },
    {
        "name": "Sandbox options",
        "options": ["--python-sandbox", "--javascript-sandbox", "--ignore-bundled-openscad"],
    },
    {
        "name": "Telemetry options",
        "options": [
            "--telemetry-type",
            "--telemetry-env",
            "--telemetry-performance",
            "--telemetry-failures",
            "--telemetry-debug",
            "--telemetry-sentry-dsn",
            "--telemetry-sentry-shutdown-timeout",
            "--telemetry-sentry-attach-stacktrace",
            "--telemetry-sentry-traces-sample-rate",
        ],
    },
    {
        "name": "Performance options",
        "options": ["--threads-max"],
    },
    {
        "name": "Caching options",
        "options": [
            "--cache",
            "--cache-max-entry-size",
            "--cache-min-entry-size",
            "--cache-memory-max-entry-size",
            "--cache-memory-double-cache-max-entry-size",
            "--cache-dependencies-ignore",
        ],
    },
    {
        "name": "Other options",
        "options": ["--path", "--help"],
    },
]
command_groups = [
    {
        "name": "Host commands",
        "commands": ["version", "config", "system", "daemon"],
    },
    {
        "name": "Package commands",
        "commands": ["init", "install", "update", "lint"],
    },
    {
        "name": "Object commands",
        "commands": ["list", "add", "import", "test", "inspect", "info", "bom", "convert", "export", "render"],
    },
    {
        "name": "Workflow commands",
        "commands": ["supply"],
    },
    {
        "name": "Other commands",
        "commands": ["adhoc", "healthcheck"],
    },
]
click.rich_click.OPTION_GROUPS = {
    "partcad": option_groups,
    "pc": option_groups,
    "partcad_cli.click.command": option_groups,
}
click.rich_click.COMMAND_GROUPS = {
    "partcad": command_groups,
    "pc": command_groups,
    "partcad_cli.click.command": command_groups,
}


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
    "--path",
    show_envvar=True,
    type=click.Path(exists=True),
    help="Specify the package path (YAML file or directory with 'partcad.yaml')",
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
    "--javascript-sandbox",
    default=None,
    show_envvar=True,
    type=click.Choice(["none", "conda"]),
    help="Sandboxing environment for invoking JavaScript scripts (defaults to the host's Node.js)",
)
@click.option(
    "--ignore-bundled-openscad",
    is_flag=True,
    default=None,
    # The env var is IGNORE_BUNDLED_OPENSCAD, read by user_config directly, so it
    # works for the standalone bundle and for `import partcad` alike. show_envvar
    # is off to avoid advertising the PC_ form that click would otherwise infer.
    show_envvar=False,
    help="Ignore the OpenSCAD bundled into the standalone build and use the host's "
    "instead (env: IGNORE_BUNDLED_OPENSCAD=1). No effect outside the bundle.",
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
    "--devel-index",
    is_flag=True,
    show_envvar=True,
    default=None,
    help="Use the 'devel' branch of the public index instead of the released one",
)
@click.option(
    "--telemetry-type",
    type=click.Choice(["none", "sentry"]),
    show_envvar=True,
    help="Telemetry type to use",
)
@click.option(
    "--telemetry-env",
    type=click.Choice(["dev", "test", "prod"]),
    show_envvar=True,
    help="Telemetry environment to use",
)
@click.option(
    "--telemetry-performance",
    is_flag=True,
    default=True,
    show_envvar=True,
    help="Use telemetry for performance reporting",
)
@click.option(
    "--telemetry-failures",
    is_flag=True,
    default=True,
    show_envvar=True,
    help="Use telemetry for failure reporting",
)
@click.option(
    "--telemetry-debug",
    is_flag=True,
    default=False,
    show_envvar=True,
    help="Enable telemetry debug mode",
)
@click.option(
    "--telemetry-sentry-dsn",
    type=str,
    show_envvar=True,
    help="Sentry DSN for error reporting",
)
@click.option(
    "--telemetry-sentry-shutdown-timeout",
    type=float,
    default=3.0,
    show_envvar=True,
    help="Shutdown timeout for Sentry in seconds",
)
@click.option(
    "--telemetry-sentry-attach-stacktrace",
    type=bool,
    default=False,
    show_envvar=True,
    help="Attach stacktrace to Sentry events",
)
@click.option(
    "--telemetry-sentry-traces-sample-rate",
    type=float,
    default=1.0,
    show_envvar=True,
    help="Traces sample rate for Sentry in percent",
)
@click.option(
    "--extra-param",
    type=str,
    multiple=True,
    default=(),
    show_envvar=True,
    help="parameter(s) for configuration. Example: --extra-param key1=value1 --extra-param key2=value2",
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool, no_ansi: bool, path: str, **kwargs):
    """
    \b
    ██████╗  █████╗ ██████╗ ████████╗ ██████╗ █████╗ ██████╗
    ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔══██╗
    ██████╔╝███████║██████╔╝   ██║   ██║     ███████║██║  ██║
    ██╔═══╝ ██╔══██║██╔══██╗   ██║   ██║     ██╔══██║██║  ██║
    ██║     ██║  ██║██║  ██║   ██║   ╚██████╗██║  ██║██████╔╝
    ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝╚═════╝

    """

    # Pull the parameters from the environment before doing anything
    user_config_options = [
        ("PC_THREADS_MAX", "threads_max"),
        ("PC_CACHE_FILES", "cache"),
        ("PC_CACHE_FILES_MAX_ENTRY_SIZE", "cache_max_entry_size"),
        ("PC_CACHE_FILES_MIN_ENTRY_SIZE", "cache_min_entry_size"),
        ("PC_CACHE_MEMORY_MAX_ENTRY_SIZE", "cache_memory_max_entry_size"),
        ("PC_CACHE_MEMORY_DOUBLE_CACHE_MAX_ENTRY_SIZE", "cache_memory_double_cache_max_entry_size"),
        ("PC_CACHE_DEPENDENCIES_IGNORE", "cache_dependencies_ignore"),
        ("PC_PYTHON_SANDBOX", "python_sandbox"),
        ("PC_JAVASCRIPT_SANDBOX", "javascript_sandbox"),
        ("IGNORE_BUNDLED_OPENSCAD", "ignore_bundled_openscad"),
        ("PC_INTERNAL_STATE_DIR", "internal_state_dir"),
        ("PC_FORCE_UPDATE", "force_update"),
        ("PC_OFFLINE", "offline"),
        ("PC_DEVEL_INDEX", "devel_index"),
        ("PC_TELEMETRY_TYPE", "telemetry_type"),
        ("PC_TELEMETRY_ENV", "telemetry_env"),
        ("PC_TELEMETRY_PERFORMANCE", "telemetry_performance"),
        ("PC_TELEMETRY_FAILURES", "telemetry_failures"),
        ("PC_TELEMETRY_DEBUG", "telemetry_debug"),
        ("PC_TELEMETRY_SENTRY_DSN", "telemetry_sentry_dsn"),
        ("PC_TELEMETRY_SENTRY_SHUTDOWN_TIMEOUT", "telemetry_sentry_shutdown_timeout"),
        ("PC_TELEMETRY_SENTRY_ATTACH_STACKTRACE", "telemetry_sentry_attach_stacktrace"),
        ("PC_TELEMETRY_SENTRY_TRACES_SAMPLE_RATE", "telemetry_sentry_traces_sample_rate"),
    ]

    for _env_var, attrib in user_config_options:
        value = kwargs.get(attrib, None)
        if value is not None:
            if "telemetry" in attrib:
                attrib = attrib.replace("telemetry_", "telemetry.")
                attrib = re.sub(r"_([a-z])", lambda x: x.group(1).upper(), attrib)
                pc_user_config.set(attrib, value)
            else:
                setattr(pc_user_config, attrib, value)

    # Initialize logging before using telemetry, as telemetry may use logging.
    # The remote-log client wraps logging_ansi_terminal (ANSI) or a plain stderr
    # handler (--no-ansi); it is the same renderer the migrated commands feed
    # their daemon-forwarded log events into, so in-process and thin-client
    # commands render identically.
    logging_remote_client.init(want_ansi=not no_ansi)

    if quiet:
        pc_logging.setLevel(logging.CRITICAL + 1)
    else:
        if verbose:
            pc_logging.setLevel(logging.DEBUG)
        else:
            pc_logging.setLevel(logging.INFO)

    # Start telemetry as soon as the config and logging are initialized
    flat_params = {k: str(v) for k, v in ctx.params.items()}
    flat_params["args"] = str(ctx.args)
    flat_params["argv"] = str(sys.argv)
    flat_params["command"] = ctx.command.name
    flat_params["subcommand"] = ctx.invoked_subcommand
    flat_params["action"] = "cli " + " ".join(sys.argv[1:])
    with pc_telemetry.start_as_current_span("cli", attributes=flat_params, end_on_exit=False) as span:
        global cli_span
        cli_span = span

        # Finish the span on exit only, as the command handler are called outside of the current stack
        def telemetry_atexit():
            pc_logging.debug("Flushing Sentry SDK events")
            global cli_span
            if cli_span:
                # There was no clean exit
                cli_span.set_attribute("aborted", True)
                cli_span.set_status(pc_telemetry.trace.StatusCode.ERROR)
                cli_span.end()
                cli_span = None
            # TODO(clairbee): investigate how is this value related to PC_TELEMETRY_SENTRY_SHUTDOWN_TIMEOUT and make it configurable
            sentry_sdk.flush(timeout=1.5)

        atexit.register(telemetry_atexit)

        # (Logging was already initialized above; init() is idempotent.)
        logging_remote_client.init(want_ansi=not no_ansi)

        if quiet:
            pc_logging.setLevel(logging.CRITICAL + 1)
        else:
            if verbose:
                pc_logging.setLevel(logging.DEBUG)
            else:
                pc_logging.setLevel(logging.INFO)

        user_config_options = [
            ("PC_THREADS_MAX", "threads_max"),
            ("PC_CACHE_FILES", "cache"),
            ("PC_CACHE_FILES_MAX_ENTRY_SIZE", "cache_max_entry_size"),
            ("PC_CACHE_FILES_MIN_ENTRY_SIZE", "cache_min_entry_size"),
            ("PC_CACHE_MEMORY_MAX_ENTRY_SIZE", "cache_memory_max_entry_size"),
            ("PC_CACHE_MEMORY_DOUBLE_CACHE_MAX_ENTRY_SIZE", "cache_memory_double_cache_max_entry_size"),
            ("PC_CACHE_DEPENDENCIES_IGNORE", "cache_dependencies_ignore"),
            ("PC_PYTHON_SANDBOX", "python_sandbox"),
            ("PC_JAVASCRIPT_SANDBOX", "javascript_sandbox"),
            ("IGNORE_BUNDLED_OPENSCAD", "ignore_bundled_openscad"),
            ("PC_INTERNAL_STATE_DIR", "internal_state_dir"),
            ("PC_FORCE_UPDATE", "force_update"),
            ("PC_OFFLINE", "offline"),
            ("PC_DEVEL_INDEX", "devel_index"),
            ("PC_TELEMETRY_TYPE", "telemetry_type"),
            ("PC_TELEMETRY_ENV", "telemetry_env"),
            ("PC_TELEMETRY_PERFORMANCE", "telemetry_performance"),
            ("PC_TELEMETRY_FAILURES", "telemetry_failures"),
            ("PC_TELEMETRY_DEBUG", "telemetry_debug"),
            ("PC_TELEMETRY_SENTRY_DSN", "telemetry_sentry_dsn"),
            ("PC_TELEMETRY_SENTRY_SHUTDOWN_TIMEOUT", "telemetry_sentry_shutdown_timeout"),
            ("PC_TELEMETRY_SENTRY_ATTACH_STACKTRACE", "telemetry_sentry_attach_stacktrace"),
            ("PC_TELEMETRY_SENTRY_TRACES_SAMPLE_RATE", "telemetry_sentry_traces_sample_rate"),
        ]

        # TODO(clairbee): revisit why envionment variables are not used
        for _env_var, attrib in user_config_options:
            value = kwargs.get(attrib, None)
            if value is not None:
                if "telemetry" in attrib:
                    attrib = attrib.replace("telemetry_", "telemetry.")
                    attrib = re.sub(r"_([a-z])", lambda x: x.group(1).upper(), attrib)
                    pc_user_config.set(attrib, value)
                else:
                    setattr(pc_user_config, attrib, value)

        # parse extra parameters and add them to the user_config
        for params in kwargs["extra_param"]:
            param, value = params.split("=")
            object_id, key = param.split(".")
            if object_id not in pc_user_config.parameter_config:
                pc_user_config.parameter_config[object_id] = {}
            pc_user_config.parameter_config[object_id][key] = value

        # Prepare the callboack to be used by command handlers should they need a PartCAD context object
        def get_partcad_context():
            nonlocal ctx, path
            from partcad.globals import init

            try:
                return init(path, user_config=pc_user_config)
            except (yaml.parser.ParserError, yaml.scanner.ScannerError) as e:
                exc = click.BadParameter("Invalid configuration file", ctx=ctx, param=path, param_hint=None)
                exc.exit_code = 2
                raise exc from e
            except Exception as e:
                pc_logging.error(e)
                # Keep the traceback for troubleshooting, but do not dump it at
                # the user during normal operation.
                if logging.getLogger("partcad").isEnabledFor(logging.DEBUG):
                    import traceback

                    traceback.print_exc()
                raise click.Abort from e

        # Pass everything the commands might need through the context object
        ctx.obj = CliContext(
            otel_context=pc_telemetry.context.get_current(),
            get_partcad_context=get_partcad_context,
            path=path,
        )


cli.context_settings = {
    "show_default": True,
    "auto_envvar_prefix": "PC",
    "help_option_names": ["-h", "--help"],
}


@cli.result_callback()
@click.pass_context
def process_result(click_ctx: click.Context, result, verbose, quiet, no_ansi, path, **kwargs):
    global cli_span

    logging_remote_client.fini()

    # Abort if there was at least one error reported during the execution time.
    # `result` is needed for the case when the command was not correct.
    if pc_logging.had_errors or result:
        if cli_span:
            cli_span.set_attribute("failed", True)
            cli_span.set_status(pc_telemetry.trace.StatusCode.ERROR)
        raise click.Abort()

    if cli_span:
        cli_span.set_attribute("success", True)
        cli_span.set_status(pc_telemetry.trace.StatusCode.OK)
        cli_span.end()
        cli_span = None


def main():
    try:
        cli()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        # When a clean error was already reported to the user (for example a
        # repository that could not be cloned), do not additionally dump a
        # traceback. Unexpected failures stay loud so that real bugs are not
        # hidden, and the traceback remains available under '-v'.
        if pc_logging.had_errors and not logging.getLogger("partcad").isEnabledFor(logging.DEBUG):
            pc_logging.error(str(e) if str(e) else type(e).__name__)
            sys.exit(1)
        raise e


if __name__ == "__main__":
    main()
