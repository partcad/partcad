from build123d import Location
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from .globals import (
    init,
    fini,
    create_package,
    get_part,
    get_part_cadquery,
    get_part_build123d,
    get_assembly,
    get_assembly_cadquery,
    get_assembly_build123d,
    _partcad_context,
    render,
)
from .ai import supported_models
from .consts import *
from .context import Context
from .assembly import Assembly
from .part import Part
from .project import Project
from .project_factory_local import ProjectFactoryLocal
from .project_factory_git import ProjectFactoryGit
from .project_factory_tar import ProjectFactoryTar
from .user_config import user_config
from .plugins import plugins
from .plugin_export_png_reportlab import PluginExportPngReportlab
from .logging_ansi_terminal import init as logging_ansi_terminal_init
from .logging_ansi_terminal import fini as logging_ansi_terminal_fini
from . import logging
from . import utils
from . import exception

__all__ = [
    "config",
    "context",
    "shape",
    "geom",
    "part",
    "part_factory",
    "part_factory_step",
    "part_factory_cadquery",
    "project",
    "project_factory",
    "project_factory_local",
    "project_factory_git",
    "project_factory_tar",
    "assembly",
    "assembly_factory",
    "assembly_factory_python",
    "scene",
    "plugins",
    "exception",
]

__version__: str = "0.7.62"

# TODO(clairbee): move the below to `logging_sentry.py`
if not sentry_sdk.is_initialized() and user_config.get_string("sentry.dsn"):
    sentry_sdk.init(
        dsn=user_config.get_string("sentry.dsn"),
        release=__version__,
        debug=user_config.get_bool("sentry.debug"),
        shutdown_timeout=user_config.get_int("sentry.shutdown_timeout"),
        enable_tracing=True,
        attach_stacktrace=False, # TODO(clairbee): enable when sanitizing is implemented, make it configurable for CI/CD
        traces_sample_rate=user_config.get_float("sentry.traces_sample_rate"),
        integrations=[
            LoggingIntegration(
                level=logging.ERROR,
            )
        ],
        before_send=lambda event, hint: event if event.level != "critical" else None,
    )
