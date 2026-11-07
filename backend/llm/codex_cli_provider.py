"""Оценка через локальный Codex CLI (`codex exec`) — подписка ChatGPT того, кто запустил.

Codex — агент, поэтому запускаем его в пустой временной папке, в read-only песочнице и без сохранения сессии.
Только для разработки/резерва: лимиты подписки, ~10–30 с на вызов.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import LLMError, LLMOutputError, LLMResult

DEFAULT_CODEX_MODEL = "gpt-5.6-terra"


def call_json(system: str, user: str, schema: dict, model: str, effort: str) -> LLMResult:
    exe = shutil.which(os.getenv("CODEX_CLI", "codex"))
    if not exe:
        raise LLMError("Не найден CLI `codex`")
    model = os.getenv("CODEX_MODEL", "").strip() or DEFAULT_CODEX_MODEL
    prompt = (f"{system}\n\n---\nЭто задача только на чтение и оценку текста ниже. Не выполняй команды и не "
              f"открывай файлы. Верни ответ строго по JSON-схеме.\n---\n\n{user}")
    with tempfile.TemporaryDirectory(prefix="cqa-codex-") as tmp:
        schema_path, out_path = Path(tmp, "schema.json"), Path(tmp, "out.json")
        schema_path.write_text(json.dumps(schema, ensure_ascii=False))
        cmd = [exe, "exec", "-m", model, "-c", f'model_reasoning_effort="{effort}"', "--skip-git-repo-check",
               "--ephemeral", "-s", "read-only", "-C", tmp, "--output-schema", str(schema_path),
               "-o", str(out_path), "--json", "-"]
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  timeout=int(os.getenv("CODEX_CLI_TIMEOUT", "300")))
        except subprocess.TimeoutExpired as e:
            raise LLMError("codex exec: таймаут") from e
        usage, error = {}, None
        for line in proc.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "turn.completed":
                usage = ev.get("usage", {})
            elif ev.get("type") in ("error", "turn.failed"):
                error = ev.get("message") or (ev.get("error") or {}).get("message")
        if not out_path.exists() or not out_path.read_text().strip():
            raise LLMError(f"codex exec: нет ответа ({(error or proc.stderr[-300:] or '').strip()[:300]})")
        try:
            data = json.loads(out_path.read_text())
        except json.JSONDecodeError as e:
            raise LLMOutputError("codex exec: ответ не JSON") from e
    cached = usage.get("cached_input_tokens", 0)
    return LLMResult(
        data=data, model=model,
        input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
        cache_read_tokens=cached, cost_usd=0.0,       # по подписке ChatGPT, без поштучной оплаты
        meta={"provider": "codex_cli"},
    )
