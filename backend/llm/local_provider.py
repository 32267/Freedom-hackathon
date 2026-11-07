"""Своя модель за OpenAI-совместимым сервером (Ollama, vLLM, LM Studio, llama.cpp server).

Задел под модель, дообученную в папке llm/. Настройки в .env:
  LOCAL_LLM_URL=http://localhost:11434/v1     # базовый URL с /v1
  LOCAL_LLM_MODEL=cqa-judge                   # имя модели на сервере
  LOCAL_LLM_API_KEY=                          # если сервер требует
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
    body = {
        "model": name,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "cqa_evaluation", "schema": schema, "strict": True}},
        "temperature": 0,
    }
    try:
        r = httpx.post(f"{base}/chat/completions", json=body, headers=headers,
                       timeout=float(os.getenv("LOCAL_LLM_TIMEOUT", "300")))
    except httpx.HTTPError as e:
        raise LLMError(f"Своя модель недоступна: {e}") from e
    if r.status_code >= 400:
        raise LLMError(f"Своя модель: HTTP {r.status_code} {r.text[:200]}")
    try:
        out = r.json()
        data = json.loads(out["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LLMOutputError(f"Своя модель вернула не JSON по схеме: {e}") from e
    u = out.get("usage") or {}
    return LLMResult(data=data, model=f"local:{name}", input_tokens=u.get("prompt_tokens", 0),
                     output_tokens=u.get("completion_tokens", 0), cost_usd=0.0, meta={"provider": "local"})
