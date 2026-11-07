"""API end-to-end на временной базе, оценка — на моке (без сети)."""
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import db

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCORING_MODE", "mock")
    monkeypatch.setenv("CQA_DATA_ROOT", str(tmp_path))  # нет data/DEV.json → seed возьмёт fixtures
    (tmp_path / "data").mkdir()
    db.reset_for_tests(tmp_path / "cqa.db")
    import backend.main as main
    with TestClient(main.app) as c:
        yield c
    db.reset_for_tests(ROOT / "data/cqa.db")


def test_health_and_seed(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["dialogs"] == 2
    assert client.get("/api/checklists/default").json()["version"] >= 2
    assert client.get("/").status_code in (200, 307) and client.get("/frontend/").status_code == 200


def test_dialogs_list_filters_and_derived_fields(client):
    rows = client.get("/api/dialogs").json()
    assert {r["conversation_id"] for r in rows} == {"fixture-chat-ru", "fixture-call-en"}
    assert all(r["evaluation_status"] == "not_started" for r in rows)
    assert [r["conversation_id"] for r in client.get("/api/dialogs?language=EN").json()] == ["fixture-call-en"]
    call = client.get("/api/dialogs/fixture-call-en").json()
    assert call["transcript"][2]["offset_sec"] == 15.0 and call["audio_src"].endswith("/audio")
    assert client.get("/api/dialogs/nope").status_code == 404
    assert client.get("/api/dialogs/nope").json() == {"error": "Диалог nope не найден"}


def test_evaluate_then_latest(client):
    assert client.get("/api/dialogs/fixture-chat-ru/evaluation").status_code == 404
    ev = client.post("/api/evaluations", json={"conversation_id": "fixture-chat-ru", "checklist_id": "default",
                                               "providers": "claude_cli, codex_cli", "samples": 2}).json()
    assert ev["id"].startswith("ev_") and len(ev["results"]) == 8
    assert client.get(f"/api/evaluations/{ev['id']}").json()["id"] == ev["id"]
    assert client.get("/api/dialogs/fixture-chat-ru/evaluation").json()["id"] == ev["id"]
    row = next(r for r in client.get("/api/dialogs").json() if r["conversation_id"] == "fixture-chat-ru")
    assert row["evaluation_status"] == "done" and row["total_score"] == ev["total_score"]


def test_batch_job(client):
    job = client.post("/api/evaluations/batch", json={"checklist_id": "default"}).json()
    st = job
    for _ in range(50):
        st = client.get(f"/api/jobs/{job['job_id']}").json()
        if st["status"] == "done":
            break
        time.sleep(0.05)
    assert st["done"] == 2 and st["failed"] == 0
    again = client.post("/api/evaluations/batch", json={"checklist_id": "default"}).json()
    assert again["total"] == 0                          # only_missing: уже оценены этой версией


def test_checklist_new_version_and_validation(client):
    cl = client.get("/api/checklists/default").json()
    cl["criteria"][0]["title"] = "Новый текст"
    saved = client.put("/api/checklists/default", json=cl).json()
    assert saved["version"] == cl["version"] + 1
    assert client.get(f"/api/checklists/default?version={cl['version']}").json()["criteria"][0]["title"] != "Новый текст"
    bad = {**cl, "criteria": [{"id": "x", "answer_type": "scale"}]}
    assert client.put("/api/checklists/default", json=bad).status_code == 422


def test_appeal_change_recomputes_and_keeps_original(client):
    ev = client.post("/api/evaluations", json={"conversation_id": "fixture-chat-ru"}).json()
    target = next(r for r in ev["results"] if r["criterion_id"] == "contact")
    new_answer = "no" if target["answer"] == "yes" else "yes"
    ap = client.post("/api/appeals", json={"evaluation_id": ev["id"], "criterion_id": "contact",
                                           "comment": "Оператор не представился"}).json()
    queue = client.get("/api/appeals?status=open").json()
    assert queue[0]["id"] == ap["id"] and queue[0]["fragment"] and queue[0]["result"]["criterion_id"] == "contact"
    out = client.post(f"/api/appeals/{ap['id']}/decision",
                      json={"action": "change", "answer": new_answer, "reason": "Проверил"}).json()
    e2 = out["evaluation"]
    r2 = next(r for r in e2["results"] if r["criterion_id"] == "contact")
    assert r2["answer"] == new_answer and r2["original_answer"] == target["answer"] and r2["source"] == "appeal"
    assert e2["original_total"] == ev["total_score"] and e2["final_total"] == e2["total_score"]
    assert out["appeal"]["status"] == "changed"
    assert client.post(f"/api/appeals/{ap['id']}/decision", json={"action": "confirm", "reason": "x"}).status_code == 409


def test_providers_and_upload(client):
    p = client.get("/api/llm/providers").json()
    assert {x["id"] for x in p["presets"]} >= {"claude", "codex", "compare"}
    up = client.post("/api/dialogs/upload", json={"conversation_id": "u1", "channel": "agent chat", "language": "RU",
                                                  "transcript": [{"timestamp": "00:00", "speaker": "operator", "text": "Привет"}]})
    assert up.json() == {"imported": 1} and client.get("/api/dialogs/u1").status_code == 200


def test_audio_served_from_local_cache(client, tmp_path):
    (tmp_path / "data/audio").mkdir(parents=True)
    (tmp_path / "data/audio/fixture-call-en.mp3").write_bytes(b"ID3" + b"0" * 2000)
    r = client.get("/api/dialogs/fixture-call-en/audio", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100 and r.headers["content-type"] == "audio/mpeg"


def test_appeal_decision_when_checklist_missing_is_404(client):
    ev = client.post("/api/evaluations", json={"conversation_id": "fixture-chat-ru"}).json()
    ap = client.post("/api/appeals", json={"evaluation_id": ev["id"], "criterion_id": "contact", "comment": "x"}).json()
    ev["checklist_id"] = "deleted"
    db.save_evaluation(ev)
    r = client.post(f"/api/appeals/{ap['id']}/decision", json={"action": "confirm", "reason": "ok"})
    assert r.status_code == 404 and "Чек-лист" in r.json()["error"]


def test_stats(client):
    client.post("/api/evaluations", json={"conversation_id": "fixture-chat-ru"})
    s = client.get("/api/stats").json()
    assert s["dialogs"] == 2 and s["evaluated"] == 1 and s["open_appeals"] == 0
    assert len(s["criteria"]) == 8 and s["groups"][0]["count"] == 1


def test_basic_auth_when_enabled(client, monkeypatch):
    monkeypatch.setenv("CQA_BASIC_AUTH", "jury:secret")
    cf = {"cf-connecting-ip": "203.0.113.5"}
    assert client.get("/api/dialogs").status_code == 200                 # локально — без пароля
    assert client.get("/api/health", headers=cf).status_code == 200
    assert client.get("/api/dialogs", headers=cf).status_code == 401
    assert client.get("/frontend/", headers=cf).status_code == 401
    assert client.get("/api/dialogs", headers=cf, auth=("jury", "wrong")).status_code == 401
    assert client.get("/api/dialogs", headers=cf, auth=("jury", "secret")).status_code == 200


def test_upload_audio_creates_call(client, monkeypatch):
    import backend.asr as asr

    def fake(path, cid, language=None):
        return {"conversation_id": cid, "channel": "voice call", "language": "RU", "audio_url": None,
                "transcript": [{"timestamp": "2026-11-07T10:00:00+00:00", "speaker": "system", "text": "загружено"},
                               {"timestamp": "2026-11-07T10:00:03+00:00", "speaker": "operator", "text": "Здравствуйте"}]}
    monkeypatch.setattr(asr, "audio_to_dialog", fake)
    bad = client.post("/api/dialogs/upload-audio", files={"file": ("x.txt", b"hi", "text/plain")})
    assert bad.status_code == 422
    job = client.post("/api/dialogs/upload-audio", files={"file": ("Звонок 1.mp3", b"ID3" + b"0" * 500, "audio/mpeg")},
                      data={"conversation_id": "my-call"}).json()
    for _ in range(50):
        st = client.get(f"/api/jobs/{job['job_id']}").json()
        if st["status"] == "done":
            break
        time.sleep(0.05)
    assert st["conversation_id"] == "my-call" and st["failed"] == 0
    d = client.get("/api/dialogs/my-call").json()
    assert d["channel"] == "voice call" and d["audio_src"].endswith("/audio") and d["transcript"][1]["offset_sec"] == 3.0
    assert client.get("/api/dialogs/my-call/audio").headers["content-type"] == "audio/mpeg"
