#
# PartCAD, 2025
# OpenVMP, 2023
#
# Licensed under Apache License, Version 2.0.
#

__version__: str = "0.8.13"

# Must come before anything that spawns a process: everything PartCAD executes
# in a Python sandbox inherits this environment, so this is where the sandbox
# stops inheriting the user's PYTHON* variables and starts inheriting the
# reproducible ones PartCAD wants instead. See the module for the whole story.
from .python_env import sanitize as _sanitize_python_env

_sanitize_python_env()

# Must come before anything that can pull OCP in. VTK, which the OCP build we
# use links against, bundles its own older copy of expat and exports it under
# the standard XML_* names. Once that is in the process, the standard library's
# pyexpat resolves against it and fails with "undefined symbol:
# XML_SetReparseDeferralEnabled" on any interpreter built against expat 2.6+.
# Loading pyexpat first pins it to the right library. It matters since
# build123d 0.11, which imports IPython (-> prompt_toolkit -> xml.dom.minidom)
# at import time and so trips over this on the way in.
import pyexpat  # noqa: F401

# The shared lightweight utilities (logging, telemetry, user config) live in the
# standalone `partcad_utils` package, so the thin CLI/daemon clients can import
# them without pulling in the CAD kernel. Alias them back under the `partcad.*`
# namespace *before* any submodule below does `from . import logging` /
# `from . import telemetry` / `from .user_config import ...`, so every existing
# import resolves to the very same module object — shared mutable state such as
# `logging.had_errors` and `logging.ops` included (a plain re-export would fork
# those globals).
import sys as _sys

import partcad_utils.logging  # noqa: F401,E402
import partcad_utils.logging_ansi_terminal  # noqa: F401,E402
import partcad_utils.logging_remote_client  # noqa: F401,E402
import partcad_utils.logging_remote_server  # noqa: F401,E402
import partcad_utils.telemetry  # noqa: F401,E402
import partcad_utils.telemetry_none  # noqa: F401,E402
import partcad_utils.telemetry_sentry  # noqa: F401,E402
import partcad_utils.user_config  # noqa: F401,E402
import partcad_utils.utils  # noqa: F401,E402

for _n in (
    "logging",
    "logging_ansi_terminal",
    "logging_remote_server",
    "logging_remote_client",
    "telemetry",
    "telemetry_none",
    "telemetry_sentry",
    "utils",
    "user_config",
):
    _mod = _sys.modules["partcad_utils." + _n]
    _sys.modules["partcad." + _n] = _mod
    # Also expose it as an attribute of the `partcad` package, so `partcad.<n>`
    # resolves even when nothing does `from . import <n>` below. (`user_config`
    # is re-bound to the config *instance* by a later explicit import.)
    globals()[_n] = _mod

from . import telemetry

telemetry.init(__version__)

from . import actions, exception, healthcheck, logging, tags, utils

# Imported for the binding rather than for anything here: it makes
# `partcad.plugin` resolve as an attribute of the package, which is how the
# daemon marks the start of each command (see
# partcad_service_json_rpc.rpc.methods._begins_a_command). It resolved anyway
# while some other module happened to import it first, which is not something
# to leave a request path depending on.
from . import plugin  # noqa: F401
from .assembly import Assembly
from .assembly_connect import ConnectHold, ConnectHow
from .consts import *
from .context import Context
from .geom import Location
from .globals import (
    _partcad_context,
    convert_assembly,
    convert_part,
    convert_sketch,
    create_package,
    fini,
    get_assembly,
    get_assembly_build123d,
    get_assembly_cadquery,
    get_part,
    get_part_build123d,
    get_part_cadquery,
    get_part_sdf,
    init,
    render,
)
from .launch_config import add_render_configuration
from .logging_ansi_terminal import fini as logging_ansi_terminal_fini
from .logging_ansi_terminal import init as logging_ansi_terminal_init
from .part import Part
from .plugin_provider_data_cart import ProviderCart
from .plugin_request_provider_caps import ProviderRequestCaps
from .plugin_request_provider_quote import ProviderRequestQuote
from .project import Project
from .project_factory_git import ProjectFactoryGit
from .project_factory_local import ProjectFactoryLocal
from .project_factory_tar import ProjectFactoryTar
from .shape import Shape
from .user_config import UserConfig, user_config


# TODO: remove partcad old version usage from vscode extension
# /home/vscode/.vscode-server/extensions/openvmp.partcad-0.7.15/bundled/tool/lsp_server.py:690:        partcad.plugins.export_png = partcad.PluginExportPngReportlab()
class PluginExportPngReportlab:
    pass


plugins = PluginExportPngReportlab()

__all__ = [
    "Assembly",
    "ConnectHold",
    "ConnectHow",
    "Context",
    "Location",
    "Part",
    "Project",
    "ProjectFactoryGit",
    "ProjectFactoryLocal",
    "ProjectFactoryTar",
    "ProviderCart",
    "ProviderRequestQuote",
    "ProviderRequestCaps",
    "Shape",
    "UserConfig",
    "add_render_configuration",
    "config",
    "context",
    "convert_assembly",
    "convert_part",
    "convert_sketch",
    "create_package",
    "exception",
    "fini",
    "get_assembly",
    "get_assembly_cadquery",
    "get_assembly_build123d",
    "get_part",
    "get_part_cadquery",
    "get_part_build123d",
    "get_part_sdf",
    "healthcheck",
    "init",
    "logging",
    "part",
    "shape",
    "tags",
    "scene",
    "telemetry",
    "user_config",
    "utils",
    "actions",
]
