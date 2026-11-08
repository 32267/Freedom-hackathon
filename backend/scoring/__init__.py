"""Публичный интерфейс оценки.

Оценка чек-листа и сводка для следующего обращения — независимые операции.
Пакетная обработка создаёт сводки отдельной задачей через summaries_only.
"""
import os

from .math import ScoringError, compute


def evaluate(dialog: dict, checklist: dict, providers: str | None = None, samples: int | None = None,
             include_summary: bool = False) -> dict:
    """Оценка по контракту. Сводка — отдельная операция, если include_summary=True."""
    if os.getenv("SCORING_MODE", "llm") == "mock":
        from .mock import evaluate as _mock
        ev = _mock(dialog, checklist)
        if include_summary:
            ev["summary"] = summarize_dialog(dialog, providers)
        return ev
    from concurrent.futures import ThreadPoolExecutor

    from .ensemble import evaluate_ensemble
    with ThreadPoolExecutor(max_workers=1) as pool:          # сводка (если нужна) — параллельно с оценкой
        summary = pool.submit(summarize_dialog, dialog, providers) if include_summary else None
        ev = evaluate_ensemble(dialog, checklist, providers=providers, samples=samples)
        if summary is not None:
            ev["summary"] = summary.result()
    return ev


def summarize_dialog(dialog: dict, providers: str | None = None) -> dict | None:
    """Сводка разговора; вызывается отдельно от основной оценки."""
    from .summary import mock_summary, summarize
    if os.getenv("SCORING_MODE", "llm") == "mock":
        return mock_summary(dialog)
    return summarize(dialog, providers)


def recompute(evaluation: dict, checklist: dict) -> dict:
    """Пересчёт итогов после изменения ответов (апелляция). Без LLM."""
    return {**evaluation, **compute(evaluation["results"], checklist)}


__all__ = ["evaluate", "recompute", "summarize_dialog", "ScoringError"]
