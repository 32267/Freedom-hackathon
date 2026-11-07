import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
EV = json.loads((ROOT / "fixtures/evaluation.chat.json").read_text())


def run(*args, cwd):
    return subprocess.run([sys.executable, str(ROOT / "tools/jury_kit.py"), *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout


def test_export_then_compare_with_foreign_format(tmp_path):
    (tmp_path / "evs").mkdir()
    (tmp_path / "evs/a.json").write_text(json.dumps(EV, ensure_ascii=False))
    run("export", "--from", str(tmp_path / "evs"), "--out", "ours.json", cwd=tmp_path)
    ours = json.loads((tmp_path / "ours.json").read_text())
    assert ours[0]["conversation_id"] == EV["conversation_id"] and len(ours[0]["criteria"]) == 8

    ru = {"yes": "Да", "no": "Нет", "na": "Н/П"}
    jury = {"data": {"records": [{
        "id": EV["conversation_id"], "итог": (EV["total_score"] or 0) - 7,
        "criteria": {f"{i:02d}": ru.get(str(r["answer"]), r["answer"]) for i, r in enumerate(EV["results"], 1)},
    }]}}
    (tmp_path / "jury.json").write_text(json.dumps(jury, ensure_ascii=False))
    out = run("compare", "--ours", "ours.json", "--jury", "jury.json", cwd=tmp_path)
    assert "Диалогов для сравнения: 1" in out and "средняя ошибка 7.00" in out
    assert "Установление контакта" in out and "1/1" in out
