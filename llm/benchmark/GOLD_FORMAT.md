# Benchmark gold-label format

One UTF-8 JSON object per line in `llm/data/gold.jsonl`. Gold records must be labelled or adjudicated by a human. Synthetic test fixtures and model predictions are not gold data.

## Record contract

The following is an illustrative excerpt; a production record must include every criterion ID in the frozen checklist.

```json
{
  "conversation_id": "p1-ru-001",
  "language": "RU",
  "checklist_id": "default",
  "checklist_version": 1,
  "scenario_group": "scenario-001",
  "split": "validation",
  "criteria": {
    "contact": {
      "answer": "yes",
      "flags": [],
      "evidence": [{"msg_index": 2, "quote": "Здравствуйте, меня зовут ..."}]
    }
  },
  "total_score": 87.5
}
```

- `conversation_id`, language and checklist identity must match the source dialog and checklist.
- `criteria` must contain exactly the criterion IDs in that checklist version.
- Binary and flag answers use `yes` / `no`; permitted N/A uses `na`. Scale answers must equal one of the checklist's configured step values.
- Flag criteria use `flags` with IDs from `flag_types`; `yes` requires at least one flag and `no` requires none.
- Evidence uses transcript array indices (`msg_index`, zero-based), not timestamps. The quote must be an exact substring of the cited message.
- `scenario_group` groups translated or otherwise parallel scenarios. All records in a group must use the same `split`.
- `split` is one of `train`, `validation`, `test`, or `holdout`. The holdout is not used for prompt tuning.
- `total_score` is optional and should be included only when independently adjudicated/calculated under the frozen checklist formula.

## Annotation and adjudication

1. Freeze checklist ID/version before annotation.
2. Review the full transcript, including relevant system events; score the operator, not bot messages.
3. Apply the checklist's N/A rules and critical-error definitions literally. Record flag IDs separately from weighted scores.
4. Cite exact transcript snippets and their zero-based message indices. Never paraphrase a quote.
5. Resolve disagreements with a second human reviewer; record the adjudicated answer in the gold file and retain review history outside generated predictions.
6. Split by scenario group, never by translated transcript. Keep at least five examples untouched as holdout during early prompt/model iteration.
7. DEV is smoke/performance data, not gold unless separately human-reviewed and explicitly entered here.

The harness validates structure, answer domains, checklist identity, language, evidence indices/quotes and translated-scenario split integrity. It cannot certify that a human label is semantically correct; that remains an annotation responsibility.
