import json
from pathlib import Path

from backend.scoring import evaluate, recompute
from backend.scoring.math import compute

FIX = Path(__file__).parent.parent / "fixtures"
CL = json.loads((FIX / "checklist.example.json").read_text())


def r(cid, answer):
    return {"criterion_id": cid, "answer": answer}


def test_all_yes_is_100():
    out = compute([r("greet", "yes"), r("need", 2), r("correct", "yes")], CL)
    assert out["total_score"] == 100.0 and not out["critical_error"]


def test_na_redistributes_weight():
    res = [r("greet", "no"), r("need", "na"), r("correct", "yes")]
    out = compute(res, CL)
    assert out["total_score"] == 75.0          # 30 / (10+30)
    assert res[1]["effective_weight"] == 0.0 and res[2]["effective_weight"] == 75.0


def test_scale_and_rounding():
    out = compute([r("greet", "yes"), r("need", 1), r("correct", "yes")], CL)
    assert out["total_score"] == 83.3          # (10 + 10 + 30) / 60


def test_critical_flag_and_sections():
    out = compute([r("greet", "yes"), r("need", 2), r("correct", "no")], CL)
    assert out["critical_error"] is True
    assert {s["section_id"]: s["score"] for s in out["section_scores"]} == {"open": 100.0, "solve": 40.0}


def test_all_na_gives_null():
    cl = {**CL, "criteria": [{**CL["criteria"][1]}]}
    assert compute([r("need", "na")], cl)["total_score"] is None


def test_mock_shape_and_recompute():
    for name in ("dialog.chat.json", "dialog.call.json"):
        ev = evaluate(json.loads((FIX / name).read_text()), CL)
        assert len(ev["results"]) == 3 and "total_score" in ev
        for res in ev["results"]:
            res["answer"] = "na" if res["criterion_id"] == "need" else "yes"
        assert recompute(ev, CL)["total_score"] == 100.0
