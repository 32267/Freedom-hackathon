# Qwen 4B benchmark runs

Store Qwen 4B smoke and benchmark outputs in this directory.

Suggested artifacts:
- `predictions.jsonl` — per-dialog predictions from a run.
- `manifest.json` — model, checklist, dataset, and inference configuration.
- `metrics.json` — metrics calculated for this run.

Use a separate filename for each repeat instead of overwriting a previous run. Keep large or sensitive generated outputs out of Git unless the project explicitly requires them.
