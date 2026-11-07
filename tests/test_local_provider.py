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
    assert seen["body"]["repetition_penalty"] == 1.1
    assert seen["body"]["repetition_context_size"] == 64
    assert res.data == {"criteria": {}} and res.model == "local:cqa-judge" and res.provider == "local"
    assert res.meta["retry_count"] == 0


def test_bad_json_is_output_error(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_URL", "http://x/v1")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp(200, {"choices": [{"message": {"content": "не json"}}]}))
    with pytest.raises(LLMOutputError):
        call_json("s", "u", {}, "local")



def test_opt_in_debug_capture_saves_request_and_raw_completion(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LLM_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("LOCAL_LLM_DEBUG_DIR", str(tmp_path / "private-debug"))
    raw = '{"criteria": {}}'
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp(200, {
        "id": "resp-1",
        "model": "cqa-judge",
        "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
    }))

    result = call_json(
        "system prompt",
        "Диалог dev-ru-chat-001 · канал: agent chat · язык: RU\nТранскрипт: ...",
        {"type": "object", "properties": {"criteria": {"type": "object", "properties": {"contact": {"type": "object"}}}}},
        "local",
    )

    assert result.data == {"criteria": {}}
    files = list((tmp_path / "private-debug").glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["conversation_id"] == "dev-ru-chat-001"
    assert saved["criterion_id"] == "contact"
    assert saved["attempt"] == 1
    assert saved["request"]["messages"][0]["content"] == "system prompt"
    assert saved["response"]["content"] == raw
    assert saved["response"]["finish_reason"] == "stop"
    assert saved["response"]["usage"]["completion_tokens"] == 3
    assert files[0].stat().st_mode & 0o777 == 0o600


def test_opt_in_debug_capture_saves_truncated_completion(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LOCAL_LLM_DEBUG_DIR", str(tmp_path))
    raw = '{"criteria":{"contact":{"explanation":{"ru":"unfinished'
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp(200, {
        "choices": [{"message": {"content": raw}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 1543, "completion_tokens": 4096},
    }))

    with pytest.raises(LLMOutputError, match="finish_reason=length"):
        call_json("system", "Диалог dev-ru-chat-001 · ...\nПрошлый ответ по этим критериям не прошёл проверку:", {
            "type": "object",
            "properties": {"criteria": {"type": "object", "properties": {"contact": {"type": "object"}}}},
        }, "local")

    saved = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert saved["attempt"] == 2
    assert saved["response"]["content"] == raw
    assert saved["response"]["finish_reason"] == "length"
    assert saved["response"]["usage"]["completion_tokens"] == 4096


def test_debug_capture_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("LOCAL_LLM_DEBUG_DIR", raising=False)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp(200, {
        "choices": [{"message": {"content": '{"criteria": {}}'}, "finish_reason": "stop"}],
        "usage": {},
    }))
    call_json("system", "user", {"type": "object"}, "local")
    assert list(tmp_path.iterdir()) == []


def test_repetition_loop_gets_one_bounded_retry(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_URL", "http://localhost:8080/v1")
    responses = [
        Resp(200, {"choices": [{"message": {"content": "алады " * 30}, "finish_reason": "length"}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 100}}),
        Resp(200, {"choices": [{"message": {"content": '{"criteria": {}}'}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}),
    ]
    requests = []

    def fake_post(url, json, headers, timeout):
        requests.append(json)
        return responses.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = call_json("system", "user", {"type": "object"}, "local")
    assert len(requests) == 2
    assert requests[0]["repetition_penalty"] == 1.1
    assert requests[1]["repetition_penalty"] > requests[0]["repetition_penalty"]
    assert result.data == {"criteria": {}}
    assert result.input_tokens == 20 and result.output_tokens == 105
    assert result.meta["retry_count"] == 1


def test_repetition_loop_after_retry_is_rejected(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_URL", "http://localhost:8080/v1")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp(200, {
        "choices": [{"message": {"content": "алады " * 30}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 100},
    }))
    with pytest.raises(LLMOutputError, match="продолжила повторять"):
        call_json("system", "user", {"type": "object"}, "local")


def test_repetition_penalty_can_be_disabled(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("LOCAL_LLM_REPETITION_PENALTY", "1.0")
    seen = {}
    monkeypatch.setattr(httpx, "post", lambda url, json, **kw: (
        seen.update(body=json) or Resp(200, {
            "choices": [{"message": {"content": '{"criteria": {}}'}, "finish_reason": "stop"}],
            "usage": {},
        })
    ))
    result = call_json("system", "user", {"type": "object"}, "local")
    assert "repetition_penalty" not in seen["body"]
    assert "repetition_context_size" not in seen["body"]
    assert result.meta["repetition_penalty"] == 1.0
    assert result.meta["repetition_context_size"] is None
