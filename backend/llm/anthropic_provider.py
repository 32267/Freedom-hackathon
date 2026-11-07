import json

import anthropic

from . import LLMError, LLMOutputError, LLMResult
from .pricing import cost_usd

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=4)   # SDK сам ретраит 429/5xx/сеть
    return _client


def call_json(system: str, user: str, schema: dict, model: str, effort: str) -> LLMResult:
    try:
        resp = _get_client().beta.messages.create(
            model=model,
            max_tokens=16000,
            # Чек-лист в system стабилен между диалогами → кэшируем префикс.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # Если классификатор безопасности откажет, API сам повторит на рекомендованной модели.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise LLMError("Нет/неверный ANTHROPIC_API_KEY (или выполните `ant auth login`)") from e
    except anthropic.BadRequestError as e:
        raise LLMError(f"Запрос отклонён API: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Ошибка API {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Нет соединения с API") from e

    if resp.stop_reason == "refusal":
        raise LLMError("Модель отказалась отвечать (refusal)")
    if resp.stop_reason == "max_tokens":
        raise LLMOutputError("Ответ обрезан по max_tokens")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if text is None:
        raise LLMOutputError("В ответе нет текстового блока")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"Невалидный JSON от модели: {e}") from e

    u = resp.usage
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
    served = resp.model or model
    return LLMResult(
        data=data, model=served,
        input_tokens=u.input_tokens + cache_read + cache_write, output_tokens=u.output_tokens,
        cache_read_tokens=cache_read,
        cost_usd=cost_usd(served, u.input_tokens, u.output_tokens, cache_read, cache_write),
        meta={"request_id": getattr(resp, "_request_id", None)},
    )
