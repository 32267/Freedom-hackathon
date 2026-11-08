import json
from pathlib import Path

from backend.scoring import summary

ROOT = Path(__file__).parent.parent
CHAT = json.loads((ROOT / "fixtures/dialog.chat.json").read_text())


def test_clean_drops_unproven_issues_and_masked_names():
    t = {"ru": "x", "kz": "x", "en": "x"}
    raw = {"reason": t, "done": t, "status": "partially_resolved", "next_step": t, "operator_name": "[Имя скрыто]",
           "open_issues": [{"kind": "incomplete", "text": t, "msg_index": 4, "quote": "Вывести можно свободный остаток"},
                           {"kind": "unresolved", "text": t, "msg_index": 2, "quote": "выдуманная цитата"}]}
    out = summary._clean(raw, CHAT["transcript"])
    assert [i["msg_index"] for i in out["open_issues"]] == [5]       # индекс поправлен на реальную реплику
    assert out["operator_name"] == ""


def test_summarize_falls_back_and_returns_none(monkeypatch):
    from backend.llm import LLMError, LLMResult
    calls = []

    def fake(system, user, schema, spec=None):
        calls.append(spec)
        if spec == "claude_cli":
            raise LLMError("лимит")
        t = {"ru": "ok", "kz": "ok", "en": "ok"}
        return LLMResult(data={"reason": t, "done": t, "status": "resolved", "open_issues": [], "next_step": t,
                               "operator_name": "Анна"}, model="m")
    monkeypatch.setattr(summary, "call_json", fake)
    monkeypatch.setattr(summary, "is_alive", lambda s: True)
    out = summary.summarize(CHAT, "claude_cli | codex_cli")
    assert out["operator_name"] == "Анна" and calls == ["claude_cli", "codex_cli"]
    monkeypatch.setattr(summary, "call_json", lambda *a, **k: (_ for _ in ()).throw(LLMError("нет")))
    assert summary.summarize(CHAT, "claude_cli") is None
