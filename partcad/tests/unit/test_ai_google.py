#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for the Google provider after the `google-generativeai` ->
`google-genai` migration.

The new SDK is client-based (`client.models.generate_content(...)`) and its
response objects are pydantic models rather than proto-plus messages. These
tests pin down the parts of the port that are easy to get wrong and that no
other test covers:

  * the call shape (model / contents / config keywords),
  * text extraction from `candidate.content.parts` -- with pydantic, the old
    `"text" in part` membership test silently evaluates to False,
  * the retry classification, which moved from
    `google.api_core.exceptions.ResourceExhausted` / `InternalServerError` to
    `google.genai.errors.ClientError` (code 429) / `ServerError`.

No network access and no API key are involved: the SDK is replaced by fakes.
"""

from types import SimpleNamespace

import pytest

from partcad import ai_google
from partcad.ai_google import AiGoogle


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__("client error %d" % code)
        self.code = code


class FakeServerError(Exception):
    pass


class FakeFinishReason:
    STOP = "STOP"
    MAX_TOKENS = "MAX_TOKENS"
    SAFETY = "SAFETY"


class FakeFileState:
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"


def part(text=None, thought=None):
    return SimpleNamespace(text=text, thought=thought)


def candidate(parts, finish_reason=FakeFinishReason.STOP):
    content = None if parts is None else SimpleNamespace(parts=parts)
    return SimpleNamespace(content=content, finish_reason=finish_reason)


def response(candidates, prompt_feedback=None):
    return SimpleNamespace(candidates=candidates, prompt_feedback=prompt_feedback)


class Recorder:
    """Stands in for `client.models`, recording the generate_content() call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def google(monkeypatch):
    """Install fake SDK modules and return a factory for a wired-up AiGoogle."""
    monkeypatch.setattr(ai_google, "google_once", lambda: True)
    monkeypatch.setattr(ai_google, "pil_image", SimpleNamespace(open=lambda filename: "PIL:" + filename))
    monkeypatch.setattr(
        ai_google,
        "google_genai_types",
        SimpleNamespace(
            GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
            FinishReason=FakeFinishReason,
            FileState=FakeFileState,
        ),
    )
    monkeypatch.setattr(
        ai_google,
        "google_genai_errors",
        SimpleNamespace(ClientError=FakeClientError, ServerError=FakeServerError),
    )
    # Never actually wait during the retry tests.
    monkeypatch.setattr(ai_google.time, "sleep", lambda _seconds: None)

    def make(responses):
        recorder = Recorder(responses)
        monkeypatch.setattr(ai_google, "google_client", SimpleNamespace(models=recorder))
        ai = AiGoogle()
        ai.name = "test-part"
        return ai, recorder

    return make


def test_call_shape_and_config(google):
    ai, recorder = google([response([candidate([part(text="ok")])])])

    ai.generate_google(
        "gemini-2.5-pro",
        "draw a cube",
        {"tokens": 1234, "temperature": 0.25, "top_p": 0.9, "top_k": 40},
    )

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    # All three are keyword-only in the new SDK.
    assert call["model"] == "gemini-2.5-pro"
    assert call["contents"] == ["draw a cube"]
    config = call["config"]
    assert config.max_output_tokens == 1234
    assert config.temperature == 0.25
    assert config.top_p == 0.9
    assert config.top_k == 40
    assert config.candidate_count == 1


def test_unknown_model_does_not_raise_and_leaves_tokens_unset(google):
    ai, recorder = google([response([candidate([part(text="ok")])])])

    ai.generate_google("gemini-9.9-flash", "hi", {})

    assert recorder.calls[0]["config"].max_output_tokens is None


def test_text_is_extracted_and_thought_parts_are_skipped(google):
    ai, _ = google(
        [
            response(
                [
                    candidate(
                        [
                            part(text="internal reasoning", thought=True),
                            part(text="line one"),
                            part(),  # e.g. an inline_data part: no text at all
                            part(text="line two"),
                        ]
                    )
                ]
            )
        ]
    )

    assert ai.generate_google("gemini-2.5-pro", "hi", {}) == ["line one\nline two\n"]


def test_candidate_without_content_is_skipped(google):
    ai, _ = google([response([candidate(None, finish_reason=FakeFinishReason.SAFETY)])])

    assert ai.generate_google("gemini-2.5-pro", "hi", {}) == []


def test_quota_error_is_retried(google):
    ai, recorder = google([FakeClientError(429), response([candidate([part(text="done")])])])

    assert ai.generate_google("gemini-2.5-pro", "hi", {}) == ["done\n"]
    assert len(recorder.calls) == 2


def test_server_error_is_retried(google):
    ai, recorder = google([FakeServerError("boom"), response([candidate([part(text="done")])])])

    assert ai.generate_google("gemini-2.5-pro", "hi", {}) == ["done\n"]
    assert len(recorder.calls) == 2


def test_non_quota_client_error_is_not_retried(google):
    ai, recorder = google([FakeClientError(400)])

    with pytest.raises(FakeClientError):
        ai.generate_google("gemini-2.5-pro", "hi", {})
    assert len(recorder.calls) == 1


def test_blocked_prompt_yields_no_products(google):
    ai, _ = google([response(None, prompt_feedback=SimpleNamespace(block_reason="SAFETY"))])

    assert ai.generate_google("gemini-2.5-pro", "hi", {}) == []
