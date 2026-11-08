"""REST API по docs/CONTRACTS.md (/api/...)."""
import html
import json
import os
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from backend import db
from backend.llm import LLMError
from backend.llm.registry import list_providers
from backend.scoring import ScoringError, evaluate, recompute, summarize_dialog

router = APIRouter(prefix="/api")
def data_root() -> Path:
    """Где лежат data/ и dataset/ (по умолчанию — корень репозитория)."""
    return Path(os.getenv("CQA_DATA_ROOT") or Path(__file__).resolve().parent.parent)


def audio_dirs() -> list[Path]:
    return [data_root() / "data/audio", data_root() / "dataset/DEV/calls"]


def _err(status: int, msg: str) -> NoReturn:
    raise HTTPException(status_code=status, detail=msg)


# ---------- служебное ----------
@router.get("/health")
def health():
    return {"ok": True, "dialogs": db.count_dialogs(), "evaluations": db.count_evaluations(),
            "scoring_mode": os.getenv("SCORING_MODE", "llm")}


@router.get("/stats")
def stats():
    """Сводка для обзора: средние по языку/каналу, частота провалов по критериям, очередь апелляций."""
    dialogs = {d["conversation_id"]: d for d in db.list_dialogs()}
    latest = db.latest_evaluations()
    groups: dict[str, list[float]] = {}
    crit: dict[str, dict] = {}
    flags: dict[str, int] = {}
    for cid, ev in latest.items():
        d = dialogs.get(cid)
        if not d:
            continue
        if ev.get("total_score") is not None:
            groups.setdefault(f'{d.get("channel")}|{d.get("language")}', []).append(ev["total_score"])
        for f in ev.get("critical_flags", []):
            flags[f] = flags.get(f, 0) + 1
        for r in ev.get("results", []):
            c = crit.setdefault(r["criterion_id"], {"criterion_id": r["criterion_id"], "total": 0, "lost": 0, "na": 0, "review": 0})
            c["total"] += 1
            if r["answer"] == "na":
                c["na"] += 1
            elif r.get("max_score") and r.get("raw_score") is not None and r["raw_score"] < r["max_score"]:
                c["lost"] += 1
            if r.get("needs_review"):
                c["review"] += 1
    scores = [ev["total_score"] for cid, ev in latest.items() if cid in dialogs and ev.get("total_score") is not None]
    return {
        "dialogs": len(dialogs), "evaluated": len([c for c in latest if c in dialogs]),
        "average": round(sum(scores) / len(scores), 2) if scores else None,
        "needs_review": sum(1 for c, ev in latest.items() if c in dialogs and ev.get("needs_review")),
        "critical": sum(1 for c, ev in latest.items() if c in dialogs and ev.get("critical_error")),
        "open_appeals": len(db.list_appeals("open")),
        "groups": [{"channel": k.split("|")[0], "language": k.split("|")[1], "count": len(v), "average": round(sum(v) / len(v), 2)}
                   for k, v in sorted(groups.items())],
        "criteria": list(crit.values()), "critical_flags": flags,
        "critical_list": [_critical_item(cid, ev) for cid, ev in latest.items() if cid in dialogs and ev.get("critical_error")],
    }


def _critical_item(cid: str, ev: dict) -> dict:
    """Диалог с грубой ошибкой: вид нарушения, обоснование и цитата — для списка на «Обзоре»."""
    flag = next((r for r in ev.get("results", []) if r.get("flags") or r["criterion_id"] == "gross_errors"), {})
    ev0 = (flag.get("evidence") or [{}])[0]
    return {"conversation_id": cid, "total_score": ev.get("total_score"), "flags": ev.get("critical_flags", []),
            "explanation": flag.get("explanation"), "explanations": flag.get("explanations"),
            "quote": ev0.get("quote"), "msg_index": ev0.get("msg_index")}


@router.get("/llm/providers")
def providers():
    return list_providers()


# ---------- диалоги ----------
def _offset(ts: str, first: str) -> float | None:
    try:
        return round((datetime.fromisoformat(ts) - datetime.fromisoformat(first)).total_seconds(), 2)
    except ValueError:
        return None


def _enrich(d: dict) -> dict:
    """Производные поля (исходные не меняются): msg_index, offset_sec для звонков, audio_src."""
    t = d.get("transcript", [])
    voice = d.get("channel") == "voice call"
    first = t[0]["timestamp"] if t else ""
    out = {**d, "transcript": [{**m, "msg_index": i, **({"offset_sec": _offset(m["timestamp"], first)} if voice else {})}
                               for i, m in enumerate(t)]}
    if d.get("audio_url") or d.get("audio_local"):
        out["audio_src"] = f"/api/dialogs/{urllib.parse.quote(d['conversation_id'])}/audio"
    return out


def _operator(d: dict, ev: dict | None) -> str:
    """Оператор диалога: ручная привязка, иначе имя из сводки (если представился без маски)."""
    return (d.get("operator") or ((ev or {}).get("summary") or {}).get("operator_name") or "").strip()


def _summary(d: dict, ev: dict | None) -> dict:
    return {**_enrich(d), "turns": len(d.get("transcript", [])), "client_id": d.get("client_id"), "operator": _operator(d, ev),
            "summary_status": ((ev or {}).get("summary") or {}).get("status"),
            "evaluation_id": ev and ev["id"], "evaluation_status": ev["status"] if ev else "not_started",
            "total_score": ev and ev.get("total_score"), "critical_error": bool(ev and ev.get("critical_error")),
            "critical_flags": (ev or {}).get("critical_flags", []), "needs_review": bool(ev and ev.get("needs_review")),
            "evaluated_at": ev and ev.get("created_at")}


@router.get("/dialogs")
def dialogs(group_id: str | None = None, language: str | None = None, channel: str | None = None, search: str | None = None):
    latest = db.latest_evaluations()
    rows = [_summary(d, latest.get(d["conversation_id"])) for d in db.list_dialogs(group_id, language, channel)]
    if search:
        s = search.lower()
        rows = [r for r in rows if s in r["conversation_id"].lower() or any(s in m["text"].lower() for m in r["transcript"])]
    return rows


def _history(client_id: str, exclude: str | None = None) -> list[dict]:
    latest = db.latest_evaluations()
    out = []
    for d in db.list_dialogs():
        if d.get("client_id") != client_id or d["conversation_id"] == exclude:
            continue
        ev = latest.get(d["conversation_id"])
        out.append({"conversation_id": d["conversation_id"], "channel": d.get("channel"), "language": d.get("language"),
                    "started": (d.get("transcript") or [{}])[0].get("timestamp"), "evaluated_at": ev and ev.get("created_at"),
                    "total_score": ev and ev.get("total_score"), "operator": _operator(d, ev), "summary": (ev or {}).get("summary")})
    return sorted(out, key=lambda x: x["evaluated_at"] or "", reverse=True)


@router.get("/dialogs/{cid}")
def dialog(cid: str):
    d = db.get_dialog(cid) or _err(404, f"Диалог {cid} не найден")
    out = _summary(d, db.latest_evaluation(cid))
    out["history"] = _history(d["client_id"], exclude=cid) if d.get("client_id") else []
    return out


@router.patch("/dialogs/{cid}")
def update_dialog(cid: str, body: dict = Body(...)):
    """Привязка к клиенту (client_id) и/или оператору (operator). Пустая строка — отвязать."""
    d = db.get_dialog(cid) or _err(404, f"Диалог {cid} не найден")
    for key in ("client_id", "operator"):
        if key in body:
            value = (body[key] or "").strip()[:80]
            if value:
                d[key] = value
            else:
                d.pop(key, None)
    db.upsert_dialog(d, d.get("dataset_group_id"))
    return dialog(cid)


@router.get("/clients/{client_id}")
def client_history(client_id: str):
    """Все обращения клиента со сводками — что спрашивал, что сделано, что осталось."""
    return {"client_id": client_id, "contacts": _history(client_id)}


@router.get("/operators")
def operators():
    """Рейтинг операторов по средней оценке их диалогов (последняя оценка каждого диалога)."""
    latest = db.latest_evaluations()
    agg: dict[str, dict] = {}
    for d in db.list_dialogs():
        ev = latest.get(d["conversation_id"])
        name = _operator(d, ev)
        if not ev or not name or ev.get("total_score") is None:
            continue
        a = agg.setdefault(name, {"operator": name, "dialogs": [], "scores": [], "critical": 0, "review": 0, "open_issues": 0})
        a["dialogs"].append({"conversation_id": d["conversation_id"], "total_score": ev["total_score"], "channel": d.get("channel"),
                             "language": d.get("language")})
        a["scores"].append(ev["total_score"])
        a["critical"] += bool(ev.get("critical_error"))
        a["review"] += bool(ev.get("needs_review"))
        a["open_issues"] += len(((ev.get("summary") or {}).get("open_issues")) or [])
    rows = [{**{k: v for k, v in a.items() if k != "scores"}, "count": len(a["scores"]),
             "average": round(sum(a["scores"]) / len(a["scores"]), 2)} for a in agg.values()]
    rows.sort(key=lambda r: (-r["average"], -r["count"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


@router.get("/dialogs/{cid}/evaluation")
def dialog_evaluation(cid: str):
    return db.latest_evaluation(cid) or _err(404, "Диалог ещё не оценён")


def _resolve_audio(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "cqa-backend"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if "audio" in r.headers.get("Content-Type", ""):
            return url
        body = r.read().decode("utf-8", "replace")
    m = re.search(r'<source[^>]+src="([^"]+)"', body)
    if not m:
        raise ValueError("на странице плеера нет ссылки на запись")
    return html.unescape(m.group(1))


@router.get("/dialogs/{cid}/audio")
def dialog_audio(cid: str):
    """audio_url организаторов — страница плеера со ссылкой на mp3 (живёт ~1 ч). Скачиваем один раз и отдаём сами
    (FileResponse поддерживает Range → перемотка в <audio> работает)."""
    d = db.get_dialog(cid) or _err(404, "Диалог не найден")
    for folder in audio_dirs():
        for ext, mime in AUDIO_TYPES.items():
            f = folder / f"{cid}{ext}"
            if f.exists():
                return FileResponse(f, media_type=mime)
    if not d.get("audio_url"):
        _err(404, "У диалога нет записи")
    target = audio_dirs()[0] / f"{cid}.mp3"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(_resolve_audio(d["audio_url"]), headers={"User-Agent": "cqa-backend"})
        with urllib.request.urlopen(req, timeout=180) as r:
            tmp = target.with_suffix(".part")
            tmp.write_bytes(r.read())
            tmp.rename(target)
    except Exception as e:  # noqa: BLE001
        _err(502, f"Не удалось получить запись: {e}")
    return FileResponse(target, media_type="audio/mpeg")


AUDIO_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".webm": "audio/webm"}


def _safe_id(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip("-.") or "audio"
    return base[:60]


def _run_audio_job(job: dict, path: Path, cid: str, language: str | None) -> None:
    from backend.asr import audio_to_dialog
    try:
        job["stage"] = "распознавание речи"
        dialog = audio_to_dialog(str(path), cid, language)
        dialog["audio_local"] = True
        if len(dialog["transcript"]) <= 1:
            raise ValueError("в записи не распознано ни одной реплики")
        db.upsert_dialog(dialog, "UPLOAD")
        with _jobs_lock:
            job.update(status="done", done=1, conversation_id=cid, turns=len(dialog["transcript"]), language=dialog["language"])
    except Exception as e:  # noqa: BLE001
        with _jobs_lock:
            job.update(status="done", failed=1, errors=[f"{cid}: {e}"[:300]])
    finally:
        job["finished_at"] = db.now()


@router.post("/dialogs/upload-audio")
async def upload_audio(file: UploadFile = File(...), conversation_id: str = Form(""), language: str = Form("")):
    """MP3/WAV/M4A → расшифровка (Whisper) → разметка ролей → новый диалог-звонок. Возвращает задачу:
    прогресс — GET /api/jobs/{job_id}, по готовности в ней conversation_id."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_TYPES:
        _err(422, f"Поддерживаются аудиофайлы: {', '.join(AUDIO_TYPES)}")
    cid = _safe_id(conversation_id or file.filename or "audio")
    if db.get_dialog(cid):
        cid = f"{cid}-{db.new_id('a')[-6:]}"
    folder = audio_dirs()[0]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{cid}{ext}"
    path.write_bytes(await file.read())
    job = {"job_id": db.new_id("job"), "kind": "audio", "total": 1, "done": 0, "failed": 0, "errors": [],
           "status": "running", "stage": "загрузка", "conversation_id": None, "started_at": db.now()}
    with _jobs_lock:
        _jobs[job["job_id"]] = job
    threading.Thread(target=_run_audio_job, args=(job, path, cid, language or None), daemon=True).start()
    return job


@router.post("/dialogs/upload")
def upload(payload: dict | list = Body(...)):
    records = payload["data"]["records"] if isinstance(payload, dict) and "data" in payload else \
        payload if isinstance(payload, list) else [payload]
    for d in records:
        if not {"conversation_id", "transcript"} <= set(d):
            _err(422, "Нужны поля conversation_id и transcript")
        db.upsert_dialog(d)
    return {"imported": len(records)}


@router.post("/datasets/{group_id}/import")
def import_dataset(group_id: str):
    """Забрать набор у организаторов (DEV или контрольный) по CQA_API_URL из .env."""
    base = os.getenv("CQA_API_URL", "").strip()
    if not base:
        _err(500, "CQA_API_URL не задан в .env")
    url = f"{base}{'&' if '?' in base else '?'}group_id={urllib.parse.quote(group_id)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cqa-backend"}), timeout=120) as r:
            data = json.loads(r.read())
    except Exception as e:  # noqa: BLE001 — URL с подписью в ошибку не пишем
        _err(502, f"API организаторов недоступно: {type(e).__name__}")
    if not data.get("isSuccess"):
        _err(502, f"API организаторов вернуло ошибку: {data.get('error')}")
    records = data["data"]["records"]
    for d in records:
        db.upsert_dialog(d, group_id)
    (data_root() / "data").mkdir(exist_ok=True)
    (data_root() / f"data/{group_id}.json").write_text(json.dumps(data, ensure_ascii=False))
    return {"group_id": group_id, "imported": len(records)}


# ---------- чек-листы ----------
@router.get("/checklists")
def checklists():
    return db.list_checklists()


@router.get("/checklists/{cid}")
def checklist(cid: str, version: int | None = None):
    return db.get_checklist(cid, version) or _err(404, "Чек-лист не найден")


def _validate_checklist(cl: dict) -> None:
    ids = [c.get("id") for c in cl.get("criteria", [])]
    if not ids or len(ids) != len(set(ids)) or not all(ids):
        _err(422, "У каждого критерия должен быть уникальный id")
    for c in cl["criteria"]:
        if c.get("answer_type") not in ("binary", "scale", "flag"):
            _err(422, f"{c['id']}: answer_type должен быть binary, scale или flag")
        if c["answer_type"] == "scale" and not (c.get("scale") or {}).get("steps"):
            _err(422, f"{c['id']}: у шкалы нужны ступени scale.steps")


@router.post("/checklists")
def create_checklist(cl: dict = Body(...)):
    if not cl.get("id"):
        _err(422, "Нужен id чек-листа")
    _validate_checklist(cl)
    return db.save_checklist(cl)


@router.put("/checklists/{cid}")
def update_checklist(cid: str, cl: dict = Body(...)):
    _validate_checklist(cl)
    return db.save_checklist({**cl, "id": cid})          # новая версия; старые оценки ссылаются на свою


# ---------- оценки ----------
def _providers_arg(p) -> str | None:
    if isinstance(p, list):
        return ", ".join(p)
    return p or None


def _evaluate_one(cid: str, checklist_id: str, providers=None, samples=None, include_summary: bool = False) -> dict:
    d = db.get_dialog(cid) or _err(404, f"Диалог {cid} не найден")
    cl = db.get_checklist(checklist_id) or _err(404, f"Чек-лист {checklist_id} не найден")
    ev = evaluate(d, cl, providers=_providers_arg(providers), samples=samples, include_summary=include_summary)
    return db.save_evaluation(ev)


@router.post("/evaluations")
def create_evaluation(body: dict = Body(...)):
    try:
        return _evaluate_one(body.get("conversation_id") or _err(422, "Нужен conversation_id"),
                             body.get("checklist_id") or "default", body.get("providers"), body.get("samples"),
                             include_summary=bool(body.get("include_summary", False)))
    except LLMError as e:
        _err(503, f"Модель недоступна: {e}")
    except ScoringError as e:
        _err(422, str(e))


@router.get("/evaluations/{eid}")
def get_evaluation(eid: str):
    return db.get_evaluation(eid) or _err(404, "Оценка не найдена")


_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _run_job(job: dict, ids: list[str], body: dict) -> None:
    def one(cid):
        try:
            _evaluate_one(cid, body.get("checklist_id") or "default", body.get("providers"), body.get("samples"),
                          include_summary=bool(body.get("include_summary", False)))
            key = "done"
        except Exception as e:  # noqa: BLE001
            key = "failed"
            with _jobs_lock:
                job["errors"].append(f"{cid}: {getattr(e, 'detail', e)}"[:300])
        with _jobs_lock:
            job[key] += 1

    with ThreadPoolExecutor(max_workers=int(os.getenv("BATCH_WORKERS", "3"))) as pool:
        list(pool.map(one, ids))
    with _jobs_lock:
        job["status"] = "done"
        job["finished_at"] = db.now()


def _run_summaries(job: dict, ids: list[str], providers) -> None:
    def one(cid):
        d, ev = db.get_dialog(cid), db.latest_evaluation(cid)
        s = summarize_dialog(d, _providers_arg(providers)) if d and ev else None
        with _jobs_lock:
            if s:
                ev["summary"] = s
                db.save_evaluation(ev)
                job["done"] += 1
            else:
                job["failed"] += 1
                job["errors"].append(f"{cid}: сводка не получена")
    with ThreadPoolExecutor(max_workers=int(os.getenv("BATCH_WORKERS", "3"))) as pool:
        list(pool.map(one, ids))
    with _jobs_lock:
        job["status"] = "done"
        job["finished_at"] = db.now()


@router.post("/evaluations/batch")
def batch(body: dict = Body(...)):
    """{group_id?, conversation_ids?, checklist_id?, providers?, samples?, only_missing?} → {job_id}."""
    if body.get("conversation_ids"):
        ids = list(body["conversation_ids"])
    else:
        ids = [d["conversation_id"] for d in db.list_dialogs(group_id=body.get("group_id"))]
    if body.get("summaries_only"):
        # досоздать сводки к уже оценённым диалогам, не переоценивая их
        latest = db.latest_evaluations()
        ids = [i for i in ids if latest.get(i) and not latest[i].get("summary")]
        job = {"job_id": db.new_id("job"), "total": len(ids), "done": 0, "failed": 0, "errors": [], "status": "running",
               "started_at": db.now(), "kind": "summaries"}
        with _jobs_lock:
            _jobs[job["job_id"]] = job
        threading.Thread(target=_run_summaries, args=(job, ids, body.get("providers")), daemon=True).start()
        return job
    cl = db.get_checklist(body.get("checklist_id") or "default") or _err(404, "Чек-лист не найден")
    if body.get("only_missing", True):
        latest = db.latest_evaluations()
        ids = [i for i in ids if (latest.get(i) or {}).get("checklist_version") != cl["version"]]
    job = {"job_id": db.new_id("job"), "total": len(ids), "done": 0, "failed": 0, "errors": [],
           "status": "running", "started_at": db.now()}
    with _jobs_lock:
        _jobs[job["job_id"]] = job
    threading.Thread(target=_run_job, args=(job, ids, body), daemon=True).start()
    return job


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    with _jobs_lock:
        return dict(_jobs.get(job_id) or _err(404, "Задача не найдена"))


# ---------- апелляции ----------
@router.post("/appeals")
def create_appeal(body: dict = Body(...)):
    ev = db.get_evaluation(body.get("evaluation_id", "")) or _err(404, "Оценка не найдена")
    r = next((r for r in ev["results"] if r["criterion_id"] == body.get("criterion_id")), None) or \
        _err(422, "Нет такого критерия в оценке")
    if not (body.get("comment") or "").strip():
        _err(422, "Нужен комментарий")
    return db.save_appeal({
        "evaluation_id": ev["id"], "conversation_id": ev["conversation_id"], "criterion_id": r["criterion_id"],
        "comment": body["comment"].strip(), "status": "open",
        "original": {"answer": r["answer"], "weighted_score": r.get("weighted_score"), "total_score": ev.get("total_score")},
        "decision": None,
    })


@router.get("/appeals")
def appeals(status: str | None = None, evaluation_id: str | None = None):
    out = []
    for ap in db.list_appeals(status, evaluation_id):
        ev = db.get_evaluation(ap["evaluation_id"]) or {}
        d = db.get_dialog(ap["conversation_id"]) or {}
        r = next((x for x in ev.get("results", []) if x["criterion_id"] == ap["criterion_id"]), {})
        idx = [e["msg_index"] for e in r.get("evidence", [])] + \
              ([r["checked_range"]["from"], r["checked_range"]["to"]] if r.get("checked_range") else [])
        lo, hi = (max(min(idx) - 2, 0), max(idx) + 3) if idx else (0, 6)
        out.append({**ap, "result": r, "fragment": [{**m, "msg_index": i} for i, m in
                                                    enumerate(d.get("transcript", [])) if lo <= i < hi]})
    return out


@router.post("/appeals/{aid}/decision")
def decide(aid: str, body: dict = Body(...)):
    """{action: "confirm"|"change", answer?, reason} → пересчёт итога. Исходная оценка сохраняется в original_*."""
    ap = db.get_appeal(aid) or _err(404, "Апелляция не найдена")
    if ap["status"] != "open":
        _err(409, "По апелляции уже принято решение")
    action, reason = body.get("action"), (body.get("reason") or "").strip()
    if action not in ("confirm", "change") or not reason:
        _err(422, "Нужны action (confirm|change) и reason")
    ev = db.get_evaluation(ap["evaluation_id"]) or _err(404, "Оценка не найдена")
    cl = db.get_checklist(ev["checklist_id"], ev.get("checklist_version")) or db.get_checklist(ev["checklist_id"]) \
        or _err(404, f"Чек-лист {ev['checklist_id']} не найден")
    ev.setdefault("original_total", ev.get("total_score"))
    for r in ev["results"]:
        if r["criterion_id"] != ap["criterion_id"]:
            continue
        r.setdefault("original_answer", r["answer"])
        if action == "change":
            if "answer" not in body:
                _err(422, "Для change нужен answer")
            ans = body["answer"]
            crit = next((c for c in cl["criteria"] if c["id"] == r["criterion_id"]), {})
            if crit.get("answer_type") == "scale" and ans != "na":
                try:
                    ans = int(float(ans))
                except (TypeError, ValueError):
                    _err(422, "Для шкалы answer — число из ступеней или na")
            r["answer"] = ans
        r.update(source="appeal", appeal_id=aid, reviewer_reason=reason, needs_review=False)
    try:
        ev = recompute(ev, cl)
    except ScoringError as e:
        _err(422, str(e))
    ev["final_total"] = ev["total_score"]
    ev["needs_review"] = any(r.get("needs_review") for r in ev["results"])
    db.save_evaluation(ev)
    ap.update(status="changed" if action == "change" else "confirmed",
              decision={"action": action, "answer": body.get("answer"), "reason": reason, "decided_at": db.now()},
              final={"total_score": ev["total_score"]})
    db.save_appeal(ap)
    return {"appeal": ap, "evaluation": ev}


def error_handler(_: Request, exc: Exception) -> JSONResponse:
    status = getattr(exc, "status_code", 500)
    return JSONResponse({"error": getattr(exc, "detail", str(exc))}, status_code=status)
