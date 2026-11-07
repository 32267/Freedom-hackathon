# CQA model benchmark plan

Status: **Phase 1 merged in PR #11; Phase 2 tooling prepared, target-Mac validation pending**  
Owner: CQA / LLM workstream  
Branch: `codex/benchmark-phase2`

## Decision

**Primary candidate: Qwen3.5-4B, 4-bit quantized for MLX.**

The benchmark host is now confirmed:
- Apple Mac with **M5**
- **16 GB unified memory**
- **macOS 26.6.2**
- Native local inference target: **Apple Silicon / Metal using MLX**

The previously reported RTX 3060 12 GB is not part of this native Mac configuration. It should only be included as a separate benchmark target if it is available in another Windows/Linux machine or through a remote inference endpoint.

A 4B-class model is the practical starting point for 16 GB unified memory. This leaves more room for the OS, runtime, KV cache, and long CQA transcripts than beginning with an 8B/9B model. This is a **candidate recommendation, not a quality result**. No CQA-specific benchmark has been run yet.

macOS 26.6.2 is newer than the macOS 26.2 version floor previously identified for M5 Neural Accelerator optimizations. Actual use of those optimizations depends on the installed MLX/runtime and model implementation; do not assume that every MLX inference path uses the Neural Accelerators. Record the exact runtime and verify acceleration during the smoke test.

## Candidate matrix

| Role | Model | Initial precision/runtime | Reason to include |
|---|---|---|---|
| Primary | Qwen3.5-4B | 4-bit MLX | First candidate for multilingual RU/KZ/EN CQA within 16 GB |
| Smaller alternative | Gemma 4 E2B | 4-bit MLX | Lower-memory comparison point |
| Larger compact alternative | Gemma 4 E4B | 4-bit MLX | Tests whether a larger compact model improves evaluation quality |
| API reference | Current configured Claude model | API | Reference point for quality, latency, and cost; not a local-model candidate |

Model references:
- Qwen3.5-4B: https://huggingface.co/Qwen/Qwen3.5-4B
- Gemma 4 model card and memory information: https://ai.google.dev/gemma/docs/core/model_card_4

Confirm the exact MLX-compatible repository/conversion and license for each candidate before downloading. Do not assume a standard Hugging Face checkpoint is directly loadable by MLX without conversion or a compatible MLX distribution.

## Hardware and runtime constraints

- Target host: M5 Mac, 16 GB unified memory, macOS 26.6.2.
- Start with 4-bit weights and a **4K context**; test 8K only after measuring memory headroom and output quality.
- Run one inference at a time for the baseline.
- Record peak memory pressure / process memory, tokens per second, time to first token if available, and end-to-end latency.
- Keep enough unified memory available for macOS and other processes. A model's weight-file size is not its total runtime memory requirement.
- Use MLX/Metal as the initial local runtime. Validate structured JSON output against the existing provider contract before running the full dataset.
- Treat M5 Neural Accelerator support as an implementation/runtime capability to verify, not an automatic consequence of using an M5 Mac.

## Evaluation data

The DEV set described in `docs/DATA.md` has 65 conversations: 30 RU chats, 15 KZ chats, 15 EN chats, and 5 RU voice calls. It is useful for smoke/performance testing, but **it is not a gold-label benchmark**.

Create a human-reviewed gold set before ranking models:
- Start with 15 conversations, covering RU/KZ/EN and chat/voice where available.
- Include translated parallel scenarios where available, but keep translations of the same scenario in the same split to avoid leakage.
- Have a reviewer label each criterion, N/A, critical-error flags, and supporting message indices.
- Keep at least 5 conversations as a held-out check; do not tune prompts against this holdout.
- Expand toward 30–50 human-reviewed examples before treating small score differences as meaningful.
- Keep model-generated labels separate. Do not use model agreement as ground truth.

The 65-dialog DEV set is too small to train a model from scratch and is not sufficient by itself for reliable fine-tuning.

## Benchmark protocol

1. Freeze the checklist version, prompt version, decoding settings, and dataset split for a benchmark run.
2. Run every candidate on the same conversations with the same prompt and schema.
3. Use deterministic decoding where supported. Record runtime/model version, quantization, context limit, temperature, elapsed time, token counts, and failures.
4. Save raw model outputs as well as validated evaluator outputs. Never discard invalid JSON or invalid evidence from the report.
5. Run the existing deterministic evidence validator after inference. A plausible explanation with a fabricated quote is a failure.
6. Compare against human labels, not against another model's output.
7. First run a 3–5 conversation smoke test across RU/KZ/EN; only proceed to the full DEV and gold sets after confirming output validity and stable memory use.

### Primary metrics

- Per-criterion exact agreement and macro-F1 (report each language separately).
- Critical-error recall and precision (prioritize recall; show false positives too).
- N/A precision/recall and confusion matrix.
- Evidence validity: percentage of evidence quotes found in the cited transcript message; also measure correct speaker/message attribution.
- Score MAE against the human-reviewed total and criterion scores.
- Structured-output validity and evaluator completion rate.
- Median and p95 latency per conversation; peak memory use; tokens/sec where available.
- Cost per conversation for the API reference.

Do not collapse everything into one score without showing the per-language and critical-error results. A model that is strong in English but weak in Kazakh is not an acceptable overall winner for this project.

## Pass/fail gates

A local candidate is eligible for further development only if:
- it returns schema-valid outputs reliably;
- evidence validity is effectively 100% after deterministic validation (invalid evidence must not silently pass);
- it does not materially regress Kazakh or critical-error recall versus the API reference on the gold set;
- it fits the M5 Mac at the agreed context length without routine memory-pressure or out-of-memory failures;
- latency is acceptable for batch evaluation.

If the gold set is too small to distinguish candidates, report the result as inconclusive and label more examples. Do not fine-tune to compensate for ambiguous checklist rules.

## Implementation sequence

### Phase 0 — benchmark specification
- [x] Confirm target hardware: M5 Mac, 16 GB unified memory, macOS 26.6.2.
- [x] Select MLX/Metal as the initial local runtime.
- [x] Select a 4B-class primary candidate and shortlist.
- [x] Define dataset, metrics, and acceptance gates.

### Phase 1 — benchmark harness
- [x] Add a CLI that loads a fixed dialog JSON and checklist, calls one configured provider/model per run, and writes JSONL results plus a run manifest.
- [x] Add a model matrix config (model ID, runtime name, quantization, context length); exact MLX distributions remain unverified.
- [x] Add metric aggregation against human-labelled gold JSONL.
- [x] Add tests for split integrity, metric calculations, missing outputs, invalid evidence, and language-level reporting.
- [ ] Keep the existing `backend/scoring/validate.py` as the evidence-validation authority.

### Phase 2 — local inference
- [ ] Install and record a compatible MLX runtime and candidate model packages/checkpoints.
- [ ] Run a 3–5 conversation RU/KZ/EN smoke test on the M5 Mac.
- [ ] Verify JSON-schema-constrained output with the existing `backend/llm/local_provider.py` contract.
- [ ] Measure memory use and latency at 4K context; test 8K only if headroom allows.
- [ ] Verify whether the chosen runtime actually uses M5 Neural Accelerator optimizations; record the result without assuming support.

### Phase 3 — decision
- [ ] Run the same gold set against Qwen3.5-4B, Gemma 4 E2B, Gemma 4 E4B, and the configured Claude reference.
- [ ] Publish per-language and per-criterion comparison.
- [ ] Select the model only after reviewing evidence quality and critical-error recall.

### Phase 4 — only after model selection
- [ ] Collect at least 300–500 human-verified examples across all three languages (more is preferable).
- [ ] Split by conversation/scenario, not by individual translated transcript.
- [ ] Try LoRA/QLoRA only after the baseline and validation set are stable.
- [ ] Compare the fine-tuned checkpoint against the unchanged base model on the untouched holdout.

## First command-line contract (planned)

The first harness should support a repeatable command in this shape:

```bash
python -m llm.benchmark run \
  --dialogs data/DEV.json \
  --checklist checklists/default.json \
  --gold llm/data/gold.jsonl \
  --model qwen3.5-4b-mlx-q4 \
  --out llm/runs/qwen3.5-4b-mlx-q4.jsonl
```

And a separate report command:

```bash
python -m llm.benchmark report \
  --gold llm/data/gold.jsonl \
  --predictions llm/runs/qwen3.5-4b-mlx-q4.jsonl \
  --out llm/runs/qwen3.5-4b-mlx-q4-report.json
```

The CLI is implemented in Phase 1. The gold-label schema and annotation guide are in `llm/benchmark/GOLD_FORMAT.md`. Run `python -m unittest discover -s llm/benchmark/tests -v` for the harness unit tests. Phase 2 remains unstarted until a compatible MLX runtime/model is installed and smoke-tested on the target M5 Mac.
