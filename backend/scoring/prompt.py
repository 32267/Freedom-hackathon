"""Компактный промпт и JSON-схема строятся из чек-листа; критерии из UI поддерживаются без правки кода."""

LANGS = ("ru", "kz", "en")


def _i18n_schema() -> dict:
    return {"type": "object", "properties": {lang: {"type": "string"} for lang in LANGS},
            "required": list(LANGS), "additionalProperties": False}


def _criterion_block(c: dict) -> str:
    lines = [f'### {c["id"]} — {c["title"]}']
    if c["answer_type"] == "binary":
        opts = "yes/no" + ("/na" if c.get("na_allowed") else "")
        lines.append(f'Тип: binary ({opts}); вес {c["weight"]}.')
    elif c["answer_type"] == "scale":
        vals = ", ".join(f'{s["value"]}: {s["label"]}' for s in c["scale"]["steps"])
        lines.append(f'Тип: scale; допустимые значения: {vals}'
                     + (", na" if c.get("na_allowed") else "") + f'; вес {c["weight"]}.')
    else:
        flags = "; ".join(f'{f["id"]}={f["label"]}' for f in c.get("flag_types", []))
        lines.append(f'Тип: flag; yes=нарушение, no=нарушения нет. При yes укажи flags: {flags}.')
    lines.append(f'Правило: {c["description"]}')
    if c.get("lower_if"):
        lines.append("Снижай, если: " + "; ".join(c["lower_if"]) + ".")
    if c.get("keep_if"):
        lines.append("Не снижай / учитывай исключения: " + "; ".join(c["keep_if"]) + ".")
    if c.get("na_allowed") and c.get("na_rule"):
        lines.append(f'N/A только если: {c["na_rule"]}')
    elif c["answer_type"] != "flag":
        lines.append("N/A для этого критерия запрещён.")
    return "\n".join(lines)


def build_system(checklist: dict, only: list[str] | None = None) -> str:
    notes = "\n".join(f"- {n}" for n in checklist.get("notes", []))
    selected = [c for c in checklist["criteria"] if not only or c["id"] in only]
    criteria = "\n\n".join(_criterion_block(c) for c in selected)
    return f"""Ты — аудитор качества поддержки Freedom Broker. Оценивай только фактические действия и реплики оператора по чек-листу «{checklist["name"]}».

Транскрипт пронумерован; роли operator, client, bot, system. bot/system — только контекст, их действия не засчитывай оператору. Системные события о подтверждении личности, закрытии чата, выходе клиента, разрыве соединения и паузах записи — факты. Скрытые маркеры персональных данных означают, что данные были произнесены. В звонках возможны ошибки распознавания: оценивай смысл, не качество транскрипции.

Общие правила чек-листа:
{notes}

Порядок оценки:
1. Сначала проверь применимость критерия и условия N/A: явное na_rule или исключение keep_if, означающее неприменимость, даёт na, если разрешено.
2. keep_if имеет приоритет над похожим lower_if. Не отменяй исключение общим правилом.
3. Определи требуемое в ситуации действие. Не требуй необязательных вопросов, скриптовых фраз или эмоций.
4. Учитывай только подтверждённые действия оператора; не делай выводов по предположениям или действиям других ролей.
5. Затем примени description/lower_if. Для шкалы выбери одну подходящую ступень; штрафы не суммируй автоматически.
6. answer должен подтверждаться evidence и checked_range. Не выдумывай факты. При нехватке данных начни explanation с «Недостаточно данных:».

Формат:
- Верни только объект по JSON Schema, без Markdown и текста вокруг.
- evidence: точная цитата из реплики на языке оригинала и её индекс; обычно 3–15 слов. Не переводи цитату.
- explanation: максимум ОДНО короткое предложение на каждом из ru/kz/en (ориентир до 18 слов на язык); одинаковый смысл, без повторов и вводных фраз.
- checked_range: [from,to] — участок, где ожидалось пропущенное действие; иначе [].
- na_reason: краткая причина N/A на ru/kz/en; если не N/A — пустые строки.
- Сначала найди evidence, затем выбери answer.

Критерии:
{criteria}
"""


def _short_ts(ts: str) -> str:
    """ISO 8601 звонков → ЧЧ:ММ:СС для промпта; исходная метка не меняется."""
    return ts[11:19] if len(ts) >= 19 and ts[10] == "T" else ts


def _fmt_transcript(dialog: dict) -> str:
    return "\n".join(f'[{i}] {_short_ts(m["timestamp"])} {m["speaker"]}: {m["text"]}'
                     for i, m in enumerate(dialog["transcript"]))


def dialog_hints(dialog: dict) -> list[str]:
    """Факты, которые надёжнее посчитать кодом."""
    t = dialog["transcript"]
    ops = [i for i, m in enumerate(t) if m["speaker"] == "operator"]
    hints = []
    if not ops:
        hints.append("В диалоге нет реплик оператора.")
    else:
        hints.append(f"Первая реплика оператора — [{ops[0]}], последняя — [{ops[-1]}].")
        if any(m["speaker"] == "bot" for m in t[:ops[0]]):
            hints.append("До оператора с клиентом общался бот.")
    if t:
        hints.append(f"Последняя реплика — [{len(t) - 1}], роль {t[-1]['speaker']}.")
    return hints


def build_user(dialog: dict, only: list[str] | None = None, feedback: str | None = None) -> str:
    head = (f'Диалог {dialog["conversation_id"]} · канал: {dialog["channel"]} · язык: {dialog["language"]}\n'
            + "\n".join(f"Факт: {h}" for h in dialog_hints(dialog)))
    body = f"{head}\n\nТранскрипт:\n{_fmt_transcript(dialog)}"
    if only:
        body += f"\n\nОцени только: {', '.join(only)}."
    if feedback:
        body += f"\nПроблемы предыдущего ответа: {feedback}. Исправь только их."
    return body


def build_schema(checklist: dict, only: list[str] | None = None) -> dict:
    crit = [c for c in checklist["criteria"] if not only or c["id"] in only]
    props = {}
    for c in crit:
        if c["answer_type"] == "scale":
            answers = [str(s["value"]) for s in c["scale"]["steps"]]
        else:
            answers = ["yes", "no"]
        if c.get("na_allowed"):
            answers.append("na")
        p = {
            "evidence": {"type": "array", "items": {
                "type": "object",
                "properties": {"msg_index": {"type": "integer"}, "quote": {"type": "string"}},
                "required": ["msg_index", "quote"], "additionalProperties": False}},
            "explanation": _i18n_schema(),
            "checked_range": {"type": "array", "items": {"type": "integer"}},
            "na_reason": _i18n_schema(),
        }
        if c["answer_type"] == "flag":
            p["flags"] = {"type": "array", "items": {"type": "string", "enum": [f["id"] for f in c.get("flag_types", [])]}}
        p["answer"] = {"type": "string", "enum": answers}
        props[c["id"]] = {"type": "object", "properties": p, "required": list(p), "additionalProperties": False}
    return {
        "type": "object",
        "properties": {"criteria": {"type": "object", "properties": props,
                                    "required": list(props), "additionalProperties": False}},
        "required": ["criteria"], "additionalProperties": False,
    }
