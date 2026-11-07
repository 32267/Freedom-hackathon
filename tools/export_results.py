"""Выгрузка результатов в формате организаторов (Приложение к гайду, JSON 1.0).

    python tools/export_results.py --set dev                       # DEV: 60 чатов + 5 звонков → results/dev/results.json
    python tools/export_results.py --set prod --group <group_id>   # контрольные 10 чатов → results/prod/results.json
    python tools/export_results.py --set dev --check-only          # только проверить, без записи

Берёт последнюю оценку каждого диалога из базы (data/cqa.db). Диалог без оценки попадает со status="error" —
по правилам его нельзя скрывать или подменять нулём. Перед записью файл проверяется по всем правилам приложения.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import db  # noqa: E402

# наш id критерия → код организаторов
CODES = {"contact": "contact", "needs": "discovery", "identification": "identification", "consultation": "consultation",
         "empathy": "empathy", "dialog_management": "dialogue", "closing": "closure", "gross_errors": "critical"}
ORDER = ["contact", "discovery", "identification", "consultation", "empathy", "dialogue", "closure", "critical"]
ALLOWED = {  # допустимые значения value по таблице приложения
    # contact: в таблице только true/false, но жюри разрешило N/A для звонка, если приветствие не попало в запись
    "contact": {True, False, None}, "discovery": {True, False, None}, "identification": {True, False, None},
    "consultation": {0, 5, 10, 15, 20, None}, "empathy": {True, False}, "dialogue": {0, 4, 7, 10},
    "closure": {True, False, None}, "critical": {True, False},
}


def _code(cid: str) -> str:
    """Наш id → код организаторов; новый критерий (после замены на контроле) выгружается со своим id."""
    return CODES.get(cid, cid)


def _value(answer, criterion: dict):
    if answer == "na":
        return None
    if criterion.get("answer_type") == "scale":
        return int(float(answer))
    return answer == "yes"


def _allowed(criterion: dict) -> set:
    """Допустимые value для критерия из чек-листа (для нового критерия — по его типу и ступеням)."""
    code = _code(criterion["id"])
    if code in ALLOWED:
        return ALLOWED[code]
    vals = {s["value"] for s in criterion["scale"]["steps"]} if criterion.get("answer_type") == "scale" else {True, False}
    return vals | ({None} if criterion.get("na_allowed") else set())


def _turns(r: dict, n_turns: int) -> list[int]:
    turns = {e["msg_index"] + 1 for e in r.get("evidence", []) if isinstance(e.get("msg_index"), int)}
    rng = r.get("checked_range")
    if not turns and rng:
        turns = set(range(rng["from"] + 1, min(rng["to"], rng["from"] + 9) + 2))
    return sorted(t for t in turns if 1 <= t <= n_turns)


def record(dialog: dict, ev: dict | None, checklist: dict | None = None) -> dict:
    """checklist — версия, по которой сделана оценка: из неё порядок и типы критериев (важно после замены критерия)."""
    cid = dialog["conversation_id"]
    if not ev or ev.get("status") not in (None, "done"):
        return {"conversation_id": cid, "status": "error", "criteria": [], "score": None,
                "error": "Диалог не оценён: нет результата модели."}
    if checklist is None:
        checklist = db.get_checklist(ev.get("checklist_id", "default"), ev.get("checklist_version")) or {"criteria": []}
    by_id = {r["criterion_id"]: r for r in ev["results"]}
    crits = [c for c in checklist["criteria"] if c["id"] in by_id] or \
        [{"id": cid_, "answer_type": "scale" if CODES.get(cid_) in ("consultation", "dialogue") else "binary"} for cid_ in by_id]
    criteria = [{"criterion_id": _code(c["id"]), "value": _value(by_id[c["id"]]["answer"], c),
                 "rationale": (by_id[c["id"]].get("explanation") or by_id[c["id"]].get("na_reason") or "").strip(),
                 "evidence_turns": _turns(by_id[c["id"]], len(dialog["transcript"]))} for c in crits]
    flags = [x["value"] for x, c in zip(criteria, crits) if c.get("answer_type") == "flag" or x["criterion_id"] == "critical"]
    total = ev.get("total_score")
    return {"conversation_id": cid, "status": "ok", "criteria": criteria,
            "score": {"final_score": None if total is None else round(float(total), 2),
                      "critical_flag": any(bool(v) for v in flags)}}


def validate(doc: dict, expected_ids: list[str], exact: int | None, checklist: dict | None = None) -> list[str]:
    """checklist — действующий чек-лист: 8 критериев в его порядке (после замены — с новым кодом на месте старого)."""
    expected_codes = [_code(c["id"]) for c in checklist["criteria"]] if checklist else ORDER
    allowed = {_code(c["id"]): _allowed(c) for c in checklist["criteria"]} if checklist else ALLOWED
    errs = []
    ids = [r["conversation_id"] for r in doc["results"]]
    if len(ids) != len(set(ids)):
        errs.append("повторяющиеся conversation_id")
    if set(ids) != set(expected_ids):
        errs.append(f"ID не совпадают с набором: лишние {sorted(set(ids) - set(expected_ids))[:5]}, нет {sorted(set(expected_ids) - set(ids))[:5]}")
    if exact is not None and len(ids) != exact:
        errs.append(f"должно быть ровно {exact} записей, а их {len(ids)}")
    for r in doc["results"]:
        cid = r["conversation_id"]
        if r["status"] == "error":
            if r["criteria"] or r["score"] is not None or not r.get("error"):
                errs.append(f"{cid}: у ошибки должны быть пустые criteria, score=null и причина")
            continue
        codes = [c["criterion_id"] for c in r["criteria"]]
        if codes != expected_codes or len(codes) != 8:
            errs.append(f"{cid}: нужны все 8 критериев действующего чек-листа ровно по одному разу (есть {codes})")
        for c in r["criteria"]:
            v, code = c["value"], c["criterion_id"]
            ok_vals = allowed.get(code, set())
            scale = any(isinstance(x, int) and not isinstance(x, bool) for x in ok_vals)
            right_type = v is None or (isinstance(v, int) and not isinstance(v, bool) if scale else isinstance(v, bool))
            if not right_type or v not in ok_vals:
                errs.append(f"{cid}/{code}: недопустимое значение {v!r}")
            if not isinstance(c["evidence_turns"], list) or not all(isinstance(t, int) and t >= 1 for t in c["evidence_turns"]):
                errs.append(f"{cid}/{c['criterion_id']}: evidence_turns — номера реплик с 1")
        s = r["score"]
        if s["final_score"] is not None and not (0 <= s["final_score"] <= 100):
            errs.append(f"{cid}: final_score вне 0..100")
        crit = next((c["value"] for c in r["criteria"] if c["criterion_id"] == "critical"), None)
        if crit is not None and s["critical_flag"] != crit:
            errs.append(f"{cid}: critical_flag должен совпадать с value критерия critical")
    return errs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["dev", "prod"], required=True)
    ap.add_argument("--group", default="", help="group_id набора (по умолчанию DEV для dev)")
    ap.add_argument("--team", default=os.getenv("TEAM_NAME", "sol32267"))
    ap.add_argument("--mode", default=os.getenv("MODEL_MODE", "external_api"), choices=["local", "external_api", "hybrid"])
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args()

    group = a.group or ("DEV" if a.set == "dev" else "")
    if not group:
        sys.exit("Для prod укажите --group <group_id контрольного набора>")
    dialogs = db.list_dialogs(group_id=group)
    if not dialogs:
        sys.exit(f"В базе нет диалогов набора {group}. Сначала импортируйте его: POST /api/datasets/{group}/import")
    latest = db.latest_evaluations()
    results = [record(d, latest.get(d["conversation_id"])) for d in dialogs]
    models = sorted({m.strip() for d in dialogs for m in (latest.get(d["conversation_id"]) or {}).get("model", "").split(",") if m.strip()})
    doc = {"schema_version": "1.0", "team_name": a.team, "model": {"mode": a.mode, "name": ", ".join(models) or "—"},
           "results": results}

    current = db.get_checklist("default")
    stale = [d["conversation_id"] for d in dialogs if (latest.get(d["conversation_id"]) or {}).get("checklist_version") not in (None, current["version"])]
    if stale:
        print(f"  ! {len(stale)} диалог(ов) оценены по старой версии чек-листа (сейчас v{current['version']}): {stale[:5]}… — переоцените")
    errs = validate(doc, [d["conversation_id"] for d in dialogs], 10 if a.set == "prod" else None, current)
    ok = sum(r["status"] == "ok" for r in results)
    print(f"{a.set}: записей {len(results)} · ok {ok} · error {len(results) - ok} · модель {doc['model']['name']}")
    if a.set == "dev":
        chats = sum(d["channel"] == "agent chat" for d in dialogs)
        print(f"  чатов {chats}, звонков {len(dialogs) - chats} (по приложению: 60 и 5)")
    for e in errs:
        print("  ✗", e)
    if errs:
        sys.exit(1)
    if a.check_only:
        print("  ✓ формат верный (файл не записан: --check-only)")
        return
    out = ROOT / "results" / a.set / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ записано: {out.relative_to(ROOT)} — не забудьте commit и push до стоп-кода")


if __name__ == "__main__":
    main()
