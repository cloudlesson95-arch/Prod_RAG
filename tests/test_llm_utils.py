from types import SimpleNamespace

import groq
import httpx
import pytest

from src.core import utils
from src.core.utils import EmptyAnswerError, invoke_text, rate_limit_retry_after

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class ScriptedLLM:
    """Answers with the given replies in order and records the prompts."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.replies.pop(0), response_metadata={"finish_reason": "stop"})


def groq_error(status, headers=None):
    """A real Groq SDK error for the given status, as the client raises it after its own retries."""
    response = httpx.Response(status, headers=headers or {}, request=httpx.Request("POST", GROQ_URL))
    error_class = groq.RateLimitError if status == 429 else groq.InternalServerError
    return error_class("Rate limit reached. Please try again in 6.015s.", response=response, body=None)


def test_a_text_answer_takes_one_call():
    """Verify a non-blank answer is returned as it is, without a second call."""
    llm = ScriptedLLM("A clowder.")
    assert invoke_text(llm, "What is a group of cats called?") == "A clowder."
    assert len(llm.prompts) == 1


def test_a_blank_answer_is_asked_again():
    """Verify a blank answer gets one more call with the same prompt."""
    llm = ScriptedLLM("  \n", "A clowder.")
    assert invoke_text(llm, "What is a group of cats called?") == "A clowder."
    assert llm.prompts == ["What is a group of cats called?"] * 2


def test_two_blank_answers_raise():
    """Verify a second blank answer raises instead of returning empty text."""
    llm = ScriptedLLM("", "")
    with pytest.raises(EmptyAnswerError):
        invoke_text(llm, "Who is Elena Rostova?")
    assert len(llm.prompts) == 2


@pytest.mark.parametrize("headers, seconds", [({"retry-after": "7"}, 7), ({"retry-after": "0.802"}, 1), ({}, 10)])
def test_a_rate_limit_gives_the_seconds_to_wait(headers, seconds):
    """Verify a 429's retry-after is rounded up to whole seconds, with a default when it's missing."""
    assert rate_limit_retry_after(groq_error(429, headers)) == seconds


def test_other_errors_are_not_rate_limits():
    """Verify server errors and non-HTTP errors give no wait."""
    assert rate_limit_retry_after(groq_error(500)) is None
    assert rate_limit_retry_after(ValueError("not an HTTP error")) is None


def test_groq_client_retries_as_configured(monkeypatch):
    """Verify the SDK's retry count comes from GROQ_MAX_RETRIES (no network: the model and key are faked)."""
    monkeypatch.setattr(utils, "get_model", lambda provider: "openai/gpt-oss-20b")
    monkeypatch.setattr(utils, "get_secret", lambda name: "test-key")
    monkeypatch.setattr(utils, "GROQ_MAX_RETRIES", 3)
    assert utils.create_llm("groq").max_retries == 3
