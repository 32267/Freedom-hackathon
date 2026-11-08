"""Сводка разговора для следующего обращения клиента.

После оценки модель составляет: с чем клиент обращался, что оператор сделал, что осталось нерешённым или
объяснено не полностью (каждый пункт — с цитатой-доказательством), следующий шаг и имя оператора (для рейтинга).
При повторном звонке оператор видит сводки прошлых обращений клиента и продолжает с того же места.
Цитаты проверяются так же, как в оценке: пункт без подтверждённой цитаты отбрасывается.
"""
from backend.llm import LLMError, call_json, is_alive, provider_tiers

from .prompt import _fmt_transcript
from .validate import _find_quote

LANGS = ("ru", "kz", "en")


def _i18n() -> dict:
    return {"type": "object", "properties": {lang: {"type": "string"} for lang in LANGS},
            "required": list(LANGS), "additionalProperties": False}


SCHEMA = {
    "type": "object",
    "properties": {
        "reason": _i18n(),
        "done": _i18n(),
        "status": {"type": "string", "enum": ["resolved", "partially_resolved", "unresolved"]},
        "open_issues": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["unresolved", "incomplete"]},
                "text": _i18n(),
                "msg_index": {"type": "integer"},
                "quote": {"type": "string"},
            },
            "required": ["kind", "text", "msg_index", "quote"], "additionalProperties": False}},
        "next_step": _i18n(),
        "operator_name": {"type": "string"},
    },
    "required": ["reason", "done", "status", "open_issues", "next_step", "operator_name"],
    "additionalProperties": False,
}

SYSTEM = """Ты готовишь сводку разговора клиента с поддержкой брокера Freedom Broker для оператора, который
примет следующее обращение этого клиента. Цель — чтобы клиенту не пришлось заново объяснять историю.

Заполни:
- reason — с чем обращался клиент (1–2 предложения).
- done — что оператор уже сделал или объяснил (1–3 предложения). Только то, что есть в диалоге.
- status — resolved (вопрос закрыт), partially_resolved (частично), unresolved (не решён).
- open_issues — что осталось: kind=unresolved — вопрос клиента без ответа или решения; kind=incomplete — оператор
  объяснил не полностью (не хватает шага, срока, условия). Каждый пункт подтверди цитатой: msg_index — номер реплики
  в квадратных скобках, quote — дословный фрагмент этой реплики (3–15 слов). Если всё решено — пустой список.
- next_step — что сделать при следующем обращении (например: «проверить, зачислен ли перевод в тенге»).
- operator_name — имя оператора, если он представился ([Имя скрыто] или нет имени — пустая строка).
Тексты reason, done, open_issues.text и next_step пиши на трёх языках: ru — русский, kz — казахский (кириллица),
en — английский. Не выдумывай того, чего нет в диалоге; бот и системные события — контекст."""


def _clean(raw: dict, transcript: list[dict]) -> dict:
    issues = []
    for it in raw.get("open_issues") or []:
        idx = it.get("msg_index")
        found = _find_quote(it.get("quote", ""), min(max(idx if isinstance(idx, int) else 0, 0), max(len(transcript) - 1, 0)),
                            transcript) if transcript else None
        if found is None:
            continue                                   # замечание без подтверждённой цитаты не показываем
        issues.append({"kind": it.get("kind", "unresolved"), "text": it.get("text", {}), "msg_index": found,
                       "quote": it.get("quote", "")})
    name = (raw.get("operator_name") or "").strip()
    if "скрыто" in name.lower() or len(name) > 40:
        name = ""
    return {"reason": raw.get("reason", {}), "done": raw.get("done", {}), "status": raw.get("status", "unresolved"),
            "open_issues": issues, "next_step": raw.get("next_step", {}), "operator_name": name}


def summarize(dialog: dict, providers: str | None = None) -> dict | None:
    """Сводка разговора или None, если ни один оценщик не ответил (оценка от этого не страдает)."""
    user = (f'Диалог {dialog["conversation_id"]} · канал: {dialog.get("channel")} · язык: {dialog.get("language")}\n\n'
            f"Транскрипт:\n{_fmt_transcript(dialog)}")
    for tier in provider_tiers(providers):
        for spec in tier:
            if not is_alive(spec):
                continue
            try:
                res = call_json(SYSTEM, user, SCHEMA, spec)
            except LLMError:
                continue
            out = _clean(res.data, dialog.get("transcript", []))
            out.update(model=res.model, cost_usd=res.cost_usd)
            return out
    return None


def mock_summary(dialog: dict) -> dict:
    ops = [i for i, m in enumerate(dialog.get("transcript", [])) if m.get("speaker") == "operator"]
    i = ops[-1] if ops else 0
    text = dialog["transcript"][i]["text"] if dialog.get("transcript") else ""
    t = lambda s: {"ru": s, "kz": s, "en": s}  # noqa: E731
    return {"reason": t("[MOCK] Клиент обратился с вопросом."), "done": t("[MOCK] Оператор ответил."),
            "status": "partially_resolved",
            "open_issues": [{"kind": "incomplete", "text": t("[MOCK] Не уточнены сроки."), "msg_index": i, "quote": text[:60]}] if text else [],
            "next_step": t("[MOCK] Уточнить, решён ли вопрос."), "operator_name": "", "model": "mock", "cost_usd": 0.0}
