"""Фейковая оценка той же формы, что настоящая (docs/CONTRACTS.md). Детерминированная — удобно для UI и тестов."""
import hashlib
from datetime import datetime, timezone

from .math import compute


def evaluate(dialog: dict, checklist: dict) -> dict:
    ops = [i for i, m in enumerate(dialog["transcript"]) if m["speaker"] == "operator"]
    results = []
    for k, c in enumerate(checklist["criteria"]):
        h = int(hashlib.md5(f'{dialog["conversation_id"]}{c["id"]}'.encode()).hexdigest(), 16)
        if c.get("na_allowed") and h % 7 == 0:
            answer = "na"
        elif c["answer_type"] == "binary":
            answer = "yes" if h % 3 else "no"
        else:
            answer = c["scale"]["min"] + h % (c["scale"]["max"] - c["scale"]["min"] + 1)
        idx = ops[k % len(ops)] if ops else None
        evidence = [] if answer == "na" or idx is None else [
            {"msg_index": idx, "quote": dialog["transcript"][idx]["text"][:80]}]
        results.append({
            "criterion_id": c["id"], "answer": answer,
            "raw_score": None if answer == "na" else (1 if answer == "yes" else 0) if c["answer_type"] == "binary" else answer,
            "max_score": 1 if c["answer_type"] == "binary" else c["scale"]["max"],
            "explanation": f"[MOCK] Объяснение по критерию «{c['title']}».",
            "evidence": evidence,
            "checked_range": {"from": 0, "to": len(dialog["transcript"]) - 1} if answer == "no" else None,
            "na_reason": "[MOCK] Критерий неприменим к этому диалогу." if answer == "na" else None,
            "source": "llm", "validated": True,
        })
    return {
        "conversation_id": dialog["conversation_id"],
        "checklist_id": checklist["id"], "checklist_version": checklist["version"],
        "status": "done", "model": "mock", "cost_usd": 0.0, "tokens": {"input": 0, "output": 0},
        "results": results, **compute(results, checklist),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
