"""Слой LLM: один вызов → JSON по схеме + токены и стоимость.

Провайдеры (spec в LLM_PROVIDERS):
  claude_cli            — локальный Claude Code по подписке (аккаунт по умолчанию)
  claude_cli@<папка>    — другой аккаунт Claude Code (папка CLAUDE_CONFIG_DIR, где выполнен `claude` → /login)
  codex_cli             — локальный Codex CLI по подписке ChatGPT
  anthropic             — Claude API по ANTHROPIC_API_KEY (для демо и честной стоимости в README)
  local                 — своя модель за OpenAI-совместимым сервером (Ollama / vLLM / LM Studio), LOCAL_LLM_URL;
                          сюда подключится модель, дообученная в папке llm/

LLM_PROVIDERS — уровни через «|», внутри уровня — через запятую:
  "claude_cli,claude_cli@~/.claude-team | codex_cli"  → сначала Claude-аккаунты, Codex — только если Claude не отвечает.
"""
import os
import threading
import time
from dataclasses import dataclass, field

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
DEAD_FOR_SEC = 120          # провайдер, упавший по лимиту/логину, не дёргаем 2 минуты
_dead: dict[str, float] = {}


class LLMError(RuntimeError):
    """Провайдер недоступен (нет CLI, логина, лимит, сеть) — его временно исключаем."""


class LLMOutputError(LLMError):
    """Провайдер ответил, но ответ негодный — провайдер не исключаем."""


@dataclass
class LLMResult:
    data: dict
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    meta: dict = field(default_factory=dict)
    provider: str = ""


def provider_tiers(raw: str | None = None) -> list[list[str]]:
    """raw — строка вида "claude_cli | codex_cli"; без неё берётся LLM_PROVIDERS из .env."""
    raw = (raw or "").strip() or os.getenv("LLM_PROVIDERS", "").strip() or os.getenv("LLM_PROVIDER", "").strip() or "anthropic"
    return [[s.strip() for s in tier.split(",") if s.strip()] for tier in raw.split("|") if tier.strip()]


def is_alive(spec: str) -> bool:
    return _dead.get(spec, 0) < time.monotonic()


def mark_dead(spec: str) -> None:
    _dead[spec] = time.monotonic() + DEAD_FOR_SEC


_slots = threading.BoundedSemaphore(max(1, int(os.getenv("LLM_MAX_CONCURRENCY", "8"))))


def call_json(system: str, user: str, schema: dict, spec: str | None = None) -> LLMResult:
    """Не больше LLM_MAX_CONCURRENCY одновременных вызовов на весь сервер (CLI-провайдеры — отдельные процессы)."""
    with _slots:
        return _call_json(system, user, schema, spec)


def _call_json(system: str, user: str, schema: dict, spec: str | None = None) -> LLMResult:
    spec = spec or provider_tiers()[0][0]
    kind, _, profile = spec.partition("@")
    model = os.getenv("LLM_MODEL", "").strip() or DEFAULT_CLAUDE_MODEL
    effort = os.getenv("LLM_EFFORT", "medium").strip() or "medium"
    if kind == "anthropic":
        from .anthropic_provider import call_json as impl
        res = impl(system=system, user=user, schema=schema, model=model, effort=effort)
    elif kind == "claude_cli":
        from .claude_cli_provider import call_json as impl
        res = impl(system=system, user=user, schema=schema, model=model, effort=effort, profile=profile or None)
    elif kind == "codex_cli":
        from .codex_cli_provider import call_json as impl
        res = impl(system=system, user=user, schema=schema, model=model, effort=effort)
    elif kind == "local":
        from .local_provider import call_json as impl
        res = impl(system=system, user=user, schema=schema, model=model, effort=effort)
    else:
        raise LLMError(f"Неизвестный провайдер {spec!r} (есть: anthropic, claude_cli[@папка], codex_cli, local)")
    res.provider = spec
    return res
