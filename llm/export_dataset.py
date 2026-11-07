"""Оценки → обучающий набор для своей модели (JSONL в чат-формате).

Каждая строка: {"messages": [system, user, assistant]} — тот же промпт, что видит Claude/Codex,
а в ответе assistant — итоговая оценка в формате JSON-схемы. Формат понимают OpenAI fine-tuning,
Unsloth, Axolotl, LLaMA-Factory.

Какие оценки берём:
  - по умолчанию — только проверенные людьми: решение по апелляции (source = "appeal") или ручная разметка
    (source = "human", золотой набор);
  - с флагом --include-model-labels — ещё и ответы моделей, где все согласились (agreement = 1.0) и цитаты прошли
    проверку. ВНИМАНИЕ: условия Anthropic и OpenAI ограничивают обучение моделей на их ответах — прежде чем
    включать, проверьте условия использования (см. llm/README.md).
Диалог попадает в набор, только если надёжны ВСЕ его критерии (иначе учили бы модель на шуме).

    python llm/export_dataset.py --dialogs data/DEV.json --evaluations runs/dev_eval.json --out llm/data/train.jsonl
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.scoring.prompt import LANGS, build_system, build_user  # noqa: E402


def _load_dialogs(path: str) -> dict:
    data = json.loads(Path(path).read_text())
    records = data["data"]["records"] if isinstance(data, dict) and "data" in data else data
    return {d["conversation_id"]: d for d in records}


def _trusted(r: dict, min_agreement: float, model_labels: bool) -> bool:
    if r.get("source") in ("appeal", "human"):
        return True
    return model_labels and r.get("validated", False) and r.get("agreement", 1.0) >= min_agreement


def _target(ev: dict, types: dict) -> dict:
    """Evaluation → ответ модели в формате build_schema()."""
    out = {}
    for r in ev["results"]:
        exp = r.get("explanations") or {"ru": r.get("explanation", ""), "kz": "", "en": ""}
        na = r.get("na_reasons") or {lang: "" for lang in LANGS}
        rng = r.get("checked_range")
        item = {
            "evidence": [{"msg_index": e["msg_index"], "quote": e["quote"]} for e in r.get("evidence", [])],
            "explanation": {lang: exp.get(lang, "") for lang in LANGS},
            "checked_range": [rng["from"], rng["to"]] if rng else [],
            "na_reason": {lang: na.get(lang, "") for lang in LANGS},
        }
        if types.get(r["criterion_id"]) == "flag":
            item["flags"] = r.get("flags") or []
        item["answer"] = str(r["answer"])
        out[r["criterion_id"]] = item
    return {"criteria": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialogs", required=True)
    ap.add_argument("--evaluations", required=True, nargs="+", help="JSON-файлы со списками оценок")
    ap.add_argument("--checklist", default="checklists/default.json")
    ap.add_argument("--out", default="llm/data/train.jsonl")
    ap.add_argument("--min-agreement", type=float, default=1.0)
    ap.add_argument("--val-share", type=float, default=0.15)
    ap.add_argument("--include-model-labels", action="store_true",
                    help="брать и согласованные ответы моделей (проверьте условия провайдеров)")
    a = ap.parse_args()

    dialogs = _load_dialogs(a.dialogs)
    checklist = json.loads(Path(a.checklist).read_text())
    system = build_system(checklist)
    types = {c["id"]: c["answer_type"] for c in checklist["criteria"]}
    evals = [e for f in a.evaluations for e in json.loads(Path(f).read_text())]

    train, val, skipped = [], [], 0
    for ev in evals:
        d = dialogs.get(ev["conversation_id"])
        if d is None or ev.get("checklist_version") != checklist["version"] or \
                not all(_trusted(r, a.min_agreement, a.include_model_labels) for r in ev["results"]):
            skipped += 1
            continue
        target = _target(ev, types)
        if any(not v["explanation"][lang] for v in target["criteria"].values() for lang in LANGS):
            skipped += 1                       # старые оценки без обоснований на трёх языках
            continue
        row = {"messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": build_user(d)},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ], "meta": {"conversation_id": d["conversation_id"], "language": d["language"], "channel": d["channel"]}}
        # разбиение по диалогу, а не по строке: один диалог не попадёт и в train, и в val
        bucket = int(hashlib.md5(d["conversation_id"].encode()).hexdigest(), 16) % 100
        (val if bucket < a.val_share * 100 else train).append(row)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in train))
    out.with_name(out.stem + ".val.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in val))
    print(f"train: {len(train)} · val: {len(val)} · пропущено (ненадёжные, без 3 языков, другая версия чек-листа): {skipped}")


if __name__ == "__main__":
    main()
