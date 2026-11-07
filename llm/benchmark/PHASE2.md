# Phase 2 — local MLX inference on Apple Silicon

This procedure installs an MLX runtime in an isolated environment, starts one OpenAI-compatible local model server, and runs a 3–5-dialog RU/KZ/EN smoke test through the existing `backend/llm/local_provider.py` contract.

**Target:** Apple M5, 16 GB unified memory, macOS 26.6.2.  
**Primary candidate:** `mlx-community/Qwen3.5-4B-MLX-4bit`.  
**Comparisons:** Gemma 4 E2B and E4B 4-bit QAT MLX distributions.

The repository configuration records model candidates; `verified_installed` remains false until the user runs the installation and smoke test on the target Mac. Model files, DEV data, logs, and run outputs must not be committed.

## 1. Install the MLX server environment

Use a separate environment for MLX so that its dependencies do not alter the project's application environment:

```bash
python3.11 -m venv .venv-mlx
source .venv-mlx/bin/activate
python -m pip install --upgrade pip
python -m pip install --upgrade mlx-vlm
```

Check the runtime:

```bash
python -c "import mlx.core as mx; print('MLX device:', mx.default_device()); print('Metal available:', mx.metal.is_available())"
```

This confirms MLX/Metal availability only. It does **not** prove that an inference request uses the M5 Neural Accelerators.

## 2. Start the primary candidate

In the MLX environment:

```bash
python -m mlx_vlm.server --model mlx-community/Qwen3.5-4B-MLX-4bit --host 127.0.0.1 --port 8080
```

The first launch downloads model files. Confirm the server responds from another terminal:

```bash
curl --fail http://127.0.0.1:8080/v1/models
```

The Gemma 4 alternatives use the same server interface; stop the current server before switching:

```bash
python -m mlx_vlm.server --model mlx-community/gemma-4-E2B-it-qat-4bit --host 127.0.0.1 --port 8080
python -m mlx_vlm.server --model mlx-community/gemma-4-E4B-it-qat-4bit --host 127.0.0.1 --port 8080
```

Run one model at a time. Review the upstream model cards and applicable license terms before downloading. The Qwen MLX distribution is a community conversion; the Gemma distributions are community conversions, not first-party Apple releases.

## 3. Run the CQA smoke test

In a second terminal, use the project's normal Python environment and install the repository requirements if needed:

```bash
source .venv/bin/activate
export LOCAL_LLM_URL=http://127.0.0.1:8080/v1
export LOCAL_LLM_MODEL=mlx-community/Qwen3.5-4B-MLX-4bit
export LOCAL_LLM_TIMEOUT=300
export SCORING_MODE=llm
python -m llm.benchmark.smoke \
  --dialogs data/DEV.json \
  --checklist checklists/default.json \
  --model mlx-community/Qwen3.5-4B-MLX-4bit \
  --limit 5 \
  --out llm/runs/qwen35-m5-smoke.json
```

The selector chooses RU, KZ and EN chat examples, then adds a RU voice call when available. To choose exact examples, pass `--ids id1,id2,id3`. The smoke test invokes `scoring.evaluate(..., providers="local", samples=1)`, so the existing deterministic evidence validator remains authoritative.

The local provider sends a strict JSON Schema response-format request. If the server rejects `response_format: json_schema`, the smoke test records the failure; do not silently downgrade to unconstrained text or claim schema-constrained output passed.

## 4. Record latency and memory

The JSON output records per-dialog wall-clock latency, total elapsed time, token usage when exposed by the server, Python process peak RSS, host details, MLX default device, and Metal availability.

Also record the inference server's memory separately while the model is loaded and during a request. On macOS, use Activity Monitor (Memory tab) or:

```bash
pgrep -fl mlx_vlm.server
ps -o pid,rss,command -p <SERVER_PID>
memory_pressure -Q
```

Record the server RSS before and during inference, and whether macOS reports memory pressure. RSS is an approximation of process resident memory, not a direct measurement of all GPU allocations. Keep the machine otherwise idle for comparable runs.

For Neural Accelerator verification, retain runtime/server logs and identify explicit runtime evidence of accelerator dispatch. `mx.metal.is_available()` only confirms Metal availability. If no explicit evidence exists, report Neural Accelerator use as **unverified**, not enabled.

## 5. Acceptance checklist

- [ ] MLX and mlx-vlm versions recorded; Metal available.
- [ ] Model distribution and license reviewed; model loads successfully.
- [ ] `/v1/models` responds.
- [ ] 3–5 RU/KZ/EN conversations complete through the local provider.
- [ ] Strict JSON-schema request is accepted by the server.
- [ ] Every criterion result passes the deterministic validator; evidence quotes point to exact transcript substrings.
- [ ] No out-of-memory failure or sustained macOS memory pressure at 4K context.
- [ ] Per-dialog latency and server RSS recorded.
- [ ] Neural Accelerator use explicitly verified or marked unverified.

A successful smoke test is an integration/performance check, not a model-quality result. Do not rank models until the human-reviewed gold set is available and the same frozen examples are run against each candidate and the Claude reference.

## References

- Qwen MLX distribution: https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit
- Gemma 4 MLX deployment guide: https://gemma.ai/deployment/mlx/
- Gemma 4 E2B MLX distribution: https://huggingface.co/mlx-community/gemma-4-E2B-it-qat-4bit
- Gemma 4 E4B MLX distribution: https://huggingface.co/mlx-community/gemma-4-E4B-it-qat-4bit
