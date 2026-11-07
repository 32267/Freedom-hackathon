"""Gold-set metrics. Missing/invalid predictions are failures, never implicit matches."""
from __future__ import annotations

from collections import defaultdict
from statistics import mean


def _f1_for_label(gold, pred, label):
    tp = sum(g == label and p == label for g, p in zip(gold, pred))
    fp = sum(g != label and p == label for g, p in zip(gold, pred))
    fn = sum(g == label and p != label for g, p in zip(gold, pred))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}


def classification_metrics(gold, pred):
    if not gold:
        return {"count": 0, "exact_agreement": None, "macro_f1": None, "labels": {}}
    labels = sorted(set(gold))
    return {
        "count": len(gold),
        "exact_agreement": sum(a == b for a, b in zip(gold, pred)) / len(gold),
        "macro_f1": mean(_f1_for_label(gold, pred, label)["f1"] for label in labels),
        "labels": {label: _f1_for_label(gold, pred, label) for label in labels},
    }


def _eval_results(prediction):
    evaluation = prediction.get("evaluation") or {}
    return evaluation.get("results", prediction.get("results", []))


def build_report(gold_records, prediction_records, checklist):
    gold_by_id = {r["conversation_id"]: r for r in gold_records}
    pred_by_id = {r.get("conversation_id"): r for r in prediction_records if r.get("conversation_id")}
    criteria = {c["id"]: c for c in checklist["criteria"]}
    by_language, totals = {}, defaultdict(lambda: {"gold": [], "pred": []})
    critical_gold, critical_pred, na_gold, na_pred = [], [], [], []
    evidence_total = evidence_valid = 0
    scores_gold, scores_pred = [], []
    criterion_score_pairs = defaultdict(lambda: [[], []])
    latency = []
    missing = failed = invalid_criteria = 0

    for cid, gold_record in gold_by_id.items():
        prediction = pred_by_id.get(cid)
        if prediction is None:
            missing += 1
            prediction = {"status": "missing", "evaluation": {"results": []}}
        if prediction.get("status") != "done":
            failed += 1
        evaluation = prediction.get("evaluation") or {}
        pred_results = {x.get("criterion_id"): x for x in _eval_results(prediction)}
        for criterion_id, gold_label in gold_record["criteria"].items():
            criterion = criteria[criterion_id]
            p = pred_results.get(criterion_id)
            answer = p.get("answer") if p else "__missing__"
            lang = gold_record["language"]
            totals[(lang, criterion_id)]["gold"].append(str(gold_label["answer"]))
            totals[(lang, criterion_id)]["pred"].append(str(answer))
            na_gold.append(gold_label["answer"] == "na")
            na_pred.append(answer == "na")
            if criterion["answer_type"] == "flag":
                critical_gold.append(gold_label["answer"] == "yes")
                critical_pred.append(answer == "yes")
            elif gold_label["answer"] != "na" and p and isinstance(p.get("raw_score"), (int, float)):
                try:
                    gold_value = float(gold_label["answer"])
                except (TypeError, ValueError):
                    gold_value = 1.0 if gold_label["answer"] == "yes" else 0.0
                criterion_score_pairs[criterion_id][0].append(gold_value)
                criterion_score_pairs[criterion_id][1].append(float(p["raw_score"]))
            if p:
                if p.get("validated") is not True:
                    invalid_criteria += 1
                for _ev in p.get("evidence", []):
                    evidence_total += 1
                    if p.get("validated") is True:
                        evidence_valid += 1
            else:
                invalid_criteria += 1
        if gold_record.get("total_score") is not None:
            value = evaluation.get("total_score")
            if isinstance(value, (int, float)):
                scores_gold.append(float(gold_record["total_score"]))
                scores_pred.append(float(value))
        if isinstance(prediction.get("latency_seconds"), (int, float)):
            latency.append(prediction["latency_seconds"])

    for (lang, criterion_id), values in totals.items():
        by_language.setdefault(lang, {})[criterion_id] = classification_metrics(values["gold"], values["pred"])
    na_metrics = classification_metrics([str(x) for x in na_gold], [str(x) for x in na_pred])
    critical_metrics = classification_metrics([str(x) for x in critical_gold], [str(x) for x in critical_pred])
    ordered_latency = sorted(latency)
    criterion_mae = {
        cid: mean(abs(a - b) for a, b in zip(pair[0], pair[1]))
        for cid, pair in criterion_score_pairs.items() if pair[0]
    }
    return {
        "metric_version": 1,
        "gold_conversations": len(gold_records),
        "predictions_received": len(pred_by_id),
        "missing_predictions": missing,
        "failed_predictions": failed,
        "invalid_or_missing_criterion_outputs": invalid_criteria,
        "by_language": by_language,
        "critical_error": critical_metrics,
        "not_applicable": na_metrics,
        "criterion_score_mae": criterion_mae,
        "total_score_mae": mean(abs(a - b) for a, b in zip(scores_gold, scores_pred)) if scores_gold else None,
        "evidence": {
            "validated_quotes": evidence_valid,
            "prediction_quotes": evidence_total,
            "validity_rate": evidence_valid / evidence_total if evidence_total else None,
            "note": "A validated flag means the existing scoring validator accepted that criterion; gold quotes are checked on input. Attribution accuracy is not independently inferred here."
        },
        "latency_seconds": {
            "count": len(ordered_latency),
            "p50": ordered_latency[(len(ordered_latency) - 1) // 2] if ordered_latency else None,
            "p95": ordered_latency[min(len(ordered_latency) - 1, int(0.95 * len(ordered_latency)))] if ordered_latency else None
        }
    }
