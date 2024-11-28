#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-01-20
#
# Licensed under Apache License, Version 2.0.

from .plugin_export_png import plugin_export_png


class Plugins:
    export_png = plugin_export_png


plugins = Plugins()
