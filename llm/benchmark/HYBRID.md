# Hybrid evaluator and release benchmark

## Runtime configuration

The hybrid evaluator runs the local VLM first and calls the LM only for criteria that
fail deterministic validation or are marked insufficient.

Set these values in `.env`:

```dotenv
SCORING_MODE=llm
HYBRID_VLM_PROVIDER=local
HYBRID_LM_PROVIDER=claude_cli
HYBRID_DEADLINE_SECONDS=120
```

The LM provider must be a configured provider supported by `backend.llm`, for example
`claude_cli`, `codex_cli`, or `anthropic`. Do not set both providers to the same value.
Select the `Гибрид: VLM + LM fallback` preset (provider value `hybrid`) in the evaluator
selector, or set `SCORING_STRATEGY=hybrid` for the default scoring route.

The VLM stage receives at most 65% of the cooperative deadline. Local MLX requests
receive a per-request timeout derived from the remaining stage budget. LM fallback
starts only while time remains and re-evaluates only the failed criterion. Translation
runs once after routing.

**Deadline limitation:** the scoring layer checks the deadline between requests. It can
bound local HTTP requests, but it cannot forcibly terminate an already-running Claude
or Codex CLI process. Therefore the 120-second limit is a benchmark acceptance target,
not a hard real-time guarantee for every provider. A timeout or unresolved criterion
must be treated as a failure / human-review case, never as a silently accepted score.

## Run comparable baselines

Use the same frozen dialog file, checklist version, and human-reviewed gold file for
each run. Run each model separately:

```bash
python -m llm.benchmark run --dialogs llm/data/DEV.json --checklist checklists/default.json --gold llm/data/gold.jsonl --model qwen3.5-4b-mlx-q4 --out llm/runs/qwen-4b/predictions.jsonl
python -m llm.benchmark run --dialogs llm/data/DEV.json --checklist checklists/default.json --gold llm/data/gold.jsonl --model claude-reference --out llm/runs/claude/predictions.jsonl
python -m llm.benchmark run --dialogs llm/data/DEV.json --checklist checklists/default.json --gold llm/data/gold.jsonl --model hybrid-qwen-vlm-claude-fallback --out llm/runs/hybrid/predictions.jsonl
```

For each output:

```bash
python -m llm.benchmark report --gold llm/data/gold.jsonl --predictions llm/runs/hybrid/predictions.jsonl --checklist checklists/default.json --dialogs llm/data/DEV.json --out llm/reports/hybrid.json
```

Run reports for LM-only, VLM-only, and hybrid outputs, then compare hybrid against the LM-only report:

```bash
python -m llm.benchmark compare --baseline-report llm/reports/lm.json --candidate-report llm/reports/hybrid.json --out llm/reports/hybrid-vs-lm.json
```

The comparison exits with status 1 when the candidate loses more than 0.02 macro-F1 overall or 0.03 in any language. Do not use DEV labels as gold
unless each record has been independently reviewed and added to the gold file.

## Initial release gates

These are target thresholds, not claims about current model performance:

| Metric | Target |
|---|---:|
| Overall criterion macro-F1 | >= 0.90 |
| Criterion macro-F1 in each language (RU/KZ/EN) | >= 0.85 |
| Critical-error recall | >= 0.95 |
| N/A classification accuracy | >= 0.90 |
| Schema-valid criterion outputs | >= 0.99 |
| p95 end-to-end latency | <= 120 seconds |
| Gold conversations completed within 120 seconds | >= 0.95 |
| Hybrid macro-F1 versus LM-only | no more than 0.02 lower overall |
| Hybrid macro-F1 versus LM-only, each language | no more than 0.03 lower |

The report calculates the single-run gates it can measure. The comparison against LM-only
must be checked by comparing the corresponding reports; do not infer it from a hybrid
report alone.

Evidence quote validity and exact overlap with human gold quotes are reported separately.
Neither is a semantic evidence-attribution score: a quote can be present and still fail
to support the criterion. Semantic support needs human review or a separately validated
attribution annotation.

## Minimum benchmark design

- Start with at least 100 human-reviewed conversations per language for iteration.
- Expand to at least 300 per language for a release decision.
- Include chat and voice, positive and negative cases, N/A edge cases, and critical errors.
- Ensure critical-error positives exist; otherwise recall is undefined and the release gate
  cannot pass.
- Keep translated versions of the same scenario in the same split.
- Keep a separate holdout set out of prompt tuning.
- Preserve raw predictions, manifest, exact model/runtime settings, and report for each run.

The hybrid prediction records include per-criterion route metadata and fallback reasons.
Use those fields to inspect whether latency improvements come from VLM acceptance rather
than from silently dropping difficult criteria.
