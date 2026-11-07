"""CQA backend: API + раздача фронта.

    uvicorn backend.main:app --reload --port 8000     → http://localhost:8000

При первом запуске сам наполняет базу: чек-лист из checklists/default.json, диалоги из data/DEV.json
(или fixtures/, если набора нет) и готовые оценки из dataset/DEV/evaluations/ (если есть).
"""
import base64
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
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


@app.middleware("http")
async def basic_auth(request, call_next):
    """CQA_BASIC_AUTH=логин:пароль закрывает сайт и API паролем для тех, кто пришёл через Cloudflare
    (у таких запросов есть заголовок cf-connecting-ip). Локально (localhost) пароль не спрашивается,
    если не задан CQA_AUTH_LOCAL=1. /api/health открыт всегда — для проверки, что сервер жив."""
    creds = os.getenv("CQA_BASIC_AUTH", "").strip()
    via_cloudflare = "cf-connecting-ip" in request.headers
    if not creds or request.url.path == "/api/health" or not (via_cloudflare or os.getenv("CQA_AUTH_LOCAL") == "1"):
        return await call_next(request)
    header = request.headers.get("authorization", "")
    given = ""
    if header.lower().startswith("basic "):
        try:
            given = base64.b64decode(header[6:]).decode()
        except ValueError:
            given = ""
    if not secrets.compare_digest(given.encode(), creds.encode()):
        return JSONResponse({"error": "Нужен логин и пароль"}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Freedom Broker CQA"'})
    return await call_next(request)


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    """Статика — с ревалидацией (ETag), чтобы после обновления кода браузер не держал старые модули."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response
app.include_router(router)
for name in ("frontend", "fixtures", "checklists"):
    app.mount(f"/{name}", StaticFiles(directory=ROOT / name, html=True), name=name)


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/frontend/")
