"""Separate translation stage tests; scoring decisions remain untouched."""
from backend.llm import LLMResult
from backend.scoring.translation import translate_explanations


def test_translation_populates_three_languages_and_preserves_source(monkeypatch):
    source = "Оператор уточнил вопрос клиента."
    translated = {
        "criteria": {
            "needs": {
                "explanations": {
                    "ru": source,
                    "kz": "Оператор клиенттің сұрағын нақтылады.",
                    "en": "The operator clarified the client's question.",
                },
                "na_reasons": {"ru": "", "kz": "", "en": ""},
            }
        }
    }
    calls = []

    def fake(system, user, schema, spec=None):
        calls.append((system, user, schema, spec))
        return LLMResult(data=translated, model="translator", input_tokens=50, output_tokens=30)

    monkeypatch.setattr("backend.scoring.translation.call_json", fake)
    evaluation = {
        "cost_usd": 0.01,
        "tokens": {"input": 100, "output": 40, "cache_read": 0, "calls": 1},
        "results": [{
            "criterion_id": "needs", "answer": "yes", "evidence": [{"msg_index": 2, "quote": "Уточните"}],
            "flags": [], "_source_language": "ru", "_source_explanation": source, "_source_na_reason": "",
        }],
    }
    dialog = {"language": "RU"}
    checklist = {"criteria": [{"id": "needs"}]}
    result = translate_explanations(evaluation, dialog, checklist, "local")

    item = result["results"][0]
    assert len(calls) == 1 and calls[0][3] == "local"
    assert item["explanations"]["ru"] == source
    assert item["explanations"]["kz"] == translated["criteria"]["needs"]["explanations"]["kz"]
    assert item["explanations"]["en"] == translated["criteria"]["needs"]["explanations"]["en"]
    assert item["explanation"] == source
    assert "_source_explanation" not in item
    assert result["tokens"]["calls"] == 2 and result["tokens"]["input"] == 150


def test_translation_rejects_changed_canonical_explanation(monkeypatch):
    monkeypatch.setattr(
        "backend.scoring.translation.call_json",
        lambda *args, **kwargs: LLMResult(data={"criteria": {"needs": {
            "explanations": {"ru": "Изменённый текст", "kz": "Қазақша", "en": "English"},
            "na_reasons": {"ru": "", "kz": "", "en": ""},
        }}}, model="translator"),
    )
    evaluation = {"results": [{
        "criterion_id": "needs", "answer": "yes",
        "_source_language": "ru", "_source_explanation": "Исходный текст", "_source_na_reason": "",
    }], "tokens": {}}
    import pytest
    from backend.llm import LLMOutputError
    with pytest.raises(LLMOutputError, match="changed canonical|changed canonical|измен"):
        translate_explanations(evaluation, {"language": "RU"}, {"criteria": [{"id": "needs"}]}, "local")
