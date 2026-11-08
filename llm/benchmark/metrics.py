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
    critical_positive_gold, critical_positive_pred = [], []
    hybrid_counts = {"vlm_accepted_criteria": 0, "lm_fallback_criteria": 0, "needs_review_criteria": 0,
                     "conversations": 0, "deadline_exceeded": 0}
    gold_evidence_count = gold_evidence_matched = 0
    completed_under_120 = 0

    for cid, gold_record in gold_by_id.items():
        prediction = pred_by_id.get(cid)
        if prediction is None:
            missing += 1
            prediction = {"status": "missing", "evaluation": {"results": []}}
        if prediction.get("status") != "done":
            failed += 1
        evaluation = prediction.get("evaluation") or {}
        hybrid = evaluation.get("hybrid") or {}
        if hybrid:
            hybrid_counts["conversations"] += 1
            hybrid_counts["deadline_exceeded"] += int(bool(hybrid.get("deadline_exceeded")))
            routes = hybrid.get("routes") or {}
            hybrid_counts["vlm_accepted_criteria"] += len(routes.get("vlm", []))
            hybrid_counts["lm_fallback_criteria"] += len(routes.get("lm_fallback", []))
            hybrid_counts["needs_review_criteria"] += len(routes.get("needs_review", []))
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
                critical_positive_gold.append(gold_label["answer"] == "yes")
                critical_positive_pred.append(answer == "yes")
            elif gold_label["answer"] != "na" and p and isinstance(p.get("raw_score"), (int, float)):
                try:
                    gold_value = float(gold_label["answer"])
                except (TypeError, ValueError):
                    gold_value = 1.0 if gold_label["answer"] == "yes" else 0.0
                criterion_score_pairs[criterion_id][0].append(gold_value)
                criterion_score_pairs[criterion_id][1].append(float(p["raw_score"]))
            if p:
                gold_items = gold_label.get("evidence", [])
                pred_items = p.get("evidence", [])
                for expected in gold_items:
                    gold_evidence_count += 1
                    if any(actual.get("msg_index") == expected.get("msg_index") and
                           actual.get("quote") == expected.get("quote") for actual in pred_items):
                        gold_evidence_matched += 1
                if p.get("validated") is not True:
                    invalid_criteria += 1
                for _ev in p.get("evidence", []):
                    evidence_total += 1
                    if p.get("validated") is True:
                        evidence_valid += 1
            else:
                invalid_criteria += 1
                gold_evidence_count += len(gold_label.get("evidence", []))
        if gold_record.get("total_score") is not None:
            value = evaluation.get("total_score")
            if isinstance(value, (int, float)):
                scores_gold.append(float(gold_record["total_score"]))
                scores_pred.append(float(value))
        if isinstance(prediction.get("latency_seconds"), (int, float)):
            latency.append(prediction["latency_seconds"])
            if prediction.get("status") == "done" and prediction["latency_seconds"] <= 120:
                completed_under_120 += 1

    for (lang, criterion_id), values in totals.items():
        by_language.setdefault(lang, {})[criterion_id] = classification_metrics(values["gold"], values["pred"])
    na_metrics = classification_metrics([str(x) for x in na_gold], [str(x) for x in na_pred])
    critical_metrics = classification_metrics([str(x) for x in critical_gold], [str(x) for x in critical_pred])
    critical_recall = (sum(g and p for g, p in zip(critical_positive_gold, critical_positive_pred)) /
                       sum(critical_positive_gold)) if any(critical_positive_gold) else None
    language_summary = {
        lang: {
            "criterion_macro_f1": mean(item["macro_f1"] for item in values.values() if item["macro_f1"] is not None)
                if any(item["macro_f1"] is not None for item in values.values()) else None,
            "criterion_mean_exact_agreement": mean(item["exact_agreement"] for item in values.values()
                if item["exact_agreement"] is not None) if values else None,
        } for lang, values in by_language.items()
    }
    all_criterion_f1 = [item["macro_f1"] for values in by_language.values() for item in values.values()
                        if item["macro_f1"] is not None]
    overall_macro_f1 = mean(all_criterion_f1) if all_criterion_f1 else None
    total_expected = len(gold_records) * len(criteria)
    schema_validity = max(0.0, 1.0 - invalid_criteria / total_expected) if total_expected else None
    p95 = (sorted(latency)[min(len(latency) - 1, int(0.95 * len(latency)))] if latency else None)
    sla_rate = completed_under_120 / len(gold_records) if gold_records else None
    acceptance = {
        "overall_macro_f1_gte_0_90": overall_macro_f1 is not None and overall_macro_f1 >= 0.90,
        "each_language_macro_f1_gte_0_85": {"RU", "KZ", "EN"}.issubset(language_summary) and all(
            value["criterion_macro_f1"] is not None and value["criterion_macro_f1"] >= 0.85
            for value in language_summary.values()),
        "critical_error_recall_gte_0_95": critical_recall is not None and critical_recall >= 0.95,
        "na_accuracy_gte_0_90": na_metrics["exact_agreement"] is not None and na_metrics["exact_agreement"] >= 0.90,
        "schema_validity_gte_0_99": schema_validity is not None and schema_validity >= 0.99,
        "p95_latency_lte_120_seconds": p95 is not None and p95 <= 120,
        "completion_within_120_seconds_gte_0_95": sla_rate is not None and sla_rate >= 0.95,
    }
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
        "language_summary": language_summary,
        "overall_criterion_macro_f1": overall_macro_f1,
        "schema_validity_rate": schema_validity,
        "critical_error": {**critical_metrics, "positive_recall": critical_recall},
        "not_applicable": na_metrics,
        "criterion_score_mae": criterion_mae,
        "total_score_mae": mean(abs(a - b) for a, b in zip(scores_gold, scores_pred)) if scores_gold else None,
        "evidence": {
            "validated_quotes": evidence_valid,
            "prediction_quotes": evidence_total,
            "validity_rate": evidence_valid / evidence_total if evidence_total else None,
            "gold_quote_exact_match_count": gold_evidence_matched,
            "gold_quote_count": gold_evidence_count,
            "gold_quote_exact_match_rate": gold_evidence_matched / gold_evidence_count if gold_evidence_count else None,
            "note": "Validator acceptance and exact gold-quote matching are proxies, not semantic evidence attribution. Human review is required to certify semantic support."
        },
        "latency_seconds": {
            "count": len(ordered_latency),
            "p50": ordered_latency[(len(ordered_latency) - 1) // 2] if ordered_latency else None,
            "p95": p95
        },
        "sla": {"completed_within_120_seconds": completed_under_120, "rate": sla_rate},
        "hybrid": {**hybrid_counts,
                   "vlm_acceptance_rate": hybrid_counts["vlm_accepted_criteria"] / max(1, hybrid_counts["vlm_accepted_criteria"] + hybrid_counts["lm_fallback_criteria"] + hybrid_counts["needs_review_criteria"]),
                   "lm_fallback_rate": hybrid_counts["lm_fallback_criteria"] / max(1, hybrid_counts["vlm_accepted_criteria"] + hybrid_counts["lm_fallback_criteria"] + hybrid_counts["needs_review_criteria"])},
        "acceptance_gates": acceptance,
        "release_ready": bool(acceptance) and all(acceptance.values()),
    }


def compare_reports(baseline: dict, candidate: dict, overall_tolerance: float = 0.02,
                    language_tolerance: float = 0.03) -> dict:
    """Check that a faster candidate stays within the agreed macro-F1 loss margins."""
    base_overall = baseline.get("overall_criterion_macro_f1")
    cand_overall = candidate.get("overall_criterion_macro_f1")
    overall_delta = (cand_overall - base_overall) if isinstance(base_overall, (int, float)) and isinstance(cand_overall, (int, float)) else None
    languages = {}
    base_lang = baseline.get("language_summary") or {}
    cand_lang = candidate.get("language_summary") or {}
    for lang in sorted(set(base_lang) | set(cand_lang)):
        b = (base_lang.get(lang) or {}).get("criterion_macro_f1")
        c = (cand_lang.get(lang) or {}).get("criterion_macro_f1")
        delta = c - b if isinstance(b, (int, float)) and isinstance(c, (int, float)) else None
        languages[lang] = {"baseline_macro_f1": b, "candidate_macro_f1": c, "delta": delta,
                           "pass": delta is not None and delta >= -language_tolerance}
    gates = {
        "all_languages_present": {"RU", "KZ", "EN"}.issubset(set(base_lang) & set(cand_lang)),
        "overall_accuracy_loss_within_tolerance": overall_delta is not None and overall_delta >= -overall_tolerance,
        "each_language_loss_within_tolerance": bool(languages) and all(item["pass"] for item in languages.values()),
    }
    return {
        "comparison_version": 1,
        "baseline_overall_macro_f1": base_overall,
        "candidate_overall_macro_f1": cand_overall,
        "overall_delta": overall_delta,
        "overall_tolerance": overall_tolerance,
        "language_tolerance": language_tolerance,
        "by_language": languages,
        "acceptance_gates": gates,
        "pass": all(gates.values()),
    }
