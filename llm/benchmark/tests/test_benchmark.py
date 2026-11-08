import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm.benchmark.metrics import build_report, classification_metrics, compare_reports
from llm.benchmark.runner import run_benchmark
from llm.benchmark.schemas import BenchmarkDataError, validate_gold, validate_model_config


CHECKLIST = {
    "id": "tiny", "version": 1,
    "criteria": [
        {"id": "binary", "answer_type": "binary", "na_allowed": True},
        {"id": "scale", "answer_type": "scale", "na_allowed": False,
         "scale": {"steps": [{"value": 0}, {"value": 5}, {"value": 10}]}},
        {"id": "gross_errors", "answer_type": "flag", "na_allowed": False,
         "flag_types": [{"id": "insult"}]}
    ]
}
DIALOG = {
    "conversation_id": "c1", "language": "RU",
    "transcript": [{"speaker": "operator", "text": "Здравствуйте"}]
}
GOLD = {
    "conversation_id": "c1", "language": "RU", "checklist_id": "tiny",
    "checklist_version": 1, "scenario_group": "parallel-1", "split": "holdout",
    "criteria": {
        "binary": {"answer": "yes", "evidence": [{"msg_index": 0, "quote": "Здравствуйте"}]},
        "scale": {"answer": 10, "evidence": []},
        "gross_errors": {"answer": "no", "flags": [], "evidence": []}
    }
}


class SchemaTests(unittest.TestCase):
    def test_valid_gold(self):
        validate_gold([GOLD], CHECKLIST, {"c1": DIALOG})

    def test_rejects_bad_message_index(self):
        bad = {**GOLD, "criteria": {**GOLD["criteria"],
            "binary": {"answer": "yes", "evidence": [{"msg_index": 3, "quote": "Здравствуйте"}]}}}
        with self.assertRaises(BenchmarkDataError):
            validate_gold([bad], CHECKLIST, {"c1": DIALOG})

    def test_rejects_scenario_split_leakage(self):
        second = {**GOLD, "conversation_id": "c2", "split": "train"}
        dialog2 = {**DIALOG, "conversation_id": "c2", "language": "KZ"}
        second["language"] = "KZ"
        with self.assertRaises(BenchmarkDataError):
            validate_gold([GOLD, second], CHECKLIST, {"c1": DIALOG, "c2": dialog2})

    def test_model_config_duplicate_and_required_fields(self):
        valid = {"id": "x", "provider": "local", "model": "m", "runtime": "mlx", "context_length": 4096}
        with self.assertRaises(BenchmarkDataError):
            validate_model_config({"models": [valid, dict(valid)]})
        with self.assertRaises(BenchmarkDataError):
            validate_model_config({"models": [{"id": "x"}]})
        hybrid = {**valid, "id": "hybrid", "provider": "hybrid"}
        self.assertIn("hybrid", validate_model_config({"models": [hybrid]}))


class MetricTests(unittest.TestCase):
    def test_classification_empty_and_perfect(self):
        self.assertIsNone(classification_metrics([], [])["macro_f1"])
        self.assertEqual(classification_metrics(["yes", "no"], ["yes", "no"])["exact_agreement"], 1.0)

    def test_report_counts_missing_and_breaks_down_language(self):
        report = build_report([GOLD], [], CHECKLIST)
        self.assertEqual(report["missing_predictions"], 1)
        self.assertIn("RU", report["by_language"])
        self.assertEqual(report["critical_error"]["count"], 1)
        self.assertEqual(report["not_applicable"]["count"], 3)

    def test_report_uses_validated_evidence_and_latency(self):
        prediction = {
            "conversation_id": "c1", "status": "done", "latency_seconds": 1.25,
            "evaluation": {"total_score": 90, "results": [
                {"criterion_id": "binary", "answer": "yes", "raw_score": 1,
                 "validated": True, "evidence": [{"msg_index": 0, "quote": "Здравствуйте"}]},
                {"criterion_id": "scale", "answer": 10, "raw_score": 10,
                 "validated": True, "evidence": []},
                {"criterion_id": "gross_errors", "answer": "no", "validated": True, "evidence": []}
            ]}
        }
        report = build_report([GOLD], [prediction], CHECKLIST)
        self.assertEqual(report["evidence"]["validity_rate"], 1.0)
        self.assertEqual(report["latency_seconds"]["p50"], 1.25)
        self.assertEqual(report["criterion_score_mae"]["scale"], 0.0)
        self.assertIn("acceptance_gates", report)
        self.assertIn("schema_validity_rate", report)
        self.assertEqual(report["sla"]["rate"], 1.0)

    def test_report_summarizes_hybrid_routes(self):
        prediction = {
            "conversation_id": "c1", "status": "done", "latency_seconds": 20,
            "evaluation": {"results": [], "hybrid": {
                "routes": {"vlm": ["binary"], "lm_fallback": ["scale"], "needs_review": ["gross_errors"]},
                "deadline_exceeded": False,
            }}
        }
        report = build_report([GOLD], [prediction], CHECKLIST)
        self.assertEqual(report["hybrid"]["vlm_accepted_criteria"], 1)
        self.assertEqual(report["hybrid"]["lm_fallback_criteria"], 1)
        self.assertEqual(report["hybrid"]["needs_review_criteria"], 1)


class RunnerTests(unittest.TestCase):
    def test_run_writes_prediction_and_manifest_without_touching_input(self):
        fake_result = {"conversation_id": "c1", "status": "done", "results": [], "tokens": {"input": 1}}
        model = {"provider": "local", "model": "fake", "runtime": "fake runtime",
                 "context_length": 4096}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "predictions.jsonl"
            with patch("llm.benchmark.runner.evaluate", return_value=fake_result) as evaluate:
                manifest = run_benchmark([DIALOG], CHECKLIST, [GOLD], model, "fake-model", output)
            self.assertEqual(evaluate.call_count, 1)
            self.assertEqual(manifest["completed"], 1)
            self.assertTrue(Path(str(output) + ".manifest.json").exists())
            self.assertIn('"raw_output_available": false', output.read_text(encoding="utf-8"))
            self.assertEqual(DIALOG["transcript"][0]["text"], "Здравствуйте")


class ComparisonTests(unittest.TestCase):
    def test_candidate_must_stay_within_overall_and_language_accuracy_loss(self):
        baseline = {"overall_criterion_macro_f1": 0.92, "language_summary": {
            "RU": {"criterion_macro_f1": 0.93}, "KZ": {"criterion_macro_f1": 0.90}}}
        candidate = {"overall_criterion_macro_f1": 0.905, "language_summary": {
            "RU": {"criterion_macro_f1": 0.91}, "KZ": {"criterion_macro_f1": 0.88}}}
        result = compare_reports(baseline, candidate)
        self.assertTrue(result["pass"])
        candidate["language_summary"]["KZ"]["criterion_macro_f1"] = 0.86
        self.assertFalse(compare_reports(baseline, candidate)["pass"])


if __name__ == "__main__":
    unittest.main()
