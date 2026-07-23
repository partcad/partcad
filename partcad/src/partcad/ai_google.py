#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-03-23
#
# Licensed under Apache License, Version 2.0.
#

import threading
import time
from typing import Any

from . import telemetry
from .ai_deps import import_optional
from .ai_feature_file import AiContentFile, AiContentProcessor
from . import logging as pc_logging
from . import interactive
from .user_config import user_config

# Lazy-load AI imports as they are not always needed
# import PIL.Image
pil_image = None
# from google import genai
google_genai = None
# from google.genai import types as google_genai_types
google_genai_types = None
# from google.genai import errors as google_genai_errors
google_genai_errors = None

lock = threading.Lock()
GOOGLE_API_KEY = None
# The `google-genai` SDK is client-based: there is no global `configure()` any
# more, so the client is created here and recreated whenever the key changes.
google_client = None

# The maximum number of output tokens per model, where a documented limit is
# known. Models that are absent from this map are left to the SDK/service
# default, which is the model's own maximum.
model_tokens = {
    "gemini-2.5-pro": 65536,
    "gemini-2.5-flash": 65536,
    "gemini-2.5-flash-lite": 65536,
}

# Google's file processing (PDF and video uploads) is asynchronous.
FILE_PROCESSING_TIMEOUT = 300  # 5 minutes
FILE_PROCESSING_POLL_INTERVAL = 5


def google_once():
    global GOOGLE_API_KEY
    global pil_image
    global google_genai
    global google_genai_types
    global google_genai_errors
    global google_client

    with lock:
        if pil_image is None:
            pil_image = import_optional("PIL.Image", "Google AI", "ai-google")

        # `from google import genai` is the same import as `google.genai`.
        if google_genai is None:
            google_genai = import_optional("google.genai", "Google AI", "ai-google")

        if google_genai_types is None:
            google_genai_types = import_optional("google.genai.types", "Google AI", "ai-google")

        # `google.api_core.exceptions` is not used any more: the new SDK raises
        # its own `google.genai.errors.APIError` hierarchy.
        if google_genai_errors is None:
            google_genai_errors = import_optional("google.genai.errors", "Google AI", "ai-google")

        latest_key = user_config.google_api_key
        if not latest_key:
            latest_key = interactive.prompt("API_KEY_GOOGLE", "Enter Google Cloud Generative Language API key")
        if latest_key != GOOGLE_API_KEY:
            GOOGLE_API_KEY = latest_key
            if not GOOGLE_API_KEY is None:
                google_client = google_genai.Client(api_key=GOOGLE_API_KEY)
                return True

        if GOOGLE_API_KEY is None:
            raise Exception("Google API key is not set")

        if google_client is None:
            google_client = google_genai.Client(api_key=GOOGLE_API_KEY)

    return True


@telemetry.instrument()
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
            tokens = model_tokens.get(model, None)

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

        def wait_for_file(uploaded):
            """Block until an uploaded file leaves the PROCESSING state."""
            start_time = time.time()
            while uploaded.state == google_genai_types.FileState.PROCESSING:
                if time.time() - start_time > FILE_PROCESSING_TIMEOUT:
                    raise TimeoutError("File processing timeout exceeded")
                time.sleep(FILE_PROCESSING_POLL_INTERVAL)
                uploaded = google_client.files.get(name=uploaded.name)
            if uploaded.state == google_genai_types.FileState.FAILED:
                raise Exception("Google failed to process the uploaded file: %s" % str(uploaded.error))
            return uploaded

        def handle_content(content: AiContentFile):
            # PIL images are accepted directly by the SDK: it converts them to
            # an inline data part on the way out.
            if content.is_image:
                return pil_image.open(content.filename)
            # `genai.upload_file()` became `client.files.upload()`, and it
            # returns a `types.File` which `contents` accepts as a part.
            if content.is_pdf:
                return wait_for_file(google_client.files.upload(file=content.filename))
            if content.is_video:
                return wait_for_file(google_client.files.upload(file=content.filename))
            return "FILE-TYPE-NOT-SUPPORTED"

        content_parts, content_inserts = self.process_content(prompt)
        content_inserts = list(map(handle_content, content_inserts))
        content = []
        for i in range(len(content_parts)):
            content.append(content_parts[i])
            if i < len(content_inserts):
                content.append(content_inserts[i])

        # `GenerativeModel` is gone: the generation config is passed per call.
        generate_config = google_genai_types.GenerateContentConfig(
            candidate_count=1,
            # candidate_count=options_num,  # TODO(clairbee): not supported yet? not any more?
            max_output_tokens=tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
        )

        candidates = []
        options_left = options_num
        while options_left > 0:
            response = None
            retry = True
            while retry == True:
                retry = False
                try:
                    response = google_client.models.generate_content(
                        model=model,
                        contents=content,
                        config=generate_config,
                    )
                except google_genai_errors.ClientError as e:
                    # 429 RESOURCE_EXHAUSTED is the quota error that used to be
                    # `google.api_core.exceptions.ResourceExhausted`.
                    if getattr(e, "code", None) != 429:
                        raise
                    pc_logging.exception(e)
                    retry = True
                    time.sleep(60)
                except google_genai_errors.ServerError as e:
                    # 5xx, previously `google.api_core.exceptions.InternalServerError`.
                    pc_logging.exception(e)
                    retry = True
                    time.sleep(1)

            if response is None:
                error = "%s: Failed to generate content" % self.name
                pc_logging.error(error)
                continue

            response_candidates = response.candidates or []
            if not response_candidates and response.prompt_feedback is not None:
                pc_logging.error(
                    "%s: The prompt was rejected by Google: %s" % (self.name, str(response.prompt_feedback))
                )

            options_created = len(response_candidates)
            candidates.extend(response_candidates)
            options_left -= options_created if options_created > 0 else 1

        products = []
        try:
            for candidate in candidates:
                if candidate.finish_reason is not None and candidate.finish_reason not in (
                    google_genai_types.FinishReason.STOP,
                    google_genai_types.FinishReason.MAX_TOKENS,
                ):
                    pc_logging.warning("%s: Google stopped generating: %s" % (self.name, str(candidate.finish_reason)))

                product = ""
                if candidate.content is None or not candidate.content.parts:
                    continue
                for part in candidate.content.parts:
                    # Skip the reasoning parts emitted by thinking models.
                    if part.thought:
                        continue
                    # `Part` is a pydantic model now: `"text" in part` silently
                    # evaluates to False, so the attribute must be tested.
                    if part.text:
                        product += part.text + "\n"

                products.append(product)
        except Exception as e:
            pc_logging.exception(e)

        return products
