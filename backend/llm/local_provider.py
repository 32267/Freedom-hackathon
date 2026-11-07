"""Своя модель за OpenAI-совместимым сервером (Ollama, vLLM, LM Studio, llama.cpp server).

Задел под модель, дообученную в папке llm/. Настройки в .env:
  LOCAL_LLM_URL=http://localhost:11434/v1     # базовый URL с /v1
  LOCAL_LLM_MODEL=cqa-judge                   # имя модели на сервере
  LOCAL_LLM_API_KEY=                          # если сервер требует
  LOCAL_LLM_MAX_TOKENS=12288                  # максимум токенов ответа
  LOCAL_LLM_TIMEOUT=600                       # таймаут запроса в секундах

Ответ запрашивается по JSON-схеме (response_format json_schema); сервер должен это поддерживать.
"""
import json
import os

import httpx

from . import LLMError, LLMOutputError, LLMResult


def call_json(system: str, user: str, schema: dict, model: str, effort: str) -> LLMResult:
    base = os.getenv("LOCAL_LLM_URL", "").strip().rstrip("/")
    if not base:
        raise LLMError("LOCAL_LLM_URL не задан — своя модель не подключена")
    name = os.getenv("LOCAL_LLM_MODEL", "").strip() or "cqa-judge"
    headers = {"Authorization": f"Bearer {os.getenv('LOCAL_LLM_API_KEY', '').strip()}"} if os.getenv("LOCAL_LLM_API_KEY") else {}

    try:
        max_tokens = int(os.getenv("LOCAL_LLM_MAX_TOKENS", "12288"))
        if max_tokens < 1:
            raise ValueError
    except ValueError as e:
        raise LLMError("LOCAL_LLM_MAX_TOKENS должен быть целым числом больше 0") from e

    timeout = float(os.getenv("LOCAL_LLM_TIMEOUT", "600"))
    body = {
        "model": name,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "cqa_evaluation", "schema": schema, "strict": True}},
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    try:
        r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=timeout)
    except httpx.TimeoutException as e:
        raise LLMError(f"Своя модель: таймаут после {timeout:g} с (LOCAL_LLM_TIMEOUT)") from e
    except httpx.HTTPError as e:
        raise LLMError(f"Своя модель недоступна: {e}") from e
    if r.status_code >= 400:
        raise LLMError(f"Своя модель: HTTP {r.status_code} {r.text[:200]}")

    try:
        out = r.json()
    except ValueError as e:
        raise LLMOutputError(f"Своя модель вернула не JSON-ответ API: {e}") from e

    try:
        choice = out["choices"][0]
        message = choice["message"]
        content = message["content"]
        finish_reason = choice.get("finish_reason")
        usage = out.get("usage") or {}
        data = json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        # Do not include the raw completion: it may contain customer transcript data.
        choice = (out.get("choices") or [{}])[0] if isinstance(out, dict) else {}
        usage = out.get("usage") or {} if isinstance(out, dict) else {}
        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        message = choice.get("message") or {} if isinstance(choice, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        content_chars = len(content) if isinstance(content, str) else 0
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        if finish_reason == "length":
            reason = "генерация остановлена по лимиту токенов (finish_reason=length)"
        else:
            reason = "ответ не удалось разобрать как JSON"
        raise LLMOutputError(
            f"Своя модель: {reason}; parse_error={e}; finish_reason={finish_reason!r}; "
            f"prompt_tokens={prompt_tokens}; completion_tokens={completion_tokens}; "
            f"response_chars={content_chars}; max_tokens={max_tokens}"
        ) from e

    return LLMResult(
        data=data,
        model=f"local:{name}",
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        cost_usd=0.0,
        meta={
            "provider": "local",
            "finish_reason": finish_reason,
            "max_tokens": max_tokens,
            "response_chars": len(content) if isinstance(content, str) else 0,
        },
    )
