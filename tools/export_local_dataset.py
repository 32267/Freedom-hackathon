"""Набор организаторов → локальная папка: по файлу на диалог, читаемый .md и mp3 звонков.

    python tools/export_local_dataset.py data/DEV.json                 # → dataset/DEV/
    python tools/export_local_dataset.py data/DEV.json --no-audio

Структура (папка dataset/ в git не попадает — данные организаторов):
    dataset/DEV/
      index.md                  — таблица всех диалогов
      chats/<id>.json, <id>.md
      calls/<id>.json, <id>.md, <id>.mp3

audio_url организаторов отдаёт HTML-страницу плеера; внутри <source src="..."> — подписанная ссылка на mp3,
живущая ~1 час. Скрипт достаёт её и скачивает файл.
"""
import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

UA = {"User-Agent": "cqa-hackathon-exporter"}


def _get(url: str, timeout: int = 120) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def resolve_audio(url: str) -> str:
    """Ссылка из audio_url → прямая ссылка на mp3 (если это страница плеера)."""
    body, ctype = _get(url, 60)
    if "audio" in ctype:
        return url
    m = re.search(r'<source[^>]+src="([^"]+)"', body.decode("utf-8", "replace"))
    if not m:
        raise RuntimeError("в странице плеера нет <source src>")
    return html.unescape(m.group(1))


def to_md(d: dict) -> str:
    lines = [f"# {d['conversation_id']}", "",
             f"Канал: **{d['channel']}** · язык: **{d['language']}** · реплик: {len(d['transcript'])}", ""]
    if d.get("audio_file"):
        lines += [f"Запись: [{d['audio_file']}]({d['audio_file']})", ""]
    lines += ["| # | время | роль | текст |", "|---|---|---|---|"]
    for i, t in enumerate(d["transcript"]):
        ts = t["timestamp"][11:19] if "T" in t["timestamp"] else t["timestamp"]
        text = t["text"].replace("|", "\\|").replace("\n", " ")
        role = {"operator": "**operator**"}.get(t["speaker"], t["speaker"])
        lines.append(f"| {i} | {ts} | {role} | {text} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--out", default="dataset")
    ap.add_argument("--no-audio", action="store_true")
    a = ap.parse_args()

    data = json.loads(Path(a.path).read_text())
    group = data["data"].get("dataset_group_id", "DATA")
    records = data["data"]["records"]
    root = Path(a.out) / group
    index = ["| id | канал | язык | реплик | запись |", "|---|---|---|---|---|"]
    failed = []
    for d in records:
        sub = root / ("calls" if d["channel"] == "voice call" else "chats")
        sub.mkdir(parents=True, exist_ok=True)
        cid = d["conversation_id"]
        rec = {**d, "dataset_group_id": group}
        if d.get("audio_url") and not a.no_audio:
            mp3 = sub / f"{cid}.mp3"
            try:
                for attempt in range(3):                  # ссылка живёт ~1 ч, при сбое берём свежую
                    if mp3.exists():
                        break
                    try:
                        body, _ = _get(resolve_audio(d["audio_url"]), 180)
                        tmp = mp3.with_suffix(".part")
                        tmp.write_bytes(body)
                        tmp.rename(mp3)
                    except Exception:  # noqa: BLE001
                        if attempt == 2:
                            raise
                rec["audio_file"] = mp3.name
                print(f"{cid}: {mp3.stat().st_size / 1e6:.1f} MB", flush=True)
            except Exception as e:  # noqa: BLE001 — один сбойный файл не должен ронять выгрузку
                failed.append(f"{cid}: {e}")
        (sub / f"{cid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2))
        (sub / f"{cid}.md").write_text(to_md(rec))
        link = f"[{cid}]({sub.name}/{cid}.md)"
        index.append(f"| {link} | {d['channel']} | {d['language']} | {len(d['transcript'])} | "
                     f"{'[mp3](' + sub.name + '/' + rec['audio_file'] + ')' if rec.get('audio_file') else '—'} |")
    (root / "index.md").write_text(f"# {group}: {len(records)} диалогов\n\n" + "\n".join(index) + "\n")
    print(f"Готово: {root} · диалогов {len(records)}" + (f" · ошибки аудио: {failed}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
