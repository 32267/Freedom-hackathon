"""Один «ответ» одного провайдера: отдельный вызов на каждый критерий → проверка → повтор проблемных критериев.
Сравнение нескольких ответов и выбор провайдеров — в ensemble.py."""
from datetime import datetime, timezone
import time

from backend.llm import LLMError, LLMOutputError, call_json

from .math import compute
from .prompt import build_schema, build_system, build_user
from .validate import check_criterion

MAX_RETRIES = 1
CRITERIA_PER_REQUEST = 1


def _usage(acc: dict, res) -> None:
    acc["input"] += res.input_tokens
    acc["output"] += res.output_tokens
    acc["cache_read"] += res.cache_read_tokens
    acc["cost"] += res.cost_usd
    acc["calls"] += 1
    acc["model"] = res.model
    acc["provider"] = res.provider


def evaluate_llm(dialog: dict, checklist: dict, spec: str | None = None, criterion_ids: list[str] | None = None, deadline_monotonic: float | None = None) -> dict:
    all_criteria = {c["id"]: c for c in checklist["criteria"]}
    selected = list(criterion_ids) if criterion_ids is not None else list(all_criteria)
    unknown = set(selected) - set(all_criteria)
    if unknown:
        raise LLMOutputError(f"Неизвестные критерии: {sorted(unknown)}")
    by_id = {cid: all_criteria[cid] for cid in selected}
    transcript = dialog["transcript"]
    usage = {"input": 0, "output": 0, "cache_read": 0, "cost": 0.0, "calls": 0, "model": None, "provider": spec}

    criterion_ids = list(by_id)
    raw = {}
    for start in range(0, len(criterion_ids), CRITERIA_PER_REQUEST):
        group = criterion_ids[start:start + CRITERIA_PER_REQUEST]
        timeout_override = None
        if deadline_monotonic is not None:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise LLMError("Hybrid deadline expired before model request")
            requests_left = max(1, (len(criterion_ids) - start + CRITERIA_PER_REQUEST - 1) // CRITERIA_PER_REQUEST)
            timeout_override = max(0.5, remaining / requests_left)
        system = build_system(checklist, only=group)
        user = build_user(dialog, only=group)
        schema = build_schema(checklist, only=group)
        res = call_json(system, user, schema, spec, timeout_override=timeout_override)
        _usage(usage, res)
        raw.update(res.data.get("criteria", {}))

    answers, problems = {}, {}
    for cid, c in by_id.items():
        if cid not in raw:
            problems[cid] = ["нет ответа по критерию"]
            continue
        answers[cid], probs = check_criterion(raw[cid], c, transcript, dialog.get("channel"), dialog.get("language", "RU"))
        if probs:
            problems[cid] = probs

    for _ in range(MAX_RETRIES):
        if not problems:
            break
        # Keep retries criterion-scoped too: a combined retry can recreate the
        # oversized response that per-criterion initial calls are designed to avoid.
        for cid in list(problems):
            feedback = (
                f"- {cid}: {'; '.join(problems[cid])}\\n"
                "Начни оценку этого критерия заново по всему транскрипту; не повторяй прежний answer автоматически. "
                "Сначала проверь na_rule и keep_if. Если условие N/A выполнено, верни answer=na и непустые explanation/na_reason. "
                "Если выбираешь yes, приложи точную подтверждающую цитату и объяснение на языке диалога. "
                "Не используй сведения клиента или бота как доказательство действия оператора."
            )
            try:
                retry_system = build_system(checklist, only=[cid])
                retry_timeout = None
                if deadline_monotonic is not None:
                    retry_timeout = deadline_monotonic - time.monotonic()
                    if retry_timeout <= 0:
                        raise LLMError("Hybrid deadline expired before criterion retry")
                res = call_json(
                    retry_system,
                    build_user(dialog, only=[cid], feedback=feedback),
                    build_schema(checklist, only=[cid]),
                    spec,
                    timeout_override=retry_timeout,
                )
            except LLMError:
                continue
            _usage(usage, res)
            retry_raw = res.data.get("criteria", {})
            if cid not in retry_raw:
                continue
            fixed, probs = check_criterion(retry_raw[cid], by_id[cid], transcript, dialog.get("channel"), dialog.get("language", "RU"))
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
            "_source_language": a["_source_language"],
            "_source_explanation": a["_source_explanation"],
            "_source_na_reason": a["_source_na_reason"],
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
        **(compute(results, checklist) if len(results) == len(checklist["criteria"]) else {}),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
