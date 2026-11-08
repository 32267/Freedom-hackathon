"""Какие оценщики есть и доступны — для сайта (выбор «Claude / Codex / сравнить» и подписи к голосам)."""
import os
import shutil

from . import is_alive, provider_tiers

LABELS = {
    "claude_cli": ("Claude (подписка)", "subscription"),
    "codex_cli": ("Codex (подписка ChatGPT)", "subscription"),
    "anthropic": ("Claude API", "api"),
    "local": ("Своя модель", "local"),
}

# Готовые варианты для выпадающего списка на сайте; providers — строка в формате LLM_PROVIDERS.
PRESETS = [
    {"id": "default", "label": "Как в настройках", "providers": None, "samples": None},
    {"id": "claude", "label": "Только Claude", "providers": "claude_cli", "samples": 1},
    {"id": "codex", "label": "Только Codex", "providers": "codex_cli", "samples": 1},
    {"id": "compare", "label": "Claude + Codex — сравнить", "providers": "claude_cli, codex_cli", "samples": 2},
    {"id": "claude_x3", "label": "Claude ×3 — голосование", "providers": "claude_cli | codex_cli", "samples": 3},
    {"id": "local", "label": "Своя модель (VLM)", "providers": "local", "samples": 1},
    {"id": "hybrid", "label": "Гибрид: VLM + LM fallback", "providers": "hybrid", "samples": 1},
]


def _availability(spec: str) -> tuple[bool, str]:
    kind, _, profile = spec.partition("@")
    if kind == "claude_cli":
        if not shutil.which(os.getenv("CLAUDE_CLI", "claude")):
            return False, "не установлен Claude Code"
        if profile and not os.path.isdir(os.path.expanduser(profile)):
            return False, f"нет папки аккаунта {profile}"
    elif kind == "codex_cli" and not shutil.which(os.getenv("CODEX_CLI", "codex")):
        return False, "не установлен Codex CLI"
    elif kind == "anthropic" and not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return False, "нет ANTHROPIC_API_KEY"
    elif kind == "local" and not os.getenv("LOCAL_LLM_URL", "").strip():
        return False, "своя модель ещё не подключена (LOCAL_LLM_URL)"
    elif kind not in LABELS:
        return False, "неизвестный провайдер"
    if not is_alive(spec):
        return False, "временно недоступен (лимит или ошибка входа)"
    return True, ""


def list_providers() -> dict:
    """Ответ для GET /api/llm/providers."""
    configured = [s for tier in provider_tiers() for s in tier]
    specs = list(dict.fromkeys(configured + ["claude_cli", "codex_cli", "anthropic", "local"]))
    providers = []
    for spec in specs:
        kind, _, profile = spec.partition("@")
        label, billing = LABELS.get(kind, (kind, "unknown"))
        ok, reason = _availability(spec)
        providers.append({"id": spec, "label": label + (f" · {profile}" if profile else ""), "kind": kind,
                          "billing": billing, "available": ok, "reason": reason or None,
                          "configured": spec in configured})
    return {
        "providers": providers,
        "presets": PRESETS,
        "default": {"providers": os.getenv("LLM_PROVIDERS", "") or None, "samples": int(os.getenv("LLM_SAMPLES", "1") or 1)},
    }
