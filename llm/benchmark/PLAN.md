# CQA model benchmark plan

Status: **Phase 0 — benchmark design**  
Owner: CQA / LLM workstream  
Branch: `islam/model-benchmark`

## Decision

**Primary candidate: `Qwen/Qwen3.5-9B`, quantized to 4-bit (Q4).**

Why it is the first model to test:
- The official model card describes 9B parameters and support for 201 languages and dialects, which makes it the strongest language-coverage starting point for RU/KZ/EN in this shortlist.
- A 9B model in Q4 is a plausible inference target for an RTX 3060 12 GB, subject to the actual runtime, context length, KV cache, and available VRAM.
- It is open-weight and can later be adapted with LoRA/QLoRA if human-labelled CQA data justifies fine-tuning.

This is a **candidate recommendation, not a quality result**. No CQA-specific benchmark has been run yet.

## Hardware assumptions to confirm

The reported configuration is: Apple machine, RTX 3060 12 GB, 16 GB system RAM.

These details may describe two different machines. An RTX 3060 is a CUDA/NVIDIA GPU and is not normally available as a native GPU backend on macOS/Apple Silicon. Before choosing the runtime, confirm whether:
1. the RTX 3060 is in a separate Windows/Linux PC (recommended benchmark host), or
2. the benchmark host is an Apple Silicon Mac, in which case use Metal/MLX and the Mac's unified memory; or
3. the GPU is accessed remotely.

For the RTX 3060 host, start with a 4-bit quantized model, 4K–8K context, one request at a time, and leave VRAM headroom for the runtime/KV cache. Do not assume the full advertised context fits in 12 GB.

## Candidate matrix

| Role | Model | Initial precision | Reason to include |
|---|---|---|---|
| Primary | Qwen3.5-9B Instruct | Q4 | Explicit broad multilingual coverage; 9B-class quality target |
| Smaller alternative | Gemma 4 E4B IT | Q4 | Compact local baseline; official Q4 memory estimate is about 4.5 GB before runtime/context overhead |
| Previous-generation control | Qwen3-8B Instruct | Q4 | Helps measure whether the newer Qwen family improves our actual CQA task |
| API reference | Current configured Claude model | API | Reference point for quality, latency, and cost; not a local-model candidate |

Model references:
- Qwen3.5-9B: https://huggingface.co/Qwen/Qwen3.5-9B
- Gemma 4 model card and memory table: https://ai.google.dev/gemma/docs/core/model_card_4
- Qwen3-8B: https://huggingface.co/Qwen/Qwen3-8B

Gemma 4 E4B is a useful size/speed comparator, but its published language summary is broader than its explicit language list; we must measure Kazakh quality rather than assume parity with Qwen.

## Evaluation data

The DEV set described in `docs/DATA.md` has 65 conversations: 30 RU chats, 15 KZ chats, 15 EN chats, and 5 RU voice calls. It is useful for smoke/performance testing, but **it is not a gold-label benchmark**.

Create a human-reviewed gold set before ranking models:
- Start with 15 conversations, covering RU/KZ/EN and chat/voice where available.
- Include the translated parallel scenarios where available, but keep translations of the same scenario in the same split to avoid leakage.
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

### Primary metrics

- Per-criterion exact agreement and macro-F1 (report each language separately).
- Critical-error recall and precision (prioritize recall; show false positives too).
- N/A precision/recall and confusion matrix.
- Evidence validity: percentage of evidence quotes found in the cited transcript message; also measure correct speaker/message attribution.
- Score MAE against the human-reviewed total and criterion scores.
- Structured-output validity and evaluator completion rate.
- Median and p95 latency per conversation; peak VRAM/RAM; tokens/sec where available.
- Cost per conversation for the API reference.

Do not collapse everything into one score without showing the per-language and critical-error results. A model that is strong in English but weak in Kazakh is not an acceptable overall winner for this project.

## Pass/fail gates

A local candidate is eligible for further development only if:
- it returns schema-valid outputs reliably;
- evidence validity is effectively 100% after deterministic validation (invalid evidence must not silently pass);
- it does not materially regress Kazakh or critical-error recall versus the API reference on the gold set;
- it fits the target machine at the agreed context length without routine out-of-memory failures;
- latency is acceptable for batch evaluation.

If the gold set is too small to distinguish candidates, report the result as inconclusive and label more examples. Do not fine-tune to compensate for ambiguous checklist rules.

## Implementation sequence

### Phase 0 — now: benchmark specification
- [x] Select first candidate and shortlist.
- [x] Record hardware ambiguity and memory constraints.
- [x] Define dataset, metrics, and acceptance gates.

### Phase 1 — benchmark harness
- [ ] Add a CLI that loads a fixed dialog JSON and checklist, calls one configured provider/model per run, and writes JSONL results plus a run manifest.
- [ ] Add a model matrix config (model ID, runtime name, quantization, context length).
- [ ] Add metric aggregation against human-labelled gold JSONL.
- [ ] Add tests for split integrity, metric calculations, missing outputs, invalid evidence, and language-level reporting.
- [ ] Keep the existing `backend/scoring/validate.py` as the evidence-validation authority.

### Phase 2 — local inference
- [ ] Confirm benchmark host OS and GPU availability.
- [ ] Select an inference server that supports the model architecture and the project's required structured output.
- [ ] Verify JSON-schema-constrained output with the existing `backend/llm/local_provider.py` contract before running the full set.
- [ ] Record actual VRAM/RAM and latency at 4K and 8K context.

### Phase 3 — decision
- [ ] Run the same gold set against Qwen3.5-9B, Gemma 4 E4B, Qwen3-8B, and the configured Claude reference.
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
  --model qwen3.5-9b-q4 \
  --out llm/runs/qwen3.5-9b-q4.jsonl
```

And a separate report command:

```bash
python -m llm.benchmark report \
  --gold llm/data/gold.jsonl \
  --predictions llm/runs/qwen3.5-9b-q4.jsonl \
  --out llm/runs/qwen3.5-9b-q4-report.json
```

These commands describe the intended interface; the CLI is not implemented yet.
