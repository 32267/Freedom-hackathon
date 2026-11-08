"""Таблица «Результаты» в README из файлов для организаторов.

    python tools/readme_results.py     # перечитать results/prod и results/dev и обновить README

Пишет между маркерами <!-- RESULTS:START --> и <!-- RESULTS:END -->. Контрольный набор (prod) — подробно, по каждому
чату и критерию; DEV — сводно по каналам и языкам.
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
SHORT = {"contact": "Контакт", "discovery": "Потребн.", "identification": "Идентиф.", "consultation": "Консульт.",
         "empathy": "Эмпатия", "dialogue": "Диалог", "closure": "Заверш.", "critical": "Грубая"}
CHANNEL = {"agent chat": "Чат", "voice call": "Звонок"}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _cell(v) -> str:
    return "N/A" if v is None else "Да" if v is True else "Нет" if v is False else str(v)


def _meta() -> dict:
    """channel/language по conversation_id из исходных наборов (если они есть локально)."""
    out = {}
    for f in (ROOT / "data").glob("*.json"):
        try:
            data = json.loads(f.read_text())
            for r in data["data"]["records"]:
                out[r["conversation_id"]] = (r.get("channel"), r.get("language"))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def prod_section(doc: dict | None) -> list[str]:
    if not doc:
        return ["### Контрольный набор — 10 чатов", "",
                "_Появится после получения контрольного набора: `tools/export_results.py --set prod` → `tools/readme_results.py`._", ""]
    rows = doc["results"]
    ok = [r for r in rows if r["status"] == "ok"]
    codes = [c["criterion_id"] for c in ok[0]["criteria"]] if ok else list(SHORT)
    scores = [r["score"]["final_score"] for r in ok if r["score"]["final_score"] is not None]
    L = ["### Контрольный набор — 10 чатов", "",
         f"Оценено **{len(ok)} из {len(rows)}** · средний итог **{sum(scores) / len(scores):.2f}** · "
         f"грубые ошибки: **{sum(r['score']['critical_flag'] for r in ok)}** · модель: {doc['model']['name']}" if scores else
         f"Оценено {len(ok)} из {len(rows)}.", "",
         "| № | Диалог | Итог | " + " | ".join(SHORT.get(c, c) for c in codes) + " |",
         "|---|---|---|" + "---|" * len(codes)]
    for i, r in enumerate(rows, 1):
        if r["status"] != "ok":
            L.append(f"| {i} | `{r['conversation_id']}` | ошибка | " + " | ".join("—" for _ in codes) + " |")
            continue
        vals = {c["criterion_id"]: c["value"] for c in r["criteria"]}
        crit = " ⚠" if r["score"]["critical_flag"] else ""
        L.append(f"| {i} | `{r['conversation_id']}` | **{r['score']['final_score']}**{crit} | "
                 + " | ".join(_cell(vals.get(c)) for c in codes) + " |")
    L += ["", "<details><summary>Обоснования по контрольным чатам</summary>", ""]
    for r in ok:
        L.append(f"**`{r['conversation_id']}` — {r['score']['final_score']}**" + (" · ⚠ грубая ошибка" if r["score"]["critical_flag"] else ""))
        L += [f"- {SHORT.get(c['criterion_id'], c['criterion_id'])}: **{_cell(c['value'])}** — {c['rationale']} (реплики {', '.join(map(str, c['evidence_turns'])) or '—'})"
              for c in r["criteria"]]
        L.append("")
    L += ["</details>", ""]
    return L


def dev_section(doc: dict | None) -> list[str]:
    if not doc:
        return []
    meta = _meta()
    ok = [r for r in doc["results"] if r["status"] == "ok"]
    groups = defaultdict(list)
    for r in ok:
        ch, lang = meta.get(r["conversation_id"], (None, None))
        if not ch:  # без исходного набора — по префиксу id: p4-… звонки
            ch = "voice call" if r["conversation_id"].startswith("p4-") else "agent chat"
            lang = r["conversation_id"].split("-")[1].upper() if r["conversation_id"].count("-") >= 2 else "—"
        groups[(ch, lang)].append(r["score"]["final_score"])
    allv = [s for v in groups.values() for s in v if s is not None]
    L = ["### DEV — 60 чатов и 5 звонков", "",
         f"Оценено **{len(ok)} из {len(doc['results'])}** · средний итог **{sum(allv) / len(allv):.2f}** · "
         f"грубые ошибки: **{sum(r['score']['critical_flag'] for r in ok)}**", "",
         "| Канал | Язык | Диалогов | Средний итог |", "|---|---|---|---|"]
    for (ch, lang), v in sorted(groups.items()):
        vv = [s for s in v if s is not None]
        L.append(f"| {CHANNEL.get(ch, ch)} | {lang} | {len(v)} | {sum(vv) / len(vv):.2f} |")
    dist = defaultdict(Counter)
    for r in ok:
        for c in r["criteria"]:
            dist[c["criterion_id"]][_cell(c["value"])] += 1
    L += ["", "| Критерий | Ответы |", "|---|---|"]
    L += [f"| {SHORT.get(k, k)} | " + ", ".join(f"{a}: {n}" for a, n in sorted(v.items(), key=lambda x: -x[1])) + " |" for k, v in dist.items()]
    return L + [""]


def main() -> None:
    prod = _load(ROOT / "results/prod/results.json")
    dev = _load(ROOT / "results/dev/results.json")
    block = "\n".join([START, *prod_section(prod), *dev_section(dev), END])
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit("В README нет маркеров RESULTS:START / RESULTS:END")
    README.write_text(re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S), encoding="utf-8")
    print(f"README обновлён: prod {'есть' if prod else 'ещё нет'}, dev {'есть' if dev else 'нет'}")


if __name__ == "__main__":
    main()
