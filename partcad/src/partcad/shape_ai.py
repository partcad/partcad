#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-23
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
from pathlib import Path
import tempfile

from .ai import Ai
from . import logging as pc_logging
from .shape import Shape
from .user_config import user_config


class ShapeWithAi(Shape, Ai):

    def __init__(self, config):
        super().__init__(config)

    # @override
    async def get_summary_async(self, project=None):
        configured_summary = await super().get_summary_async(project)
        if not configured_summary is None:
            return configured_summary

        image_filename = tempfile.mktemp(".png")
        await self.render_png_async(project.ctx, project, image_filename)

        prompt = """The attached image is a single-color (the color doesn't
matter) line drawing of a mechanical design.
The design is stored in the folder "%s" and is named "%s".
""" % (
            self.project_name,
            self.name,
        )
        if not self.desc is None:
            prompt += 'The design is accompanied by the following description: "%s". ' % self.desc
        prompt += """Create a text which describes the design displayed on the
image so that a blind person (with background in mechanical engineering and
computer aided design) can picture it in their mind.
Do not repeat any information from the prompt without significant changes.
Make no assumptions. Provide as many details as possible.
Refer to the design as "this design" and not as "the image".
Produce text which is ready to be narrated as is.
"""

        config = {
            "model": ("gpt-4o" if user_config.openai_api_key is not None else "gemini-1.5-pro"),
            "provider": ("openai" if user_config.openai_api_key is not None else "google"),
        }
        summary = self.generate(
            "Desc",
            self.project_name,
            self.name,
            prompt,
            config,
            # image_filenames=[image_filename],
        )
        return summary[0] if len(summary) > 0 else "Failed to summarize"

    # @override
    def get_summary(self, project=None):
        return asyncio.run(self.get_summary_async(project))
