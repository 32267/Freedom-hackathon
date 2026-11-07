"""Хранилище SQLite (data/cqa.db). Документы лежат как JSON — схема данных задаётся docs/CONTRACTS.md."""
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("CQA_DB") or Path(__file__).resolve().parent.parent / "data/cqa.db")
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS dialogs (
  conversation_id TEXT PRIMARY KEY, group_id TEXT, channel TEXT, language TEXT, doc TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checklists (
  id TEXT NOT NULL, version INTEGER NOT NULL, doc TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (id, version));
CREATE TABLE IF NOT EXISTS evaluations (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, checklist_id TEXT, checklist_version INTEGER,
  doc TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ev_by_dialog ON evaluations(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS appeals (
  id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL, status TEXT NOT NULL, doc TEXT NOT NULL, created_at TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
        return _conn


def reset_for_tests(path: Path) -> None:
    global _conn, DB_PATH
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn, DB_PATH = None, path


def _q(sql: str, args=()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, args).fetchall()


def _x(sql: str, args=()) -> None:
    with _lock:
        c = conn()
        c.execute(sql, args)
        c.commit()


# ---- dialogs ----
def upsert_dialog(d: dict, group_id: str | None = None) -> None:
    group_id = group_id or d.get("dataset_group_id") or "UPLOAD"
    doc = {**d, "dataset_group_id": group_id}
    _x("INSERT INTO dialogs VALUES (?,?,?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET "
       "group_id=excluded.group_id, channel=excluded.channel, language=excluded.language, doc=excluded.doc",
       (d["conversation_id"], group_id, d.get("channel"), d.get("language"), json.dumps(doc, ensure_ascii=False), now()))


def get_dialog(cid: str) -> dict | None:
    rows = _q("SELECT doc FROM dialogs WHERE conversation_id=?", (cid,))
    return json.loads(rows[0]["doc"]) if rows else None


def list_dialogs(group_id=None, language=None, channel=None) -> list[dict]:
    sql, args = "SELECT doc FROM dialogs WHERE 1=1", []
    for col, val in (("group_id", group_id), ("language", language), ("channel", channel)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    return [json.loads(r["doc"]) for r in _q(sql + " ORDER BY group_id, conversation_id", args)]


def count_dialogs() -> int:
    return _q("SELECT COUNT(*) n FROM dialogs")[0]["n"]


# ---- checklists ----
def save_checklist(cl: dict, bump: bool = True) -> dict:
    with _lock:
        latest = get_checklist(cl["id"])
        version = (latest["version"] + 1) if (latest and bump) else (cl.get("version") or 1)
        if latest and not bump and latest["version"] >= version:
            return latest
        doc = {**cl, "version": version}
        _x("INSERT OR REPLACE INTO checklists VALUES (?,?,?,?)", (cl["id"], version, json.dumps(doc, ensure_ascii=False), now()))
        return doc


def get_checklist(cid: str, version: int | None = None) -> dict | None:
    if version:
        rows = _q("SELECT doc FROM checklists WHERE id=? AND version=?", (cid, version))
    else:
        rows = _q("SELECT doc FROM checklists WHERE id=? ORDER BY version DESC LIMIT 1", (cid,))
    return json.loads(rows[0]["doc"]) if rows else None


def list_checklists() -> list[dict]:
    rows = _q("SELECT doc FROM checklists c WHERE version=(SELECT MAX(version) FROM checklists WHERE id=c.id)")
    return [json.loads(r["doc"]) for r in rows]


# ---- evaluations ----
def save_evaluation(ev: dict) -> dict:
    ev = {**ev, "id": ev.get("id") or new_id("ev")}
    _x("INSERT OR REPLACE INTO evaluations VALUES (?,?,?,?,?,?)",
       (ev["id"], ev["conversation_id"], ev.get("checklist_id"), ev.get("checklist_version"),
        json.dumps(ev, ensure_ascii=False), ev.get("created_at") or now()))
    return ev


def get_evaluation(eid: str) -> dict | None:
    rows = _q("SELECT doc FROM evaluations WHERE id=?", (eid,))
    return json.loads(rows[0]["doc"]) if rows else None


def latest_evaluation(cid: str) -> dict | None:
    rows = _q("SELECT doc FROM evaluations WHERE conversation_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (cid,))
    return json.loads(rows[0]["doc"]) if rows else None


def latest_evaluations() -> dict[str, dict]:
    rows = _q("SELECT conversation_id, doc FROM evaluations ORDER BY created_at, rowid")
    return {r["conversation_id"]: json.loads(r["doc"]) for r in rows}


def count_evaluations() -> int:
    return _q("SELECT COUNT(*) n FROM evaluations")[0]["n"]


# ---- appeals ----
def save_appeal(ap: dict) -> dict:
    ap = {**ap, "id": ap.get("id") or new_id("ap"), "created_at": ap.get("created_at") or now()}
    _x("INSERT OR REPLACE INTO appeals VALUES (?,?,?,?,?)",
       (ap["id"], ap["evaluation_id"], ap["status"], json.dumps(ap, ensure_ascii=False), ap["created_at"]))
    return ap


def get_appeal(aid: str) -> dict | None:
    rows = _q("SELECT doc FROM appeals WHERE id=?", (aid,))
    return json.loads(rows[0]["doc"]) if rows else None


def list_appeals(status: str | None = None, evaluation_id: str | None = None) -> list[dict]:
    sql, args = "SELECT doc FROM appeals WHERE 1=1", []
    if status:
        sql += " AND status=?"
        args.append(status)
    if evaluation_id:
        sql += " AND evaluation_id=?"
        args.append(evaluation_id)
    return [json.loads(r["doc"]) for r in _q(sql + " ORDER BY created_at DESC", args)]
