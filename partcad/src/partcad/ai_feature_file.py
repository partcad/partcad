#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-11
#
# Licensed under Apache License, Version 2.0.
#

import tempfile
import re
import requests

from . import logging as pc_logging


class AiContentFile:
    def __init__(self, url: str):
        self.url = url
        self.is_text = False
        self.is_image = False
        self.is_video = False
        self.is_pdf = False
        self.suffix = ".txt"
        self.filename = None

        # Switch to lowercase to normalize the file extension in the URL
        lower_url = url.lower()
        if lower_url.startswith("http://") or lower_url.startswith("https://"):
            response = requests.get(self.url)
            if response.status_code == 200:
                self.filename = tempfile.NamedTemporaryFile(suffix=self.suffix, delete=False)
                self.filename.write(response.content)
                self.filename.close()
            else:
                raise Exception(f"Failed to download the file {self.url}")

            # Strip the query string from the URL to get the extension
            if "?" in lower_url:
                lower_url = lower_url[: lower_url.index("?")]
        else:
            self.filename = self.url

        if lower_url.endswith(".png"):
            self.is_image = True
            self.suffix = ".png"
        elif lower_url.endswith(".jpg") or lower_url.endswith(".jpeg"):
            self.is_image = True
            self.suffix = ".jpg"
        elif lower_url.endswith(".mp4"):
            self.is_video = True
            self.suffix = ".mp4"
        elif lower_url.endswith(".pdf"):
            self.is_pdf = True
            self.suffix = ".pdf"

    def __repr__(self):
        type = "unknown"
        if self.is_text:
            type = "text"
        elif self.is_image:
            type = "image"
        elif self.is_video:
            type = "video"
        elif self.is_pdf:
            type = "pdf"
        return f"AiContentFile({self.url}, {type})"


class AiContentProcessor:
    MARKER = "CONTENT_INSERTED_HERE"

    def process_content(self, content: str):
        content_inserts = []

        def include_content(match):
            location = match.group(2)
            if (location.startswith('"') and location.endswith('"')) or (
                location.startswith("'") and location.endswith("'")
            ):
                location = location[1:-1]
            try:
                content_inserts.append(AiContentFile(location))
                return "CONTENT_INSERTED_HERE"
            except Exception as e:
                pc_logging.error(f"Failed to include content from {location}: {e}")
                return "PARTCAD-FAILED-TO-INSERT-CONTENT-HERE"

        content = re.sub(r"(INSERT_IMAGE_HERE|INCLUDE|DOWNLOAD)\(([^)]*)\)", include_content, content)
        content_parts = content.split("CONTENT_INSERTED_HERE")

        return content_parts, content_inserts
