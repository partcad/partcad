#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-07-24
#
# Licensed under Apache License, Version 2.0.
#

import base64
import os

import aiofiles

from . import telemetry
from .file_factory import FileFactory
from . import logging as pc_logging


@telemetry.instrument()
class FileFactoryPlugin(FileFactory):
    """Materializes a file served by a repository plugin.

    An object served by a plugin references its source by a 'path' the plugin
    knows it by. The object lives in the plugin-backed package's cache directory
    (which has no source tree of its own), so the file has to be fetched from
    the plugin and written there on demand. The plugin returns the content under
    the 'files/<path>' key (base64-encoded bytes).
    """

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)
        # The path the plugin knows the file by (its declared 'path', before it
        # was rebased into the cache directory by the object factory).
        self.plugin_path = config.get("path")

    async def download(self, path):
        pc_logging.debug("Materializing plugin file '%s' to '%s'" % (self.plugin_path, path))

        get_data_async = getattr(self.project, "get_data_async", None)
        if get_data_async is None or self.plugin_path is None:
            raise Exception("Cannot materialize '%s': the package is not plugin-backed" % path)

        data = await get_data_async("files/" + self.plugin_path)
        if data is None:
            raise Exception("The plugin did not provide the file: %s" % self.plugin_path)
        content = base64.b64decode(data) if isinstance(data, str) else bytes(data)

        dirs = os.path.dirname(path)
        if dirs != "" and not os.path.exists(dirs):
            os.makedirs(dirs)
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
