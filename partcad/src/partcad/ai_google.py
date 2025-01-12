#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-23
#
# Licensed under Apache License, Version 2.0.
#

import importlib
import threading
import time
from typing import Any

# Lazy-load AI imports as they are not always needed
# import PIL.Image
pil_image = None
# import google.generativeai as google_genai
google_genai = None
# import google.api_core.exceptions
google_api_core_exceptions = None

from .ai_feature_file import AiContentProcessor
from . import logging as pc_logging
from .user_config import user_config

lock = threading.Lock()
GOOGLE_API_KEY = None

model_tokens = {
    "gemini-pro": 32600,
    "gemini-pro-vision": 16300,
}


def google_once():
    global GOOGLE_API_KEY
    global pil_image
    global google_genai
    global google_api_core_exceptions

    with lock:
        if pil_image is None:
            pil_image = importlib.import_module("PIL.Image")

        if google_genai is None:
            google_genai = importlib.import_module("google.generativeai")

        if google_api_core_exceptions is None:
            google_api_core_exceptions = importlib.import_module("google.api_core.exceptions")

        latest_key = user_config.google_api_key
        if latest_key != GOOGLE_API_KEY:
            GOOGLE_API_KEY = latest_key
            if not GOOGLE_API_KEY is None:
                google_genai.configure(api_key=GOOGLE_API_KEY)
                return True

        if GOOGLE_API_KEY is None:
            raise Exception("Google API key is not set")

    return True


class AiGoogle(AiContentProcessor):
    def generate_google(
        self,
        model: str,
        prompt: str,
        config: dict[str, Any] = {},
        options_num: int = 1,
    ):
        if not google_once():
            return None

        if "tokens" in config:
            tokens = config["tokens"]
        else:
            tokens = model_tokens[model] if model in model_tokens else None

        if "top_p" in config:
            top_p = config["top_p"]
        else:
            top_p = None

        if "top_k" in config:
            top_k = config["top_k"]
        else:
            top_k = None

        if "temperature" in config:
            temperature = config["temperature"]
        else:
            temperature = None

        def handle_content(content):
            if content.is_image:
                return pil_image.open(content.filename)
            if content.is_pdf:
                return google_genai.upload_file(content.filename)
            if content.is_video:
                video_content = google_genai.upload_file(content.filename)
                while video_content.state.name == "PROCESSING":
                    time.sleep(5)
                    video_content = google_genai.get_file(video_content.name)
                return video_content

        content_parts, content_inserts = self.process_content(prompt)
        content_inserts = list(map(handle_content, content_inserts))
        content = []
        for i in range(len(content_parts)):
            content.append(content_parts[i])
            if i < len(content_inserts):
                content.append(content_inserts[i])

        client = google_genai.GenerativeModel(
            model,
            generation_config={
                "candidate_count": 1,
                # "candidate_count": options_num,  # TODO(clairbee): not supported yet? not any more?
                "max_output_tokens": tokens,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
            },
        )
        candidates = []
        options_left = options_num
        while options_left > 0:
            retry = True
            while retry == True:
                retry = False
                try:
                    response = client.generate_content(content)
                except google_api_core_exceptions.ResourceExhausted as e:
                    pc_logging.exception(e)
                    retry = True
                    time.sleep(60)
                except google_api_core_exceptions.InternalServerError as e:
                    pc_logging.exception(e)
                    retry = True
                    time.sleep(1)

            if response is None:
                error = "%s: Failed to generate content" % self.name
                pc_logging.error(error)
                continue

            options_created = len(response.candidates)
            candidates.extend(response.candidates)
            options_left -= options_created if options_created > 0 else 1

        products = []
        try:
            for candidate in candidates:
                product = ""
                for part in candidate.content.parts:
                    if "text" in part:
                        product += part.text + "\n"

                products.append(product)
        except Exception as e:
            pc_logging.exception(e)

        return products
