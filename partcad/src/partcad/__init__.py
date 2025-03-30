import sentry_sdk
from build123d import Location

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
    init_sentry,
    __version__
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
from .logging_ansi_terminal import init as logging_ansi_terminal_init
from .logging_ansi_terminal import fini as logging_ansi_terminal_fini
from . import logging
from . import utils
from . import exception
from . import part_factory
from .part_types import PartTypes

# TODO: remove partcad old version usage from vscode extension
# /home/vscode/.vscode-server/extensions/openvmp.partcad-0.7.15/bundled/tool/lsp_server.py:690:        partcad.plugins.export_png = partcad.PluginExportPngReportlab()
class PluginExportPngReportlab:
  pass

plugins = PluginExportPngReportlab()

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
    "PluginExportPngReportlab",
    "PartTypes"
]

if not sentry_sdk.is_initialized() and user_config.get_string("sentry.dsn"):
    init_sentry(user_config.sentry_config)
