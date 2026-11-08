"""Один ответ провайдера: пакет критериев → проверка → точечный повтор проблемных критериев."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from backend.llm import LLMError, LLMOutputError, call_json

from .math import compute
from .prompt import build_schema, build_system, build_user
from .validate import check_criterion

MAX_RETRIES = 1
# Two criteria per request halves the initial call count while keeping each
# structured response small enough for local 4B models and 3072-token limits.
CRITERIA_PER_REQUEST = 2


def _usage(acc: dict, res) -> None:
    acc["input"] += res.input_tokens
    acc["output"] += res.output_tokens
    acc["cache_read"] += res.cache_read_tokens
    acc["cost"] += res.cost_usd
    acc["calls"] += 1
    acc["model"] = res.model
    acc["provider"] = res.provider


def evaluate_llm(dialog: dict, checklist: dict, spec: str | None = None) -> dict:
    by_id = {c["id"]: c for c in checklist["criteria"]}
    transcript = dialog["transcript"]
    usage = {"input": 0, "output": 0, "cache_read": 0, "cost": 0.0, "calls": 0, "model": None, "provider": spec}

    criterion_ids = list(by_id)
    groups = [criterion_ids[i:i + CRITERIA_PER_REQUEST] for i in range(0, len(criterion_ids), CRITERIA_PER_REQUEST)]

    def ask(group):
        return call_json(build_system(checklist, only=group), build_user(dialog, only=group),
                         build_schema(checklist, only=group), spec)

    # пакеты критериев независимы → запрашиваем параллельно (общий лимит одновременных вызовов — в backend.llm)
    with ThreadPoolExecutor(max_workers=max(1, min(len(groups), int(os.getenv("CRITERIA_PARALLEL", "8"))))) as pool:
        responses = list(pool.map(ask, groups))
    raw = {}
    for res in responses:
        _usage(usage, res)
        raw.update(res.data.get("criteria", {}))

    answers, problems = {}, {}
    for cid, c in by_id.items():
        if cid not in raw:
            problems[cid] = ["нет ответа по критерию"]
            continue
        answers[cid], probs = check_criterion(raw[cid], c, transcript, dialog.get("channel"))
        if probs:
            problems[cid] = probs

    for _ in range(MAX_RETRIES):
        if not problems:
            break
        # Retry only the failed criterion, not its original batch.
        for cid in list(problems):
            feedback = f"- {cid}: {'; '.join(problems[cid])}"
            try:
                res = call_json(build_system(checklist, only=[cid]),
                                build_user(dialog, only=[cid], feedback=feedback),
                                build_schema(checklist, only=[cid]), spec)
            except LLMError:
                continue
            _usage(usage, res)
            retry_raw = res.data.get("criteria", {})
            if cid not in retry_raw:
                continue
            fixed, probs = check_criterion(retry_raw[cid], by_id[cid], transcript, dialog.get("channel"))
            if not probs or cid not in answers:
                answers[cid] = fixed
            if probs:
                problems[cid] = probs
            else:
                problems.pop(cid, None)

    results = []
    for cid, c in by_id.items():
        a = answers.get(cid)
        if a is None:
            raise LLMOutputError(f"Модель не дала ответа по критерию {cid}")
        binary = c["answer_type"] == "binary"
        results.append({
            "criterion_id": cid,
            "answer": a["answer"],
            "raw_score": None if a["answer"] == "na" or c["answer_type"] == "flag"
            else (1 if a["answer"] == "yes" else 0) if binary else a["answer"],
            "max_score": None if c["answer_type"] == "flag" else 1 if binary else c["scale"]["max"],
            "explanation": a["explanation"],
            "explanations": a["explanations"],
            "evidence": a["evidence"],
            "checked_range": a["checked_range"],
            "na_reason": a["na_reason"],
            "na_reasons": a["na_reasons"],
            "flags": a["flags"],
            "insufficient": a.get("insufficient", False),
            "source": "llm",
            "validated": cid not in problems,
            "problems": problems.get(cid, []),
        })

    return {
        "conversation_id": dialog["conversation_id"],
        "checklist_id": checklist["id"], "checklist_version": checklist["version"],
        "status": "done",
        "model": usage["model"],
        "provider": usage["provider"],
        "cost_usd": round(usage["cost"], 6),
        "tokens": {"input": usage["input"], "output": usage["output"], "cache_read": usage["cache_read"],
                   "calls": usage["calls"]},
        "results": results,
        **compute(results, checklist),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
