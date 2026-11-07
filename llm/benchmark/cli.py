"""CLI for repeatable benchmark runs and reports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .metrics import build_report
from .runner import run_benchmark
from .schemas import (BenchmarkDataError, dialog_records, read_json, read_jsonl,
                      validate_gold, validate_model_config)


def _parser():
    parser = argparse.ArgumentParser(prog="python -m llm.benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one configured provider/model")
    run.add_argument("--dialogs", required=True)
    run.add_argument("--checklist", required=True)
    run.add_argument("--gold", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--models-config", default=str(Path(__file__).with_name("models.json")))
    report = sub.add_parser("report", help="compare predictions with human-reviewed gold labels")
    report.add_argument("--gold", required=True)
    report.add_argument("--predictions", required=True)
    report.add_argument("--checklist", default="checklists/default.json")
    report.add_argument("--dialogs", help="optional dialog file for full gold evidence validation")
    report.add_argument("--out", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        checklist = read_json(args.checklist) if args.command == "run" else read_json(args.checklist)
        gold = read_jsonl(args.gold)
        if args.command == "run":
            models = validate_model_config(read_json(args.models_config))
            if args.model not in models:
                raise BenchmarkDataError(f"unknown model ID {args.model!r}; configured: {', '.join(models)}")
            dialogs = dialog_records(read_json(args.dialogs))
            validate_gold(gold, checklist, {d["conversation_id"]: d for d in dialogs})
            manifest = run_benchmark(dialogs, checklist, gold, models[args.model], args.model, args.out)
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        else:
            if args.dialogs:
                dialogs = dialog_records(read_json(args.dialogs))
                validate_gold(gold, checklist, {d["conversation_id"]: d for d in dialogs})
            predictions = read_jsonl(args.predictions)
            report = build_report(gold, predictions, checklist)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (BenchmarkDataError, OSError, KeyError, ValueError) as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        return 2
