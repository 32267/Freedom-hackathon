"""Несколько ответов → один результат.

- Провайдеры берутся по уровням из LLM_PROVIDERS: сначала Claude-аккаунты; следующий уровень (Codex)
  подключается, только если на текущем не набралось LLM_SAMPLES успешных ответов.
- Ответы собираются параллельно, каждый проходит свою проверку цитат (llm_eval).
- По каждому критерию — голосование: большинство (да/нет/N/A/флаг) или нижняя медиана (шкала).
  При ничьей побеждает ответ первого провайдера (Claude). Расхождение → needs_review для проверяющего.
"""
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from backend.llm import LLMError, LLMOutputError, is_alive, mark_dead, provider_tiers

from .llm_eval import evaluate_llm
from .math import compute


def _samples_wanted(override: int | None = None) -> int:
    if override:
        return max(1, int(override))
    try:
        return max(1, int(os.getenv("LLM_SAMPLES", "1")))
    except ValueError:
        return 1


def _collect(dialog: dict, checklist: dict, n: int, providers: str | None = None) -> tuple[list[dict], list[str]]:
    samples, errors = [], []
    for tier in provider_tiers(providers):
        alive = [s for s in tier if is_alive(s)]
        attempts = 0
        while alive and len(samples) < n and attempts < n + len(tier):
            need = n - len(samples)
            batch = [alive[(len(samples) + i) % len(alive)] for i in range(need)]   # по кругу внутри уровня
            attempts += need
            with ThreadPoolExecutor(max_workers=need) as pool:
                futures = {pool.submit(evaluate_llm, dialog, checklist, spec): spec for spec in batch}
            for fut, spec in futures.items():
                try:
                    samples.append(fut.result())
                except LLMError as e:
                    errors.append(f"{spec}: {e}")
                    if not isinstance(e, LLMOutputError):
                        mark_dead(spec)
                        if spec in alive:
                            alive.remove(spec)
        if len(samples) >= n:
            break
    return samples, errors


def _vote(criterion: dict, results: list[dict]) -> tuple[object, float]:
    answers = [r["answer"] for r in results]
    na = answers.count("na")
    if criterion["answer_type"] == "scale" and na * 2 <= len(answers):
        nums = sorted(a for a in answers if a != "na")
        chosen = nums[(len(nums) - 1) // 2]                      # нижняя медиана — реальная ступень
    else:
        counts = Counter(answers)
        top = max(counts.values())
        chosen = next(a for a in answers if counts[a] == top)    # ничья → первый провайдер
    return chosen, answers.count(chosen) / len(answers)


def merge(samples: list[dict], checklist: dict) -> dict:
    by_id = {c["id"]: c for c in checklist["criteria"]}
    results = []
    for cid, c in by_id.items():
        per = [next(r for r in s["results"] if r["criterion_id"] == cid) for s in samples]
        chosen, agreement = _vote(c, per)
        same = [r for r in per if r["answer"] == chosen]
        base = next((r for r in same if r.get("validated")), same[0])
        merged = {k: v for k, v in base.items() if k not in ("weight", "effective_weight", "weighted_score")}
        if c["answer_type"] == "flag" and chosen == "yes":
            merged["flags"] = sorted({f for r in same for f in r.get("flags", [])})
        merged["votes"] = [{"provider": s.get("provider"), "model": s.get("model"), "answer": r["answer"]}
                           for s, r in zip(samples, per)]
        merged["agreement"] = round(agreement, 2)
        merged["insufficient"] = any(r.get("insufficient") for r in same)
        merged["needs_review"] = agreement < 1.0 or merged["insufficient"]
        results.append(merged)

    first = samples[0]
    return {
        "conversation_id": first["conversation_id"],
        "checklist_id": first["checklist_id"], "checklist_version": first["checklist_version"],
        "status": "done",
        "model": ", ".join(dict.fromkeys(s["model"] for s in samples)),
        "providers": [s.get("provider") for s in samples],
        "samples": len(samples),
        "cost_usd": round(sum(s["cost_usd"] for s in samples), 6),
        "tokens": {k: sum(s["tokens"].get(k, 0) for s in samples) for k in ("input", "output", "cache_read", "calls")},
        "results": results,
        "needs_review": any(r["needs_review"] for r in results),
        **compute(results, checklist),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def evaluate_ensemble(dialog: dict, checklist: dict, providers: str | None = None, samples: int | None = None) -> dict:
    """providers/samples — выбор на сайте (пресет из backend.llm.registry); None — из .env."""
    answers, errors = _collect(dialog, checklist, _samples_wanted(samples), providers)
    if not answers:
        raise LLMError("Ни один провайдер не ответил: " + "; ".join(errors))
    ev = merge(answers, checklist)
    if errors:
        ev["provider_errors"] = errors
    return ev
