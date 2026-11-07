"""Run a small, language-stratified local inference smoke test on the target Mac."""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load the repository-level .env even when this module is launched from a
# different working directory. Existing shell environment variables win.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

from backend.scoring import evaluate
from .schemas import dialog_records, read_json


def select_smoke_dialogs(dialogs: list[dict], limit: int = 5, ids: str | None = None) -> list[dict]:
    """Select deterministic RU/KZ/EN coverage, adding a RU voice call when available."""
    if ids:
        wanted = [part.strip() for part in ids.split(",") if part.strip()]
        by_id = {item["conversation_id"]: item for item in dialogs}
        missing = [cid for cid in wanted if cid not in by_id]
        if missing:
            raise ValueError(f"Unknown conversation IDs: {', '.join(missing)}")
        return [by_id[cid] for cid in wanted]

    selected: list[dict] = []
    used: set[str] = set()
    for language in ("RU", "KZ", "EN"):
        match = next((d for d in dialogs if d.get("language") == language
                      and d.get("channel") == "agent chat"), None)
        if match:
            selected.append(match)
            used.add(match["conversation_id"])
    voice = next((d for d in dialogs if d.get("language") == "RU"
                  and d.get("channel") == "voice call"
                  and d["conversation_id"] not in used), None)
    if voice and len(selected) < limit:
        selected.append(voice)
        used.add(voice["conversation_id"])
    for dialog in dialogs:
        if len(selected) >= limit:
            break
        if dialog["conversation_id"] not in used:
            selected.append(dialog)
            used.add(dialog["conversation_id"])
    if len(selected) < 3 or {d.get("language") for d in selected} != {"RU", "KZ", "EN"}:
        raise ValueError("Need at least one RU, KZ and EN dialog in the input dataset")
    return selected[:limit]


def host_diagnostics() -> dict:
    info = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
        "max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "mlx_installed": False,
        "metal_available": None,
        "mlx_default_device": None,
        "neural_accelerator": "not verified by generic MLX diagnostics",
    }
    if sys.platform == "darwin":
        for key, command in (("chip", ["sysctl", "-n", "machdep.cpu.brand_string"]),
                             ("unified_memory_bytes", ["sysctl", "-n", "hw.memsize"])):
            try:
                value = subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()
                info[key] = value
            except (OSError, subprocess.CalledProcessError):
                info[key] = None
    try:
        import mlx.core as mx
        info["mlx_installed"] = True
        info["mlx_version"] = getattr(mx, "__version__", "unknown")
        info["mlx_default_device"] = str(mx.default_device())
        try:
            info["metal_available"] = bool(mx.metal.is_available())
        except (AttributeError, RuntimeError):
            info["metal_available"] = None
    except ImportError:
        pass
    return info


def validate_evaluation(evaluation: dict, dialog: dict) -> list[str]:
    problems = []
    results = evaluation.get("results")
    if not isinstance(results, list) or not results:
        return ["evaluation.results is missing or empty"]
    transcript = dialog.get("transcript", [])
    for item in results:
        if not isinstance(item, dict) or not item.get("criterion_id"):
            problems.append("malformed criterion result")
            continue
        if "answer" not in item:
            problems.append(f"{item['criterion_id']}: answer missing")
        if item.get("validated") is not True:
            problems.append(f"{item['criterion_id']}: deterministic evidence validator did not pass")
        for evidence in item.get("evidence") or []:
            idx, quote = evidence.get("msg_index"), evidence.get("quote")
            if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(transcript):
                problems.append(f"{item['criterion_id']}: evidence message index out of range")
            elif not isinstance(quote, str) or not quote or quote not in transcript[idx].get("text", ""):
                problems.append(f"{item['criterion_id']}: evidence quote is not an exact substring")
    return problems


def run_smoke(dialog_payload, checklist, model_name: str, output_path: str | Path,
              limit: int = 5, ids: str | None = None) -> dict:
    dialogs = select_smoke_dialogs(dialog_records(dialog_payload), limit, ids)
    os.environ["LOCAL_LLM_MODEL"] = model_name
    os.environ["SCORING_MODE"] = "llm"
    host_before = host_diagnostics()
    records = []
    started = time.perf_counter()
    for dialog in dialogs:
        tick = time.perf_counter()
        record = {"conversation_id": dialog["conversation_id"], "language": dialog.get("language"),
                  "channel": dialog.get("channel"), "status": "error"}
        try:
            evaluation = evaluate(dialog, checklist, providers="local", samples=1)
            problems = validate_evaluation(evaluation, dialog)
            record.update({
                "status": "done" if not problems else "invalid",
                "model": evaluation.get("model"),
                "tokens": evaluation.get("tokens"),
                "cost_usd": evaluation.get("cost_usd"),
                "total_score": evaluation.get("total_score"),
                "criterion_count": len(evaluation.get("results") or []),
                "validated_evidence_count": sum(bool(x.get("validated")) for x in evaluation.get("results") or []),
                "problems": problems,
            })
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["latency_seconds"] = round(time.perf_counter() - tick, 4)
        records.append(record)

    elapsed = round(time.perf_counter() - started, 4)
    host_after = host_diagnostics()
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "run_type": "local_smoke",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "runtime": "MLX OpenAI-compatible server (expected; verify diagnostics)",
        "requested_context_length": os.getenv("LOCAL_LLM_CONTEXT_LENGTH", "4096"),
        "host_before": host_before,
        "host_after": host_after,
        "conversation_count": len(records),
        "completed": sum(r["status"] == "done" for r in records),
        "invalid": sum(r["status"] == "invalid" for r in records),
        "failed": sum(r["status"] == "error" for r in records),
        "elapsed_seconds": elapsed,
        "latency_seconds": [r["latency_seconds"] for r in records],
        "records": records,
        "notes": [
            "Results are smoke/performance diagnostics, not gold-label accuracy.",
            "max_rss_bytes is process peak RSS; it is not total system memory pressure.",
            "Metal availability does not prove M5 Neural Accelerator usage.",
            "Raw provider output is not exposed by scoring.evaluate().",
        ],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"output": str(target), "completed": sum(r["status"] == "done" for r in records),
            "invalid": sum(r["status"] == "invalid" for r in records),
            "failed": sum(r["status"] == "error" for r in records), "elapsed_seconds": elapsed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run 3–5 RU/KZ/EN local inference smoke tests")
    parser.add_argument("--dialogs", required=True, help="DEV organiser JSON export")
    parser.add_argument("--checklist", default="checklists/default.json")
    parser.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--ids", help="comma-separated conversation IDs (optional)")
    parser.add_argument("--out", default="llm/runs/local-smoke.json")
    args = parser.parse_args(argv)
    if args.limit < 3:
        parser.error("--limit must be at least 3")
    try:
        result = run_smoke(read_json(args.dialogs), read_json(args.checklist),
                           args.model, args.out, args.limit, args.ids)
    except (OSError, ValueError, KeyError) as exc:
        print(f"local smoke test failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["completed"] == result["completed"] + result["invalid"] + result["failed"] and not result["invalid"] and not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
