"""Оценить диалоги из командной строки:

    python -m backend.scoring fixtures/dialog.chat.json
    python -m backend.scoring data/DEV.json --limit 5 --ids p1-ru-001,p1-kz-003
    python -m backend.scoring data/DEV.json --out-dir dataset/DEV/evaluations --workers 3   # все, по файлу на диалог

С --out-dir уже оценённые диалоги (той же версии чек-листа) пропускаются — прогон можно прерывать и продолжать.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from . import evaluate


def _load(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict) and "data" in data:          # ответ API организаторов
        return data["data"]["records"]
    return data if isinstance(data, list) else [data]


def _line(d: dict, ev: dict) -> str:
    review = [r["criterion_id"] for r in ev["results"] if r.get("needs_review")]
    answers = " ".join(f'{r["criterion_id"]}={r["answer"]}' for r in ev["results"])
    return (f'{d["conversation_id"]:<12} {d["language"]} итог={ev["total_score"]} грубая={ev["critical_error"]} '
            f'${ev["cost_usd"]:.4f} {ev.get("providers", ev.get("model"))}\n   {answers}'
            + (f"\n   ⚑ модели разошлись: {review}" if review else ""))


def _summary(out_dir: Path, checklist: dict, dialogs: list[dict]) -> None:
    rows, langs = [], {}
    names = {c["id"]: c["title"] for c in checklist["criteria"]}
    for d in dialogs:
        f = out_dir / f'{d["conversation_id"]}.json'
        if not f.exists():
            continue
        ev = json.loads(f.read_text())
        rows.append((d, ev))
        langs.setdefault((d["channel"], d["language"]), []).append(ev["total_score"])
    crit_ids = [c["id"] for c in checklist["criteria"]]
    head = "| id | канал | язык | итог | грубая | " + " | ".join(names[c] for c in crit_ids) + " | расхождения |"
    lines = [f"# Оценки: {len(rows)} диалогов · чек-лист v{checklist['version']}", "",
             "| канал | язык | диалогов | средний итог |", "|---|---|---|---|"]
    for (ch, lg), scores in sorted(langs.items()):
        ok = [s for s in scores if s is not None]
        lines.append(f"| {ch} | {lg} | {len(scores)} | {sum(ok) / len(ok):.2f} |" if ok else f"| {ch} | {lg} | {len(scores)} | — |")
    lines += ["", head, "|" + "---|" * (len(crit_ids) + 6)]
    csv = ["conversation_id,channel,language,total_score,critical_error," + ",".join(crit_ids) + ",needs_review,cost_usd"]
    for d, ev in rows:
        ans = {r["criterion_id"]: r["answer"] for r in ev["results"]}
        rev = [r["criterion_id"] for r in ev["results"] if r.get("needs_review")]
        lines.append(f'| {d["conversation_id"]} | {d["channel"]} | {d["language"]} | {ev["total_score"]} | '
                     f'{"⚠ " + ",".join(ev.get("critical_flags", [])) if ev["critical_error"] else ""} | '
                     + " | ".join(str(ans.get(c, "")) for c in crit_ids) + f' | {", ".join(rev)} |')
        csv.append(f'{d["conversation_id"]},{d["channel"]},{d["language"]},{ev["total_score"]},{ev["critical_error"]},'
                   + ",".join(str(ans.get(c, "")) for c in crit_ids) + f',{"|".join(rev)},{ev["cost_usd"]}')
    cost = sum(ev["cost_usd"] for _, ev in rows)
    lines += ["", f"Эквивалент стоимости по прайсу API: ${cost:.4f} (в среднем ${cost / max(len(rows), 1):.4f} на диалог)."]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
    (out_dir / "summary.csv").write_text("\n".join(csv) + "\n")


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--checklist", default="checklists/default.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--out", default="", help="один JSON-файл со списком оценок")
    ap.add_argument("--out-dir", default="", help="папка: по файлу на диалог + summary.md/csv")
    ap.add_argument("--workers", type=int, default=1, help="сколько диалогов оценивать параллельно")
    ap.add_argument("--providers", default=None, help='перекрыть LLM_PROVIDERS, например "codex_cli"')
    ap.add_argument("--samples", type=int, default=None, help="перекрыть LLM_SAMPLES")
    a = ap.parse_args()

    checklist = json.loads(Path(a.checklist).read_text())
    dialogs = _load(a.path)
    if a.ids:
        want = set(a.ids.split(","))
        dialogs = [d for d in dialogs if d["conversation_id"] in want]
    if a.limit:
        dialogs = dialogs[: a.limit]

    out_dir = Path(a.out_dir) if a.out_dir else None
    todo = dialogs
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

        def done(d):
            f = out_dir / f'{d["conversation_id"]}.json'
            return f.exists() and json.loads(f.read_text()).get("checklist_version") == checklist["version"]
        todo = [d for d in dialogs if not done(d)]
        print(f"Оценить: {len(todo)} из {len(dialogs)} (остальные уже есть)", flush=True)

    results, failed, started = [], [], time.monotonic()

    def run(d):
        return d, evaluate(d, checklist, providers=a.providers, samples=a.samples)

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
        futures = [pool.submit(run, d) for d in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                d, ev = fut.result()
            except Exception as e:  # noqa: BLE001 — один сбойный диалог не останавливает прогон
                failed.append(str(e)[:200])
                print(f"[{i}/{len(todo)}] ОШИБКА: {str(e)[:200]}", flush=True)
                continue
            results.append(ev)
            if out_dir:
                (out_dir / f'{d["conversation_id"]}.json').write_text(json.dumps(ev, ensure_ascii=False, indent=2))
            print(f"[{i}/{len(todo)}] " + _line(d, ev), flush=True)

    if results:
        cost = sum(ev["cost_usd"] for ev in results)
        print(f"\nОценено: {len(results)} · ошибок: {len(failed)} · {time.monotonic() - started:.0f} с · "
              f"стоимость: ${cost:.4f} · в среднем ${cost / len(results):.4f}")
    if a.out:
        Path(a.out).write_text(json.dumps(results, ensure_ascii=False, indent=2))
    if out_dir:
        _summary(out_dir, checklist, dialogs)
        print(f"Сводка: {out_dir / 'summary.md'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
