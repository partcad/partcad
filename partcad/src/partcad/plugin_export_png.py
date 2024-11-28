#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-01-20
#
# Licensed under Apache License, Version 2.0.


class PluginExportPng:
    """This is a stub for plugins that provide functionality of exporting to PNG"""

    def is_supported(self):
        return False

    def export(self, project, svg_path, width, height, filepath):
        return


plugin_export_png = PluginExportPng()
