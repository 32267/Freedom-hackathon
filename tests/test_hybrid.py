"""Hybrid routing tests: VLM accepted when valid, LM called only for failed criteria."""
from backend.scoring import hybrid


CHECKLIST = {
    "id": "tiny", "version": 1, "rounding": "half_up_2",
    "criteria": [
        {"id": "contact", "answer_type": "binary", "weight": 50, "na_allowed": False, "section_id": "s"},
        {"id": "closing", "answer_type": "binary", "weight": 50, "na_allowed": False, "section_id": "s"},
    ],
    "sections": [{"id": "s"}],
}
DIALOG = {"conversation_id": "d1", "language": "RU", "transcript": []}


def result(cid, validated=True, answer="yes"):
    return {
        "criterion_id": cid, "answer": answer, "raw_score": 1 if answer == "yes" else 0,
        "max_score": 1, "explanation": "ok", "explanations": {"ru": "ok", "kz": "", "en": ""},
        "_source_language": "ru", "_source_explanation": "ok", "_source_na_reason": "",
        "evidence": [], "checked_range": None, "na_reason": None, "na_reasons": None,
        "flags": [], "insufficient": False, "source": "llm", "validated": validated,
        "problems": [] if validated else ["evidence invalid"],
    }


def sample(spec, results):
    return {
        "conversation_id": "d1", "checklist_id": "tiny", "checklist_version": 1,
        "provider": spec, "model": spec, "cost_usd": 0.01,
        "tokens": {"input": 10, "output": 5, "cache_read": 0, "calls": len(results)},
        "results": results,
    }


def test_lm_fallback_only_rechecks_invalid_vlm_criteria(monkeypatch):
    calls = []

    def fake(dialog, checklist, spec, criterion_ids=None):
        calls.append((spec, criterion_ids))
        if spec == "local":
            return sample(spec, [result("contact"), result("closing", validated=False, answer="no")])
        assert criterion_ids == ["closing"]
        return sample(spec, [result("closing", validated=True, answer="yes")])

    monkeypatch.setenv("HYBRID_VLM_PROVIDER", "local")
    monkeypatch.setenv("HYBRID_LM_PROVIDER", "claude_cli")
    monkeypatch.setattr(hybrid, "evaluate_llm", fake)
    monkeypatch.setattr(hybrid, "translate_explanations", lambda evaluation, *args: evaluation)
    evaluation = hybrid.evaluate_hybrid(DIALOG, CHECKLIST)

    assert calls == [("local", None), ("claude_cli", ["closing"])]
    assert evaluation["hybrid"]["routes"]["vlm"] == ["contact"]
    assert evaluation["hybrid"]["routes"]["lm_fallback"] == ["closing"]
    assert evaluation["results"][1]["model_route"] == "lm_fallback"
    assert evaluation["total_score"] == 100.0
    assert not evaluation["needs_review"]


def test_deadline_prevents_starting_lm_fallback(monkeypatch):
    calls = []

    def fake(dialog, checklist, spec, criterion_ids=None):
        calls.append(spec)
        return sample(spec, [result("contact", validated=False), result("closing")])

    monkeypatch.setenv("HYBRID_VLM_PROVIDER", "local")
    monkeypatch.setenv("HYBRID_LM_PROVIDER", "claude_cli")
    monkeypatch.setattr(hybrid, "evaluate_llm", fake)
    monkeypatch.setattr(hybrid, "translate_explanations", lambda evaluation, *args: evaluation)
    evaluation = hybrid.evaluate_hybrid(DIALOG, CHECKLIST, deadline_seconds=0.000001)

    assert calls == ["local"]
    assert evaluation["needs_review"]
    assert "contact" in evaluation["hybrid"]["routes"]["needs_review"]


def test_missing_result_from_both_models_is_not_fabricated(monkeypatch):
    from backend.llm import LLMOutputError
    monkeypatch.setenv("HYBRID_VLM_PROVIDER", "local")
    monkeypatch.setenv("HYBRID_LM_PROVIDER", "claude_cli")

    def fake(dialog, checklist, spec, criterion_ids=None):
        if spec == "local":
            raise LLMOutputError("bad VLM output")
        raise LLMOutputError("bad LM output")

    monkeypatch.setattr(hybrid, "evaluate_llm", fake)
    with __import__("pytest").raises(LLMOutputError, match="Human review required"):
        hybrid.evaluate_hybrid(DIALOG, CHECKLIST)
