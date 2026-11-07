import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("export_results", ROOT / "tools/export_results.py")
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)
CHAT = json.loads((ROOT / "fixtures/dialog.chat.json").read_text())
EV = json.loads((ROOT / "fixtures/evaluation.chat.json").read_text())


def test_record_matches_appendix_format():
    r = ex.record(CHAT, EV)
    assert r["status"] == "ok" and [c["criterion_id"] for c in r["criteria"]] == ex.ORDER
    vals = {c["criterion_id"]: c["value"] for c in r["criteria"]}
    assert all(isinstance(vals[k], int) and not isinstance(vals[k], bool) or vals[k] is None for k in ("consultation", "dialogue"))
    assert r["score"]["critical_flag"] == vals["critical"]
    assert all(t >= 1 for c in r["criteria"] for t in c["evidence_turns"])
    doc = {"schema_version": "1.0", "results": [r]}
    assert ex.validate(doc, [CHAT["conversation_id"]], None) == []


def test_missing_evaluation_is_error_not_zero():
    r = ex.record(CHAT, None)
    assert r == {"conversation_id": CHAT["conversation_id"], "status": "error", "criteria": [], "score": None, "error": r["error"]}
    assert ex.validate({"results": [r]}, [CHAT["conversation_id"]], 10) == ["должно быть ровно 10 записей, а их 1"]


def test_evidence_index_is_one_based():
    ev = json.loads(json.dumps(EV))
    ev["results"][0]["evidence"] = [{"msg_index": 0, "quote": "x"}]
    assert ex.record(CHAT, ev)["criteria"][0]["evidence_turns"] == [1]
