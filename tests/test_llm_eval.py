"""LLM-оценка без сети: call_json подменяется фейком."""
import json
from pathlib import Path

import pytest

from backend.llm import LLMResult
from backend.scoring import llm_eval
from backend.scoring.prompt import build_schema, build_system, build_user
from backend.scoring.validate import check_criterion

ROOT = Path(__file__).parent.parent
CL = json.loads((ROOT / "checklists/default.json").read_text())
CHAT = json.loads((ROOT / "fixtures/dialog.chat.json").read_text())
BY_ID = {c["id"]: c for c in CL["criteria"]}


def tri(text):
    return {"ru": text, "kz": text, "en": text}


EMPTY = {"ru": "", "kz": "", "en": ""}


def good(answer, idx=3, quote="меня зовут Анна", **kw):
    return {"evidence": [{"msg_index": idx, "quote": quote}], "explanation": tri("ok"),
            "checked_range": [], "na_reason": EMPTY, "answer": answer, **kw}


GOOD = {
    "contact": good("yes"),
    "needs": good("yes", quote="какую ошибку вы видите"),
    "identification": {**good("na"), "evidence": [], "na_reason": tri("Общий вопрос, данные не раскрывались")},
    "consultation": good("15", idx=5, quote="Вывести можно свободный остаток"),
    "empathy": good("yes"),
    "dialog_management": good("10", idx=5, quote="Часть средств заблокирована"),
    "closing": good("yes", idx=7, quote="Хорошего дня"),
    "gross_errors": {"evidence": [], "explanation": tri("Нарушений нет"), "checked_range": [], "na_reason": EMPTY,
                     "flags": [], "answer": "no"},
}


def fake(responses):
    calls = []

    def _call(system, user, schema, spec=None):
        calls.append({"user": user, "schema": schema})
        return LLMResult(data={"criteria": responses[len(calls) - 1]}, model="fake", input_tokens=1000,
                         output_tokens=500, cost_usd=0.01)
    return _call, calls


def test_schema_follows_checklist():
    s = build_schema(CL)["properties"]["criteria"]
    assert set(s["required"]) == set(BY_ID)
    assert s["properties"]["consultation"]["properties"]["answer"]["enum"] == ["20", "15", "10", "5", "0", "na"]
    assert "na" not in s["properties"]["empathy"]["properties"]["answer"]["enum"]
    assert "flags" in s["properties"]["gross_errors"]["properties"]


def test_prompt_contains_rules_and_numbered_transcript():
    sys_p, user = build_system(CL), build_user(CHAT)
    assert "Общий вопрос о тарифах" in sys_p or "общий вопрос о тарифах" in sys_p
    assert "N/A для этого критерия запрещён" in sys_p
    assert "[3] 00:20 operator: Здравствуйте, меня зовут Анна" in user
    assert "До оператора с клиентом общался бот" in user


def test_quote_validation_fixes_index_and_rejects_fake():
    fixed, probs = check_criterion(good("yes", idx=4), BY_ID["contact"], CHAT["transcript"])
    assert not probs and fixed["evidence"][0]["msg_index"] == 3        # сдвинули на реальную реплику
    _, probs = check_criterion(good("yes", quote="Добрый день, я Олег"), BY_ID["contact"], CHAT["transcript"])
    assert any("не найдена" in p for p in probs)


def _groups(mapping):
    ids = list(BY_ID)
    return [
        {cid: mapping[cid] for cid in ids[start:start + llm_eval.CRITERIA_PER_REQUEST]}
        for start in range(0, len(ids), llm_eval.CRITERIA_PER_REQUEST)
    ]


def test_happy_path_one_criterion_per_call(monkeypatch):
    f, calls = fake(_groups(GOOD))
    monkeypatch.setattr(llm_eval, "call_json", f)
    ev = llm_eval.evaluate_llm(CHAT, CL)
    assert len(calls) == len(BY_ID) == 8 and all(r["validated"] for r in ev["results"])
    assert all(len(c["schema"]["properties"]["criteria"]["required"]) == 1 for c in calls)
    # identification N/A → 80 весов; consultation 15/20 → 15 из 20 → итог 75/80
    assert ev["total_score"] == 93.75 and ev["cost_usd"] == 0.08


def test_retry_only_bad_criteria(monkeypatch):
    bad = {**GOOD, "closing": good("yes", quote="До свидания и всего доброго")}
    grouped = _groups(bad)
    f, calls = fake(grouped + [{"closing": good("yes", idx=7, quote="Хорошего дня")}])
    monkeypatch.setattr(llm_eval, "call_json", f)
    ev = llm_eval.evaluate_llm(CHAT, CL)
    assert len(calls) == 9
    assert list(calls[8]["schema"]["properties"]["criteria"]["properties"]) == ["closing"]
    assert "не найдена" in calls[8]["user"]
    assert all(len(c["schema"]["properties"]["criteria"]["required"]) == 1 for c in calls)
    assert all(r["validated"] for r in ev["results"]) and ev["tokens"]["calls"] == 9


def test_still_bad_after_retry_is_marked(monkeypatch):
    bad = {**GOOD, "closing": good("yes", quote="выдумка")}
    f, _ = fake(_groups(bad) + [{"closing": good("yes", quote="снова выдумка")}])
    monkeypatch.setattr(llm_eval, "call_json", f)
    ev = llm_eval.evaluate_llm(CHAT, CL)
    closing = next(r for r in ev["results"] if r["criterion_id"] == "closing")
    assert closing["validated"] is False and closing["evidence"] == [] and closing["problems"]


def test_flag_counts_as_critical(monkeypatch):
    resp = {**GOOD, "gross_errors": good("yes", idx=5, quote="Часть средств заблокирована", flags=["confidential"])}
    f, _ = fake(_groups(resp))
    monkeypatch.setattr(llm_eval, "call_json", f)
    ev = llm_eval.evaluate_llm(CHAT, CL)
    assert ev["critical_error"] and ev["critical_flags"] == ["confidential"] and ev["total_score"] == 93.75


def test_na_reason_serves_as_explanation():
    raw = {"evidence": [], "explanation": EMPTY, "checked_range": [], "na_reason": tri("Общий вопрос о тарифах"), "answer": "na"}
    fixed, probs = check_criterion(raw, BY_ID["identification"], CHAT["transcript"])
    assert not probs and fixed["explanation"] == "Общий вопрос о тарифах"
    assert fixed["na_reasons"]["en"] == "Общий вопрос о тарифах"


def test_three_languages_required_and_returned():
    raw = good("yes", explanation={"ru": "Поздоровался", "kz": "Сәлемдесті", "en": "Greeted"})
    fixed, probs = check_criterion(raw, BY_ID["contact"], CHAT["transcript"])
    assert not probs and fixed["explanation"] == "Поздоровался"
    assert fixed["explanations"] == {"ru": "Поздоровался", "kz": "Сәлемдесті", "en": "Greeted"}
    _, probs = check_criterion(good("yes", explanation={"ru": "Поздоровался", "kz": "", "en": ""}),
                               BY_ID["contact"], CHAT["transcript"])
    assert any("kz, en" in p for p in probs)


def test_system_prompt_can_be_limited_to_group():
    selected = build_system(CL, only=["contact", "needs"])
    assert "### contact" in selected and "### needs" in selected
    assert "### consultation" not in selected and "### gross_errors" not in selected


def test_schema_asks_for_three_languages():
    p = build_schema(CL)["properties"]["criteria"]["properties"]["contact"]["properties"]
    assert p["explanation"]["required"] == ["ru", "kz", "en"] and p["na_reason"]["required"] == ["ru", "kz", "en"]


def test_call_timestamps_shortened_in_prompt_only():
    call = json.loads((ROOT / "fixtures/dialog.call.json").read_text())
    user = build_user(call)
    assert "[0] 10:00:00 operator:" in user and "+05:00" not in user
    assert call["transcript"][0]["timestamp"] == "2026-11-01T10:00:00+05:00"


def test_insufficient_prefix_detected():
    raw = good("yes", explanation=tri("Недостаточно данных: начало записи отсутствует"))
    fixed, probs = check_criterion(raw, BY_ID["contact"], CHAT["transcript"])
    assert not probs and fixed["insufficient"] is True


def test_contact_na_only_for_calls():
    cl = json.loads((ROOT / "checklists/default.json").read_text())
    contact = next(c for c in cl["criteria"] if c["id"] == "contact")
    raw = {"evidence": [], "explanation": tri("Приветствие не попало в запись"), "checked_range": [],
           "na_reason": tri("Запись началась после приветствия"), "answer": "na"}
    _, probs = check_criterion(raw, contact, CHAT["transcript"], "agent chat")
    assert any("только в канале" in p for p in probs)
    _, probs = check_criterion(raw, contact, CHAT["transcript"], "voice call")
    assert not probs
