"""CQA backend: API + раздача фронта.

    uvicorn backend.main:app --reload --port 8000     → http://localhost:8000

При первом запуске сам наполняет базу: чек-лист из checklists/default.json, диалоги из data/DEV.json
(или fixtures/, если набора нет) и готовые оценки из dataset/DEV/evaluations/ (если есть).
"""
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from backend import db  # noqa: E402
from backend.api import data_root, error_handler, router  # noqa: E402

log = logging.getLogger("cqa")
ROOT = Path(__file__).resolve().parent.parent


def seed() -> None:
    cl = json.loads((ROOT / "checklists/default.json").read_text())
    db.save_checklist(cl, bump=False)
    if db.count_dialogs() == 0:
        dev = data_root() / "data/DEV.json"
        if dev.exists():
            data = json.loads(dev.read_text())
            for d in data["data"]["records"]:
                db.upsert_dialog(d, data["data"].get("dataset_group_id", "DEV"))
        else:
            for f in sorted((ROOT / "fixtures").glob("dialog.*.json")):
                db.upsert_dialog(json.loads(f.read_text()))
    if db.count_evaluations() == 0:
        for f in sorted((data_root() / "dataset/DEV/evaluations").glob("*.json")):
            ev = json.loads(f.read_text())
            if isinstance(ev, dict) and "results" in ev and db.get_dialog(ev.get("conversation_id", "")):
                db.save_evaluation(ev)
    log.info("CQA: диалогов %s, оценок %s", db.count_dialogs(), db.count_evaluations())


@asynccontextmanager
async def lifespan(_app):
    seed()
    yield


app = FastAPI(title="CQA — Conversation Quality Analytics", lifespan=lifespan)
app.add_exception_handler(HTTPException, error_handler)
app.include_router(router)
for name in ("frontend", "fixtures", "checklists"):
    app.mount(f"/{name}", StaticFiles(directory=ROOT / name, html=True), name=name)


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/frontend/")
