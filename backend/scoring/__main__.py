"""Оценить диалоги из командной строки (для отладки промпта):

    python -m backend.scoring fixtures/dialog.chat.json
    python -m backend.scoring data/DEV.json --limit 5 --ids p1-ru-001,p1-kz-003
"""
import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import evaluate


def _load(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict) and "data" in data:          # ответ API организаторов
        return data["data"]["records"]
    return data if isinstance(data, list) else [data]


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--checklist", default="checklists/default.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    checklist = json.loads(Path(a.checklist).read_text())
    dialogs = _load(a.path)
    if a.ids:
        want = set(a.ids.split(","))
        dialogs = [d for d in dialogs if d["conversation_id"] in want]
    if a.limit:
        dialogs = dialogs[: a.limit]

    out, total_cost = [], 0.0
    for d in dialogs:
        ev = evaluate(d, checklist)
        out.append(ev)
        total_cost += ev["cost_usd"]
        bad = [r["criterion_id"] for r in ev["results"] if not r.get("validated", True)]
        answers = " ".join(f'{r["criterion_id"]}={r["answer"]}' for r in ev["results"])
        print(f'{d["conversation_id"]:<16} {d["language"]} итог={ev["total_score"]} грубая={ev["critical_error"]} '
              f'${ev["cost_usd"]:.4f} {ev["tokens"]}\n   {answers}' + (f"\n   ⚠ не прошли проверку: {bad}" if bad else ""),
              flush=True)
    if dialogs:
        print(f"\nДиалогов: {len(dialogs)} · стоимость: ${total_cost:.4f} · в среднем ${total_cost / len(dialogs):.4f}")
    if a.out:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
