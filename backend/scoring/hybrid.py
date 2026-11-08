"""Hybrid local evaluator: fast VLM first pass with criterion-scoped LM recovery.

The deadline is cooperative: no new fallback work starts after it expires. A provider
request already in flight cannot be force-cancelled by this synchronous scoring layer.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from backend.llm import LLMError, LLMOutputError
from .llm_eval import evaluate_llm
from .math import compute
from .translation import translate_explanations


def _provider(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def evaluate_hybrid(dialog: dict, checklist: dict, deadline_seconds: float | None = None) -> dict:
    """Run VLM once, then send only invalid/uncertain criteria to the LM fallback."""
    started = time.monotonic()
    budget = float(deadline_seconds if deadline_seconds is not None else os.getenv("HYBRID_DEADLINE_SECONDS", "120"))
    if budget <= 0:
        raise ValueError("HYBRID_DEADLINE_SECONDS must be positive")
    vlm_spec = _provider("HYBRID_VLM_PROVIDER", "local")
    lm_spec = _provider("HYBRID_LM_PROVIDER", "local_lm")
    if vlm_spec == lm_spec:
        raise ValueError("HYBRID_VLM_PROVIDER and HYBRID_LM_PROVIDER must be different")

    criteria = {c["id"]: c for c in checklist["criteria"]}
    errors = []
    routes = {"vlm": [], "lm_fallback": [], "needs_review": []}
    try:
        first = evaluate_llm(dialog, checklist, vlm_spec, deadline_monotonic=started + budget * 0.65)
        results = {r["criterion_id"]: dict(r) for r in first["results"]}
        usage = dict(first.get("tokens") or {})
        cost = float(first.get("cost_usd") or 0)
        models = [first.get("model")] if first.get("model") else []
    except LLMError as exc:
        errors.append(f"{vlm_spec}: {exc}")
        first = None
        results = {}
        usage = {"input": 0, "output": 0, "cache_read": 0, "calls": 0}
        cost = 0.0
        models = []

    fallback_ids = []
    fallback_reasons = {}
    for cid in criteria:
        item = results.get(cid)
        if item is None:
            fallback_ids.append(cid)
            fallback_reasons[cid] = ["VLM did not return this criterion"]
        elif item.get("validated") is not True:
            fallback_ids.append(cid)
            fallback_reasons[cid] = list(item.get("problems") or ["VLM validation failed"])
        elif item.get("insufficient"):
            fallback_ids.append(cid)
            fallback_reasons[cid] = ["VLM marked the evidence as insufficient"]
        else:
            routes["vlm"].append(cid)

    # Recover criteria individually. The LM never votes against a valid VLM answer:
    # it replaces only a criterion that failed deterministic checks or was uncertain.
    for cid in fallback_ids:
        if time.monotonic() - started >= budget:
            item = results.get(cid)
            if item is None:
                raise LLMOutputError(f"Hybrid deadline expired before any valid result for {cid}; human review required")
            if item is not None:
                item["needs_review"] = True
                item["problems"] = list(item.get("problems") or []) + ["Hybrid deadline expired before LM fallback"]
            routes["needs_review"].append(cid)
            continue
        try:
            recovered = evaluate_llm(dialog, checklist, lm_spec, criterion_ids=[cid], deadline_monotonic=started + budget)
            replacement = recovered["results"][0]
            usage = {key: usage.get(key, 0) + (recovered.get("tokens") or {}).get(key, 0)
                     for key in ("input", "output", "cache_read", "calls")}
            cost += float(recovered.get("cost_usd") or 0)
            if recovered.get("model") and recovered["model"] not in models:
                models.append(recovered["model"])
            if replacement.get("validated") is True and not replacement.get("insufficient"):
                replacement["model_route"] = "lm_fallback"
                replacement["fallback_reason"] = fallback_reasons[cid]
                results[cid] = replacement
                routes["lm_fallback"].append(cid)
            else:
                replacement["needs_review"] = True
                replacement["model_route"] = "lm_fallback"
                replacement["fallback_reason"] = fallback_reasons[cid]
                results[cid] = replacement
                routes["needs_review"].append(cid)
        except LLMError as exc:
            errors.append(f"{lm_spec}/{cid}: {exc}")
            item = results.get(cid)
            if item is None:
                raise LLMOutputError(
                    f"No valid result for {cid}; VLM and LM fallback failed. Human review required."
                )
            else:
                item["needs_review"] = True
                item["problems"] = list(item.get("problems") or []) + [f"LM fallback failed: {exc}"]
            routes["needs_review"].append(cid)

    ordered = [results[cid] for cid in criteria]
    for item in ordered:
        item.setdefault("needs_review", False)
        if item.get("criterion_id") in routes["vlm"]:
            item["model_route"] = "vlm"
    evaluation = {
        "conversation_id": dialog["conversation_id"],
        "checklist_id": checklist["id"],
        "checklist_version": checklist["version"],
        "status": "done",
        "model": ", ".join(dict.fromkeys(models)) or f"{vlm_spec} + {lm_spec}",
        "providers": [vlm_spec] + ([lm_spec] if routes["lm_fallback"] or errors else []),
        "samples": 1,
        "cost_usd": round(cost, 6),
        "tokens": usage,
        "results": ordered,
        "needs_review": bool(routes["needs_review"]) or any(r.get("needs_review") for r in ordered),
        "provider_errors": errors,
        "hybrid": {
            "vlm_provider": vlm_spec,
            "lm_provider": lm_spec,
            "deadline_seconds": budget,
            "elapsed_before_translation_seconds": round(time.monotonic() - started, 3),
            "routes": routes,
            "fallback_reasons": fallback_reasons,
        },
        **compute(ordered, checklist),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # Never invent empty explanations to satisfy the translation contract.
    if any(not str(item.get("_source_explanation") or "").strip() for item in ordered):
        raise LLMOutputError("Hybrid evaluation has criteria without a valid explanation; human review required")
    # Preserve the source-language-first contract and translate only after routing.
    evaluation = translate_explanations(evaluation, dialog, checklist, lm_spec)
    elapsed = round(time.monotonic() - started, 3)
    evaluation["hybrid"]["elapsed_seconds"] = elapsed
    evaluation["hybrid"]["deadline_exceeded"] = elapsed > budget
    if elapsed > budget:
        evaluation["needs_review"] = True
        evaluation["hybrid"]["deadline_note"] = "Evaluation exceeded its cooperative deadline; an in-flight provider call cannot be interrupted."
    return evaluation
