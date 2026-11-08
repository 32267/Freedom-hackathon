"""Публичный интерфейс оценки. Codex-2 вызывает только evaluate() и recompute().

SCORING_MODE в .env: "llm" — настоящая оценка моделью (по умолчанию), "mock" — фейковая, без ключа и затрат.
Провайдеры и число ответов для сравнения — LLM_PROVIDERS и LLM_SAMPLES (см. backend/llm/__init__.py, ensemble.py).
"""
import os

from .math import ScoringError, compute


def evaluate(dialog: dict, checklist: dict, providers: str | None = None, samples: int | None = None) -> dict:
    """Evaluation по контракту (без id). Бросает backend.llm.LLMError при сбое модели.

    providers — строка формата LLM_PROVIDERS ("claude_cli | codex_cli"), samples — сколько ответов сравнить.
    Оба необязательны: сайт передаёт их из выбранного пресета (backend.llm.registry.PRESETS), иначе берутся из .env.
    """
    if os.getenv("SCORING_MODE", "llm") == "mock":
        from .mock import evaluate as _mock
        ev = _mock(dialog, checklist)
    else:
        from .ensemble import evaluate_ensemble
        ev = evaluate_ensemble(dialog, checklist, providers=providers, samples=samples)
    ev["summary"] = summarize_dialog(dialog, providers)
    return ev


def summarize_dialog(dialog: dict, providers: str | None = None) -> dict | None:
    """Сводка для следующего обращения: причина, что сделано, открытые вопросы с цитатами, имя оператора."""
    from .summary import mock_summary, summarize
    if os.getenv("SCORING_MODE", "llm") == "mock":
        return mock_summary(dialog)
    return summarize(dialog, providers)


def recompute(evaluation: dict, checklist: dict) -> dict:
    """Пересчёт итогов после изменения ответов (апелляция). Без LLM."""
    return {**evaluation, **compute(evaluation["results"], checklist)}


__all__ = ["evaluate", "recompute", "summarize_dialog", "ScoringError"]
