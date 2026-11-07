"""Итоговый балл по «Порядку расчёта» чек-листа (стр. 2 PDF, см. docs/CHECKLIST.md). Без LLM.

1. N/A только где разрешён.          2. Да = полный вес, Нет = 0, шкала — одна из ступеней.
3. Шкала → пропорционально весу (верхняя ступень = полный вес).
4. N/A исключаются, их вес перераспределяется пропорционально, максимум = 100.
5. Итог округляется до двух знаков; нет применимых критериев с весом → итог не рассчитывается.
   Грубые ошибки (answer_type "flag") в балл не входят, отмечаются отдельно.
"""
from decimal import ROUND_HALF_UP, Decimal


class ScoringError(ValueError):
    pass


def _round(value: float, rule: str) -> float:
    digits = int(rule.rsplit("_", 1)[-1]) if rule.startswith("half_up_") else 2
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def normalize(answer, criterion: dict):
    """Доля от веса 0..1; None — N/A. Флаги сюда не попадают."""
    if answer == "na":
        if not criterion.get("na_allowed"):
            raise ScoringError(f'N/A не разрешён для «{criterion["id"]}»')
        return None
    if criterion["answer_type"] == "binary":
        if answer not in ("yes", "no"):
            raise ScoringError(f'«{criterion["id"]}»: ожидается yes/no/na, получено {answer!r}')
        return 1.0 if answer == "yes" else 0.0
    scale = criterion["scale"]
    steps = [s["value"] for s in scale.get("steps", [])]
    value = float(answer)
    if steps and value not in steps:
        raise ScoringError(f'«{criterion["id"]}»: {answer} не из ступеней {steps}')
    return (value - scale["min"]) / (scale["max"] - scale["min"])


def _scored(criteria_answers):
    return [(c, normalize(a, c)) for c, a in criteria_answers if c["answer_type"] != "flag" and c["weight"] > 0]


def _weighted(pairs):
    applicable = [(c, n) for c, n in pairs if n is not None]
    total_w = sum(c["weight"] for c, _ in applicable)
    if not applicable or total_w == 0:
        return None, {}
    eff = {c["id"]: c["weight"] / total_w * 100 for c, _ in applicable}
    return sum(n * eff[c["id"]] for c, n in applicable), eff


def compute(results: list[dict], checklist: dict) -> dict:
    """Заполняет weight / effective_weight / weighted_score в results и возвращает итоги оценки."""
    by_id = {c["id"]: c for c in checklist["criteria"]}
    rule = checklist.get("rounding", "half_up_2")
    missing = set(by_id) - {r["criterion_id"] for r in results}
    if missing:
        raise ScoringError(f"Нет ответа по критериям: {sorted(missing)}")

    answers = [(by_id[r["criterion_id"]], r["answer"]) for r in results]
    pairs = _scored(answers)
    total, eff = _weighted(pairs)
    norm = {c["id"]: n for c, n in pairs}

    critical_flags = []
    for r in results:
        c = by_id[r["criterion_id"]]
        r["weight"] = c["weight"]
        if c["answer_type"] == "flag":
            r["effective_weight"] = r["weighted_score"] = 0.0
            if r["answer"] == "yes":
                critical_flags.extend(r.get("flags") or [c["id"]])
            continue
        w = eff.get(c["id"], 0.0)
        r["effective_weight"] = _round(w, rule)
        r["weighted_score"] = _round((norm[c["id"]] or 0.0) * w, rule)

    sections = []
    for s in checklist.get("sections", []):
        score, _ = _weighted([(c, n) for c, n in pairs if c.get("section_id") == s["id"]])
        if any(c.get("section_id") == s["id"] for c, _ in pairs):
            sections.append({"section_id": s["id"], "score": None if score is None else _round(score, rule)})

    critical = bool(critical_flags)
    if total is not None and critical and checklist.get("critical_policy") == "zero_total":
        total = 0.0
    return {
        "total_score": None if total is None else _round(total, rule),
        "critical_error": critical,
        "critical_flags": critical_flags,
        "section_scores": sections,
    }
