"""Слот своей модели: OpenAI-совместимый сервер подменяется фейком."""
import json

import httpx
import pytest

from backend.llm import LLMError, LLMOutputError, call_json


class Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, json.dumps(body)

    def json(self):
        return self._body


def test_not_configured(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_URL", raising=False)
    with pytest.raises(LLMError, match="LOCAL_LLM_URL"):
        call_json("s", "u", {}, "local")


def test_calls_openai_compatible_server(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "cqa-judge")
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, body=json)
        return Resp(200, {"choices": [{"message": {"content": '{"criteria": {}}'}}],
                          "usage": {"prompt_tokens": 10, "completion_tokens": 3}})
    monkeypatch.setattr(httpx, "post", fake_post)
    res = call_json("sys", "user", {"type": "object"}, "local")
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["body"]["response_format"]["json_schema"]["schema"] == {"type": "object"}
    assert res.data == {"criteria": {}} and res.model == "local:cqa-judge" and res.provider == "local"


def test_bad_json_is_output_error(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_URL", "http://x/v1")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp(200, {"choices": [{"message": {"content": "не json"}}]}))
    with pytest.raises(LLMOutputError):
        call_json("s", "u", {}, "local")
