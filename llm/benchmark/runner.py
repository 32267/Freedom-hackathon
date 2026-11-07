"""Execute a single configured evaluator against a frozen dialog set."""
from __future__ import annotations

import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.scoring import evaluate

from .schemas import dialog_records, read_jsonl, validate_gold, write_jsonl


def run_benchmark(dialog_payload, checklist, gold_records, model, model_id, output_path):
    dialogs = dialog_records(dialog_payload)
    dialog_map = {d["conversation_id"]: d for d in dialogs}
    validate_gold(gold_records, checklist, dialog_map)
    selected = {r["conversation_id"] for r in gold_records}
    if selected:
        dialogs = [d for d in dialogs if d["conversation_id"] in selected]
    predictions = []
    started = time.perf_counter()
    for dialog in dialogs:
        t0 = time.perf_counter()
        record = {
            "conversation_id": dialog["conversation_id"],
            "language": dialog.get("language"),
            "model_id": model_id,
            "status": "error",
            "raw_output": None,
            "raw_output_available": False,
        }
        try:
            provider = model["provider"]
            model_env = model.get("model_env")
            if model_env:
                os.environ[model_env] = model["model"]
            evaluation = evaluate(dialog, checklist, providers=provider, samples=1)
            record.update({
                "status": "done",
                "evaluation": evaluation,
                "provider": evaluation.get("provider") or provider,
                "model": evaluation.get("model") or model["model"],
                "tokens": evaluation.get("tokens"),
                "cost_usd": evaluation.get("cost_usd"),
            })
        except Exception as exc:  # preserve individual failures in benchmark output
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["latency_seconds"] = round(time.perf_counter() - t0, 4)
        predictions.append(record)
    elapsed = round(time.perf_counter() - started, 4)
    write_jsonl(output_path, predictions)
    manifest = {
        "manifest_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_id": model_id,
        "model_config": model,
        "provider": model["provider"],
        "runtime": model["runtime"],
        "hardware_target": "as configured; actual host details below",
        "host": {"platform": platform.platform(), "python": platform.python_version(), "machine": platform.machine()},
        "checklist_id": checklist["id"],
        "checklist_version": checklist["version"],
        "conversation_count": len(dialogs),
        "completed": sum(p["status"] == "done" for p in predictions),
        "failed": sum(p["status"] != "done" for p in predictions),
        "elapsed_seconds": elapsed,
        "raw_output_capture": "unavailable: public scoring.evaluate() exposes validated evaluator results only",
        "prediction_file": str(output_path),
    }
    manifest_path = Path(str(output_path) + ".manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
