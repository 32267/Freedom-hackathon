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

    na_reason = (raw.get("na_reason") or "").strip()
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
    explanation = (raw.get("explanation") or "").strip() or (na_reason if answer == "na" else "")
    if not explanation:
        problems.append("пустое explanation")

    fixed = {
        "answer": answer if ctype != "scale" or answer == "na" or answer is None else _to_num(answer),
        "explanation": explanation,
        "evidence": evidence,
        "checked_range": checked,
        "na_reason": na_reason or None,
        "flags": list(raw.get("flags") or []) if ctype == "flag" else [],
    }
    return fixed, problems


def _to_num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return v
