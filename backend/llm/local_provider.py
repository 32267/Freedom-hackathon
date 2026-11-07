"""Своя модель за OpenAI-совместимым сервером (Ollama, vLLM, LM Studio, llama.cpp server).

Задел под модель, дообученную в папке llm/. Настройки в .env:
  LOCAL_LLM_URL=http://localhost:11434/v1     # базовый URL с /v1
  LOCAL_LLM_MODEL=cqa-judge                   # имя модели на сервере
  LOCAL_LLM_API_KEY=                          # если сервер требует
  LOCAL_LLM_MAX_TOKENS=12288                  # максимум токенов ответа
  LOCAL_LLM_TIMEOUT=600                       # таймаут запроса в секундах
  LOCAL_LLM_DEBUG_DIR=                        # каталог для opt-in локальной диагностики

Ответ запрашивается по JSON-схеме (response_format json_schema); сервер должен это поддерживать.
Диагностические файлы могут содержать полный текст клиентского диалога. Они создаются
только при явно заданном LOCAL_LLM_DEBUG_DIR и остаются локальными.
"""
import json
import os
import re
import stat
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import LLMError, LLMOutputError, LLMResult


def _debug_context(user: str, schema: dict) -> dict:
    criteria = schema.get("properties", {}).get("criteria", {}).get("properties", {})
    conversation = re.search(r"^Диалог ([^ ·\n]+)", user)
    return {
        "conversation_id": conversation.group(1) if conversation else None,
        "criterion_id": next(iter(criteria)) if len(criteria) == 1 else None,
        "attempt": 2 if "Прошлый ответ по этим критериям не прошёл проверку:" in user else 1,
    }


def _capture_debug(
    *,
    debug_dir: str,
    context: dict,
    request_body: dict,
    response_body: dict | None = None,
    response_text: str | None = None,
    http_status: int | None = None,
    capture_error: str | None = None,
) -> None:
    """Write a private, opt-in request/response record; never affect evaluation."""
    try:
        directory = Path(debug_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
        stamp = datetime.now(timezone.utc)
        record = {
            "captured_at": stamp.isoformat(),
            **context,
            "request": {
                "model": request_body.get("model"),
                "messages": request_body.get("messages"),
                "response_format": request_body.get("response_format"),
                "temperature": request_body.get("temperature"),
                "max_tokens": request_body.get("max_tokens"),
            },
            "http_status": http_status,
            "response": response_body,
            "response_text": response_text,
            "capture_error": capture_error,
        }
        filename = f"{stamp.strftime('%Y%m%dT%H%M%S_%fZ')}_{uuid.uuid4().hex[:8]}.json"
        target = directory / filename
        payload = (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
    except (OSError, TypeError, ValueError) as exc:
        warnings.warn(f"Could not write local LLM diagnostic capture: {exc}", RuntimeWarning)


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
    debug_dir = os.getenv("LOCAL_LLM_DEBUG_DIR", "").strip()
    debug_context = _debug_context(user, schema) if debug_dir else None
    try:
        r = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=timeout)
    except httpx.TimeoutException as e:
        raise LLMError(f"Своя модель: таймаут после {timeout:g} с (LOCAL_LLM_TIMEOUT)") from e
    except httpx.HTTPError as e:
        raise LLMError(f"Своя модель недоступна: {e}") from e
    if r.status_code >= 400:
        if debug_dir:
            _capture_debug(debug_dir=debug_dir, context=debug_context, request_body=body,
                           response_text=r.text, http_status=r.status_code)
        raise LLMError(f"Своя модель: HTTP {r.status_code} {r.text[:200]}")

    try:
        out = r.json()
    except ValueError as e:
        if debug_dir:
            _capture_debug(debug_dir=debug_dir, context=debug_context, request_body=body,
                           response_text=r.text, http_status=r.status_code, capture_error=str(e))
        raise LLMOutputError(f"Своя модель вернула не JSON-ответ API: {e}") from e

    choice = (out.get("choices") or [{}])[0] if isinstance(out, dict) else {}
    message = choice.get("message") or {} if isinstance(choice, dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    usage = out.get("usage") or {} if isinstance(out, dict) else {}
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None

    if debug_dir:
        _capture_debug(
            debug_dir=debug_dir,
            context=debug_context,
            request_body=body,
            response_body={
                "content": content,
                "finish_reason": finish_reason,
                "usage": usage,
                "id": out.get("id") if isinstance(out, dict) else None,
                "model": out.get("model") if isinstance(out, dict) else None,
            },
            http_status=r.status_code,
        )

    try:
        data = json.loads(content)
    except (ValueError, TypeError) as e:
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
