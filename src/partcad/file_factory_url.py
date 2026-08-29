#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-04-17
#
# Licensed under Apache License, Version 2.0.
#

import aiofiles
import aiohttp
import os

from . import telemetry
from .file_factory import FileFactory
from .logging import debug


@telemetry.instrument()
class FileFactoryUrl(FileFactory):
    url: str = None

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)

        # 'fileUrl' is what this factory exists for, so say which object is
        # missing it. Left to itself this is a bare KeyError with a traceback
        # and no hint of which declaration in 'partcad.yaml' is at fault.
        if "fileUrl" not in config:
            raise Exception("ERROR: '%s' declares 'fileFrom: url' but no 'fileUrl'" % config.get("name", "<unnamed>"))
        self.url = config["fileUrl"]

    async def _download(self, path):
        debug("Downloading file from %s to %s" % (self.url, path))

        dirs = os.path.dirname(path)
        if dirs != "" and not os.path.exists(dirs):
            os.makedirs(dirs)

        async with aiohttp.ClientSession() as session:
            r = await session.get(self.url)
            content = await r.read()

        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
