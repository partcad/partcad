#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-04-17
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .sentry import instrument


@instrument()
class FileFactory:
    path: typing.Optional[str] = None

    def __init__(self, ctx, source_project, target_project, config):
        self.config = config
        self.ctx = ctx
        self.project = source_project

    async def download(self, path):
        raise NotImplementedError("FileFactory.download is implemented in child classes")
