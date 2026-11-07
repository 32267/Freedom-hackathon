import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CHAT = json.loads((ROOT / "fixtures/dialog.chat.json").read_text())
EV = json.loads((ROOT / "fixtures/evaluation.chat.json").read_text())


def run(tmp, ev, *flags):
    (tmp / "d.json").write_text(json.dumps([CHAT], ensure_ascii=False))
    (tmp / "e.json").write_text(json.dumps([ev], ensure_ascii=False))
    out = tmp / "train.jsonl"
    subprocess.run([sys.executable, str(ROOT / "llm/export_dataset.py"), "--dialogs", str(tmp / "d.json"),
                    "--evaluations", str(tmp / "e.json"), "--out", str(out), "--val-share", "0", *flags],
                   check=True, cwd=ROOT, capture_output=True)
    return [json.loads(line) for line in out.read_text().splitlines()]


def test_model_labels_excluded_by_default(tmp_path):
    assert run(tmp_path, EV) == []
    assert len(run(tmp_path, EV, "--include-model-labels", "--min-agreement", "0")) == 1


def test_human_labels_exported_in_schema_format(tmp_path):
    ev = json.loads(json.dumps(EV))
    for r in ev["results"]:
        r["source"] = "human"
    rows = run(tmp_path, ev)
    assert len(rows) == 1
    roles = [m["role"] for m in rows[0]["messages"]]
    target = json.loads(rows[0]["messages"][2]["content"])["criteria"]
    assert roles == ["system", "user", "assistant"] and set(target) == {r["criterion_id"] for r in ev["results"]}
    assert set(target["contact"]["explanation"]) == {"ru", "kz", "en"} and "flags" in target["gross_errors"]
