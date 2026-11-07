import json
from pathlib import Path

import pytest

from backend.scoring import evaluate, recompute
from backend.scoring.math import ScoringError, compute

ROOT = Path(__file__).parent.parent
CL = json.loads((ROOT / "checklists/default.json").read_text())
ALL_YES = {"contact": "yes", "needs": "yes", "identification": "yes", "consultation": 20,
           "empathy": "yes", "dialog_management": 10, "closing": "yes", "gross_errors": "no"}


def res(**over):
    return [{"criterion_id": k, "answer": v} for k, v in {**ALL_YES, **over}.items()]


def score(**over):
    return compute(res(**over), CL)


def test_weights_sum_to_100():
    assert sum(c["weight"] for c in CL["criteria"]) == 100


def test_all_yes_is_100():
    out = score()
    assert out["total_score"] == 100.0 and not out["critical_error"]


def test_scale_proportional_to_weight():
    assert score(consultation=15)["total_score"] == 95.0        # 15/20 * 20 = 15 → -5
    assert score(dialog_management=7)["total_score"] == 95.5    # 7/10 * 15 = 10.5 → -4.5


def test_na_redistributes_and_max_stays_100():
    r = res(identification="na", contact="no")
    out = compute(r, CL)
    assert out["total_score"] == 87.5                            # 1 - 10/80
    assert {x["criterion_id"]: x["effective_weight"] for x in r}["contact"] == 12.5


def test_rounding_two_digits():
    assert score(needs="na", contact="no")["total_score"] == 88.24   # 1 - 10/85


def test_gross_error_is_flag_only():
    r = res(gross_errors="yes")
    r[-1]["flags"] = ["bypass"]
    out = compute(r, CL)
    assert out["total_score"] == 100.0 and out["critical_error"] and out["critical_flags"] == ["bypass"]


def test_na_not_allowed_and_bad_step():
    with pytest.raises(ScoringError):
        score(empathy="na")
    with pytest.raises(ScoringError):
        score(consultation=12)


def test_all_na_gives_null():
    cl = {**CL, "criteria": [c for c in CL["criteria"] if c["na_allowed"] or c["answer_type"] == "flag"]}
    r = [{"criterion_id": c["id"], "answer": "no" if c["answer_type"] == "flag" else "na"} for c in cl["criteria"]]
    assert compute(r, cl)["total_score"] is None


def test_sections():
    out = score(closing="no")
    s = {x["section_id"]: x["score"] for x in out["section_scores"]}
    assert s == {"start": 100.0, "security": 100.0, "conduct": 85.71}   # 30/35


def test_mock_shape_and_recompute(monkeypatch):
    monkeypatch.setenv("SCORING_MODE", "mock")
    for name in ("dialog.chat.json", "dialog.call.json"):
        ev = evaluate(json.loads((ROOT / "fixtures" / name).read_text()), CL)
        assert len(ev["results"]) == 8 and "total_score" in ev
        for r in ev["results"]:
            r["answer"], r["flags"] = ALL_YES[r["criterion_id"]], []
        assert recompute(ev, CL)["total_score"] == 100.0
