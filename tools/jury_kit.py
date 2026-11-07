"""Финал: 10 примеров от жюри.

    # 1) выгрузить наши оценки в чистый JSON (из папки с оценками или из API)
    python tools/jury_kit.py export --from dataset/DEV/evaluations --out our_scores.json
    python tools/jury_kit.py export --from http://localhost:8000 --ids id1,id2 --out our_scores.json

    # 2) когда жюри покажет свои оценки — сравнить
    python tools/jury_kit.py compare --ours our_scores.json --jury jury.json

Формат файла жюри заранее неизвестен, поэтому compare понимает разные варианты: список или словарь по id,
обёртку {"data": {"records": [...]}}, ключи conversation_id / id / dialog_id, итог total_score / total / score,
ответы по критериям словарём {id: ответ} или списком results, критерии по id, номеру («01», «1») или названию.
"""
import argparse
import json
import statistics
import sys
import urllib.request
from pathlib import Path

CHECKLIST = Path(__file__).resolve().parent.parent / "checklists/default.json"
ANSWER = {"yes": "yes", "да": "yes", "иә": "yes", "true": "yes", "1": "yes", "y": "yes",
          "no": "no", "нет": "no", "жоқ": "no", "false": "no", "0": "no", "n": "no",
          "na": "na", "n/a": "na", "н/п": "na", "н/а": "na", "қ/ж": "na", "null": "na", "none": "na", "-": "na"}


def _checklist():
    return json.loads(CHECKLIST.read_text())


def _crit_key(raw, cl) -> str | None:
    """id / номер / название критерия → id из чек-листа."""
    s = str(raw).strip().lower()
    for i, c in enumerate(cl["criteria"], 1):
        if s in (c["id"].lower(), str(i), f"{i:02d}", f"c{i}", f"c{i:02d}") or s == c["title"].lower():
            return c["id"]
    for c in cl["criteria"]:
        if c["title"].lower() in s or s in c["title"].lower():
            return c["id"]
    return None


def _norm_answer(v, crit: dict):
    if isinstance(v, dict):
        v = v.get("answer", v.get("score", v.get("value")))
    if v is None:
        return "na"
    if crit["answer_type"] == "scale":
        s = str(v).strip().lower()
        if s in ("na", "n/a", "н/п", "н/а", "қ/ж", "none", "null", "-"):
            return "na"
        try:
            return float(s.replace(",", "."))
        except ValueError:
            return s
    return ANSWER.get(str(v).strip().lower(), str(v).strip().lower())


def _records(data):
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        data = data["data"].get("records", data["data"])
    if isinstance(data, dict) and not any(k in data for k in ("conversation_id", "id", "dialog_id")):
        return [{"conversation_id": k, **(v if isinstance(v, dict) else {"total_score": v})} for k, v in data.items()]
    return data if isinstance(data, list) else [data]


def _parse(data, cl) -> dict[str, dict]:
    out = {}
    by_id = {c["id"]: c for c in cl["criteria"]}
    for r in _records(data):
        cid = r.get("conversation_id") or r.get("id") or r.get("dialog_id")
        if not cid:
            continue
        total = next((r[k] for k in ("total_score", "total", "score", "итог", "final_total") if k in r), None)
        answers = {}
        crits = r.get("criteria") or r.get("answers") or {}
        if isinstance(crits, dict):
            items = crits.items()
        else:
            items = ((x.get("criterion_id") or x.get("id") or x.get("criterion"), x) for x in crits)
        for k, v in list(items) + [((x.get("criterion_id")), x) for x in r.get("results", []) if isinstance(x, dict)]:
            key = _crit_key(k, cl) if k is not None else None
            if key:
                answers[key] = _norm_answer(v, by_id[key])
        crit_flag = r.get("critical_error", r.get("gross_error"))
        if crit_flag is None and "gross_errors" in answers:
            crit_flag = answers["gross_errors"] == "yes"
        out[str(cid)] = {"total": None if total is None else float(total), "answers": answers, "critical": crit_flag}
    return out


def _load_ours(src: str, ids: list[str]) -> list[dict]:
    if src.startswith("http"):
        evs = []
        for cid in ids:
            with urllib.request.urlopen(f"{src.rstrip('/')}/api/dialogs/{cid}/evaluation", timeout=30) as r:
                evs.append(json.loads(r.read()))
        return evs
    p = Path(src)
    if p.is_dir():
        evs = [json.loads(f.read_text()) for f in sorted(p.glob("*.json")) if f.name[0] != "_"]
        evs = [e for e in evs if isinstance(e, dict) and "results" in e]
    else:
        evs = json.loads(p.read_text())
    return [e for e in evs if not ids or e["conversation_id"] in ids]


def export(a) -> None:
    ids = [i for i in a.ids.split(",") if i]
    rows = []
    for ev in _load_ours(a.src, ids):
        rows.append({
            "conversation_id": ev["conversation_id"],
            "total_score": ev.get("total_score"),
            "critical_error": ev.get("critical_error"),
            "critical_flags": ev.get("critical_flags", []),
            "section_scores": ev.get("section_scores", []),
            "model": ev.get("model"),
            "checklist_version": ev.get("checklist_version"),
            "criteria": {r["criterion_id"]: {
                "answer": r["answer"], "weighted_score": r.get("weighted_score"),
                "explanation": r.get("explanation"), "na_reason": r.get("na_reason"),
                "evidence": r.get("evidence", []), "checked_range": r.get("checked_range"),
                "needs_review": r.get("needs_review", False)} for r in ev["results"]},
        })
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"Выгружено оценок: {len(rows)} → {a.out}")


def compare(a) -> None:
    cl = _checklist()
    ours = _parse(json.loads(Path(a.ours).read_text()), cl)
    jury = _parse(json.loads(Path(a.jury).read_text()), cl)
    common = [k for k in jury if k in ours]
    if not common:
        sys.exit(f"Нет общих диалогов. Жюри: {list(jury)[:5]}…, наши: {list(ours)[:5]}…")
    print(f"Диалогов для сравнения: {len(common)} (у жюри {len(jury)}, у нас {len(ours)})\n")

    diffs = [(k, ours[k]["total"] - jury[k]["total"]) for k in common
             if ours[k]["total"] is not None and jury[k]["total"] is not None]
    if diffs:
        ad = [abs(d) for _, d in diffs]
        print(f"Итоговый балл: средняя ошибка {statistics.mean(ad):.2f} · медиана {statistics.median(ad):.2f} · "
              f"в пределах 5 баллов {sum(x <= 5 for x in ad)}/{len(ad)} · 10 баллов {sum(x <= 10 for x in ad)}/{len(ad)} · "
              f"сдвиг (мы − жюри) {statistics.mean(d for _, d in diffs):+.2f}")
    print("\nСовпадение по критериям:")
    for c in cl["criteria"]:
        pairs = [(ours[k]["answers"].get(c["id"]), jury[k]["answers"].get(c["id"])) for k in common
                 if c["id"] in jury[k]["answers"] and c["id"] in ours[k]["answers"]]
        if not pairs:
            continue
        same = sum(o == j for o, j in pairs)
        miss = [f"{o}≠{j}" for o, j in pairs if o != j]
        print(f"  {c['title']:<48} {same}/{len(pairs)}  {', '.join(miss[:6])}")
    crit = [(ours[k]["critical"], jury[k]["critical"]) for k in common if jury[k]["critical"] is not None]
    if crit:
        print(f"\nГрубые ошибки: совпало {sum(bool(o) == bool(j) for o, j in crit)}/{len(crit)}")
    if diffs:
        print("\nСамые большие расхождения итога:")
        for k, d in sorted(diffs, key=lambda x: -abs(x[1]))[:5]:
            print(f"  {k}: мы {ours[k]['total']} · жюри {jury[k]['total']} ({d:+.2f})")


def main() -> None:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    e = sp.add_parser("export")
    e.add_argument("--from", dest="src", default="dataset/DEV/evaluations")
    e.add_argument("--ids", default="")
    e.add_argument("--out", default="our_scores.json")
    c = sp.add_parser("compare")
    c.add_argument("--ours", required=True)
    c.add_argument("--jury", required=True)
    a = ap.parse_args()
    export(a) if a.cmd == "export" else compare(a)


if __name__ == "__main__":
    main()
