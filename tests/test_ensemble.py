"""Несколько ответов: уровни провайдеров (Claude → Codex) и голосование. Без сети."""
import copy
import json
from pathlib import Path

import pytest

import backend.llm as llm
from backend.llm import LLMError, LLMOutputError
from backend.scoring import ensemble

ROOT = Path(__file__).parent.parent
CL = json.loads((ROOT / "checklists/default.json").read_text())
BASE = {"contact": "yes", "needs": "yes", "identification": "na", "consultation": 20,
        "empathy": "yes", "dialog_management": 10, "closing": "yes", "gross_errors": "no"}


def sample(spec, **over):
    ans = {**BASE, **over}
    return {"conversation_id": "d1", "checklist_id": "default", "checklist_version": 1, "provider": spec,
            "model": spec.split("@")[0], "cost_usd": 0.01, "tokens": {"input": 10, "output": 5, "calls": 1},
            "results": [{"criterion_id": k, "answer": v, "validated": True, "evidence": [], "flags": [],
                         "explanation": f"{spec}:{k}"} for k, v in ans.items()]}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    llm._dead.clear()
    monkeypatch.setenv("SCORING_MODE", "llm")


def install(monkeypatch, behaviour):
    calls = []

    def fake(dialog, checklist, spec):
        calls.append(spec)
        b = behaviour[spec]
        if isinstance(b, Exception):
            raise copy.copy(b)
        return sample(spec, **(b.pop(0) if isinstance(b, list) else b))
    monkeypatch.setattr(ensemble, "evaluate_llm", fake)
    return calls


def test_claude_first_codex_untouched(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "claude_cli | codex_cli")
    monkeypatch.setenv("LLM_SAMPLES", "3")
    calls = install(monkeypatch, {"claude_cli": {}, "codex_cli": {}})
    ev = ensemble.evaluate_ensemble({}, CL)
    assert calls == ["claude_cli"] * 3 and ev["samples"] == 3 and not ev["needs_review"]
    assert ev["total_score"] == 100.0 and ev["cost_usd"] == 0.03


def test_codex_takes_over_when_claude_down(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "claude_cli | codex_cli")
    monkeypatch.setenv("LLM_SAMPLES", "2")
    calls = install(monkeypatch, {"claude_cli": LLMError("лимит"), "codex_cli": {}})
    ev = ensemble.evaluate_ensemble({}, CL)
    assert ev["providers"] == ["codex_cli", "codex_cli"] and "claude_cli: лимит" in ev["provider_errors"][0]
    ensemble.evaluate_ensemble({}, CL)                       # Claude помечен недоступным → сразу Codex
    assert calls.count("claude_cli") == 2


def test_second_claude_account_fills_in(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "claude_cli, claude_cli@~/.claude-b | codex_cli")
    monkeypatch.setenv("LLM_SAMPLES", "2")
    install(monkeypatch, {"claude_cli": LLMError("лимит"), "claude_cli@~/.claude-b": {}, "codex_cli": {}})
    ev = ensemble.evaluate_ensemble({}, CL)
    assert ev["providers"] == ["claude_cli@~/.claude-b", "claude_cli@~/.claude-b"]


def test_bad_answer_does_not_disable_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "claude_cli | codex_cli")
    calls = install(monkeypatch, {"claude_cli": LLMOutputError("кривой JSON"), "codex_cli": {}})
    ensemble.evaluate_ensemble({}, CL)
    assert llm.is_alive("claude_cli") and calls[-1] == "codex_cli"


def test_all_down_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "claude_cli | codex_cli")
    install(monkeypatch, {"claude_cli": LLMError("нет"), "codex_cli": LLMError("нет")})
    with pytest.raises(LLMError, match="Ни один провайдер"):
        ensemble.evaluate_ensemble({}, CL)


def test_majority_vote_and_review_flag():
    s = [sample("a", closing="no"), sample("b"), sample("c")]
    ev = ensemble.merge(s, CL)
    closing = next(r for r in ev["results"] if r["criterion_id"] == "closing")
    assert closing["answer"] == "yes" and closing["agreement"] == 0.67 and closing["needs_review"]
    assert closing["explanation"] == "b:closing" and [v["answer"] for v in closing["votes"]] == ["no", "yes", "yes"]
    assert ev["needs_review"]


def test_tie_goes_to_first_provider():
    ev = ensemble.merge([sample("claude", contact="no"), sample("codex")], CL)
    assert next(r for r in ev["results"] if r["criterion_id"] == "contact")["answer"] == "no"


def test_scale_lower_median_and_na_majority():
    ev = ensemble.merge([sample("a", consultation=20), sample("b", consultation=10), sample("c", consultation=15)], CL)
    assert next(r for r in ev["results"] if r["criterion_id"] == "consultation")["answer"] == 15
    ev = ensemble.merge([sample("a", consultation="na"), sample("b", consultation="na"), sample("c")], CL)
    assert next(r for r in ev["results"] if r["criterion_id"] == "consultation")["answer"] == "na"


def test_flags_union():
    s = [sample("a", gross_errors="yes"), sample("b", gross_errors="yes")]
    s[0]["results"][-1]["flags"], s[1]["results"][-1]["flags"] = ["bypass"], ["insult"]
    ev = ensemble.merge(s, CL)
    assert ev["critical_error"] and ev["critical_flags"] == ["bypass", "insult"]


def test_site_override_beats_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "claude_cli | codex_cli")
    monkeypatch.setenv("LLM_SAMPLES", "3")
    install(monkeypatch, {"claude_cli": {}, "codex_cli": {}})
    ev = ensemble.evaluate_ensemble({}, CL, providers="claude_cli, codex_cli", samples=2)
    assert ev["providers"] == ["claude_cli", "codex_cli"] and ev["samples"] == 2


def test_registry_lists_presets_and_availability(monkeypatch):
    from backend.llm import registry
    monkeypatch.setenv("LLM_PROVIDERS", "claude_cli | codex_cli")
    monkeypatch.delenv("LOCAL_LLM_URL", raising=False)
    out = registry.list_providers()
    by = {p["id"]: p for p in out["providers"]}
    assert by["local"]["available"] is False and "LOCAL_LLM_URL" in by["local"]["reason"]
    assert by["claude_cli"]["configured"] and {p["id"] for p in out["presets"]} >= {"claude", "codex", "compare"}


def test_insufficient_data_goes_to_review():
    a, b = sample("a"), sample("b")
    for s in (a, b):
        next(r for r in s["results"] if r["criterion_id"] == "contact")["insufficient"] = True
    ev = ensemble.merge([a, b], CL)
    contact = next(r for r in ev["results"] if r["criterion_id"] == "contact")
    assert contact["agreement"] == 1.0 and contact["needs_review"] and ev["needs_review"]


def test_claude_schema_failure_is_output_error(monkeypatch):
    import subprocess

    from backend.llm import claude_cli_provider as cp

    class P:
        returncode, stderr = 1, ""
        stdout = json.dumps({"is_error": True, "subtype": "error_max_structured_output_retries"})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: P())
    monkeypatch.setattr(cp.shutil, "which", lambda *_: "/usr/bin/claude")
    with pytest.raises(LLMOutputError):
        cp.call_json("s", "u", {}, "m", "medium")
