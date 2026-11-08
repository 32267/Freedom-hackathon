"""Проверка ответа модели без LLM: цитаты, N/A, шкалы и флаги."""
import re
import unicodedata


def _norm(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s).casefold()
    s = re.sub(r"[«»\"“”„'\x60’‘]", "", s)
    s = s.replace("…", "").replace("...", "")
    return re.sub(r"\s+", " ", s).strip(" .,!?;:-—")


def _find_quote(quote: str, msg_index: int, transcript: list[dict]) -> int | None:
    """Подтверждает цитату только в реплике, на которую модель сослалась.

    Не исправляет индекс поиском по всему диалогу: совпавшая фраза в другой
    реплике не доказывает, что указанное сообщение поддерживает оценку.
    """
    if not isinstance(msg_index, int) or isinstance(msg_index, bool) or not 0 <= msg_index < len(transcript):
        return None
    q = _norm(quote)
    if not q:
        return None
    return msg_index if q in _norm(transcript[msg_index].get("text", "")) else None


LANGS = ("ru", "kz", "en")


def _i18n(value) -> dict:
    """{"ru","kz","en"} из объекта модели; строка (старый формат) считается русской."""
    if isinstance(value, dict):
        return {lang: (value.get(lang) or "").strip() for lang in LANGS}
    return {"ru": (value or "").strip(), "kz": "", "en": ""}


def check_criterion(raw: dict, criterion: dict, transcript: list[dict], channel: str | None = None) -> tuple[dict, list[str]]:
    """Возвращает (исправленный ответ, список проблем); цитата обязана быть в указанной реплике."""
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
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < n:
            problems.append(f"msg_index={idx!r} вне допустимого диапазона 0..{n - 1}")
            continue
        found = _find_quote(quote, idx, transcript)
        if found is None:
            elsewhere = _find_quote_anywhere(quote, transcript)
            if elsewhere is not None:
                problems.append(f"цитата есть в реплике {elsewhere}, но модель указала msg_index {idx}")
            else:
                problems.append(f"цитата «{quote}» не найдена в указанной реплике {idx}")
            continue
        evidence.append({"msg_index": found, "quote": quote})

    rng = raw.get("checked_range") or []
    checked = None
    if rng:
        if len(rng) == 2 and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < n for x in rng) and rng[0] <= rng[1]:
            checked = {"from": rng[0], "to": rng[1]}
        else:
            problems.append(f"checked_range={rng} некорректен (нужно [от, до] в пределах 0..{n - 1})")

    na_reasons = _i18n(raw.get("na_reason"))
    na_reason = na_reasons["ru"]
    if answer != "na" and any(na_reasons.values()):
        problems.append("na_reason должен быть пустым, если answer не na")
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
    if answer == "na" and not na_reason:
        problems.append("answer=na без na_reason")
    if answer == "yes" and not evidence:
        problems.append("answer=yes без подтверждающей реплики")
    is_shortfall = answer == "no" or (ctype == "scale" and answer not in ("na", None)
                                      and str(answer) != str(criterion["scale"]["max"]))
    if ctype != "flag" and is_shortfall and not evidence and checked is None:
        problems.append("снижение балла без доказательства и без checked_range")
    explanations = _i18n(raw.get("explanation"))
    if answer == "na":
        explanations = {lang: explanations[lang] or na_reasons[lang] for lang in LANGS}
    missing = [lang for lang in LANGS if not explanations[lang]]
    if missing:
        problems.append(f"explanation пустое на языках: {', '.join(missing)}")
    if answer == "na" and na_reason and any(not na_reasons[lang] for lang in LANGS):
        problems.append("na_reason нужен на ru, kz и en")

    fixed = {
        "answer": answer if ctype != "scale" or answer == "na" or answer is None else _to_num(answer),
        "explanation": explanations["ru"],
        "explanations": explanations,
        "evidence": evidence,
        "checked_range": checked,
        "na_reason": na_reason or None,
        "na_reasons": na_reasons if answer == "na" else None,
        "flags": list(raw.get("flags") or []) if ctype == "flag" else [],
        "insufficient": explanations["ru"].lower().startswith("недостаточно данных:")
        or explanations["en"].lower().startswith("insufficient data:"),
    }
    return fixed, problems


def _find_quote_anywhere(quote: str, transcript: list[dict]) -> int | None:
    """Диагностика только: сообщает, что цитата есть в другой реплике, но не принимает её."""
    q = _norm(quote)
    if not q:
        return None
    for i, message in enumerate(transcript):
        if q in _norm(message.get("text", "")):
            return i
    return None


def _to_num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return v
