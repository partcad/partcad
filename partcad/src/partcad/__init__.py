import hashlib
import os
import psutil
import socket
import uuid


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
    "part_factory_brep",
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

__version__: str = "0.7.70"

# TODO(clairbee): move the below to `logging_sentry.py`
if not sentry_sdk.is_initialized() and user_config.get_string("sentry.dsn"):
    critical_to_ignore = [
        "action_start: ",
        "action_end: ",
    ]
    debug_to_ignore = [
        "Starting action",
        "Finished action",
    ]

    def before_send(event, hint):
        # Reduce noise in logs (drop events from "with logging.Process():")
        if event.get("level") == "critical":
            # from logging_ansi_terminal.py
            message = event.get("logentry", {}).get("message")
            if message and message.startswith(critical_to_ignore):
                return None
        elif event.get("level") == "debug":
            # from logging.py
            message = event.get("logentry", {}).get("message")
            if message and message.startswith(debug_to_ignore):
                return None

        return event

    sentry_sdk.init(
        # FIXME: sentry_sdk.utils.BadDsn: Missing public key
        dsn=user_config.get_string("sentry.dsn"),
        release=__version__,
        environment=user_config.get_string("sentry.environment"),
        debug=user_config.get_bool("sentry.debug"),
        shutdown_timeout=user_config.get_int("sentry.shutdown_timeout"),
        enable_tracing=user_config.get_bool("sentry.enable_tracing"),
        attach_stacktrace=user_config.get_bool("sentry.attach_stacktrace"),
        traces_sample_rate=user_config.get_float("sentry.traces_sample_rate"),
        integrations=[
            LoggingIntegration(
                level=logging.logging.getLevelName(
                    user_config.get_string("sentry.integrations.LoggingIntegration.level").upper()
                )
            )
        ],
        before_send=before_send,
    )

    # # https://develop.sentry.dev/sdk/data-model/event-payloads/user/
    # # For some reason, the {{auto}} tag is not working:
    # # "null - Replaced because of SDK configuration"
    # sentry_sdk.set_user({"ip_address": "{{auto}}"})

    sentry_sdk.set_tag("utm.source", "PartCAD")
    sentry_sdk.set_tag("utm.medium", "Sentry")
    sentry_sdk.set_tag("utm.campaign", "Open Source")
    sentry_sdk.set_tag("utm.content", "API")

    sentry_sdk.set_tag("env.remote_containers", os.environ.get("REMOTE_CONTAINERS", "false").lower() == "true")

    hostname = socket.getfqdn()
    hostname_md5 = hashlib.md5(hostname.encode()).hexdigest()
    sentry_sdk.set_tag("hostname.md5", hostname_md5)

    username = os.getenv("USER")
    username_md5 = hashlib.md5(username.encode()).hexdigest()
    sentry_sdk.set_tag("username.md5", username_md5)

    cache_dir = os.path.expanduser("~/.cache/partcad")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "id")

    # Check if the ID is already cached
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            unique_uid = f.read().strip()
    else:
        # Generate a new unique ID and cache it
        unique_uid = str(uuid.uuid4())
        with open(cache_file, "w") as f:
            f.write(unique_uid)

    sentry_sdk.set_user({"id": unique_uid})

    # https://docs.sentry.io/product/performance/metrics/#custom-performance-measurements
    # https://docs.sentry.io/platforms/python/tracing/instrumentation/performance-metrics/
    memory_rss = psutil.Process().memory_info().rss
    cpu_user = psutil.Process().cpu_times().user

    # TODO: Report internal metrics, such as following:

    # INFO:  PartCAD version: 0.7.63
    # INFO:  Internal data storage location: /home/vscode/.partcad
    # INFO:  Total internal data storage size: 0.00MB
    # INFO:  Git cache size: 0.00MB
    # INFO:  Tar cache size: 0.00MB
    # INFO:  Runtime environments size: 0.00MB
    # INFO:  DONE: Status: this: 0.07s

    sentry_sdk.set_measurement("memory.rss", memory_rss, "byte")
    sentry_sdk.set_measurement("cpu.user", cpu_user, "second")

    sentry_sdk.profiler.start_profiler()
