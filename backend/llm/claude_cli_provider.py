"""Оценка через локальный Claude Code (`claude -p`) — расходует подписку того, кто запустил, а не API-ключ.

Только для локальной разработки и подбора промпта: лимиты подписки, ~5–30 с на вызов,
не подходит как бэкенд для чужих пользователей. Для демо/README — провайдер anthropic.
"""
import json
import os
import shutil
import subprocess

from . import LLMError, LLMOutputError, LLMResult


def call_json(system: str, user: str, schema: dict, model: str, effort: str, profile: str | None = None) -> LLMResult:
    """profile — папка CLAUDE_CONFIG_DIR другого залогиненного аккаунта Claude Code (None — аккаунт по умолчанию)."""
    exe = shutil.which(os.getenv("CLAUDE_CLI", "claude"))
    if not exe:
        raise LLMError("Не найден CLI `claude` (Claude Code). Установите или используйте LLM_PROVIDER=anthropic")
    cmd = [exe, "-p", "--output-format", "json", "--json-schema", json.dumps(schema, ensure_ascii=False),
           "--system-prompt", system, "--tools", "", "--strict-mcp-config", "--setting-sources", "",
           "--no-session-persistence", "--model", model, "--effort", effort]
    try:
        env = {**os.environ, "CLAUDE_CONFIG_DIR": os.path.expanduser(profile)} if profile else None
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, env=env,
                              timeout=int(os.getenv("CLAUDE_CLI_TIMEOUT", "300")))
    except subprocess.TimeoutExpired as e:
        raise LLMError("claude -p: таймаут") from e
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"claude -p вернул не JSON (код {proc.returncode}): {proc.stderr[-300:]}") from e
    if out.get("is_error") or out.get("subtype") != "success":
        msg = f"claude -p: {out.get('subtype')} {out.get('api_error_status') or ''} {str(out.get('result'))[:300]}"
        # Сбой конкретного ответа (не уложился в схему, исчерпал ходы) — не повод считать Claude недоступным.
        if str(out.get("subtype", "")).startswith(("error_max_structured_output", "error_max_turns", "error_during_execution")):
            raise LLMOutputError(msg)
        raise LLMError(msg)
    data = out.get("structured_output")
    if data is None:
        try:
            data = json.loads(out.get("result") or "")
        except json.JSONDecodeError as e:
            raise LLMOutputError("claude -p: нет structured_output") from e
    u = out.get("usage", {})
    cache_read = u.get("cache_read_input_tokens", 0)
    return LLMResult(
        data=data, model=next(iter(out.get("modelUsage", {})), model),
        input_tokens=u.get("input_tokens", 0) + cache_read + u.get("cache_creation_input_tokens", 0),
        output_tokens=u.get("output_tokens", 0), cache_read_tokens=cache_read,
        cost_usd=float(out.get("total_cost_usd") or 0.0),   # эквивалент по прайсу API; по подписке не списывается
        meta={"provider": "claude_cli", "profile": profile, "duration_ms": out.get("duration_ms")},
    )
