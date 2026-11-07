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


def check_criterion(raw: dict, criterion: dict, transcript: list[dict]) -> tuple[dict, list[str]]:
    """Возвращает (исправленный ответ, список проблем). Исправляет только безопасное: сдвиг msg_index."""
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

    na_reasons = _i18n(raw.get("na_reason"))
    na_reason = na_reasons["ru"]
    if answer == "na" and not na_reason:
        problems.append("answer=na без na_reason")
    if answer == "yes" and not evidence:
        problems.append("answer=yes без подтверждающей реплики")
    if ctype == "flag" and answer == "yes" and not raw.get("flags"):
        problems.append("флаг yes без указания вида нарушения (flags)")
    is_shortfall = answer == "no" or (ctype == "scale" and answer not in ("na", None)
                                      and str(answer) != str(criterion["scale"]["max"]))
    if ctype != "flag" and is_shortfall and not evidence and checked is None:
        problems.append("снижение балла без доказательства и без checked_range")
    explanations = _i18n(raw.get("explanation"))
    if answer == "na":                         # для N/A причина может служить обоснованием
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
    }
    return fixed, problems


def _to_num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return v
