"""Промпт и JSON-схема строятся из чек-листа целиком — новый критерий из UI работает без правки кода."""

LANGS = ("ru", "kz", "en")


def _i18n_schema() -> dict:
    return {"type": "object", "properties": {lang: {"type": "string"} for lang in LANGS},
            "required": list(LANGS), "additionalProperties": False}


def _criterion_block(c: dict) -> str:
    lines = [f'### {c["id"]} — {c["title"]}']
    if c["answer_type"] == "binary":
        opts = "yes / no" + (" / na" if c.get("na_allowed") else "")
        lines.append(f'Тип: да/нет. Варианты answer: {opts}. Вес: {c["weight"]}.')
    elif c["answer_type"] == "scale":
        vals = ", ".join(str(s["value"]) for s in c["scale"]["steps"])
        lines.append(f'Тип: шкала. answer — строго одно из: {vals}' + (", na" if c.get("na_allowed") else "")
                     + f'. Вес: {c["weight"]}.')
        lines += [f'- {s["value"]}: {s["label"]}' for s in c["scale"]["steps"]]
    else:
        flags = "; ".join(f'{f["id"]} = {f["label"]}' for f in c.get("flag_types", []))
        lines.append("Тип: флаг нарушения, без баллов. answer: yes — нарушение найдено, no — не найдено. "
                     f"При yes перечисли в flags виды: {flags}.")
    lines.append(f'Условие: {c["description"]}')
    if c.get("na_allowed") and c.get("na_rule"):
        lines.append(f'N/A допустим, только если: {c["na_rule"]}')
    elif c["answer_type"] != "flag":
        lines.append("N/A для этого критерия запрещён.")
    return "\n".join(lines)


def build_system(checklist: dict) -> str:
    notes = "\n".join(f"- {n}" for n in checklist.get("notes", []))
    criteria = "\n\n".join(_criterion_block(c) for c in checklist["criteria"])
    return f"""Ты — специалист по контролю качества клиентской поддержки брокерской компании Freedom Broker.
Ты оцениваешь работу ОПЕРАТОРА в одном диалоге по чек-листу «{checklist["name"]}».
Диалоги бывают на русском, казахском и английском; чек-лист один для всех языков.

Как читать транскрипт:
- Каждая реплика пронумерована: [индекс] время роль: текст. Роли: operator, client, bot, system.
- Оценивается только operator. Реплики bot и system — контекст (например, бот мог поздороваться до оператора,
  системное сообщение может показать передачу чата или его закрытие).
- Системные события — факты, на них можно ссылаться: «Личность клиента подтверждена» (и аналоги на KZ/EN) —
  идентификация пройдена; «Оператор закрыл чат», «Клиент покинул чат», «Соединение прервано» — как закончился диалог;
  «Запись и транскрибирование приостановлены/возобновлены» — часть звонка не записана, не додумывай, что было в паузе.
- Метки [Имя скрыто], [Персональные данные скрыты], [Данные идентификации скрыты] — данные прозвучали, но замаскированы.
  Считай их сказанными: «меня зовут [Имя скрыто]» — оператор представился; клиент назвал скрытые данные — он их сообщил.
- Звонки (voice call) расшифрованы автоматически: возможны искажения слов, обрывки и повторы реплик. Не снижай оценку
  за ошибки распознавания — оценивай смысл и поведение оператора.

Общие правила:
{notes}

Как заполнять каждый критерий:
- evidence — реплики, на которых основан вывод: msg_index и quote. quote — дословный фрагмент текста этой реплики
  (на языке оригинала, без перевода и пересказа), достаточно 3–15 слов.
- explanation — 1–3 предложения: что сделал или не сделал оператор и почему такой ответ. Пиши одно и то же
  обоснование на трёх языках: ru — русский, kz — казахский (кириллица), en — английский. Смысл во всех трёх одинаковый.
- Если требуемое действие пропущено (no или шкала ниже максимума из-за пропуска), checked_range — [от, до]:
  индексы участка, где действие ожидалось. Иначе — пустой массив.
- Если answer = na — na_reason: какое условие неприменимости выполнено, тоже на ru, kz, en. Иначе — пустые строки.
- Для na evidence может быть пустым или указывать реплику, подтверждающую неприменимость.
- Сначала собери доказательства, потом выбирай answer.

Критерии:

{criteria}
"""


def _short_ts(ts: str) -> str:
    """ISO 8601 звонков → ЧЧ:ММ:СС для промпта (в данных исходная метка не меняется)."""
    return ts[11:19] if len(ts) >= 19 and ts[10] == "T" else ts


def _fmt_transcript(dialog: dict) -> str:
    return "\n".join(f'[{i}] {_short_ts(m["timestamp"])} {m["speaker"]}: {m["text"]}'
                     for i, m in enumerate(dialog["transcript"]))


def dialog_hints(dialog: dict) -> list[str]:
    """Факты, которые надёжнее посчитать кодом, чем доверить модели."""
    t = dialog["transcript"]
    ops = [i for i, m in enumerate(t) if m["speaker"] == "operator"]
    hints = []
    if not ops:
        hints.append("В диалоге нет ни одной реплики оператора.")
    else:
        hints.append(f"Первая реплика оператора — [{ops[0]}], последняя — [{ops[-1]}].")
        before = {m["speaker"] for m in t[: ops[0]]}
        if "bot" in before:
            hints.append("До оператора с клиентом общался бот.")
    if t:
        hints.append(f"Последняя реплика диалога — [{len(t) - 1}] от {t[-1]['speaker']}.")
    return hints


def build_user(dialog: dict, only: list[str] | None = None, feedback: str | None = None) -> str:
    head = (f'Диалог {dialog["conversation_id"]} · канал: {dialog["channel"]} · язык: {dialog["language"]}\n'
            + "\n".join(f"Факт: {h}" for h in dialog_hints(dialog)))
    body = f"{head}\n\nТранскрипт:\n{_fmt_transcript(dialog)}"
    if only:
        body += f"\n\nОцени только критерии: {', '.join(only)}."
    if feedback:
        body += f"\n\nПрошлый ответ по этим критериям не прошёл проверку:\n{feedback}\nИсправь."
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
