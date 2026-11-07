"""Публичный интерфейс оценки. Codex-2 вызывает только evaluate() и recompute()."""
import os

from .math import compute


def evaluate(dialog: dict, checklist: dict) -> dict:
    if os.getenv("SCORING_MODE", "mock") == "mock":
        from .mock import evaluate as _mock
        return _mock(dialog, checklist)
    raise NotImplementedError("LLM-оценка — задачи S4–S6")


def recompute(evaluation: dict, checklist: dict) -> dict:
    """Пересчёт итогов после изменения ответов (апелляция). Без LLM."""
    return {**evaluation, **compute(evaluation["results"], checklist)}
