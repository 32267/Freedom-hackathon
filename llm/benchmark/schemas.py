"""Gold-label and benchmark configuration validation."""
from __future__ import annotations

import json
from pathlib import Path


class BenchmarkDataError(ValueError):
    """Invalid benchmark input."""


def read_json(path: str | Path):
    try:
        with Path(path).open(encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkDataError(f"Cannot read JSON file {path}: {exc}") from exc


def read_jsonl(path: str | Path) -> list[dict]:
    records = []
    try:
        with Path(path).open(encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BenchmarkDataError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
                if not isinstance(item, dict):
                    raise BenchmarkDataError(f"{path}:{line_no}: each JSONL line must be an object")
                records.append(item)
    except OSError as exc:
        raise BenchmarkDataError(f"Cannot read JSONL file {path}: {exc}") from exc
    return records


def write_jsonl(path: str | Path, records) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def dialog_records(payload) -> list[dict]:
    """Accept the organiser export envelope or a plain list of Dialog objects."""
    if isinstance(payload, dict):
        payload = payload.get("data", payload)
        if isinstance(payload, dict):
            payload = payload.get("records", payload.get("dialogs"))
    if not isinstance(payload, list):
        raise BenchmarkDataError("dialogs must be a list or organiser export with data.records")
    seen = set()
    for dialog in payload:
        if not isinstance(dialog, dict) or not dialog.get("conversation_id"):
            raise BenchmarkDataError("each dialog must be an object with conversation_id")
        cid = dialog["conversation_id"]
        if cid in seen:
            raise BenchmarkDataError(f"duplicate conversation_id: {cid}")
        seen.add(cid)
        if not isinstance(dialog.get("transcript"), list):
            raise BenchmarkDataError(f"{cid}: transcript must be a list")
    return payload


def validate_model_config(config: dict) -> dict[str, dict]:
    models = config.get("models") if isinstance(config, dict) else None
    if not isinstance(models, list) or not models:
        raise BenchmarkDataError("model config must contain a non-empty models array")
    result = {}
    required = ("provider", "model", "runtime", "context_length")
    for item in models:
        if not isinstance(item, dict) or not item.get("id"):
            raise BenchmarkDataError("each model entry must have an id")
        mid = item["id"]
        if mid in result:
            raise BenchmarkDataError(f"duplicate model id: {mid}")
        missing = [key for key in required if item.get(key) in (None, "")]
        if missing:
            raise BenchmarkDataError(f"{mid}: missing fields: {', '.join(missing)}")
        if item["provider"] not in ("anthropic", "claude_cli", "codex_cli", "local"):
            raise BenchmarkDataError(f"{mid}: unsupported provider {item['provider']!r}")
        if not isinstance(item["context_length"], int) or item["context_length"] <= 0:
            raise BenchmarkDataError(f"{mid}: context_length must be a positive integer")
        result[mid] = item
    return result


def validate_gold_record(record: dict, checklist: dict, dialogs: dict[str, dict]) -> None:
    required = ("conversation_id", "language", "checklist_id", "checklist_version", "split", "criteria")
    missing = [key for key in required if key not in record]
    if missing:
        raise BenchmarkDataError(f"gold record missing fields: {', '.join(missing)}")
    cid = record["conversation_id"]
    if cid not in dialogs:
        raise BenchmarkDataError(f"{cid}: no matching dialog")
    if record["language"] not in ("RU", "KZ", "EN"):
        raise BenchmarkDataError(f"{cid}: language must be RU, KZ, or EN")
    if record["language"] != dialogs[cid].get("language"):
        raise BenchmarkDataError(f"{cid}: gold language does not match dialog")
    if record["checklist_id"] != checklist["id"] or record["checklist_version"] != checklist["version"]:
        raise BenchmarkDataError(f"{cid}: checklist id/version mismatch")
    if record["split"] not in ("train", "validation", "test", "holdout"):
        raise BenchmarkDataError(f"{cid}: unsupported split {record['split']!r}")
    criteria = {item["id"]: item for item in checklist["criteria"]}
    labels = record["criteria"]
    if not isinstance(labels, dict) or set(labels) != set(criteria):
        raise BenchmarkDataError(f"{cid}: gold criteria must match checklist criterion IDs exactly")
    transcript = dialogs[cid]["transcript"]
    for criterion_id, label in labels.items():
        criterion = criteria[criterion_id]
        if not isinstance(label, dict) or "answer" not in label:
            raise BenchmarkDataError(f"{cid}/{criterion_id}: label must contain answer")
        answer = label["answer"]
        ctype = criterion["answer_type"]
        allowed = ["yes", "no"] if ctype in ("binary", "flag") else []
        if ctype == "scale":
            scale_values = [x["value"] for x in criterion["scale"]["steps"]]
            allowed = scale_values + [str(value) for value in scale_values]
        if criterion.get("na_allowed"):
            allowed.append("na")
        if answer not in allowed:
            raise BenchmarkDataError(f"{cid}/{criterion_id}: invalid answer {answer!r}; expected {allowed}")
        flags = label.get("flags", [])
        known_flags = {x["id"] for x in criterion.get("flag_types", [])}
        if not isinstance(flags, list) or any(flag not in known_flags for flag in flags):
            raise BenchmarkDataError(f"{cid}/{criterion_id}: unknown or malformed flags")
        if ctype == "flag" and ((answer == "yes") != bool(flags)):
            raise BenchmarkDataError(f"{cid}/{criterion_id}: flag answer and flags disagree")
        evidence_items = label.get("evidence", [])
        if not isinstance(evidence_items, list):
            raise BenchmarkDataError(f"{cid}/{criterion_id}: evidence must be a list")
        for evidence in evidence_items:
            if not isinstance(evidence, dict):
                raise BenchmarkDataError(f"{cid}/{criterion_id}: evidence item must be an object")
            idx, quote = evidence.get("msg_index"), evidence.get("quote")
            if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(transcript):
                raise BenchmarkDataError(f"{cid}/{criterion_id}: evidence msg_index out of range")
            if not isinstance(quote, str) or not quote or quote not in transcript[idx].get("text", ""):
                raise BenchmarkDataError(f"{cid}/{criterion_id}: evidence quote is not in cited message")


def validate_gold(records: list[dict], checklist: dict, dialogs: dict[str, dict]) -> None:
    if not records:
        raise BenchmarkDataError("gold JSONL is empty; add human-reviewed labels before running")
    seen = set()
    scenario_splits = {}
    for record in records:
        validate_gold_record(record, checklist, dialogs)
        cid = record["conversation_id"]
        if cid in seen:
            raise BenchmarkDataError(f"duplicate gold conversation_id: {cid}")
        seen.add(cid)
        group = record.get("scenario_group")
        if group:
            previous = scenario_splits.setdefault(group, record["split"])
            if previous != record["split"]:
                raise BenchmarkDataError(f"translated scenario leakage: {group} spans {previous} and {record['split']}")
