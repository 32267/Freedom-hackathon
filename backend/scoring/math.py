"""Итоговый балл по формуле из docs/CONTRACTS.md. Без LLM — используется и после апелляции."""
from decimal import ROUND_HALF_UP, Decimal


def _round(value: float, rule: str) -> float:
    digits = int(rule.rsplit("_", 1)[-1]) if rule.startswith("half_up_") else 1
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def normalize(answer, criterion: dict):
    """0..1 или None для N/A."""
    if answer == "na":
        return None
    if criterion["answer_type"] == "binary":
        return 1.0 if answer == "yes" else 0.0
    lo, hi = criterion["scale"]["min"], criterion["scale"]["max"]
    return (float(answer) - lo) / (hi - lo)


def _weighted(items: list[tuple[dict, float | None]]) -> tuple[float | None, dict]:
    applicable = [(c, n) for c, n in items if n is not None]
    total_w = sum(c["weight"] for c, _ in applicable)
    if not applicable or total_w == 0:
        return None, {}
    eff = {c["id"]: c["weight"] / total_w * 100 for c, _ in applicable}
    return sum(n * eff[c["id"]] for c, n in applicable), eff


def compute(results: list[dict], checklist: dict) -> dict:
    """Заполняет effective_weight / weighted_score в results и возвращает итоги."""
    by_id = {c["id"]: c for c in checklist["criteria"]}
    rule = checklist.get("rounding", "half_up_1")
    pairs = [(by_id[r["criterion_id"]], normalize(r["answer"], by_id[r["criterion_id"]])) for r in results]

    total, eff = _weighted(pairs)
    critical = False
    for r, (c, n) in zip(results, pairs):
        r["weight"] = c["weight"]
        r["effective_weight"] = _round(eff.get(c["id"], 0.0), rule)
        r["weighted_score"] = _round((n or 0.0) * eff.get(c["id"], 0.0), rule)
        if c.get("is_critical") and n is not None and n < 1.0 and c["answer_type"] == "binary":
            critical = True
        if c.get("is_critical") and n is not None and c["answer_type"] == "scale":
            threshold = c.get("critical_below")
            if threshold is not None and float(r["answer"]) < threshold:
                critical = True

    sections = []
    for s in checklist.get("sections", []):
        sec_pairs = [(c, n) for c, n in pairs if c.get("section_id") == s["id"]]
        score, _ = _weighted(sec_pairs)
        sections.append({"section_id": s["id"], "score": None if score is None else _round(score, rule)})

    if total is not None and critical and checklist.get("critical_policy") == "zero_total":
        total = 0.0
    return {
        "total_score": None if total is None else _round(total, rule),
        "critical_error": critical,
        "section_scores": sections,
    }
