"""Проверка ответа модели без LLM: ни одной выдуманной цитаты, N/A только где разрешён, шкала только из ступеней."""
import re
import unicodedata


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    s = re.sub(r"[«»\"“”„'`’‘]", "", s)
    s = s.replace("…", "").replace("...", "")
    return re.sub(r"\s+", " ", s).strip(" .,!?;:-—")


def _find_quote(quote: str, msg_index: int, transcript: list[dict]) -> int | None:
    """Индекс реплики, где реально есть цитата: сначала указанная, затем ближайшие."""
    q = _norm(quote)
    if not q:
        return None
    order = sorted(range(len(transcript)), key=lambda i: abs(i - msg_index))
    for i in order:
        if q in _norm(transcript[i]["text"]):
            return i
    return None


LANGS = ("ru", "kz", "en")


def _i18n(value) -> dict:
    """{"ru","kz","en"} из объекта модели; строка (старый формат) считается русской."""
    if isinstance(value, dict):
        return {lang: (value.get(lang) or "").strip() for lang in LANGS}
    return {"ru": (value or "").strip(), "kz": "", "en": ""}


def check_criterion(raw: dict, criterion: dict, transcript: list[dict], channel: str | None = None, language: str = "RU") -> tuple[dict, list[str]]:
    """Возвращает (исправленный ответ, список проблем). Исправляет только безопасное: сдвиг msg_index.
    channel — канал диалога: N/A, разрешённый только для некоторых каналов (na_channels), в других — ошибка."""
    problems = []
    n = len(transcript)
    answer = raw.get("answer")
    ctype = criterion["answer_type"]

    allowed = (["yes", "no"] if ctype != "scale" else [str(s["value"]) for s in criterion["scale"]["steps"]])
    if criterion.get("na_allowed"):
        allowed = allowed + ["na"]
    if answer not in allowed:
        problems.append(f"answer={answer!r} недопустим, варианты: {allowed}")

    evidence = []
    for ev in raw.get("evidence") or []:
        idx, quote = ev.get("msg_index"), ev.get("quote", "")
        if not isinstance(idx, int):
            problems.append(f"msg_index={idx!r} не число")
            continue
        found = _find_quote(quote, min(max(idx, 0), max(n - 1, 0)), transcript) if n else None
        if found is None:
            problems.append(f"цитата «{quote}» не найдена в транскрипте (msg_index {idx})")
            continue
        evidence.append({"msg_index": found, "quote": quote})

    rng = raw.get("checked_range") or []
    checked = None
    if rng:
        if len(rng) == 2 and all(isinstance(x, int) and 0 <= x < n for x in rng) and rng[0] <= rng[1]:
            checked = {"from": rng[0], "to": rng[1]}
        else:
            problems.append(f"checked_range={rng} некорректен (нужно [от, до] в пределах 0..{n - 1})")

    if ctype == "flag":
        allowed_flags = {item["id"] for item in criterion.get("flag_types", [])}
        supplied_flags = raw.get("flags") or []
        unknown_flags = sorted(set(supplied_flags) - allowed_flags)
        if unknown_flags:
            problems.append(f"неизвестные flags: {unknown_flags}")
        if answer == "no" and supplied_flags:
            problems.append("answer=no не должен содержать flags")
        if answer == "yes" and not supplied_flags:
            problems.append("флаг yes без указания вида нарушения (flags)")
    if answer == "na" and criterion.get("na_channels") and channel and channel not in criterion["na_channels"]:
        problems.append(f"N/A для этого критерия допустим только в канале {', '.join(criterion['na_channels'])}, а это {channel}")
    if answer == "yes" and not evidence:
        problems.append("answer=yes без подтверждающей реплики")
    if answer == "yes" and evidence:
        supported_roles = {"operator", "system"}
        if not any(0 <= item["msg_index"] < n and transcript[item["msg_index"]].get("speaker") in supported_roles
                   for item in evidence):
            problems.append("answer=yes подтверждён только репликами клиента/бота, а не действием оператора или системным событием")
    is_shortfall = answer == "no" or (ctype == "scale" and answer not in ("na", None)
                                      and str(answer) != str(criterion["scale"]["max"]))
    if ctype != "flag" and is_shortfall and not evidence and checked is None:
        problems.append("снижение балла без доказательства и без checked_range")
    source_lang = {"RU": "ru", "KZ": "kz", "EN": "en"}.get(str(language).upper(), "ru")
    source_explanation = raw.get("explanation")
    if isinstance(source_explanation, dict):
        explanations = _i18n(source_explanation)
        source_explanation = explanations[source_lang] or explanations["ru"] or explanations["en"] or explanations["kz"]
    else:
        source_explanation = (source_explanation or "").strip()
        explanations = {lang: (source_explanation if lang == source_lang else "") for lang in LANGS}
    source_na_reason = raw.get("na_reason")
    if isinstance(source_na_reason, dict):
        na_reasons = _i18n(source_na_reason)
        source_na_reason = na_reasons[source_lang] or na_reasons["ru"] or na_reasons["en"] or na_reasons["kz"]
    else:
        source_na_reason = (source_na_reason or "").strip()
        na_reasons = {lang: (source_na_reason if lang == source_lang else "") for lang in LANGS}
    if answer == "na" and not source_explanation:
        source_explanation = source_na_reason
        explanations[source_lang] = source_explanation
    if not source_explanation:
        problems.append(f"explanation пустое на языке диалога ({source_lang})")
    if answer == "na" and not source_na_reason:
        problems.append(f"na_reason пустое на языке диалога ({source_lang})")
    if answer != "na" and source_na_reason:
        problems.append("na_reason должен быть пустым, если answer не na")

    fixed = {
        "answer": answer if ctype != "scale" or answer == "na" or answer is None else _to_num(answer),
        "explanation": explanations["ru"] or source_explanation,
        "explanations": explanations,
        "_source_language": source_lang,
        "_source_explanation": source_explanation,
        "_source_na_reason": source_na_reason,
        "evidence": evidence,
        "checked_range": checked,
        "na_reason": source_na_reason or None,
        "na_reasons": na_reasons if answer == "na" else None,
        "flags": list(raw.get("flags") or []) if ctype == "flag" else [],
        # модель сама отметила, что данных не хватило → критерий уходит на проверку человеку (балл — по чек-листу)
        "insufficient": source_explanation.lower().startswith(("недостаточно данных:", "жеткіліксіз дерек:", "insufficient data:")),
    }
    return fixed, problems


def _to_num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return v
