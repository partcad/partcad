#
# PartCAD, 2025
# OpenVMP, 2023
#
# Licensed under Apache License, Version 2.0.
#

__version__: str = "0.7.133"

from . import telemetry

telemetry.init(__version__)

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
from .plugin_provider_data_cart import ProviderCart
from .plugin_request_provider_quote import ProviderRequestQuote
from .plugin_request_provider_caps import ProviderRequestCaps
from .shape import Shape
from .user_config import user_config
from .logging_ansi_terminal import init as logging_ansi_terminal_init
from .logging_ansi_terminal import fini as logging_ansi_terminal_fini
from . import logging
from . import utils
from . import exception

from .user_config import UserConfig


# TODO: remove partcad old version usage from vscode extension
# /home/vscode/.vscode-server/extensions/openvmp.partcad-0.7.15/bundled/tool/lsp_server.py:690:        partcad.plugins.export_png = partcad.PluginExportPngReportlab()
class PluginExportPngReportlab:
    pass


plugins = PluginExportPngReportlab()

__all__ = [
    "Assembly",
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
    "config",
    "context",
    "create_package",
    "exception",
    "fini",
    "get_assembly",
    "get_assembly_cadquery",
    "get_assembly_build123d",
    "get_part",
    "get_part_cadquery",
    "get_part_build123d",
    "init",
    "logging",
    "part",
    "shape",
    "scene",
    "telemetry",
    "user_config",
    "utils",
]
